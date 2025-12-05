from django.db import transaction
from django.urls import reverse
from django.db.models import Prefetch
from rest_framework import serializers

from apps.media_library import models


class LibraryLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.LibraryLocation
        fields = [
            "id",
            "path",
            "include_subdirectories",
            "is_primary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class LibrarySerializer(serializers.ModelSerializer):
    locations = LibraryLocationSerializer(many=True, required=False)

    class Meta:
        model = models.Library
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "library_type",
            "auto_scan_enabled",
            "scan_interval_minutes",
            "metadata_language",
            "metadata_country",
            "use_as_vod_source",
            "metadata_options",
            "last_scan_at",
            "last_successful_scan_at",
            "created_at",
            "updated_at",
            "locations",
        ]
        read_only_fields = [
            "id",
            "slug",
            "last_scan_at",
            "last_successful_scan_at",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        locations_data = validated_data.pop("locations", [])
        with transaction.atomic():
            library = super().create(validated_data)
            self._sync_locations(library, locations_data)
        return library

    def update(self, instance, validated_data):
        locations_data = validated_data.pop("locations", None)
        with transaction.atomic():
            library = super().update(instance, validated_data)
            if locations_data is not None:
                self._sync_locations(library, locations_data)
        return library

    def _sync_locations(self, library: models.Library, locations_data):
        seen_location_ids = set()
        primary_set = False

        for entry in locations_data:
            location_id = entry.get("id")
            entry_data = {
                "path": entry["path"],
                "include_subdirectories": entry.get("include_subdirectories", True),
                "is_primary": entry.get("is_primary", False),
            }

            if entry_data["is_primary"]:
                primary_set = True
            if location_id:
                updated = models.LibraryLocation.objects.filter(pk=location_id, library=library).update(**entry_data)
                if updated:
                    seen_location_ids.add(location_id)
                    continue

            defaults = {
                "include_subdirectories": entry_data["include_subdirectories"],
                "is_primary": entry_data["is_primary"],
            }
            location, _ = models.LibraryLocation.objects.update_or_create(
                library=library,
                path=entry_data["path"],
                defaults=defaults,
            )
            seen_location_ids.add(location.id)
            if location.is_primary:
                primary_set = True

        # Remove locations not present in payload
        models.LibraryLocation.objects.filter(library=library).exclude(id__in=seen_location_ids).delete()

        # Ensure a primary location exists
        if not primary_set:
            first_location = models.LibraryLocation.objects.filter(library=library).order_by("id").first()
            if first_location:
                first_location.is_primary = True
                first_location.save(update_fields=["is_primary", "updated_at"])


class LibraryScanSerializer(serializers.ModelSerializer):
    library_name = serializers.CharField(source="library.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    stages = serializers.SerializerMethodField()

    class Meta:
        model = models.LibraryScan
        fields = [
            "id",
            "library",
            "library_name",
            "created_by",
            "created_by_name",
            "status",
            "started_at",
            "finished_at",
            "total_files",
            "processed_files",
            "new_files",
            "updated_files",
            "removed_files",
            "matched_items",
            "unmatched_files",
            "task_id",
            "summary",
            "log",
            "extra",
            "discovery_status",
            "discovery_total",
            "discovery_processed",
            "metadata_status",
            "metadata_total",
            "metadata_processed",
            "artwork_status",
            "artwork_total",
            "artwork_processed",
            "stages",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "library_name",
            "created_by_name",
            "status",
            "started_at",
            "finished_at",
            "total_files",
            "processed_files",
            "new_files",
            "updated_files",
            "removed_files",
            "matched_items",
            "unmatched_files",
            "task_id",
            "summary",
            "log",
            "extra",
            "discovery_status",
            "discovery_total",
            "discovery_processed",
            "metadata_status",
            "metadata_total",
            "metadata_processed",
            "artwork_status",
            "artwork_total",
            "artwork_processed",
            "stages",
            "created_at",
            "updated_at",
        ]

    def get_stages(self, obj):
        return obj.stage_snapshot(normalize=True)


class ArtworkAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ArtworkAsset
        fields = [
            "id",
            "asset_type",
            "external_url",
            "local_path",
            "width",
            "height",
            "language",
            "source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SubtitleAssetSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    def get_url(self, obj):
        request = self.context.get("request")
        if not obj.file_path and obj.external_url:
            return obj.external_url
        if not obj.file_path:
            return None
        try:
            relative = reverse("media-library-subtitle-file", args=[obj.id])
        except Exception:
            relative = None
        if request and relative:
            return request.build_absolute_uri(relative)
        return relative

    class Meta:
        model = models.SubtitleAsset
        fields = [
            "id",
            "language",
            "is_forced",
            "source",
            "format",
            "file_path",
            "external_url",
            "url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "file_path", "external_url"]


class MediaFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.MediaFile
        fields = [
            "id",
            "library",
            "media_item",
            "location",
            "absolute_path",
            "relative_path",
            "file_name",
            "size_bytes",
            "duration_ms",
            "video_codec",
            "audio_codec",
            "audio_channels",
            "width",
            "height",
            "frame_rate",
            "bit_rate",
            "container",
            "has_subtitles",
            "subtitle_languages",
            "extra_streams",
            "checksum",
            "fingerprint",
            "last_modified_at",
            "requires_transcode",
            "transcode_status",
            "transcoded_path",
            "transcoded_mime_type",
            "transcode_error",
            "transcoded_at",
            "last_seen_at",
            "missing_since",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "last_modified_at",
            "requires_transcode",
            "transcode_status",
            "transcoded_path",
            "transcoded_mime_type",
            "transcode_error",
            "transcoded_at",
            "last_seen_at",
            "missing_since",
            "created_at",
            "updated_at",
        ]


class MediaItemBaseSerializer(serializers.ModelSerializer):
    parent_id = serializers.PrimaryKeyRelatedField(source="parent", read_only=True)
    watch_progress = serializers.SerializerMethodField()
    watch_summary = serializers.SerializerMethodField()

    def _get_user(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        return user

    def _get_progress(self, obj, user):
        prefetched = getattr(obj, "_user_watch_progress", None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        return obj.watch_progress.filter(user=user).first()

    def get_watch_progress(self, obj):
        user = self._get_user()
        if not user:
            return None
        progress = self._get_progress(obj, user)
        if not progress:
            return None
        duration = progress.duration_ms or obj.runtime_ms
        percentage = (progress.position_ms / duration) if duration else 0
        return {
            "id": progress.id,
            "position_ms": progress.position_ms,
            "duration_ms": duration,
            "completed": progress.completed,
            "percentage": percentage,
            "last_watched_at": progress.last_watched_at,
        }

    def get_watch_summary(self, obj):
        user = self._get_user()
        if not user:
            return None

        if obj.item_type == models.MediaItem.TYPE_SHOW:
            episodes = getattr(obj, "_prefetched_children", None)
            if episodes is None:
                episodes = list(
                    models.MediaItem.objects.filter(
                        parent=obj, item_type=models.MediaItem.TYPE_EPISODE
                    )
                    .prefetch_related(
                        Prefetch(
                            "watch_progress",
                            queryset=models.WatchProgress.objects.filter(user=user),
                            to_attr="_user_watch_progress",
                        )
                    )
                    .order_by("season_number", "episode_number", "id")
                )
            total = len([ep for ep in episodes if ep.item_type == models.MediaItem.TYPE_EPISODE])
            completed = 0
            resume_episode = None
            resume_progress_time = None
            next_episode = None
            last_completed_episode = None
            last_completed_time = None

            for episode in episodes:
                if episode.item_type != models.MediaItem.TYPE_EPISODE:
                    continue
                progress = self._get_progress(episode, user)
                if progress and progress.completed:
                    completed += 1
                    if not last_completed_time or progress.last_watched_at > last_completed_time:
                        last_completed_time = progress.last_watched_at
                        last_completed_episode = episode
                elif progress and progress.position_ms:
                    if (
                        resume_progress_time is None
                        or progress.last_watched_at > resume_progress_time
                    ):
                        resume_progress_time = progress.last_watched_at
                        resume_episode = episode
                else:
                    if not next_episode:
                        next_episode = episode

            status = "unwatched"
            if total == 0:
                status = "unwatched"
            elif completed >= total and total > 0:
                status = "watched"
                next_episode = None
            elif resume_episode or completed > 0:
                status = "in_progress"
                if not resume_episode:
                    resume_episode = next_episode

            return {
                "status": status,
                "total_episodes": total,
                "completed_episodes": completed,
                "resume_episode_id": resume_episode.id if resume_episode else None,
                "next_episode_id": next_episode.id if next_episode else None,
                "last_completed_episode_id": last_completed_episode.id if last_completed_episode else None,
            }

        progress = self._get_progress(obj, user)
        if not progress:
            return {"status": "unwatched"}
        if progress.completed:
            return {
                "status": "watched",
                "position_ms": progress.position_ms,
                "duration_ms": progress.duration_ms,
            }
        return {
            "status": "in_progress",
            "position_ms": progress.position_ms,
            "duration_ms": progress.duration_ms,
            "percentage": (progress.position_ms / progress.duration_ms)
            if progress.duration_ms
            else 0,
        }


class MediaItemListSerializer(MediaItemBaseSerializer):
    class Meta:
        model = models.MediaItem
        fields = [
            "id",
            "library",
            "parent_id",
            "item_type",
            "status",
            "title",
            "sort_title",
            "poster_url",
            "backdrop_url",
            "runtime_ms",
            "release_year",
            "season_number",
            "episode_number",
            "genres",
            "is_missing",
            "tags",
            "tagline",
            "synopsis",
            "metadata_last_synced_at",
            "metadata_source",
            "watch_progress",
            "watch_summary",
        ]
        read_only_fields = fields


class MediaItemSerializer(MediaItemBaseSerializer):
    files = MediaFileSerializer(many=True, read_only=True)
    artwork = ArtworkAssetSerializer(many=True, read_only=True)
    subtitles = SubtitleAssetSerializer(many=True, read_only=True)

    class Meta:
        model = models.MediaItem
        fields = [
            "id",
            "library",
            "parent_id",
            "item_type",
            "status",
            "title",
            "sort_title",
            "normalized_title",
            "release_year",
            "season_number",
            "episode_number",
            "runtime_ms",
            "synopsis",
            "tagline",
            "rating",
            "genres",
            "studios",
            "cast",
            "crew",
            "tags",
            "poster_url",
            "backdrop_url",
            "tmdb_id",
            "imdb_id",
            "tvdb_id",
            "vod_movie",
            "vod_series",
            "vod_episode",
            "metadata",
            "metadata_last_synced_at",
            "metadata_source",
            "is_missing",
            "first_imported_at",
            "updated_at",
            "files",
            "artwork",
            "watch_progress",
            "watch_summary",
            "subtitles",
        ]
        read_only_fields = [
            "id",
            "library",
            "parent_id",
            "item_type",
            "normalized_title",
            "metadata_last_synced_at",
            "first_imported_at",
            "updated_at",
            "files",
            "artwork",
            "vod_movie",
            "vod_series",
            "vod_episode",
            "watch_progress",
            "subtitles",
            "is_missing",
        ]
        extra_kwargs = {
            "genres": {"required": False, "allow_null": True},
            "studios": {"required": False, "allow_null": True},
            "cast": {"required": False, "allow_null": True},
            "crew": {"required": False, "allow_null": True},
            "tags": {"required": False, "allow_null": True},
            "metadata": {"required": False, "allow_null": True},
        }


class WatchProgressSerializer(serializers.ModelSerializer):
    user_display = serializers.CharField(source="user.username", read_only=True)
    media_title = serializers.CharField(source="media_item.title", read_only=True)

    class Meta:
        model = models.WatchProgress
        fields = [
            "id",
            "user",
            "user_display",
            "media_item",
            "media_title",
            "position_ms",
            "duration_ms",
            "completed",
            "last_watched_at",
        ]
        read_only_fields = ["id", "user", "user_display", "media_title", "last_watched_at"]
        extra_kwargs = {"user": {"required": False}}
        validators = []  # DB constraint enforces uniqueness; allow update-or-create writes

    def create(self, validated_data):
        user = self.context["request"].user
        progress, _ = models.WatchProgress.objects.update_or_create(
            user=user,
            media_item=validated_data["media_item"],
            defaults={
                "position_ms": validated_data.get("position_ms", 0),
                "duration_ms": validated_data.get("duration_ms", 0),
                "completed": validated_data.get("completed", False),
            },
        )
        return progress

    def update(self, instance, validated_data):
        instance.position_ms = validated_data.get("position_ms", instance.position_ms)
        instance.duration_ms = max(
            instance.duration_ms, validated_data.get("duration_ms", instance.duration_ms)
        )
        instance.completed = validated_data.get("completed", instance.completed)
        instance.save()
        return instance
