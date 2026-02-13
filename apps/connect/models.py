from django.db import models
from .utils import SUPPORTED_EVENTS

SUPPORTED_EVENTS = {
    "channel_start": "Channel Started",
    "channel_stop": "Channel Stopped",
    "channel_reconnect": "Channel Reconnected",
    "channel_error": "Channel Error",
    "channel_failover": "Channel Failover",
    "stream_switch": "Stream Switch",
    "recording_start": "Recording Started",
    "recording_end": "Recording Ended",
    "epg_refresh": "EPG Refreshed",
    "m3u_refresh": "M3U Refreshed",
    "client_connect": "Client Connected",
    "client_disconnect": "Client Disconnected",
}

class Integration(models.Model):
    TYPE_CHOICES = [
        ("webhook", "Webhook"),
        ("api", "API"),
        ("script", "Custom Script"),
    ]
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    config = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EventSubscription(models.Model):
    EVENT_CHOICES = list(SUPPORTED_EVENTS.items())
    event = models.CharField(max_length=100, choices=EVENT_CHOICES)
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="subscriptions")
    enabled = models.BooleanField(default=True)
    payload_template = models.TextField(blank=True, null=True, help_text="Optional Jinja2/Django template for customizing payload")

class DeliveryLog(models.Model):
    subscription = models.ForeignKey(EventSubscription, on_delete=models.CASCADE, related_name="logs")
    status = models.CharField(max_length=50, choices=[("success", "Success"), ("failed", "Failed")])
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
