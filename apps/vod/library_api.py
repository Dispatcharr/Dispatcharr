"""Focused Library API layered on the part 2 source/identity contract."""

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin, IsStandardUser, permissions_for_action

from . import library
from .library_serializers import (
    LibraryBulkSerializer,
    LibraryCanonicalTargetsSerializer,
    LibraryCategoryCleanupSerializer,
    LibraryCleanupPreviewSerializer,
    LibraryConnectionStatusSerializer,
    LibraryConnectionTestSerializer,
    LibraryContentPatchSerializer,
    LibraryDetailRequestSerializer,
    LibraryDetailSerializer,
    LibraryFilterSerializer,
    LibraryItemSerializer,
    LibraryLookupSerializer,
    LibraryMatchSerializer,
    LibraryOptionsSerializer,
    LibraryPreviewSerializer,
    LibraryResultSerializer,
    LibrarySettingsSerializer,
    LibrarySettingsUpdateSerializer,
    LibrarySourcePatchSerializer,
    LibraryStateSerializer,
)
from .metadata import validate_source_metadata
from .models import M3UVODCategoryRelation, Movie, VODCategory, VODMetadataState
from .title_cleanup import normalize_group_title_cleanup
from .tmdb import TMDBError
from .utils import is_vod_movies_enabled, is_vod_series_enabled


class LibraryPagination(PageNumberPagination):
    page_size = 24
    page_size_query_param = "page_size"
    max_page_size = 100


