from __future__ import annotations

import json
import logging
import os
import uuid
from types import SimpleNamespace
from urllib.parse import urlencode

import requests
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.m3u.models import M3UAccount
from apps.vod.models import (
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
    VODCategory,
)
from core.models import CoreSettings
from core.utils import RedisClient

from .export_tasks import (
    export_media_library,
    queue_automatic_exports,
    refresh_selected_series_and_export,
)
from .local_metadata import has_tmdb_api_key
from .models import (
    MediaLibraryExportRun,
    MediaLibraryExportTarget,
    MediaLibraryImportRun,
    MediaLibrarySource,
)
from core.path_browser import browse_directories
from .providers import MediaProviderSession, get_provider_client
from .serializers import (
    MediaLibraryExportRunSerializer,
    MediaLibraryExportTargetSerializer,
    MediaLibraryImportRunSerializer,
    MediaLibrarySourceSerializer,
)
from .strm_export import remove_managed_export_files
from .tasks import (
    _default_sync_stages,
    cleanup_integration_vod,
    ensure_integration_vod_account,
    integration_library_ids,
    remove_integration_library_scopes,
    sync_media_server_integration,
)

logger = logging.getLogger(__name__)

PLEX_PRODUCT = "Dispatcharr"
PLEX_DEVICE = "Media Library"
PLEX_PLATFORM = "Web"
PLEX_VERSION = "1.0"


def _plex_headers(client_identifier: str, token: str = "") -> dict:
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": PLEX_PRODUCT,
        "X-Plex-Client-Identifier": client_identifier,
        "X-Plex-Device-Name": PLEX_DEVICE,
        "X-Plex-Platform": PLEX_PLATFORM,
        "X-Plex-Version": PLEX_VERSION,
    }
    if token:
        headers["X-Plex-Token"] = token
    return headers


class AdminOnlyViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAdmin]


