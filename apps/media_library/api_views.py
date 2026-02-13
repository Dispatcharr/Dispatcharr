from datetime import datetime, time
import os
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.urls import reverse
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.permissions import Authenticated, IsAdmin, permission_classes_by_action
from apps.media_library.models import Library, LibraryScan, MediaItem, WatchProgress
from apps.media_library.serializers import (
    LibraryScanSerializer,
    LibrarySerializer,
    MediaItemDetailSerializer,
    MediaItemListSerializer,
    MediaItemSerializer,
    MediaItemUpdateSerializer,
)
from apps.media_library.file_utils import media_files_for_item, primary_media_file_for_item
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
    serializer_class = LibrarySerializer

    def get_queryset(self):
        return (
            Library.objects.prefetch_related("locations")
            .annotate(
                movie_count=Count(
                    "items",
                    filter=Q(items__item_type=MediaItem.TYPE_MOVIE),
                    distinct=True,
                ),
                show_count=Count(
                    "items",
                    filter=Q(items__item_type=MediaItem.TYPE_SHOW),
                    distinct=True,
                ),
            )
        )

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def perform_create(self, serializer):
        library = serializer.save()
        sync_library_vod_account_state(library)
        if library.auto_scan_enabled:
            scan = LibraryScan.objects.create(
                library=library,
                scan_type=LibraryScan.SCAN_QUICK,
                status=LibraryScan.STATUS_QUEUED,
                summary="Quick scan",
                stages={},
            )
            task = scan_library.delay(library.id, full=False, scan_id=scan.id)
            scan.task_id = task.id
            scan.save(update_fields=["task_id", "updated_at"])

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
            action = getattr(self, self.action, None)
            if action and hasattr(action, "permission_classes"):
                return [perm() for perm in action.permission_classes]
            return [Authenticated()]

    def _parse_query_ids(self):
        raw_ids = []
        ids_csv = self.request.query_params.get("ids")
        if ids_csv:
            raw_ids.extend([entry.strip() for entry in ids_csv.split(",") if entry.strip()])
        raw_ids.extend(
            [str(entry).strip() for entry in self.request.query_params.getlist("id") if str(entry).strip()]
        )
        if not raw_ids:
            return None

        parsed_ids = []
        invalid_ids = []
        for raw in raw_ids:
            try:
                parsed_ids.append(int(raw))
            except (TypeError, ValueError):
                invalid_ids.append(raw)
        if invalid_ids:
            raise ValidationError(
                {"ids": f"Invalid id value(s): {', '.join(invalid_ids)}"}
            )
        return parsed_ids

    def _parse_updated_after(self):
        raw_value = self.request.query_params.get("updated_after") or self.request.query_params.get("since")
        if not raw_value:
            return None

        parsed = parse_datetime(raw_value)
        if parsed is None:
            parsed_date = parse_date(raw_value)
            if parsed_date:
                parsed = datetime.combine(parsed_date, time.min)
        if parsed is None:
            raise ValidationError(
                {"updated_after": "Invalid datetime. Use ISO-8601 format."}
            )
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def _parse_updated_before(self):
        raw_value = self.request.query_params.get("updated_before")
        if not raw_value:
            return None

        parsed = parse_datetime(raw_value)
        if parsed is None:
            parsed_date = parse_date(raw_value)
            if parsed_date:
                parsed = datetime.combine(parsed_date, time.max)
        if parsed is None:
            raise ValidationError(
                {"updated_before": "Invalid datetime. Use ISO-8601 format."}
            )
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def get_queryset(self):
        queryset = MediaItem.objects.select_related("library", "parent")
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

        if self.action == "list":
            parsed_ids = self._parse_query_ids()
            if parsed_ids:
                queryset = queryset.filter(id__in=parsed_ids)

            updated_after = self._parse_updated_after()
            if updated_after:
                queryset = queryset.filter(updated_at__gte=updated_after)

            updated_before = self._parse_updated_before()
            if updated_before:
                queryset = queryset.filter(updated_at__lte=updated_before)

        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return MediaItemListSerializer
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

    def _build_batched_watch_context(self, items):
        context = self.get_serializer_context()
        request = self.request
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return context

        item_ids = [item.id for item in items if item and item.id]
        progress_map = {}
        if item_ids:
            progress_map = {
                entry.media_item_id: entry
                for entry in WatchProgress.objects.filter(
                    user=user, media_item_id__in=item_ids
                )
            }
        context["progress_map"] = progress_map

        show_ids = [item.id for item in items if item.item_type == MediaItem.TYPE_SHOW]
        if not show_ids:
            context["show_summary_map"] = {}
            return context

        episode_rows = list(
            MediaItem.objects.filter(parent_id__in=show_ids, item_type=MediaItem.TYPE_EPISODE)
            .exclude(season_number__isnull=True)
            .exclude(season_number=0)
            .order_by("parent_id", "season_number", "episode_number", "id")
            .values("id", "parent_id", "runtime_ms")
        )

        episodes_by_show = {}
        for row in episode_rows:
            episodes_by_show.setdefault(row["parent_id"], []).append(row)

        episode_ids = [row["id"] for row in episode_rows]
        episode_progress = {}
        if episode_ids:
            for row in WatchProgress.objects.filter(
                user=user, media_item_id__in=episode_ids
            ).values("media_item_id", "position_ms", "duration_ms", "completed"):
                episode_progress[row["media_item_id"]] = row

        show_summary_map = {}
        for show_id in show_ids:
            episodes = episodes_by_show.get(show_id, [])
            total = len(episodes)
            if total == 0:
                show_summary_map[show_id] = {
                    "status": "unwatched",
                    "total_episodes": 0,
                    "completed_episodes": 0,
                }
                continue

            completed_episodes = 0
            resume_episode_id = None
            next_episode_id = None

            for episode in episodes:
                progress = episode_progress.get(episode["id"])
                if progress:
                    duration = progress.get("duration_ms") or episode.get("runtime_ms") or 0
                    percent = (
                        progress.get("position_ms", 0) / max(duration, 1) if duration else 0
                    )
                    completed = bool(progress.get("completed")) or percent >= 0.95
                    if completed:
                        completed_episodes += 1
                    elif progress.get("position_ms", 0) > 0 and resume_episode_id is None:
                        resume_episode_id = episode["id"]

                if next_episode_id is None:
                    if not progress:
                        next_episode_id = episode["id"]
                    else:
                        duration = progress.get("duration_ms") or episode.get("runtime_ms") or 0
                        percent = (
                            progress.get("position_ms", 0) / max(duration, 1)
                            if duration
                            else 0
                        )
                        completed = bool(progress.get("completed")) or percent >= 0.95
                        if not completed:
                            next_episode_id = episode["id"]

            if completed_episodes == total:
                status_value = "watched"
            elif completed_episodes > 0 or resume_episode_id:
                status_value = "in_progress"
            else:
                status_value = "unwatched"

            show_summary_map[show_id] = {
                "status": status_value,
                "total_episodes": total,
                "completed_episodes": completed_episodes,
                "resume_episode_id": resume_episode_id,
                "next_episode_id": next_episode_id,
            }

        context["show_summary_map"] = show_summary_map
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(
                page, many=True, context=self._build_batched_watch_context(page)
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(
            queryset, many=True, context=self._build_batched_watch_context(queryset)
        )
        return Response(serializer.data)

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
        serializer = MediaItemDetailSerializer(episodes, many=True, context={"request": request})
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
            media_file = media_files_for_item(item).filter(id=file_id).first()
        if not media_file:
            media_file = primary_media_file_for_item(item)
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
        file = primary_media_file_for_item(media_item)
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

        def _first_present(*keys):
            for key in keys:
                if key in request.data:
                    return request.data.get(key)
            return None

        def _parse_bool(value):
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "on"}:
                    return True
                if normalized in {"false", "0", "no", "off", ""}:
                    return False
            return bool(value)

        position_ms = _parse_int(
            _first_present("position_ms", "positionMs", "position")
        )
        duration_ms = _parse_int(
            _first_present("duration_ms", "durationMs", "duration")
        )
        completed_raw = _first_present("completed")
        completed = _parse_bool(completed_raw)
        if completed is None:
            completed = False

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
            media_file = media_files_for_item(item).filter(id=file_id).first()

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
