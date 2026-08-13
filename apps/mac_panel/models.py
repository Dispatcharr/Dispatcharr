# apps/mac_panel/models.py
import re

from django.core.exceptions import ValidationError
from django.db import models

from .panels import PANELS

MAC_ADDRESS_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def normalize_mac_address(value):
    """Uppercase and colon-normalize a MAC address; accepts ':' or '-'
    separators, or no separators at all, on input."""
    if not value:
        return value
    cleaned = value.strip().upper().replace("-", ":")
    if ":" not in cleaned and len(cleaned) == 12:
        cleaned = ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))
    return cleaned


def validate_mac_address(value):
    if not MAC_ADDRESS_RE.match(value or ""):
        raise ValidationError(
            "%(value)s is not a valid MAC address (expected AA:BB:CC:DD:EE:FF)",
            params={"value": value},
        )


class MacPanelDevice(models.Model):
    """A MAC-address-based player device (IBO Player Pro family) whose XC
    playlist an admin can push Dispatcharr credentials to.

    ``device_key`` is stored in plaintext, matching this codebase's existing
    posture for ``User.custom_properties['xc_password']`` — there is no
    crypto dependency in this project to encrypt it with instead.
    """

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="mac_devices",
    )
    panel = models.CharField(
        max_length=32,
        choices=[(key, entry["label"]) for key, entry in PANELS.items()],
    )
    panel_base_url = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Override the registry base URL for this panel (e.g. a sibling domain).",
    )
    mac_address = models.CharField(max_length=17, validators=[validate_mac_address])
    device_key = models.CharField(max_length=255)
    label = models.CharField(max_length=100, blank=True, default="")
    playlist_name = models.CharField(max_length=100, default="Dispatcharr")
    include_epg = models.BooleanField(default=True)
    protect_pin = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Optional PIN to protect the pushed playlist on the panel side "
            "(mirrors the panel's own 'Protect Playlist' option). Blank = "
            "not protected."
        ),
    )

    last_pushed_at = models.DateTimeField(null=True, blank=True)
    last_push_status = models.CharField(max_length=20, blank=True, default="")
    last_push_message = models.TextField(blank=True, default="")
    last_playlist_id = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("panel", "mac_address")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_panel_display()} - {self.mac_address} ({self.user.username})"

    def save(self, *args, **kwargs):
        self.mac_address = normalize_mac_address(self.mac_address)
        validate_mac_address(self.mac_address)
        super().save(*args, **kwargs)

    def resolve_base_url(self):
        from .panels import resolve_base_url
        return resolve_base_url(self.panel, self.panel_base_url)