def validated(serializer_type, data):
    serializer = serializer_type(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def safely(callback):
    try:
        return callback()
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except TMDBError as exc:
        raise ValidationError(
            "TMDB could not complete the request. Check the token or try again later."
        ) from exc


class VODLibraryViewSet(viewsets.GenericViewSet):
    queryset = Movie.objects.none()
    serializer_class = LibraryItemSerializer
    pagination_class = LibraryPagination
    permission_classes = [IsAdmin]

    def get_permissions(self):
        return permissions_for_action(self)

    def finalize_response(self, request, response, *args, **kwargs):
        # Prepared profile catalogues depend on source metadata and title flags.
        if self.action in {"content", "source_metadata", "tmdb_match"} and (
            response.status_code < 400
        ):
            from .profile_catalog import request_catalog_build

            request_catalog_build()
        return super().finalize_response(request, response, *args, **kwargs)

    @extend_schema(
        parameters=[LibraryFilterSerializer], responses=LibraryItemSerializer(many=True)
    )
    def list(self, request):
        raw = {
            key: value
            for key, value in request.query_params.items()
            if key not in {"page", "page_size", "format"}
        }
        filters = validated(LibraryFilterSerializer, raw)
        sources = filters.get("view") == "sources"
        if sources and request.user.user_level < 10:
            raise PermissionDenied("Only administrators can inspect provider sources.")
        if request.user.user_level < 10:
            filters["_hide_blocked"] = True
        allowed = []
        if is_vod_movies_enabled(user=request.user):
            allowed.append("movie")
        if is_vod_series_enabled(user=request.user):
            allowed.append("series")
        if request.user.user_level < 10 and (request.user.custom_properties or {}).get(
            "hide_adult_content"
        ):
            filters["_hide_adult"] = True
        queryset = library.library_query(filters, sources=sources, allowed=allowed)
        page = self.paginate_queryset(queryset)
        rows = library.page_documents(page, request, sources=sources, filters=filters)
        return self.get_paginated_response(LibraryItemSerializer(rows, many=True).data)

    @extend_schema(
        parameters=[LibraryDetailRequestSerializer], responses=LibraryDetailSerializer
    )
    @action(
        permission_classes=[IsStandardUser],
        detail=False,
        methods=["get"],
        url_path="details",
    )
    def details(self, request):
        from .library_preview import detail_document

        data = validated(LibraryDetailRequestSerializer, request.query_params)
        enabled = (
            is_vod_movies_enabled
            if data["content_type"] == "movie"
            else is_vod_series_enabled
        )
        if not enabled(user=request.user):
            raise Http404("This content type is not available.")
        hidden = request.user.user_level < 10 and bool(
            (request.user.custom_properties or {}).get("hide_adult_content")
        )
        return Response(
            LibraryDetailSerializer(
                detail_document(data, request, hide_adult=hidden)
            ).data
        )

    @extend_schema(
        parameters=[LibraryFilterSerializer], responses=LibraryOptionsSerializer
    )
    @action(
        permission_classes=[IsStandardUser],
        detail=False,
        methods=["get"],
        url_path="options",
    )
    def filter_options(self, request):
        filters = validated(LibraryFilterSerializer, request.query_params)
        filters = {
            key: value
            for key, value in filters.items()
            if key in {"type", "account", "category"}
        }
        if request.user.user_level < 10:
            filters["_hide_blocked"] = True
        if request.user.user_level < 10 and (request.user.custom_properties or {}).get(
            "hide_adult_content"
        ):
            filters["_hide_adult"] = True
        allowed = []
        if is_vod_movies_enabled(user=request.user):
            allowed.append("movie")
        if is_vod_series_enabled(user=request.user):
            allowed.append("series")
        category_query = VODCategory.objects.filter(
            m3u_relations__m3u_account__is_active=True, category_type__in=allowed
        )
        if request.user.user_level < 10:
            from django.db.models import Q

            category_query = category_query.filter(
                Q(category_type="movie", m3umovierelation__movie__library_blocked=False)
                | Q(
                    category_type="series",
                    m3useriesrelation__series__library_blocked=False,
                )
            )
        categories = list(
            category_query.values("id", "name", "category_type")
            .distinct()
            .order_by("name", "id")
        )
        from .library_filters import available_values

        metadata = available_values(
            (kind, library.relation_queryset(kind, filters))
            for kind in allowed
            if filters.get("type", "all") in {"all", kind}
        )
        return Response(
            LibraryOptionsSerializer(
                {
                    "accounts": library.available_accounts(filters, allowed),
                    "categories": categories,
                    "totals": library.title_totals(filters, allowed),
                    **metadata,
                }
            ).data
        )

    @extend_schema(methods=["GET"], responses=LibrarySettingsSerializer)
    @extend_schema(
        methods=["PUT"],
        request=LibrarySettingsUpdateSerializer,
        responses=LibrarySettingsSerializer,
    )
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["get", "put"],
        url_path="settings",
        url_name="settings",
    )
    def metadata_settings(self, request):
        if request.method == "PUT":
            from .library_connection import check_connection, remember_connection

            data = validated(LibrarySettingsUpdateSerializer, request.data)
            credential_changed = bool(
                data.get("api_token") or data.get("clear_api_token")
            )
            if (
                credential_changed
                and library.library_settings()["token_source"] == "environment"
            ):
                raise ValidationError(
                    {"api_token": "The server environment controls this credential."}
                )
            check = None
            if data.get("api_token") and not data.get("clear_api_token"):
                check = check_connection(data["api_token"])
                if check["status"] != "connected":
                    remember_connection(data["api_token"], check)
                    raise ValidationError({"api_token": check["detail"]})
            safely(lambda: library.save_library_settings(data))
            if check:
                remember_connection(data["api_token"], check)
        return Response(LibrarySettingsSerializer(library.library_settings()).data)

    @extend_schema(
        request=LibraryConnectionTestSerializer,
        responses=LibraryConnectionStatusSerializer,
    )
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["post"],
        url_path="test-connection",
    )
    def test_connection(self, request):
        from .library_connection import check_connection, remember_connection

        data = validated(LibraryConnectionTestSerializer, request.data)
        token = data.get(
            "api_token", library.library_settings(private=True)["api_token"]
        )
        if not token:
            raise ValidationError({"api_token": "Enter a TMDB credential first."})
        result = check_connection(token)
        remember_connection(token, result)
        return Response(LibraryConnectionStatusSerializer(result).data)

    @extend_schema(responses=LibraryStateSerializer)
    @action(permission_classes=[IsAdmin], detail=False, methods=["get"])
    def state(self, request):
        return Response(LibraryStateSerializer(library.state_payload()).data)

    @extend_schema(request=None, responses=LibraryStateSerializer)
    @action(
        permission_classes=[IsAdmin], detail=False, methods=["post"], url_path="cancel"
    )
    def cancel_job(self, request):
        with transaction.atomic():
            state = VODMetadataState.objects.select_for_update().filter(pk=1).first()
            if state and state.status in {"queued", "running"}:
                state.status = "cancelled"
                state.completed_at = timezone.now()
                state.save(update_fields=["status", "completed_at", "updated_at"])
        return Response(LibraryStateSerializer(library.state_payload()).data)

    @extend_schema(request=None, responses=LibraryStateSerializer)
    @action(
        permission_classes=[IsAdmin], detail=False, methods=["post"], url_path="resume"
    )
    def resume_job(self, request):
        with transaction.atomic():
            state = get_object_or_404(
                VODMetadataState.objects.select_for_update(), pk=1
            )
            if state.status not in {"cancelled", "failed"}:
                raise ValidationError("Only a cancelled or failed job can be resumed.")
            refs = state.selection[state.progress.get("processed", 0) :]
            result = safely(
                lambda: library.queue_library_job(
                    state.progress["operation"],
                    refs,
                    include_protected=state.progress.get("include_protected", False),
                    job_settings=state.progress.get("settings"),
                )
            )
        return Response(
            LibraryStateSerializer(result).data, status=status.HTTP_202_ACCEPTED
        )

    @extend_schema(
        request=LibraryCleanupPreviewSerializer, responses=LibraryPreviewSerializer
    )
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["post"],
        url_path="cleanup-preview",
        url_name="cleanup-preview",
    )
    def preview_cleanup(self, request):
        data = validated(LibraryCleanupPreviewSerializer, request.data)
        return Response(
            LibraryPreviewSerializer(
                safely(lambda: library.preview_cleanup_request(data))
            ).data
        )

    @extend_schema(request=LibraryBulkSerializer, responses=LibraryResultSerializer)
    @action(
        permission_classes=[IsAdmin], detail=False, methods=["post"], url_path="bulk"
    )
    def bulk(self, request):
        data = validated(LibraryBulkSerializer, request.data)
        refs = library.selected_content(data)
        if data["operation"] in {"enrich", "cleanup"}:
            state = safely(
                lambda: library.queue_library_job(
                    data["operation"],
                    refs,
                    include_protected=data["include_protected"],
                    job_settings={
                        **{
                            key: data[key]
                            for key in ("title_rules", "removal_rules", "year_rules")
                            if key in data
                        },
                        **(
                            {"match_missing": data["search_missing"]}
                            if "search_missing" in data
                            else {}
                        ),
                    },
                )
            )
            return Response(
                LibraryResultSerializer({"count": len(refs), "state": state}).data,
                status=status.HTTP_202_ACCEPTED,
            )
        changed = 0
        with transaction.atomic():
            for kind in library.KINDS:
                qs = library.model_for(kind).objects.filter(
                    pk__in=[pk for selected_kind, pk in refs if selected_kind == kind]
                )
                if data["operation"] == "reset":
                    changed += qs.update(
                        display_name="",
                        clean_title="",
                        tmdb_metadata={},
                        tmdb_status="",
                        tmdb_match_id="",
                        tmdb_imdb_id="",
                        tmdb_poster_url="",
                        tmdb_backdrop_url="",
                        tmdb_enriched_at=None,
                        tmdb_lookup_excluded=False,
                    )
                elif data["operation"] in {"block", "unblock"}:
                    changed += qs.update(library_blocked=data["operation"] == "block")
                else:
                    changed += qs.update(
                        tmdb_lookup_excluded=data["operation"] == "lock"
                    )
        return Response(LibraryResultSerializer({"count": changed}).data)

    @extend_schema(
        request=LibraryContentPatchSerializer, responses=LibraryResultSerializer
    )
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["patch"],
        url_path="content",
    )
    def content(self, request):
        data = validated(LibraryContentPatchSerializer, request.data)
        metadata = None
        if data.get("tmdb_id"):
            get_object_or_404(library.model_for(data["content_type"]), pk=data["id"])
            client = safely(library.tmdb_client)
            metadata = safely(
                lambda: client.details(
                    data["tmdb_id"],
                    data["content_type"],
                    library.library_settings()["languages"],
                    match_method="manual",
                )
            )
        return Response(
            LibraryResultSerializer(
                {"metadata": safely(lambda: library.update_content(data, metadata))}
            ).data
        )

    @extend_schema(
        parameters=[LibraryLookupSerializer],
        responses=LibraryCanonicalTargetsSerializer,
    )
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["get"],
        url_path="canonical-targets",
    )
    def canonical_targets(self, request):
        data = validated(LibraryLookupSerializer, request.query_params)
        return Response(
            LibraryCanonicalTargetsSerializer(
                {"results": library.canonical_targets(data)}
            ).data
        )

    @extend_schema(request=LibraryLookupSerializer, responses=LibraryResultSerializer)
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["post"],
        url_path="tmdb-lookup",
    )
    def tmdb_lookup(self, request):
        data = validated(LibraryLookupSerializer, request.data)
        settings = library.library_settings()
        client = safely(library.tmdb_client)
        if data.get("tmdb_id"):
            result = safely(
                lambda: client.details(
                    data["tmdb_id"],
                    data["content_type"],
                    settings["languages"],
                    match_method="manual-preview",
                )
            )
            return Response(LibraryResultSerializer({"metadata": result}).data)
        rows = safely(
            lambda: client.search_candidates(
                data["query"],
                data.get("year"),
                data["content_type"],
                settings["languages"],
            )
        )
        return Response(LibraryResultSerializer({"results": rows}).data)

    @extend_schema(request=LibraryMatchSerializer, responses=LibraryResultSerializer)
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["post"],
        url_path="tmdb-match",
    )
    def tmdb_match(self, request):
        data = validated(LibraryMatchSerializer, request.data)
        settings = library.library_settings()
        client = safely(library.tmdb_client)
        metadata = safely(
            lambda: client.details(
                data["tmdb_id"],
                data["content_type"],
                settings["languages"],
                match_method="manual",
            )
        )
        if data["source"]:
            get_object_or_404(
                library.model_for(data["content_type"], source=True), pk=data["id"]
            )
            item = safely(
                lambda: library.move_source_to_tmdb(
                    data["content_type"], data["id"], metadata
                )
            )
        else:
            item = get_object_or_404(
                library.model_for(data["content_type"]), pk=data["id"]
            )
            item = safely(lambda: library.apply_tmdb(item, metadata))
        return Response(
            LibraryResultSerializer({"metadata": library.canonical_document(item)}).data
        )

    @extend_schema(
        request=LibrarySourcePatchSerializer, responses=LibraryResultSerializer
    )
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["patch"],
        url_path="source-metadata",
    )
    def source_metadata(self, request):
        data = validated(LibrarySourcePatchSerializer, request.data)
        patch = safely(
            lambda: validate_source_metadata(
                data.get("manual_metadata", {}), allow_reset=True
            )
        )
        if data.get("all_matching"):
            refs = library.selected_content(data, sources=True)
            with transaction.atomic():
                count = library.patch_selected_sources(refs, patch)
            return Response(LibraryResultSerializer({"count": count}).data)
        metadata = None
        for kind in {row["content_type"] for row in data["items"]}:
            ids = {row["id"] for row in data["items"] if row["content_type"] == kind}
            if library.model_for(kind, source=True).objects.filter(
                pk__in=ids
            ).count() != len(ids):
                raise Http404("One or more selected sources were not found.")
        if data.get("tmdb_id"):
            settings = library.library_settings()
            metadata = safely(
                lambda: library.tmdb_client().details(
                    data["tmdb_id"],
                    data["items"][0]["content_type"],
                    settings["languages"],
                    match_method="manual",
                )
            )
        count = 0
        with transaction.atomic():
            for ref in data["items"]:
                source = get_object_or_404(
                    library.model_for(
                        ref["content_type"], source=True
                    ).objects.select_for_update(),
                    pk=ref["id"],
                )
                if metadata:
                    safely(
                        lambda ref=ref, source_pk=source.pk: library.move_source_to_tmdb(
                            ref["content_type"], source_pk, metadata
                        )
                    )
                    source.refresh_from_db()
                elif data.get("target_id") or data["create_from_provider"]:
                    safely(
                        lambda ref=ref, source_pk=source.pk: library.move_source_to_content(
                            ref["content_type"],
                            source_pk,
                            target_id=data.get("target_id"),
                            create_from_provider=data["create_from_provider"],
                            title_name=data.get("title_name"),
                            title_year=data.get("title_year"),
                        )
                    )
                    source.refresh_from_db()
                manual = dict(source.manual_metadata or {})
                for field, value in patch.items():
                    if value is None:
                        manual.pop(field, None)
                    else:
                        manual[field] = value
                source.manual_metadata = manual
                source.save(update_fields=["manual_metadata"])
                count += 1
        result = {"count": count}
        if count == 1:
            source = (
                library.model_for(data["items"][0]["content_type"], source=True)
                .objects.select_related(data["items"][0]["content_type"])
                .get(pk=data["items"][0]["id"])
            )
            result["metadata"] = library.canonical_document(
                getattr(source, data["items"][0]["content_type"])
            )
        return Response(LibraryResultSerializer(result).data)

    @extend_schema(
        request=LibraryCategoryCleanupSerializer, responses=LibraryResultSerializer
    )
    @action(
        permission_classes=[IsAdmin],
        detail=False,
        methods=["patch"],
        url_path="category-cleanup",
    )
    def category_cleanup(self, request):
        data = validated(LibraryCategoryCleanupSerializer, request.data)
        cleanup = safely(lambda: normalize_group_title_cleanup(data["title_cleanup"]))
        with transaction.atomic():
            relation = get_object_or_404(
                M3UVODCategoryRelation.objects.select_for_update(),
                category_id=data["category"],
                m3u_account_id=data["account"],
            )
            relation.custom_properties = {
                **(relation.custom_properties or {}),
                "title_cleanup": cleanup,
            }
            relation.save(update_fields=["custom_properties"])
        return Response(LibraryResultSerializer({"count": 1}).data)
