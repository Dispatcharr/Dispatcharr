from rest_framework import serializers
from .models import PluginRepo


class PluginActionSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    confirm = serializers.JSONField(required=False)
    button_label = serializers.CharField(required=False, allow_blank=True)
    button_variant = serializers.CharField(required=False, allow_blank=True)
    button_color = serializers.CharField(required=False, allow_blank=True)
    events = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )


class PluginFieldOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class PluginFieldSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField(required=False, allow_blank=True)
    type = serializers.ChoiceField(choices=["string", "number", "boolean", "select", "text", "info"])
    default = serializers.JSONField(required=False)
    help_text = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    placeholder = serializers.CharField(required=False, allow_blank=True)
    input_type = serializers.CharField(required=False, allow_blank=True)
    min = serializers.FloatField(required=False)
    max = serializers.FloatField(required=False)
    step = serializers.FloatField(required=False)
    value = serializers.CharField(required=False, allow_blank=True)
    options = PluginFieldOptionSerializer(many=True, required=False)


class PluginSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    version = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    author = serializers.CharField(required=False, allow_blank=True)
    help_url = serializers.CharField(required=False, allow_blank=True)
    enabled = serializers.BooleanField()
    fields = PluginFieldSerializer(many=True)
    settings = serializers.JSONField()
    actions = PluginActionSerializer(many=True)
    source_repo = serializers.IntegerField(required=False, allow_null=True)
    slug = serializers.CharField(required=False, allow_blank=True)
    is_managed = serializers.BooleanField(required=False)
    deprecated = serializers.BooleanField(required=False)


class PluginRepoSerializer(serializers.ModelSerializer):
    registry_url = serializers.SerializerMethodField()
    plugin_count = serializers.SerializerMethodField()

    class Meta:
        model = PluginRepo
        fields = [
            "id",
            "name",
            "url",
            "is_official",
            "enabled",
            "public_key",
            "signature_verified",
            "registry_url",
            "plugin_count",
            "last_fetched",
            "last_fetch_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "name", "is_official", "signature_verified", "registry_url", "plugin_count", "last_fetched", "last_fetch_status", "created_at", "updated_at"]

    def get_registry_url(self, obj):
        manifest = (obj.cached_manifest or {}).get("manifest", obj.cached_manifest or {})
        return manifest.get("registry_url", "") or ""

    def get_plugin_count(self, obj):
        manifest = (obj.cached_manifest or {}).get("manifest", obj.cached_manifest or {})
        plugins = manifest.get("plugins", [])
        return len(plugins) if isinstance(plugins, list) else 0
