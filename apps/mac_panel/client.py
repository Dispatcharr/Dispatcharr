# apps/mac_panel/client.py
"""HTTP client for the IBOSOL-family MAC-panel JSON API.

Same outbound-HTTP shape as core/xtream_codes.py's Client: a pooled
requests.Session, a single request helper with a 60s timeout, and handling
for empty bodies / HTML error pages / JSON decode failures.

Hard constraint: this client never solves, OCR's, or otherwise bypasses the
panel's captcha. ``device_login`` sends whatever answer the caller supplies
(typed by a human admin in Dispatcharr's UI) — it is a relay, not a solver.
"""
import logging

import requests

logger = logging.getLogger(__name__)


class MacPanelError(Exception):
    """Raised on any MAC-panel API failure. ``str(exc)`` is exactly the
    message the admin should see — either the panel's own ``message`` field,
    or a description of the transport failure (timeout, HTML error page,
    invalid JSON, etc.)."""


class MacPanelClient:
    def __init__(self, base_url):
        if not base_url:
            raise MacPanelError("No panel base URL configured for this device.")
        self.base_url = base_url.rstrip("/")

        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=2,
            max_retries=3,
            pool_block=False,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _headers(self, jwt=None):
        headers = {
            "Content-Type": "application/json",
            "X-Client-Origin": self.base_url,
        }
        if jwt:
            headers["Authorization"] = f"Bearer {jwt}"
        return headers

    def _request(self, method, path, jwt=None, json_body=None):
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                json=json_body,
                headers=self._headers(jwt),
                timeout=60,
            )
        except requests.Timeout as exc:
            raise MacPanelError(f"Timed out contacting {self.base_url}.") from exc
        except requests.RequestException as exc:
            raise MacPanelError(f"Could not reach {self.base_url}: {exc}") from exc

        if not response.content:
            raise MacPanelError(f"Panel returned an empty response from {url}.")

        text = response.text.strip()
        try:
            data = response.json()
        except ValueError as exc:
            if text.startswith("<"):
                raise MacPanelError(
                    "Panel returned an HTML error page instead of JSON "
                    "(the panel may be down or blocking this request)."
                ) from exc
            raise MacPanelError(f"Panel returned invalid JSON: {text[:200]}") from exc

        if not response.ok:
            message = None
            if isinstance(data, dict):
                message = data.get("message") or data.get("error")
            raise MacPanelError(message or f"Panel request failed with HTTP {response.status_code}.")

        if isinstance(data, dict) and data.get("success") is False:
            raise MacPanelError(data.get("message") or "Panel rejected the request.")

        return data

    def get_captcha(self):
        """GET /frontend/captcha/generate -> {svg, token}"""
        return self._request("GET", "/frontend/captcha/generate")

    def device_login(self, mac_address, device_key, captcha, captcha_token):
        """POST /frontend/device/login -> {token, device, message}

        ``captcha`` is whatever the admin typed after reading the relayed
        captcha image — uppercased here to match the panel SPA's own
        behavior, never solved or guessed by this code.
        """
        body = {
            "mac_address": mac_address,
            "device_key": device_key,
            "captcha": (captcha or "").upper(),
            "token": captcha_token,
        }
        return self._request("POST", "/frontend/device/login", json_body=body)

    def list_playlists(self, jwt, device_id):
        """POST /frontend/device/playlists -> {playlists, device, ...}"""
        return self._request(
            "POST", "/frontend/device/playlists", jwt=jwt, json_body={"device_id": device_id}
        )

    def save_playlist(self, jwt, device_id, payload):
        """POST /frontend/device/savePlaylist"""
        body = dict(payload)
        body["device_id"] = device_id
        return self._request("POST", "/frontend/device/savePlaylist", jwt=jwt, json_body=body)
