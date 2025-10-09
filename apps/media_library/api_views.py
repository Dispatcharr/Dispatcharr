import logging
import os
from pathlib import Path

from django.conf import settings
from django.core.signing import TimestampSigner
from django.db.models import Prefetch, Q
from django.urls import reverse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, ValidationError

from apps.accounts.permissions import Authenticated
from apps.media_library import models, serializers
from apps.media_library.metadata import sync_metadata
from apps.media_library.tasks import (
    enqueue_library_scan,
    sync_metadata_task,
    cancel_library_scan,
    revoke_scan_task,
    start_next_library_scan,
    sync_library_to_vod_task,
    unsync_library_from_vod_task,
)
from apps.media_library.vod_sync import unsync_library_from_vod

logger = logging.getLogger(__name__)


class LibraryViewSet(viewsets.ModelViewSet):
    queryset = models.Library.objects.all().prefetch_related("locations")
    serializer_class = serializers.LibrarySerializer
    permission_classes = [Authenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_fields = ["library_type", "auto_scan_enabled"]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at", "updated_at", "last_scan_at"]
    ordering = ["name"]

    @action(detail=False, methods=["get"], url_path="browse")
    def browse(self, request):
        raw_path = request.query_params.get("path")

        if not raw_path:
            if os.name == "nt":
                import string

                entries = []
                for letter in string.ascii_uppercase:
                    drive = Path(f"{letter}:/")
                    if drive.exists():
                        entries.append(
                            {
                                "name": f"{letter}:",
                                "path": str(drive.resolve()),
                            }
                        )
                return Response({"path": "", "parent": None, "entries": entries})

            root = Path("/").resolve()
            entries = []
            try:
                for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                    if child.is_dir():
                        entries.append(
                            {
                                "name": child.name or str(child),
                                "path": str(child),
                            }
                        )
            except PermissionError:
                entries = []

            return Response({"path": str(root), "parent": None, "entries": entries})

        try:
            target = Path(raw_path).expanduser()
            if not target.exists():
                raise ValidationError({"detail": "Directory not found."})
            if not target.is_dir():
                target = target.parent
            target = target.resolve()
        except (ValueError, OSError, RuntimeError):
            raise ValidationError({"detail": "Invalid path."})

        entries = []
        try:
            for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                if child.is_dir():
                    entries.append(
                        {
                            "name": child.name or str(child),
                            "path": str(child),
                        }
                    )
        except PermissionError:
            entries = []

        parent = str(target.parent) if target != target.parent else None
        return Response(
            {
                "path": str(target),
                "parent": parent,
                "entries": entries,
            }
        )

    def perform_create(self, serializer):
        library = serializer.save()
        if library.auto_scan_enabled:
            enqueue_library_scan(library_id=library.id, user_id=self.request.user.id)

    def perform_update(self, serializer):
        previous_use_as_vod = bool(serializer.instance.use_as_vod_source)
        library = serializer.save()
        if previous_use_as_vod != library.use_as_vod_source:
            if library.use_as_vod_source:
                sync_library_to_vod_task.delay(library.id)
            else:
                unsync_library_from_vod_task.delay(library.id)
        if library.auto_scan_enabled and self.request.data.get("trigger_scan"):
            enqueue_library_scan(library_id=library.id, user_id=self.request.user.id)

    def perform_destroy(self, instance):
        from django.db import transaction

        with transaction.atomic():
            unsync_library_from_vod(instance)
            models.MediaItem.objects.filter(library=instance).delete()
            models.MediaFile.objects.filter(library=instance).delete()
            super().perform_destroy(instance)

    @action(detail=True, methods=["post"], url_path="scan")
    def scan(self, request, pk=None):
        library = self.get_object()
        user_id = request.user.id if request.user and request.user.is_authenticated else None
        scan = enqueue_library_scan(library_id=library.id, user_id=user_id, force_full=request.data.get("full", False))
        serializer = serializers.LibraryScanSerializer(scan)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)


