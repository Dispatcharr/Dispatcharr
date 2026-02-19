from rest_framework import serializers


FUSE_SETTINGS_DEFAULTS = {
    "enable_fuse": False,
    "backend_base_url": "",
    "movies_mount_path": "/mnt/vod_movies",
    "tv_mount_path": "/mnt/vod_tv",
    "fuse_max_read": 8388608,
    "readahead_bytes": 1048576,
    "probe_read_bytes": 524288,
    "mkv_prefetch_bytes": 16777216,
    "mkv_max_fetch_bytes": 33554432,
    "mkv_buffer_cache_bytes": 100663296,
    "prefetch_trigger_bytes": 2097152,
    "transcoder_prefetch_bytes": 4194304,
    "transcoder_max_fetch_bytes": 8388608,
    "buffer_cache_bytes": 33554432,
    "smooth_buffering_enabled": True,
    "initial_prebuffer_bytes": 33554432,
    "initial_prebuffer_timeout_seconds": 20.0,
    "target_buffer_ahead_bytes": 134217728,
    "low_watermark_bytes": 16777216,
    "max_total_buffer_bytes": 1073741824,
    "prefetch_loop_sleep_seconds": 0.12,
    "seek_reset_threshold_bytes": 4194304,
    "buffer_release_on_close": True,
    "fuse_stats_grace_seconds": 30,
}


class FuseEntrySerializer(serializers.Serializer):
    """Lightweight serializer for filesystem-style entries."""

    name = serializers.CharField()
    path = serializers.CharField()
    is_dir = serializers.BooleanField()
    content_type = serializers.CharField()
    uuid = serializers.UUIDField(required=False, allow_null=True)
    extension = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    size = serializers.IntegerField(required=False, allow_null=True)
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    season = serializers.IntegerField(required=False, allow_null=True)
    episode_number = serializers.IntegerField(required=False, allow_null=True)
    stream_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class FuseSettingsSerializer(serializers.Serializer):
    enable_fuse = serializers.BooleanField(default=FUSE_SETTINGS_DEFAULTS["enable_fuse"])
    backend_base_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    movies_mount_path = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=FUSE_SETTINGS_DEFAULTS["movies_mount_path"],
    )
    tv_mount_path = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=FUSE_SETTINGS_DEFAULTS["tv_mount_path"],
    )
    fuse_max_read = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["fuse_max_read"],
    )
    readahead_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["readahead_bytes"],
    )
    probe_read_bytes = serializers.IntegerField(
        min_value=4096,
        default=FUSE_SETTINGS_DEFAULTS["probe_read_bytes"],
    )
    mkv_prefetch_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["mkv_prefetch_bytes"],
    )
    mkv_max_fetch_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["mkv_max_fetch_bytes"],
    )
    mkv_buffer_cache_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["mkv_buffer_cache_bytes"],
    )
    prefetch_trigger_bytes = serializers.IntegerField(
        min_value=4 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["prefetch_trigger_bytes"],
    )
    transcoder_prefetch_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["transcoder_prefetch_bytes"],
    )
    transcoder_max_fetch_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["transcoder_max_fetch_bytes"],
    )
    buffer_cache_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["buffer_cache_bytes"],
    )
    smooth_buffering_enabled = serializers.BooleanField(
        default=FUSE_SETTINGS_DEFAULTS["smooth_buffering_enabled"],
    )
    initial_prebuffer_bytes = serializers.IntegerField(
        min_value=0,
        default=FUSE_SETTINGS_DEFAULTS["initial_prebuffer_bytes"],
    )
    initial_prebuffer_timeout_seconds = serializers.FloatField(
        min_value=0.0,
        default=FUSE_SETTINGS_DEFAULTS["initial_prebuffer_timeout_seconds"],
    )
    target_buffer_ahead_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["target_buffer_ahead_bytes"],
    )
    low_watermark_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["low_watermark_bytes"],
    )
    max_total_buffer_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["max_total_buffer_bytes"],
    )
    prefetch_loop_sleep_seconds = serializers.FloatField(
        min_value=0.01,
        default=FUSE_SETTINGS_DEFAULTS["prefetch_loop_sleep_seconds"],
    )
    seek_reset_threshold_bytes = serializers.IntegerField(
        min_value=64 * 1024,
        default=FUSE_SETTINGS_DEFAULTS["seek_reset_threshold_bytes"],
    )
    buffer_release_on_close = serializers.BooleanField(
        default=FUSE_SETTINGS_DEFAULTS["buffer_release_on_close"],
    )
    fuse_stats_grace_seconds = serializers.IntegerField(
        min_value=0,
        default=FUSE_SETTINGS_DEFAULTS["fuse_stats_grace_seconds"],
    )

    def validate_backend_base_url(self, value):
        if value and not value.startswith(("http://", "https://")):
            raise serializers.ValidationError("backend_base_url must start with http:// or https://")
        return value

    def validate(self, attrs):
        # Keep max fetch/cache relationships sane.
        attrs["mkv_max_fetch_bytes"] = max(attrs["mkv_max_fetch_bytes"], attrs["mkv_prefetch_bytes"])
        attrs["transcoder_max_fetch_bytes"] = max(
            attrs["transcoder_max_fetch_bytes"],
            attrs["transcoder_prefetch_bytes"],
        )
        attrs["mkv_buffer_cache_bytes"] = max(attrs["mkv_buffer_cache_bytes"], attrs["mkv_prefetch_bytes"])
        attrs["buffer_cache_bytes"] = max(attrs["buffer_cache_bytes"], attrs["readahead_bytes"])
        attrs["target_buffer_ahead_bytes"] = max(attrs["target_buffer_ahead_bytes"], attrs["readahead_bytes"])
        attrs["max_total_buffer_bytes"] = max(
            attrs["max_total_buffer_bytes"],
            attrs["target_buffer_ahead_bytes"],
        )
        attrs["low_watermark_bytes"] = min(
            attrs["low_watermark_bytes"],
            attrs["target_buffer_ahead_bytes"],
        )
        return attrs
