import os
from django.utils import timezone
from django.urls import reverse
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.permissions import Authenticated, IsAdmin, permission_classes_by_action
from apps.media_library.models import Library, LibraryScan, MediaFile, MediaItem, WatchProgress
from apps.media_library.serializers import (
    LibraryScanSerializer,
    LibrarySerializer,
    MediaItemDetailSerializer,
    MediaItemSerializer,
    MediaItemUpdateSerializer,
)
from apps.media_library.tasks import refresh_media_item_metadata, scan_library
from apps.media_library.vod import sync_library_vod_account_state, sync_vod_for_media_item


class MediaLibraryPagination(PageNumberPagination):
    page_size = 200
    page_size_query_param = "limit"
    max_page_size = 1000

    def get_page_size(self, request):
        if "limit" not in request.query_params and "page" not in request.query_params:
            return None
        return super().get_page_size(request)


class LibraryViewSet(viewsets.ModelViewSet):
    queryset = Library.objects.prefetch_related("locations")
    serializer_class = LibrarySerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def perform_create(self, serializer):
        library = serializer.save()
        sync_library_vod_account_state(library)

    def perform_update(self, serializer):
        library = serializer.save()
        sync_library_vod_account_state(library)

    @action(detail=True, methods=["post"], url_path="scan")
    def start_scan(self, request, pk=None):
        library = self.get_object()
        full = bool(request.data.get("full", False))
        scan = LibraryScan.objects.create(
            library=library,
            scan_type=LibraryScan.SCAN_FULL if full else LibraryScan.SCAN_QUICK,
            status=LibraryScan.STATUS_QUEUED,
            summary="Full scan" if full else "Quick scan",
            stages={},
        )
        task = scan_library.delay(library.id, full=full, scan_id=scan.id)
        scan.task_id = task.id
        scan.save(update_fields=["task_id", "updated_at"])
        return Response(LibraryScanSerializer(scan).data, status=status.HTTP_201_CREATED)


