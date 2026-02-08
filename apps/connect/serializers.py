from rest_framework import serializers
from .models import Integration, EventSubscription, DeliveryLog


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