class MediaLibrarySettingsView(APIView):
    permission_classes = [IsAdmin]

    @staticmethod
    def _payload():
        saved = CoreSettings._get_group("media_library_settings", {})
        saved_key = str(saved.get("tmdb_api_key") or "").strip()
        environment_key = str(os.environ.get("TMDB_API_KEY") or "").strip()
        return {
            "tmdb_configured": bool(saved_key or environment_key),
            "tmdb_saved": bool(saved_key),
            "tmdb_environment": bool(environment_key),
            "prefer_nfo": saved.get("prefer_nfo", True) is not False,
            "tmdb_source": (
                "saved"
                if saved_key
                else "environment"
                if environment_key
                else "none"
            ),
        }

    def get(self, request):
        return Response(self._payload())

    def patch(self, request):
        updates = {}
        if "prefer_nfo" in request.data:
            prefer_nfo = request.data.get("prefer_nfo")
            if not isinstance(prefer_nfo, bool):
                return Response(
                    {"prefer_nfo": "This value must be a boolean."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            updates["prefer_nfo"] = prefer_nfo

        clear_key = request.data.get("clear_tmdb_api_key", False)
        if not isinstance(clear_key, bool):
            return Response(
                {"clear_tmdb_api_key": "This value must be a boolean."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        has_key = "tmdb_api_key" in request.data
        if clear_key and has_key and str(request.data.get("tmdb_api_key") or "").strip():
            return Response(
                {
                    "tmdb_api_key": (
                        "Provide a new key or explicitly clear the saved key, not both."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if clear_key:
            updates["tmdb_api_key"] = ""
        elif has_key:
            value = str(request.data.get("tmdb_api_key") or "").strip()
            if not value:
                return Response(
                    {
                        "tmdb_api_key": (
                            "A blank value does not clear a saved key. "
                            "Use clear_tmdb_api_key."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if len(value) > 512:
                return Response(
                    {"tmdb_api_key": "The TMDB API key is too long."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            updates["tmdb_api_key"] = value

        if updates:
            CoreSettings._update_group(
                "media_library_settings",
                "Media Library Settings",
                updates,
            )
        return Response(self._payload())


class MediaLibrarySourceViewSet(viewsets.ModelViewSet):
    queryset = MediaLibrarySource.objects.select_related("vod_account").prefetch_related(
        "locations"
    )
    serializer_class = MediaLibrarySourceSerializer
    permission_classes = [IsAdmin]

    def list(self, request, *args, **kwargs):
        from .dvr_library import ensure_dvr_media_library_source

        ensure_dvr_media_library_source()
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        source = serializer.save()
        ensure_integration_vod_account(source)

    def perform_update(self, serializer):
        previous_provider = serializer.instance.provider_type
        previous_enabled = serializer.instance.enabled
        previous_add_to_vod = serializer.instance.add_to_vod
        represented_scope_ids = integration_library_ids(serializer.instance)
        source = serializer.save()
        ensure_integration_vod_account(source)

        if previous_provider != source.provider_type or not (
            source.enabled and source.add_to_vod
        ):
            retained_scope_ids = set()
        elif source.provider_type == MediaLibrarySource.ProviderTypes.LOCAL:
            retained_scope_ids = {
                str(value)
                for value in source.locations.filter(enabled=True).values_list(
                    "public_id", flat=True
                )
            }
        elif source.selected_library_ids:
            retained_scope_ids = source.selected_library_ids
        else:
            # An empty remote selection means "all provider libraries". Their
            # authoritative IDs are not known until discovery, so retain the
            # scopes already represented by this source.
            retained_scope_ids = represented_scope_ids

        removed = remove_integration_library_scopes(
            source,
            represented_scope_ids - retained_scope_ids,
        )
        lifecycle_changed = (
            previous_enabled != source.enabled
            or previous_add_to_vod != source.add_to_vod
        )
        if any(removed.values()) or lifecycle_changed:
            transaction.on_commit(
                lambda: queue_automatic_exports.delay(
                    f"media-library-source-updated:{source.id}"
                )
            )

    def perform_destroy(self, instance):
        if instance.provider_type == MediaLibrarySource.ProviderTypes.DVR:
            raise MethodNotAllowed(
                "DELETE",
                detail="The built-in DVR Media Library cannot be deleted.",
            )
        cleanup_integration_vod(instance)
        super().perform_destroy(instance)
        transaction.on_commit(
            lambda: queue_automatic_exports.delay("media-library-source-deleted")
        )

    @staticmethod
    def _queue_import(source, summary="Manual import"):
        try:
            run = MediaLibraryImportRun.objects.create(
                integration=source,
                status=MediaLibraryImportRun.Status.QUEUED,
                summary=summary,
                message="Import queued.",
                stages=_default_sync_stages(),
            )
        except IntegrityError:
            return None
        result = sync_media_server_integration.delay(source.id, run.id)
        run.task_id = result.id or ""
        run.save(update_fields=["task_id", "updated_at"])
        return run

    @action(detail=True, methods=["post"])
    def sync(self, request, pk=None):
        run = self._queue_import(self.get_object())
        if not run:
            return Response(
                {"detail": "An import is already active for this source."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            MediaLibraryImportRunSerializer(run).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request, pk=None):
        source = self.get_object()
        try:
            with get_provider_client(source) as client:
                client.ping()
                libraries = client.list_libraries()
        except (ValueError, OSError) as exc:
            return Response({"ok": False, "error": str(exc)}, status=400)
        except requests.RequestException:
            return Response(
                {"ok": False, "error": "The provider connection failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "ok": True,
                "libraries": [
                    {
                        "id": library.id,
                        "name": library.name,
                        "content_type": library.content_type,
                    }
                    for library in libraries
                ],
            }
        )

    @action(detail=False, methods=["post"], url_path="test-configuration")
    def test_configuration(self, request):
        source_id = request.data.get("id") or request.data.get("source_id")
        instance = None
        if source_id not in (None, ""):
            try:
                instance = self.get_queryset().get(pk=source_id)
            except (MediaLibrarySource.DoesNotExist, TypeError, ValueError):
                return Response(
                    {"detail": "The media source could not be found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=instance is not None,
        )
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        locations = values.pop("locations", None)
        values.pop("clear_api_token", None)
        values.pop("clear_password", None)

        allowed_fields = {
            "name",
            "provider_type",
            "base_url",
            "api_token",
            "username",
            "password",
            "verify_ssl",
            "enabled",
            "add_to_vod",
            "sync_interval",
            "include_libraries",
            "library_content_types",
            "provider_config",
        }
        test_values = {
            field: getattr(instance, field)
            for field in allowed_fields
            if instance is not None
        }
        test_values.update(
            {field: value for field, value in values.items() if field in allowed_fields}
        )
        if locations is not None:
            test_values["provider_config"] = {
                "locations": [
                    {
                        "id": str(entry.get("public_id") or ""),
                        "name": entry.get("name", ""),
                        "path": entry.get("path", ""),
                        "content_type": entry.get("content_type", "mixed"),
                        "include_subdirectories": entry.get(
                            "include_subdirectories",
                            True,
                        ),
                        "enabled": entry.get("enabled", True),
                    }
                    for entry in locations
                ]
            }
        test_source = MediaLibrarySource(**test_values)
        try:
            with get_provider_client(test_source) as client:
                client.ping()
                libraries = client.list_libraries()
        except (ValueError, OSError) as exc:
            return Response({"ok": False, "error": str(exc)}, status=400)
        except requests.RequestException:
            return Response(
                {"ok": False, "error": "The provider connection failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        response_libraries = [
            {
                "id": library.id,
                "name": library.name,
                "content_type": library.content_type,
            }
            for library in libraries
        ]
        return Response(
            {
                "ok": True,
                "library_count": len(response_libraries),
                "libraries": response_libraries,
                "tmdb_configured": has_tmdb_api_key(),
            }
        )

    @action(detail=True, methods=["get"])
    def libraries(self, request, pk=None):
        source = self.get_object()
        try:
            with get_provider_client(source) as client:
                libraries = client.list_libraries()
        except (ValueError, OSError) as exc:
            return Response({"detail": str(exc)}, status=400)
        except requests.RequestException:
            return Response(
                {"detail": "The provider connection failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            [
                {
                    "id": library.id,
                    "name": library.name,
                    "content_type": library.content_type,
                }
                for library in libraries
            ]
        )

    @action(detail=False, methods=["get"], url_path="browse-local")
    def browse_local(self, request):
        try:
            return Response(
                browse_directories(
                    "media-library-import",
                    str(request.query_params.get("path") or ""),
                )
            )
        except Exception as exc:
            messages = getattr(exc, "messages", None)
            return Response(
                {"detail": messages[0] if messages else str(exc)},
                status=400,
            )

    @action(detail=False, methods=["post"], url_path="plex-auth/start")
    def plex_auth_start(self, request):
        client_identifier = f"dispatcharr-{uuid.uuid4()}"
        try:
            with MediaProviderSession() as session:
                response = session.post(
                    "https://plex.tv/api/v2/pins",
                    params={"strong": "true"},
                    headers=_plex_headers(client_identifier),
                    timeout=20,
                )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return Response(
                {"detail": "Plex authorization could not be started."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        pin_id = payload.get("id")
        code = payload.get("code")
        if not pin_id or not code:
            return Response(
                {"detail": "Plex returned an incomplete authorization response."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        params = {
            "clientID": client_identifier,
            "code": code,
            "context[device][product]": PLEX_PRODUCT,
            "context[device][device]": PLEX_DEVICE,
            "context[device][platform]": PLEX_PLATFORM,
        }
        return Response(
            {
                "pin_id": pin_id,
                "client_identifier": client_identifier,
                "auth_url": f"https://app.plex.tv/auth#?{urlencode(params)}",
                "expires_in": payload.get("expiresIn"),
            }
        )

    @action(detail=False, methods=["post"], url_path="plex-auth/check")
    def plex_auth_check(self, request):
        pin_id = str(request.data.get("pin_id") or "").strip()
        client_identifier = str(
            request.data.get("client_identifier") or ""
        ).strip()
        if not pin_id or not client_identifier:
            return Response(
                {"detail": "pin_id and client_identifier are required."},
                status=400,
            )
        if not pin_id.isdecimal() or len(client_identifier) > 255:
            return Response({"detail": "Invalid Plex authorization state."}, status=400)
        try:
            with MediaProviderSession() as session:
                response = session.get(
                    f"https://plex.tv/api/v2/pins/{pin_id}",
                    headers=_plex_headers(client_identifier),
                    timeout=20,
                )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return Response(
                {"detail": "Plex authorization status could not be checked."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        token = str(payload.get("authToken") or "").strip()
        if not token:
            return Response({"claimed": False})
        handle = uuid.uuid4().hex
        RedisClient.get_client().setex(
            f"media_library_plex_auth:{handle}",
            600,
            json.dumps({"token": token, "client_identifier": client_identifier}),
        )
        return Response(
            {
                "claimed": True,
                "credential_handle": handle,
                "expires_in": 600,
            }
        )

    @action(detail=False, methods=["post"], url_path="plex-auth/servers")
    def plex_auth_servers(self, request):
        handle = str(request.data.get("credential_handle") or "").strip()
        if not handle:
            return Response({"detail": "Credential handle is required."}, status=400)
        raw = RedisClient.get_client().get(f"media_library_plex_auth:{handle}")
        if not raw:
            return Response({"detail": "Credential handle expired."}, status=400)
        try:
            credential = json.loads(raw)
            with MediaProviderSession() as session:
                response = session.get(
                    "https://plex.tv/api/v2/resources",
                    params={"includeHttps": "1", "includeRelay": "0"},
                    headers=_plex_headers(
                        credential["client_identifier"],
                        credential["token"],
                    ),
                    timeout=25,
                )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return Response(
                {"detail": "Plex servers could not be discovered."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        servers = []
        for entry in payload if isinstance(payload, list) else []:
            if "server" not in str(entry.get("provides") or "").lower():
                continue
            connections = [
                {
                    "uri": str(connection.get("uri") or "").rstrip("/"),
                    "local": bool(connection.get("local")),
                    "relay": bool(connection.get("relay")),
                }
                for connection in (entry.get("connections") or [])
                if connection.get("uri") and not connection.get("relay")
            ]
            if not connections:
                continue
            preferred = next(
                (item for item in connections if item["local"]),
                connections[0],
            )
            server_handle = uuid.uuid4().hex
            RedisClient.get_client().setex(
                f"media_library_plex_auth:{server_handle}",
                600,
                json.dumps(
                    {
                        "token": str(
                            entry.get("accessToken")
                            or credential["token"]
                        ),
                        "client_identifier": credential["client_identifier"],
                    }
                ),
            )
            servers.append(
                {
                    "id": entry.get("clientIdentifier"),
                    "name": entry.get("name") or "Plex Server",
                    "base_url": preferred["uri"],
                    "connections": connections,
                    "credential_handle": server_handle,
                }
            )
        RedisClient.get_client().delete(f"media_library_plex_auth:{handle}")
        return Response({"servers": servers})


class MediaLibraryImportRunViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    AdminOnlyViewSet,
):
    queryset = MediaLibraryImportRun.objects.select_related("integration")
    serializer_class = MediaLibraryImportRunSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        source_id = (
            self.request.query_params.get("source")
            or self.request.query_params.get("integration")
        )
        if source_id:
            queryset = queryset.filter(integration_id=source_id)
        return queryset

    def destroy(self, request, *args, **kwargs):
        run = self.get_object()
        if run.status not in {
            MediaLibraryImportRun.Status.PENDING,
            MediaLibraryImportRun.Status.QUEUED,
        }:
            return Response(
                {"detail": "Only pending or queued imports can be removed."},
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        run = self.get_object()
        if run.status not in {
            MediaLibraryImportRun.Status.PENDING,
            MediaLibraryImportRun.Status.QUEUED,
            MediaLibraryImportRun.Status.RUNNING,
        }:
            return Response({"detail": "This import is no longer active."}, status=409)
        run.cancellation_requested_at = timezone.now()
        if run.status in {
            MediaLibraryImportRun.Status.PENDING,
            MediaLibraryImportRun.Status.QUEUED,
        }:
            run.status = MediaLibraryImportRun.Status.CANCELLED
        run.save()
        return Response(self.get_serializer(run).data)

    @action(detail=False, methods=["delete"])
    def purge(self, request):
        queryset = self.get_queryset().filter(
            status__in={
                MediaLibraryImportRun.Status.COMPLETED,
                MediaLibraryImportRun.Status.FAILED,
                MediaLibraryImportRun.Status.CANCELLED,
            }
        )
        deleted, _ = queryset.delete()
        return Response({"deleted": deleted})


class MediaLibraryExportTargetViewSet(viewsets.ModelViewSet):
    queryset = MediaLibraryExportTarget.objects.all()
    serializer_class = MediaLibraryExportTargetSerializer
    permission_classes = [IsAdmin]

    OUTPUT_AFFECTING_FIELDS = {
        "enabled",
        "output_root",
        "playback_base_url",
        "include_nfo",
    }

    @staticmethod
    def _has_active_export(target):
        return target.export_runs.filter(
            status__in=("pending", "queued", "running")
        ).exists()

    def update(self, request, *args, **kwargs):
        target = self.get_object()
        if self._has_active_export(target):
            return Response(
                {"detail": "Wait for the active export to finish first."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            return super().update(request, *args, **kwargs)
        except (DjangoValidationError, OSError, ValueError) as exc:
            messages = getattr(exc, "messages", None)
            return Response(
                {"detail": "; ".join(messages) if messages else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def perform_update(self, serializer):
        target = serializer.instance
        previous = {
            field: getattr(target, field)
            for field in self.OUTPUT_AFFECTING_FIELDS
        }
        next_output_root = serializer.validated_data.get(
            "output_root",
            previous["output_root"],
        )
        next_enabled = serializer.validated_data.get(
            "enabled",
            previous["enabled"],
        )
        updated = serializer.save()
        changed = any(
            getattr(updated, field) != previous[field]
            for field in self.OUTPUT_AFFECTING_FIELDS
        )

        cleanup_target = None
        if str(next_output_root) != str(previous["output_root"]):
            cleanup_target = SimpleNamespace(output_root=previous["output_root"])
        elif previous["enabled"] and not next_enabled:
            cleanup_target = SimpleNamespace(output_root=previous["output_root"])

        target_id = updated.id

        def finalize_target_change():
            if cleanup_target is not None:
                try:
                    remove_managed_export_files(cleanup_target)
                except (DjangoValidationError, OSError, ValueError):
                    logger.exception(
                        "Unable to remove the previous Media Library snapshot for target %s",
                        target_id,
                    )
            if changed and updated.enabled:
                current = MediaLibraryExportTarget.objects.filter(
                    id=target_id,
                    enabled=True,
                ).first()
                if current:
                    self._queue_export(current, "target-configuration-changed")

        transaction.on_commit(finalize_target_change)

    def destroy(self, request, *args, **kwargs):
        target = self.get_object()
        if self._has_active_export(target):
            return Response(
                {"detail": "Wait for the active export to finish first."},
                status=status.HTTP_409_CONFLICT,
            )
        cleanup_target = SimpleNamespace(output_root=target.output_root)
        response = super().destroy(request, *args, **kwargs)

        def cleanup_deleted_target():
            try:
                remove_managed_export_files(cleanup_target)
            except (DjangoValidationError, OSError, ValueError):
                logger.exception(
                    "Unable to remove the Media Library snapshot for deleted target %s",
                    target.id,
                )

        transaction.on_commit(cleanup_deleted_target)
        return response

    @staticmethod
    def _selection_queryset(content_type, params):
        if content_type == "movie":
            queryset = Movie.objects.filter(
                m3u_relations__m3u_account__is_active=True
            )
            relation_path = "m3u_relations"
        elif content_type == "series":
            queryset = Series.objects.filter(
                m3u_relations__m3u_account__is_active=True
            )
            relation_path = "m3u_relations"
        else:
            raise ValueError("content_type must be movie or series.")

        search = str(params.get("search") or "").strip()
        provider = params.get("provider")
        category = params.get("category")
        if provider not in (None, ""):
            try:
                provider = int(provider)
            except (TypeError, ValueError) as exc:
                raise ValueError("provider must be an integer.") from exc
        if category not in (None, ""):
            try:
                category = int(category)
            except (TypeError, ValueError) as exc:
                raise ValueError("category must be an integer.") from exc
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
                | Q(genre__icontains=search)
            )
        relation_filters = {}
        if provider:
            relation_filters[f"{relation_path}__m3u_account_id"] = provider
        if category:
            relation_filters[f"{relation_path}__category_id"] = category
        if relation_filters:
            # Apply both values through the same related row. Otherwise Django
            # may satisfy provider and category using two different relations.
            queryset = queryset.filter(**relation_filters)
        return queryset.distinct().order_by("name", "year", "id")

    @action(detail=True, methods=["get"], url_path="selection-catalog")
    def selection_catalog(self, request, pk=None):
        target = self.get_object()
        content_type = request.query_params.get("content_type", "movie")
        try:
            queryset = self._selection_queryset(content_type, request.query_params)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        selected_only = request.query_params.get("selected", "").lower()
        selected_manager = (
            target.selected_movies if content_type == "movie" else target.selected_series
        )
        if selected_only in {"true", "1"}:
            queryset = queryset.filter(pk__in=selected_manager.values("pk"))
        elif selected_only in {"false", "0"}:
            queryset = queryset.exclude(pk__in=selected_manager.values("pk"))

        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(10, int(request.query_params.get("page_size", 50))))
        except (TypeError, ValueError):
            return Response(
                {"detail": "page and page_size must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        total = queryset.count()
        rows = list(queryset[(page - 1) * page_size:page * page_size])
        page_ids = [row.id for row in rows]
        selected_ids = set(
            selected_manager.filter(id__in=page_ids).values_list("id", flat=True)
        )

        relation_model = (
            M3UMovieRelation if content_type == "movie" else M3USeriesRelation
        )
        relation_attr = "movie_id" if content_type == "movie" else "series_id"
        relations_by_item = {}
        for relation in relation_model.objects.filter(
            **{
                f"{relation_attr}__in": page_ids,
                "m3u_account__is_active": True,
            }
        ).select_related("m3u_account", "category"):
            relations_by_item.setdefault(getattr(relation, relation_attr), []).append(
                relation
            )

        items = []
        for row in rows:
            relations = relations_by_item.get(row.id, [])
            items.append(
                {
                    "id": row.id,
                    "uuid": str(row.uuid),
                    "name": row.name,
                    "year": row.year,
                    "genre": row.genre,
                    "poster": (
                        f"/api/vod/vodlogos/{row.logo_id}/cache/"
                        if row.logo_id
                        else ""
                    ),
                    "selected": row.id in selected_ids,
                    "providers": sorted(
                        {
                            (relation.m3u_account_id, relation.m3u_account.name)
                            for relation in relations
                        }
                    ),
                    "categories": sorted(
                        {
                            (relation.category_id, relation.category.name)
                            for relation in relations
                            if relation.category_id
                        }
                    ),
                }
            )
        return Response(
            {
                "results": items,
                "count": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
                "selected_count": selected_manager.count(),
            }
        )

    @action(detail=True, methods=["get"], url_path="selection-options")
    def selection_options(self, request, pk=None):
        self.get_object()
        providers = M3UAccount.objects.filter(
            is_active=True,
        ).filter(
            Q(movie_relations__isnull=False) | Q(series_relations__isnull=False)
        ).distinct().order_by("name")
        movie_categories = VODCategory.objects.filter(
            category_type="movie",
            m3umovierelation__m3u_account__is_active=True,
        ).distinct().order_by("name")
        series_categories = VODCategory.objects.filter(
            category_type="series",
            m3useriesrelation__m3u_account__is_active=True,
        ).distinct().order_by("name")
        return Response(
            {
                "providers": [
                    {"value": str(provider.id), "label": provider.name}
                    for provider in providers
                ],
                "movie_categories": [
                    {"value": str(category.id), "label": category.name}
                    for category in movie_categories
                ],
                "series_categories": [
                    {"value": str(category.id), "label": category.name}
                    for category in series_categories
                ],
            }
        )

    @action(detail=True, methods=["post"], url_path="selection")
    def update_selection(self, request, pk=None):
        target = self.get_object()
        content_type = request.data.get("content_type")
        operation = request.data.get("operation")
        if content_type not in {"movie", "series"}:
            return Response(
                {"detail": "content_type must be movie or series."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if operation not in {"select", "deselect", "clear"}:
            return Response(
                {"detail": "operation must be select, deselect, or clear."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        manager = target.selected_movies if content_type == "movie" else target.selected_series
        if operation == "clear":
            manager.clear()
            return Response({"selected_count": 0})

        raw_ids = request.data.get("ids")
        matching = request.data.get("matching") is True
        filters = {
            key: request.data.get(key)
            for key in ("search", "provider", "category")
            if request.data.get(key) not in (None, "")
        }
        if matching:
            if content_type == "series" and operation == "select" and not filters:
                return Response(
                    {
                        "detail": (
                            "Selecting every series is intentionally disabled. "
                            "Choose a provider, category, search, or individual series."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                queryset = self._selection_queryset(content_type, filters)
            except ValueError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            ids = list(queryset.values_list("id", flat=True))
        else:
            if not isinstance(raw_ids, list) or not raw_ids:
                return Response(
                    {"detail": "Provide one or more ids."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                requested_ids = {int(value) for value in raw_ids}
            except (TypeError, ValueError):
                return Response(
                    {"detail": "All ids must be integers."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            model = Movie if content_type == "movie" else Series
            ids = list(
                model.objects.filter(pk__in=requested_ids).values_list(
                    "id", flat=True
                )
            )
            if len(ids) != len(requested_ids):
                return Response(
                    {"detail": "One or more selected items no longer exist."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        for start in range(0, len(ids), 1000):
            batch = ids[start:start + 1000]
            if operation == "select":
                manager.add(*batch)
            else:
                manager.remove(*batch)
        return Response({"selected_count": manager.count(), "changed": len(ids)})

    @staticmethod
    def _queue_export(target, reason, *, refresh_series=False):
        try:
            run = MediaLibraryExportRun.objects.create(
                target=target,
                status=MediaLibraryExportRun.Status.QUEUED,
                reason=reason,
                message="Export queued.",
            )
        except IntegrityError:
            return None
        if refresh_series:
            result = refresh_selected_series_and_export.delay(
                target.id,
                run.id,
                reason,
            )
        else:
            result = export_media_library.delay(target.id, run.id)
        run.task_id = result.id or ""
        run.save(update_fields=["task_id", "updated_at"])
        return run

    @action(detail=True, methods=["post"])
    def export(self, request, pk=None):
        target = self.get_object()
        if not target.enabled:
            return Response(
                {"detail": "Enable this export target before starting an export."},
                status=status.HTTP_409_CONFLICT,
            )
        run = self._queue_export(target, "manual", refresh_series=True)
        if not run:
            return Response(
                {"detail": "An export is already active for this target."},
                status=409,
            )
        return Response(
            MediaLibraryExportRunSerializer(run).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="rotate-playback-id")
    def rotate_playback_id(self, request, pk=None):
        target = self.get_object()
        if target.export_runs.filter(
            status__in=("pending", "queued", "running")
        ).exists():
            return Response(
                {
                    "detail": (
                        "Wait for the active export to finish before rotating "
                        "the playback identifier."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        target.public_id = uuid.uuid4()
        target.save()
        run = self._queue_export(target, "playback-id-rotated")
        response = self.get_serializer(target).data
        response["export_run"] = MediaLibraryExportRunSerializer(run).data
        return Response(response)

    @action(detail=True, methods=["post"], url_path="cleanup-files")
    def cleanup_files(self, request, pk=None):
        target = self.get_object()
        if target.export_runs.filter(
            status__in=("pending", "queued", "running")
        ).exists():
            return Response(
                {"detail": "Wait for the active export to finish first."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            summary = remove_managed_export_files(target)
        except (OSError, ValueError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(summary)


class MediaLibraryExportRunViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    AdminOnlyViewSet,
):
    queryset = MediaLibraryExportRun.objects.select_related("target")
    serializer_class = MediaLibraryExportRunSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        target_id = self.request.query_params.get("target")
        if target_id:
            queryset = queryset.filter(target_id=target_id)
        return queryset

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        run = self.get_object()
        if run.status not in {
            MediaLibraryExportRun.Status.PENDING,
            MediaLibraryExportRun.Status.QUEUED,
            MediaLibraryExportRun.Status.RUNNING,
        }:
            return Response({"detail": "This export is no longer active."}, status=409)
        run.cancellation_requested_at = timezone.now()
        if run.status in {
            MediaLibraryExportRun.Status.PENDING,
            MediaLibraryExportRun.Status.QUEUED,
        }:
            run.status = MediaLibraryExportRun.Status.CANCELLED
        run.save()
        return Response(self.get_serializer(run).data)

    @action(detail=False, methods=["delete"])
    def purge(self, request):
        queryset = self.get_queryset().filter(
            status__in={
                MediaLibraryExportRun.Status.COMPLETED,
                MediaLibraryExportRun.Status.FAILED,
                MediaLibraryExportRun.Status.CANCELLED,
            }
        )
        deleted, _ = queryset.delete()
        return Response({"deleted": deleted})
