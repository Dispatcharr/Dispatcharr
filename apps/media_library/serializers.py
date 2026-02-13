from django.db.models import Count
from rest_framework import serializers

from apps.media_library.models import (
    ArtworkAsset,
    Library,
    LibraryLocation,
    LibraryScan,
    MediaFile,
    MediaItem,
    WatchProgress,
)
from apps.media_library.file_utils import media_files_for_item


class LibraryLocationSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = LibraryLocation
        fields = ["id", "path", "include_subdirectories", "is_primary"]


class LibrarySerializer(serializers.ModelSerializer):
    locations = LibraryLocationSerializer(many=True)
    movie_count = serializers.IntegerField(read_only=True)
    show_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Library
        fields = [
            "id",
            "name",
            "description",
            "library_type",
            "metadata_language",
            "metadata_country",
            "metadata_options",
            "scan_interval_minutes",
            "auto_scan_enabled",
            "add_to_vod",
            "last_scan_at",
            "last_successful_scan_at",
            "movie_count",
            "show_count",
            "locations",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        locations = validated_data.pop("locations", [])
        library = Library.objects.create(**validated_data)
        for index, location in enumerate(locations):
            LibraryLocation.objects.create(
                library=library,
                path=location["path"],
                include_subdirectories=location.get("include_subdirectories", True),
                is_primary=location.get("is_primary", index == 0),
            )
        return library

    def update(self, instance, validated_data):
        locations = validated_data.pop("locations", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if locations is not None:
            existing_ids = {loc.id for loc in instance.locations.all()}
            seen_ids: set[int] = set()
            for index, location in enumerate(locations):
                location_id = location.get("id")
                if location_id and location_id in existing_ids:
                    LibraryLocation.objects.filter(id=location_id).update(
                        path=location.get("path", ""),
                        include_subdirectories=location.get("include_subdirectories", True),
                        is_primary=location.get("is_primary", index == 0),
                    )
                    seen_ids.add(location_id)
                else:
                    created = LibraryLocation.objects.create(
                        library=instance,
                        path=location.get("path", ""),
                        include_subdirectories=location.get("include_subdirectories", True),
                        is_primary=location.get("is_primary", index == 0),
                    )
                    seen_ids.add(created.id)

            missing_ids = existing_ids - seen_ids
            if missing_ids:
                LibraryLocation.objects.filter(id__in=missing_ids).delete()

        return instance


class MediaFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaFile
        fields = [
            "id",
            "path",
            "relative_path",
            "file_name",
            "size_bytes",
            "modified_at",
            "duration_ms",
        ]


class MediaItemSerializer(serializers.ModelSerializer):
    watch_progress = serializers.SerializerMethodField()
    watch_summary = serializers.SerializerMethodField()

    class Meta:
        model = MediaItem
        fields = [
            "id",
            "library",
            "parent",
            "item_type",
            "title",
            "sort_title",
            "normalized_title",
            "synopsis",
            "tagline",
            "release_year",
            "rating",
            "runtime_ms",
            "season_number",
            "episode_number",
            "genres",
            "tags",
            "studios",
            "cast",
            "crew",
            "poster_url",
            "backdrop_url",
            "movie_db_id",
            "imdb_id",
            "youtube_trailer",
            "metadata_source",
            "metadata_last_synced_at",
            "first_imported_at",
            "updated_at",
            "watch_progress",
            "watch_summary",
        ]

    def _progress_payload(self, progress: WatchProgress | None, item: MediaItem):
        if not progress:
            return None
        duration = progress.duration_ms or item.runtime_ms
        percentage = None
        completed = progress.completed
        if duration:
            percentage = min(1, max(0, progress.position_ms / duration))
            if percentage >= 0.95:
                completed = True
        return {
            "id": progress.id,
            "position_ms": progress.position_ms,
            "duration_ms": duration,
            "percentage": percentage,
            "completed": completed,
            "last_watched_at": progress.last_watched_at,
        }

    def _summary_for_progress(self, progress: WatchProgress | None, item: MediaItem):
        if not progress:
            return {"status": "unwatched"}
        duration = progress.duration_ms or item.runtime_ms or 0
        completed = progress.completed
        if duration and progress.position_ms / max(duration, 1) >= 0.95:
            completed = True
        if completed:
            status = "watched"
        elif progress.position_ms > 0:
            status = "in_progress"
        else:
            status = "unwatched"
        return {
            "status": status,
            "position_ms": progress.position_ms,
            "duration_ms": duration,
            "completed": completed,
        }

    def _summary_for_show(self, item: MediaItem, user):
        episodes = (
            MediaItem.objects.filter(parent=item, item_type=MediaItem.TYPE_EPISODE)
            .exclude(season_number__isnull=True)
            .exclude(season_number=0)
            .order_by("season_number", "episode_number", "id")
        )
        total = episodes.count()
        if total == 0:
            return {
                "status": "unwatched",
                "total_episodes": 0,
                "completed_episodes": 0,
            }

        progress_map = {
            entry.media_item_id: entry
            for entry in WatchProgress.objects.filter(user=user, media_item__in=episodes)
        }

        completed_episodes = 0
        resume_episode_id = None
        next_episode_id = None

        for episode in episodes:
            progress = progress_map.get(episode.id)
            if progress:
                duration = progress.duration_ms or episode.runtime_ms or 0
                percent = progress.position_ms / max(duration, 1) if duration else 0
                completed = progress.completed or percent >= 0.95
                if completed:
                    completed_episodes += 1
                elif progress.position_ms > 0 and resume_episode_id is None:
                    resume_episode_id = episode.id
            if next_episode_id is None:
                if not progress:
                    next_episode_id = episode.id
                else:
                    duration = progress.duration_ms or episode.runtime_ms or 0
                    percent = progress.position_ms / max(duration, 1) if duration else 0
                    completed = progress.completed or percent >= 0.95
                    if not completed:
                        next_episode_id = episode.id

        if completed_episodes == total:
            status = "watched"
        elif completed_episodes > 0 or resume_episode_id:
            status = "in_progress"
        else:
            status = "unwatched"

        return {
            "status": status,
            "total_episodes": total,
            "completed_episodes": completed_episodes,
            "resume_episode_id": resume_episode_id,
            "next_episode_id": next_episode_id,
        }

    def get_watch_progress(self, obj: MediaItem):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        progress_map = self.context.get("progress_map")
        if isinstance(progress_map, dict):
            progress = progress_map.get(obj.id)
        else:
            progress = WatchProgress.objects.filter(user=user, media_item=obj).first()
        return self._progress_payload(progress, obj)

    def get_watch_summary(self, obj: MediaItem):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        if obj.item_type == MediaItem.TYPE_SHOW:
            show_summary_map = self.context.get("show_summary_map")
            if isinstance(show_summary_map, dict) and obj.id in show_summary_map:
                return show_summary_map[obj.id]
            return self._summary_for_show(obj, user)
        progress_map = self.context.get("progress_map")
        if isinstance(progress_map, dict):
            progress = progress_map.get(obj.id)
        else:
            progress = WatchProgress.objects.filter(user=user, media_item=obj).first()
        return self._summary_for_progress(progress, obj)


class MediaItemListSerializer(MediaItemSerializer):
    class Meta(MediaItemSerializer.Meta):
        # Keep list payloads lightweight for large libraries while preserving
        # all fields needed for card rendering, sorting, progress, and polling.
        fields = [
            "id",
            "library",
            "parent",
            "item_type",
            "title",
            "sort_title",
            "normalized_title",
            "release_year",
            "rating",
            "runtime_ms",
            "season_number",
            "episode_number",
            "genres",
            "poster_url",
            "backdrop_url",
            "movie_db_id",
            "imdb_id",
            "metadata_last_synced_at",
            "first_imported_at",
            "updated_at",
            "watch_progress",
            "watch_summary",
        ]


class MediaItemDetailSerializer(MediaItemSerializer):
    files = serializers.SerializerMethodField()

    class Meta(MediaItemSerializer.Meta):
        fields = MediaItemSerializer.Meta.fields + ["files", "metadata"]

    def get_files(self, obj: MediaItem):
        files = media_files_for_item(obj)
        return MediaFileSerializer(files, many=True).data


class LibraryScanSerializer(serializers.ModelSerializer):
    class Meta:
        model = LibraryScan
        fields = [
            "id",
            "library",
            "scan_type",
            "status",
            "summary",
            "stages",
            "processed_files",
            "total_files",
            "new_files",
            "updated_files",
            "removed_files",
            "unmatched_files",
            "log",
            "extra",
            "task_id",
            "created_at",
            "started_at",
            "finished_at",
        ]


class MediaItemUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaItem
        fields = [
            "title",
            "synopsis",
            "release_year",
            "rating",
            "genres",
            "tags",
            "studios",
            "movie_db_id",
            "imdb_id",
            "poster_url",
            "backdrop_url",
        ]