class LibraryScanViewSet(viewsets.ModelViewSet):
    serializer_class = LibraryScanSerializer
    pagination_class = MediaLibraryPagination

    def get_queryset(self):
        queryset = LibraryScan.objects.all()
        library_id = self.request.query_params.get("library")
        if library_id:
            queryset = queryset.filter(library_id=library_id)
        return queryset

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_scan(self, request, pk=None):
        scan = self.get_object()
        if scan.status not in {
            LibraryScan.STATUS_PENDING,
            LibraryScan.STATUS_QUEUED,
            LibraryScan.STATUS_RUNNING,
        }:
            return Response(
                {"detail": "Scan is not running."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        scan.status = LibraryScan.STATUS_CANCELLED
        scan.save(update_fields=["status", "updated_at"])
        return Response(LibraryScanSerializer(scan).data)

    @action(detail=False, methods=["delete"], url_path="purge")
    def purge_scans(self, request):
        library_id = request.query_params.get("library")
        queryset = LibraryScan.objects.filter(
            status__in=[
                LibraryScan.STATUS_COMPLETED,
                LibraryScan.STATUS_FAILED,
                LibraryScan.STATUS_CANCELLED,
            ]
        )
        if library_id:
            queryset = queryset.filter(library_id=library_id)
        deleted, _ = queryset.delete()
        return Response({"deleted": deleted})

    def destroy(self, request, *args, **kwargs):
        scan = self.get_object()
        if scan.status not in {LibraryScan.STATUS_PENDING, LibraryScan.STATUS_QUEUED}:
            return Response(
                {"detail": "Only queued scans can be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class MediaItemViewSet(viewsets.ModelViewSet):
    serializer_class = MediaItemSerializer
    pagination_class = MediaLibraryPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["title", "sort_title", "normalized_title"]
    ordering_fields = [
        "updated_at",
        "first_imported_at",
        "release_year",
        "title",
        "sort_title",
    ]
    ordering = ["-updated_at"]

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        queryset = MediaItem.objects.all()
        library_ids = self.request.query_params.getlist("library")
        if not library_ids:
            libraries = self.request.query_params.get("libraries") or self.request.query_params.get("library_ids")
            if libraries:
                library_ids = [entry for entry in libraries.split(",") if entry]
        if library_ids:
            queryset = queryset.filter(library_id__in=library_ids)
        item_type = self.request.query_params.get("type")
        if item_type:
            queryset = queryset.filter(item_type=item_type)
        return queryset

    def get_serializer_class(self):
        if self.action == "retrieve":
            return MediaItemDetailSerializer
        if self.action in {"update", "partial_update"}:
            return MediaItemUpdateSerializer
        return MediaItemSerializer

    def perform_update(self, serializer):
        media_item = serializer.save()
        try:
            sync_vod_for_media_item(media_item)
        except Exception:
            pass

    @action(detail=True, methods=["get"], url_path="episodes")
    def episodes(self, request, pk=None):
        item = self.get_object()
        if item.item_type != MediaItem.TYPE_SHOW:
            return Response(
                {"detail": "Episodes are only available for series."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        episodes = (
            MediaItem.objects.filter(parent=item, item_type=MediaItem.TYPE_EPISODE)
            .order_by("season_number", "episode_number", "id")
        )
        serializer = MediaItemSerializer(episodes, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="refresh-metadata")
    def refresh_metadata(self, request, pk=None):
        item = self.get_object()
        refresh_media_item_metadata.delay(item.id)
        return Response({"queued": True})

    @action(detail=True, methods=["post"], url_path="stream")
    def stream(self, request, pk=None):
        item = self.get_object()
        if item.item_type not in {MediaItem.TYPE_MOVIE, MediaItem.TYPE_EPISODE}:
            return Response(
                {"detail": "Streaming is only available for movies and episodes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_id = request.data.get("fileId") or request.data.get("file_id")
        media_file = None
        if file_id:
            media_file = MediaFile.objects.filter(id=file_id, media_item=item).first()
        if not media_file:
            media_file = item.files.filter(is_primary=True).first() or item.files.first()
        if not media_file:
            return Response(
                {"detail": "No media file is linked to this item."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            sync_vod_for_media_item(item)
            item.refresh_from_db()
        except Exception:
            pass

        link = getattr(item, "vod_link", None)
        vod_uuid = None
        vod_type = None
        if link:
            if item.item_type == MediaItem.TYPE_MOVIE and link.vod_movie_id:
                vod_uuid = link.vod_movie.uuid
                vod_type = "movie"
            elif item.item_type == MediaItem.TYPE_EPISODE and link.vod_episode_id:
                vod_uuid = link.vod_episode.uuid
                vod_type = "episode"

        if not vod_uuid:
            return Response(
                {"detail": "Streaming endpoint is not ready yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        params = []
        if item.library.vod_account_id:
            params.append(f"m3u_account_id={item.library.vod_account_id}")
            params.append("include_inactive=1")

        query = f"?{'&'.join(params)}" if params else ""
        stream_path = reverse(
            "proxy:vod_proxy:vod_stream",
            kwargs={"content_type": vod_type, "content_id": vod_uuid},
        )
        stream_url = request.build_absolute_uri(f"{stream_path}{query}")
        return Response(
            {
                "url": stream_url,
                "stream_url": stream_url,
                "start_offset_ms": 0,
                "file_id": media_file.id,
                "duration_ms": media_file.duration_ms or item.runtime_ms,
                "requires_transcode": False,
            }
        )

    def _get_duration_ms(self, media_item: MediaItem) -> int:
        if media_item.runtime_ms:
            return media_item.runtime_ms
        file = media_item.files.filter(is_primary=True).first() or media_item.files.first()
        if file and file.duration_ms:
            return file.duration_ms
        return 0

    @action(detail=True, methods=["post"], url_path="progress")
    def update_progress(self, request, pk=None):
        item = self.get_object()
        if item.item_type not in {MediaItem.TYPE_MOVIE, MediaItem.TYPE_EPISODE}:
            return Response(
                {"detail": "Progress tracking is only available for movies and episodes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        def _parse_int(value):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        position_ms = _parse_int(
            request.data.get("position_ms")
            or request.data.get("positionMs")
            or request.data.get("position")
        )
        duration_ms = _parse_int(
            request.data.get("duration_ms")
            or request.data.get("durationMs")
            or request.data.get("duration")
        )
        completed_raw = request.data.get("completed")
        completed = bool(completed_raw) if completed_raw is not None else False

        if position_ms is None and not completed:
            return Response(
                {"detail": "position_ms is required to update progress."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if position_ms is None:
            position_ms = 0
        if position_ms < 0:
            position_ms = 0

        file_id = request.data.get("file_id") or request.data.get("fileId")
        media_file = None
        if file_id:
            media_file = MediaFile.objects.filter(id=file_id, media_item=item).first()

        if not duration_ms:
            if media_file and media_file.duration_ms:
                duration_ms = media_file.duration_ms
            else:
                duration_ms = self._get_duration_ms(item) or None

        if duration_ms and position_ms > duration_ms:
            position_ms = duration_ms

        if duration_ms and position_ms / max(duration_ms, 1) >= 0.95:
            completed = True

        if completed and duration_ms:
            position_ms = duration_ms

        progress, _ = WatchProgress.objects.get_or_create(
            user=request.user, media_item=item
        )
        progress.position_ms = position_ms
        if duration_ms:
            progress.duration_ms = duration_ms
        if media_file:
            progress.file = media_file
        progress.completed = completed
        progress.last_watched_at = timezone.now()
        progress.save()

        serializer = MediaItemSerializer(item, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="mark-watched")
    def mark_watched(self, request, pk=None):
        item = self.get_object()
        user = request.user
        duration_ms = self._get_duration_ms(item)
        progress, _ = WatchProgress.objects.get_or_create(user=user, media_item=item)
        progress.position_ms = duration_ms or progress.position_ms or 0
        progress.duration_ms = duration_ms or progress.duration_ms
        progress.completed = True
        progress.last_watched_at = timezone.now()
        progress.save()
        serializer = MediaItemSerializer(item, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="clear-progress")
    def clear_progress(self, request, pk=None):
        item = self.get_object()
        WatchProgress.objects.filter(user=request.user, media_item=item).delete()
        serializer = MediaItemSerializer(item, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="series/mark-watched")
    def mark_series_watched(self, request, pk=None):
        series = self.get_object()
        if series.item_type != MediaItem.TYPE_SHOW:
            return Response(
                {"detail": "Series actions are only available for shows."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        episodes = MediaItem.objects.filter(parent=series, item_type=MediaItem.TYPE_EPISODE)
        existing = {
            entry.media_item_id: entry
            for entry in WatchProgress.objects.filter(user=request.user, media_item__in=episodes)
        }
        now = timezone.now()
        to_create = []
        to_update = []

        for episode in episodes:
            duration_ms = self._get_duration_ms(episode)
            if episode.id in existing:
                progress = existing[episode.id]
                progress.position_ms = duration_ms or progress.position_ms or 0
                progress.duration_ms = duration_ms or progress.duration_ms
                progress.completed = True
                progress.last_watched_at = now
                to_update.append(progress)
            else:
                to_create.append(
                    WatchProgress(
                        user=request.user,
                        media_item=episode,
                        position_ms=duration_ms or 0,
                        duration_ms=duration_ms or None,
                        completed=True,
                        last_watched_at=now,
                    )
                )

        if to_create:
            WatchProgress.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            WatchProgress.objects.bulk_update(
                to_update,
                ["position_ms", "duration_ms", "completed", "last_watched_at", "updated_at"],
            )

        serializer = MediaItemSerializer(series, context={"request": request})
        return Response({"item": serializer.data})

    @action(detail=True, methods=["post"], url_path="series/clear-progress")
    def clear_series_progress(self, request, pk=None):
        series = self.get_object()
        if series.item_type != MediaItem.TYPE_SHOW:
            return Response(
                {"detail": "Series actions are only available for shows."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        episodes = MediaItem.objects.filter(parent=series, item_type=MediaItem.TYPE_EPISODE)
        WatchProgress.objects.filter(user=request.user, media_item__in=episodes).delete()
        serializer = MediaItemSerializer(series, context={"request": request})
        return Response({"item": serializer.data})


@api_view(["GET"])
@permission_classes([IsAdmin])
def browse_library_path(request):
    raw_path = request.query_params.get("path") or ""
    if not raw_path:
        path = os.path.abspath(os.sep)
    else:
        path = os.path.abspath(os.path.expanduser(raw_path))

    if not os.path.exists(path) or not os.path.isdir(path):
        return Response({"detail": "Path not found."}, status=status.HTTP_404_NOT_FOUND)

    parent = os.path.dirname(path.rstrip(os.sep))
    if parent == path:
        parent = None

    entries = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir():
                    entries.append({"name": entry.name, "path": entry.path})
    except PermissionError:
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    entries.sort(key=lambda item: item["name"].lower())
    return Response({"path": path, "parent": parent, "entries": entries})
