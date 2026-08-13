# apps/mac_panel/api_views.py
import logging

from django.core.cache import cache
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin
from core.models import CoreSettings
from core.utils import build_absolute_uri_with_port, log_system_event

from .client import MacPanelClient, MacPanelError
from .credentials import build_xc_payload
from .models import MacPanelDevice
from .serializers import MacPanelDeviceSerializer

logger = logging.getLogger(__name__)

# Cached device JWT: {"jwt": str, "panel_device_id": str}. ~30 min TTL — the
# panel's own JWTs are short-lived; this just avoids re-solving a captcha on
# every push within a session.
_TOKEN_CACHE_PREFIX = "macpanel:token:"
_TOKEN_CACHE_TTL_SECONDS = 30 * 60


def _token_cache_key(device_id):
    return f"{_TOKEN_CACHE_PREFIX}{device_id}"


def _public_base_url(request):
    """Return the configured public URL, or fall back to the request's own
    origin (via core.utils.build_absolute_uri_with_port, so it respects
    X-Forwarded-Host/-Port behind nginx) with a warning the caller should
    surface to the UI."""
    configured = CoreSettings.get_mac_panel_settings().get("public_url") or ""
    if configured:
        return configured.rstrip("/"), None
    fallback = build_absolute_uri_with_port(request, "").rstrip("/")
    warning = (
        "No public URL is configured for MAC-panel pushes (Settings > MAC Panel); "
        f"falling back to this request's own origin ({fallback}), which may not "
        "be what customer devices can reach."
    )
    return fallback, warning


_PLAYLIST_ID_KEYS = ("id", "_id", "current_playlist_url_id", "playlist_id")


def _find_playlist_id(playlists_response, playlist_name):
    """Best-effort match of the just-saved playlist by name.

    ``savePlaylist``'s own response cannot be trusted for a usable id — the
    panel's own SPA never reads one from it either (confirmed by reading its
    JS: it only checks ``response.status === 200`` after saving, then makes
    a *separate* ``device/playlists`` call to refresh its list). This
    mirrors that pattern instead of guessing a response key, which is what
    caused every push to fall back to ``current_playlist_url_id: -1``
    (create) and silently duplicate the playlist on every re-push.
    """
    entries = (playlists_response or {}).get("playlists")
    if not isinstance(entries, list):
        return None
    matches = [
        e for e in entries
        if isinstance(e, dict) and e.get("playlist_name") == playlist_name
    ]
    if not matches:
        return None
    # If more than one shares the name (e.g. leftover duplicates from
    # before this fix), take the last one returned — panels list playlists
    # in creation order, so this is the most recently created/updated.
    entry = matches[-1]
    for key in _PLAYLIST_ID_KEYS:
        if entry.get(key) not in (None, ""):
            return entry[key]
    return None


class MacPanelDeviceViewSet(viewsets.ModelViewSet):
    """Admin-only CRUD for MAC-panel devices, plus captcha relay + credential
    push actions. Every action requires IsAdmin — there is no owner-style
    exception like UserViewSet's ``me``."""

    serializer_class = MacPanelDeviceSerializer
    queryset = MacPanelDevice.objects.all()

    def get_permissions(self):
        return [IsAdmin()]

    def get_queryset(self):
        qs = MacPanelDevice.objects.all().select_related("user")
        user_id = self.request.query_params.get("user")
        if user_id:
            qs = qs.filter(user_id=user_id)
        return qs

    @action(detail=True, methods=["post"], url_path="captcha")
    def captcha(self, request, pk=None):
        device = self.get_object()
        client = MacPanelClient(device.resolve_base_url())
        try:
            data = client.get_captcha()
        except MacPanelError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"svg": data.get("svg"), "captcha_token": data.get("token")})

    @action(detail=True, methods=["post"], url_path="push")
    def push(self, request, pk=None):
        device = self.get_object()
        captcha = request.data.get("captcha")
        captcha_token = request.data.get("captcha_token")

        base_url = device.resolve_base_url()
        if not base_url:
            return Response(
                {"error": f"No base URL configured for panel '{device.panel}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client = MacPanelClient(base_url)

        public_base_url, warning = _public_base_url(request)
        cache_key = _token_cache_key(device.id)
        cached = cache.get(cache_key)

        jwt = None
        panel_device_id = None

        if cached:
            jwt = cached.get("jwt")
            panel_device_id = cached.get("panel_device_id")

        if not jwt:
            if not captcha or not captcha_token:
                return Response(
                    {"error": "captcha_required"}, status=status.HTTP_428_PRECONDITION_REQUIRED
                )
            try:
                login_data = client.device_login(
                    device.mac_address, device.device_key, captcha, captcha_token
                )
            except MacPanelError as exc:
                self._record_push_result(device, "error", str(exc))
                return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

            jwt = login_data.get("token")
            panel_device_id = (login_data.get("device") or {}).get("_id")
            if not jwt or not panel_device_id:
                message = login_data.get("message") or "Panel login did not return a device token."
                self._record_push_result(device, "error", message)
                return Response({"error": message}, status=status.HTTP_502_BAD_GATEWAY)

        payload = build_xc_payload(device.user, device, public_base_url)

        try:
            result = client.save_playlist(jwt, panel_device_id, payload)
        except MacPanelError as exc:
            # The cached token may have expired/been rejected; if we used a
            # cached token (no captcha on this request) drop it and ask for a
            # fresh captcha rather than surfacing a confusing panel error.
            if cached and not captcha:
                cache.delete(cache_key)
                return Response(
                    {"error": "captcha_required"}, status=status.HTTP_428_PRECONDITION_REQUIRED
                )
            self._record_push_result(device, "error", str(exc))
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        cache.set(
            cache_key,
            {"jwt": jwt, "panel_device_id": panel_device_id},
            timeout=_TOKEN_CACHE_TTL_SECONDS,
        )

        message = result.get("message") or "Credentials pushed successfully."

        # savePlaylist's own response doesn't reliably carry a usable id (see
        # _find_playlist_id's docstring) — confirm it with a follow-up
        # list_playlists call instead, the same way the panel's own SPA
        # does. Without this, last_playlist_id never gets populated and
        # every push falls back to current_playlist_url_id: -1 (create),
        # silently duplicating the playlist on every re-push.
        playlist_id = device.last_playlist_id
        try:
            playlists_response = client.list_playlists(jwt, panel_device_id)
            found_id = _find_playlist_id(playlists_response, device.playlist_name)
            if found_id:
                playlist_id = found_id
        except MacPanelError as exc:
            # The push itself already succeeded — don't fail the request
            # over this confirmation step, just log it. The next push will
            # retry the lookup; worst case it creates instead of updating.
            logger.warning(
                "MAC-panel push for device %s succeeded but the follow-up "
                "list_playlists lookup failed: %s", device.id, exc,
            )

        self._record_push_result(device, "success", message, playlist_id=playlist_id)

        response_body = {"status": "success", "message": message}
        if warning:
            response_body["warning"] = warning
        return Response(response_body)

    def _record_push_result(self, device, status_value, message, playlist_id=None):
        device.last_pushed_at = timezone.now()
        device.last_push_status = status_value
        device.last_push_message = message[:2000] if message else ""
        if playlist_id:
            device.last_playlist_id = str(playlist_id)
        device.save(update_fields=[
            "last_pushed_at", "last_push_status", "last_push_message", "last_playlist_id",
        ])

        log_system_event(
            event_type="mac_panel_push",
            user=device.user.username,
            device_id=device.id,
            panel=device.panel,
            mac_address=device.mac_address,
            status=status_value,
            message=message,
        )
