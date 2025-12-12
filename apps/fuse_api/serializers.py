from rest_framework import serializers


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
    enable_fuse = serializers.BooleanField(default=False)
    backend_base_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    movies_mount_path = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    tv_mount_path = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_backend_base_url(self, value):
        if value and not value.startswith(("http://", "https://")):
            raise serializers.ValidationError("backend_base_url must start with http:// or https://")
        return value