class LibraryScanViewSet(mixins.DestroyModelMixin, viewsets.ReadOnlyModelViewSet):
    queryset = models.LibraryScan.objects.select_related("library", "created_by")
    serializer_class = serializers.LibraryScanSerializer
    permission_classes = [Authenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["library", "status"]
    ordering_fields = ["created_at", "started_at", "finished_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "head", "options", "delete", "post"]

    def destroy(self, request, *args, **kwargs):
        scan = self.get_object()

        if scan.status == models.LibraryScan.STATUS_RUNNING:
            raise ValidationError({"detail": "Cannot remove a running scan."})

        if scan.status == models.LibraryScan.STATUS_PENDING:
            revoke_scan_task(scan.task_id, terminate=False)
            library = scan.library
            response = super().destroy(request, *args, **kwargs)
            start_next_library_scan(library)
            return response

        response = super().destroy(request, *args, **kwargs)
        return response

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        scan = self.get_object()
        summary = request.data.get("summary")
        try:
            cancelled = cancel_library_scan(scan, summary=summary)
        except ValueError as exc:  # noqa: BLE001
            raise ValidationError({"detail": str(exc)})

        serializer = self.get_serializer(cancelled)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["delete"], url_path="purge")
    def purge_completed(self, request):
        valid_statuses = {
            models.LibraryScan.STATUS_COMPLETED,
            models.LibraryScan.STATUS_FAILED,
            models.LibraryScan.STATUS_CANCELLED,
        }
        requested_statuses = request.query_params.getlist("status")
        if requested_statuses:
            statuses = [value for value in requested_statuses if value in valid_statuses]
            if not statuses:
                raise ValidationError({"detail": "No valid statuses provided."})
        else:
            statuses = list(valid_statuses)

        queryset = self.filter_queryset(
            self.get_queryset().filter(status__in=statuses)
        )
        library_id = request.query_params.get("library")
        if library_id:
            queryset = queryset.filter(library_id=library_id)

        deleted, _ = queryset.delete()
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


class MediaItemViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.MediaItemSerializer
    permission_classes = [Authenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = [
        "library",
        "item_type",
        "status",
        "release_year",
        "season_number",
        "parent",
    ]
    search_fields = ["title", "synopsis", "tags"]
    ordering_fields = [
        "sort_title",
        "release_year",
        "first_imported_at",
        "updated_at",
        "season_number",
        "episode_number",
    ]
    ordering = ["sort_title"]
    http_method_names = ["get", "head", "options", "patch", "post"]
    pagination_class = None
    _stream_signer = TimestampSigner(salt="media-library-stream")

    def get_serializer_class(self):
        if self.action == "list":
            return serializers.MediaItemListSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            watch_prefetch = Prefetch(
                "watch_progress",
                queryset=models.WatchProgress.objects.filter(user=user),
                to_attr="_user_watch_progress",
            )
            episode_watch_prefetch = Prefetch(
                "watch_progress",
                queryset=models.WatchProgress.objects.filter(user=user),
                to_attr="_user_watch_progress",
            )
        else:
            watch_prefetch = Prefetch(
                "watch_progress",
                queryset=models.WatchProgress.objects.none(),
                to_attr="_user_watch_progress",
            )
            episode_watch_prefetch = Prefetch(
                "watch_progress",
                queryset=models.WatchProgress.objects.none(),
                to_attr="_user_watch_progress",
            )

        base_queryset = models.MediaItem.objects.select_related(
            "library",
            "parent",
            "vod_movie",
            "vod_series",
            "vod_episode",
        )

        if self.action == "list":
            children_qs = (
                models.MediaItem.objects.filter(item_type=models.MediaItem.TYPE_EPISODE)
                .select_related("parent")
                .prefetch_related(episode_watch_prefetch)
                .order_by("season_number", "episode_number", "id")
            )
            return base_queryset.prefetch_related(
                watch_prefetch,
                Prefetch(
                    "children",
                    queryset=children_qs,
                    to_attr="_prefetched_children",
                ),
            )

        return base_queryset.prefetch_related("files", "artwork", watch_prefetch)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        search = self.request.query_params.get("search")
        if search:
            search = search.strip()
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(synopsis__icontains=search)
                | Q(tags__icontains=search)
            )
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def partial_update(self, request, *args, **kwargs):
        allowed_fields = {
            "title",
            "release_year",
            "synopsis",
            "tagline",
            "genres",
            "studios",
            "cast",
            "crew",
            "tags",
            "poster_url",
            "backdrop_url",
            "rating",
            "tmdb_id",
            "imdb_id",
            "runtime_ms",
            "metadata",
            "status",
        }
        unknown = {key for key in request.data.keys() if key not in allowed_fields}
        if unknown:
            raise ValidationError(
                {"detail": f"Cannot update fields: {', '.join(sorted(unknown))}"}
            )
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="refresh-metadata")
    def refresh_metadata(self, request, pk=None):
        item = self.get_object()
        sync_metadata_task.delay(item.id)
        return Response({"status": "queued"}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="set-tmdb")
    def set_tmdb(self, request, pk=None):
        item = self.get_object()
        tmdb_id = request.data.get("tmdb_id")
        if tmdb_id in (None, ""):
            raise ValidationError({"tmdb_id": "TMDB ID is required."})

        tmdb_id_str = str(tmdb_id).strip()
        if not tmdb_id_str:
            raise ValidationError({"tmdb_id": "TMDB ID is required."})

        if item.tmdb_id != tmdb_id_str:
            item.tmdb_id = tmdb_id_str
            item.save(update_fields=["tmdb_id", "updated_at"])

        refreshed = sync_metadata(item)
        if not refreshed:
            raise ValidationError(
                {"detail": "Unable to fetch TMDB metadata for this item."}
            )

        serializer = self.get_serializer(refreshed)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="stream")
    def stream(self, request, pk=None):
        item = self.get_object()
        file_id = request.query_params.get("file")
        files_qs = item.files.all()
        if file_id:
            file = files_qs.filter(pk=file_id).first()
            if not file:
                raise NotFound("Requested media file not found")
        else:
            file = files_qs.order_by("id").first()
        if not file:
            return Response(
                {"detail": "No media files available for this item."},
                status=status.HTTP_404_NOT_FOUND,
            )

        start_ms = 0
        start_ms_param = request.query_params.get("start_ms")
        if start_ms_param not in (None, "", "0"):
            try:
                start_ms = max(0, int(start_ms_param))
            except (TypeError, ValueError):
                raise ValidationError({"start_ms": "Start offset must be an integer number of milliseconds."})

        applied_start_ms = 0
        should_embed_start = False
        if start_ms > 0 and file.requires_transcode:
            cached_ready = (
                file.transcode_status == models.MediaFile.TRANSCODE_STATUS_READY
                and file.transcoded_path
                and os.path.exists(file.transcoded_path)
            )
            if not cached_ready:
                applied_start_ms = start_ms
                should_embed_start = True

        duration_ms = file.effective_duration_ms or item.runtime_ms or 0

        payload = {"file_id": file.id, "user_id": request.user.id}
        if should_embed_start:
            payload["start_ms"] = applied_start_ms

        token = self._stream_signer.sign_object(payload)
        stream_url = request.build_absolute_uri(
            reverse("api:media:stream-file", args=[token])
        )
        ttl = getattr(settings, "MEDIA_LIBRARY_STREAM_TOKEN_TTL", 3600)
        return Response(
            {
                "url": stream_url,
                "file_id": file.id,
                "expires_in": ttl,
                "type": "direct",
                "duration_ms": duration_ms,
                "bit_rate": file.bit_rate,
                "container": file.container,
                "requires_transcode": file.requires_transcode,
                "transcode_status": file.transcode_status,
                "start_offset_ms": applied_start_ms,
            }
        )

    @action(detail=True, methods=["post"], url_path="mark-watched")
    def mark_watched(self, request, pk=None):
        item = self.get_object()
        duration = item.runtime_ms
        if not duration:
            primary_file = item.files.order_by("-duration_ms").first()
            duration = primary_file.duration_ms if primary_file else 0
        if not duration:
            duration = 1000  # default to one second to allow completion state

        progress, _ = models.WatchProgress.objects.update_or_create(
            user=request.user,
            media_item=item,
            defaults={
                "position_ms": duration or 0,
                "duration_ms": duration or 0,
                "completed": True,
            },
        )
        progress.update_progress(position_ms=duration or 0, duration_ms=duration or 0)
        return Response({"status": "ok"})

    @action(detail=True, methods=["post"], url_path="mark-series-watched")
    def mark_series_watched(self, request, pk=None):
        item = self.get_object()
        if item.item_type != models.MediaItem.TYPE_SHOW:
            return Response(
                {"detail": "Series-level actions are only available for shows."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        episodes = item.children.filter(item_type=models.MediaItem.TYPE_EPISODE)
        updated = 0
        for episode in episodes:
            duration = episode.runtime_ms
            if not duration:
                primary_file = episode.files.order_by("-duration_ms").first()
                duration = primary_file.duration_ms if primary_file else 0
            if not duration:
                duration = 1000
            models.WatchProgress.objects.update_or_create(
                user=request.user,
                media_item=episode,
                defaults={
                    "position_ms": duration,
                    "duration_ms": duration,
                    "completed": True,
                },
            )
            updated += 1

        models.WatchProgress.objects.update_or_create(
            user=request.user,
            media_item=item,
            defaults={
                "position_ms": 0,
                "duration_ms": item.runtime_ms or 0,
                "completed": True,
            },
        )

        serializer = self.get_serializer(item)
        return Response({"updated": updated, "item": serializer.data})

    @action(detail=True, methods=["post"], url_path="mark-series-unwatched")
    def mark_series_unwatched(self, request, pk=None):
        item = self.get_object()
        if item.item_type != models.MediaItem.TYPE_SHOW:
            return Response(
                {"detail": "Series-level actions are only available for shows."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        episodes = item.children.filter(item_type=models.MediaItem.TYPE_EPISODE)
        cleared, _ = models.WatchProgress.objects.filter(
            user=request.user,
            media_item__in=episodes,
        ).delete()
        models.WatchProgress.objects.filter(user=request.user, media_item=item).delete()
        serializer = self.get_serializer(item)
        return Response({"cleared": cleared, "item": serializer.data})

    @action(detail=True, methods=["post"], url_path="clear-progress")
    def clear_progress(self, request, pk=None):
        item = self.get_object()
        models.WatchProgress.objects.filter(user=request.user, media_item=item).delete()
        return Response({"status": "cleared"})


class MediaFileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.MediaFile.objects.select_related("library", "media_item", "location")
    serializer_class = serializers.MediaFileSerializer
    permission_classes = [Authenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["library", "media_item", "location", "has_subtitles"]
    search_fields = ["relative_path", "file_name", "absolute_path"]
    ordering_fields = ["relative_path", "file_name", "size_bytes", "updated_at", "last_seen_at"]
    ordering = ["relative_path"]


class WatchProgressViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = serializers.WatchProgressSerializer
    permission_classes = [Authenticated]

    def get_queryset(self):
        queryset = models.WatchProgress.objects.select_related("media_item", "user")
        user_only = self.request.query_params.get("mine", "true").lower() != "false"
        if user_only:
            queryset = queryset.filter(user=self.request.user)
        return queryset

    @action(detail=False, methods=["post"], url_path="set")
    def set_progress(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        progress = serializer.save()
        progress.update_progress(
            position_ms=serializer.validated_data.get("position_ms", 0),
            duration_ms=serializer.validated_data.get("duration_ms"),
        )
        return Response(self.get_serializer(progress).data)

    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, pk=None):
        progress = self.get_object()
        if progress.duration_ms:
            percentage = progress.position_ms / progress.duration_ms
        else:
            percentage = 0
        remaining_ms = max(progress.duration_ms - progress.position_ms, 0)
        data = {
            "position_ms": progress.position_ms,
            "duration_ms": progress.duration_ms,
            "percentage": percentage,
            "remaining_ms": remaining_ms,
            "completed": progress.completed,
            "resume_allowed": progress.duration_ms * 0.04 < remaining_ms,
        }
        return Response(data)
