# apps/mac_panel/serializers.py
from rest_framework import serializers

from .models import MacPanelDevice, validate_mac_address


class MacPanelDeviceSerializer(serializers.ModelSerializer):
    panel_display = serializers.CharField(source="get_panel_display", read_only=True)

    class Meta:
        model = MacPanelDevice
        fields = [
            "id",
            "user",
            "panel",
            "panel_display",
            "panel_base_url",
            "mac_address",
            "device_key",
            "label",
            "playlist_name",
            "include_epg",
            "protect_pin",
            "last_pushed_at",
            "last_push_status",
            "last_push_message",
            "last_playlist_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "last_pushed_at",
            "last_push_status",
            "last_push_message",
            "last_playlist_id",
            "created_at",
            "updated_at",
        ]
        # device_key sits at the same sensitivity as User.custom_properties'
        # xc_password, which this codebase serializes plainly (not masked) so
        # the admin who owns it can view/edit it. Same posture here — no
        # stricter, no looser.

    def validate_mac_address(self, value):
        from .models import normalize_mac_address
        normalized = normalize_mac_address(value)
        validate_mac_address(normalized)
        return normalized
