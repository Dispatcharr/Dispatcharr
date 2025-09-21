from rest_framework import serializers


class PluginActionSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)


class PluginFieldSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    type = serializers.ChoiceField(choices=["string", "number", "boolean", "select"])  # simple types
    default = serializers.JSONField(required=False)
    help_text = serializers.CharField(required=False, allow_blank=True)
    options = serializers.ListField(child=serializers.DictField(), required=False)


class PluginSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    version = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    enabled = serializers.BooleanField()
    fields = PluginFieldSerializer(many=True)
    settings = serializers.JSONField()
    actions = PluginActionSerializer(many=True)

