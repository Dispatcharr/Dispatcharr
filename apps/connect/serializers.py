from rest_framework import serializers
from .models import Integration, EventSubscription, DeliveryLog
import os


class EventSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventSubscription
        fields = [
            "id",
            "event",
            "enabled",
            "payload_template",
            "integration",
        ]


class IntegrationSerializer(serializers.ModelSerializer):
    subscriptions = EventSubscriptionSerializer(many=True, read_only=True)

    class Meta:
        model = Integration
        fields = [
            "id",
            "name",
            "type",
            "config",
            "enabled",
            "created_at",
            "subscriptions",
        ]

    def validate(self, attrs):
        type = attrs.get("type") if "type" in attrs else getattr(self.instance, "type", None)
        config = attrs.get("config") if "config" in attrs else getattr(self.instance, "config", {})

        if type == "script":
            path = (config or {}).get("path")
            if not path or not isinstance(path, str):
                raise serializers.ValidationError({"config": "Script config must include a 'path' string"})

            real_path = os.path.abspath(os.path.realpath(path))
            if not os.path.exists(real_path):
                raise serializers.ValidationError({"config": f"Script path does not exist: {path}"})
        elif type == "webhook":
            url = (config or {}).get("url")
            if not url or not isinstance(url, str):
                raise serializers.ValidationError({"config": "Webhook config must include a 'url' string"})
        else:
            raise serializers.ValidationError({"type": "Unsupported integration type"})

        return attrs


class DeliveryLogSerializer(serializers.ModelSerializer):
    subscription = EventSubscriptionSerializer(read_only=True)

    class Meta:
        model = DeliveryLog
        fields = [
            "id",
            "subscription",
            "status",
            "request_payload",
            "response_payload",
            "error_message",
            "created_at",
        ]
