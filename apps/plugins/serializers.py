from rest_framework import serializers


class PluginActionSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    confirm = serializers.JSONField(required=False)
    button_label = serializers.CharField(required=False, allow_blank=True)
    button_variant = serializers.CharField(required=False, allow_blank=True)
    button_color = serializers.CharField(required=False, allow_blank=True)


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
