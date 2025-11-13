import logging
from urllib.parse import urlparse
from typing import Optional, List

import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)


class MacPortalError(Exception):
    """Error while accessing MAC/STB portal."""

    pass


class MacPortalClient:
    """
    Client for Stalker-/STB portals with MAC login.
    Handles:
      - resolving portal URL
      - handshake (token)
      - expiry info
      - channel list (get_all_channels)
    """

    def __init__(
        self,
        base_url: str,
        mac: str,
        proxy: Optional[str] = None,
        timezone: str = "Europe/Berlin",
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.original_base_url = base_url.rstrip("/")
        self.mac = mac
        self.timezone = timezone
        self.proxy = proxy

        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

        self.portal_url: Optional[str] = None
        self.token: Optional[str] = None

    # ------------- helpers -------------

    def _get_proxies(self) -> Optional[dict]:
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    def _default_headers(self, with_auth: bool = False) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C)",
        }
        if with_auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _cookies(self) -> dict:
        return {
            "mac": self.mac,
            "stb_lang": "en",
            "timezone": self.timezone,
        }

    # ------------- step 1: resolve portal url -------------

    def resolve_portal_url(self) -> str:
        """
        Try to detect the portal load.php URL.
        If original_base_url already ends with load.php, use it as-is.
        Otherwise probe common paths.
        """
        if self.portal_url:
            return self.portal_url

        if self.original_base_url.endswith("load.php"):
            self.portal_url = self.original_base_url
            return self.portal_url

        parsed = urlparse(self.original_base_url)
        if not parsed.scheme:
            self.original_base_url = "http://" + self.original_base_url
            parsed = urlparse(self.original_base_url)

        base = f"{parsed.scheme}://{parsed.netloc}"
        candidate_paths = [
            "/stalker_portal/server/load.php",
            "/stalker_portal/load.php",
            "/c/load.php",
            "/portal.php",
        ]

        proxies = self._get_proxies()
        headers = self._default_headers()

        for path in candidate_paths:
            url = base + path
            try:
                r = self.session.get(
                    url,
                    headers=headers,
                    cookies=self._cookies(),
                    proxies=proxies,
                    timeout=5,
                )
                if r.status_code == 200:
                    self.portal_url = url
                    logger.info("MAC portal load.php detected: %s", url)
                    return self.portal_url
            except Exception as e:
                logger.debug("Portal candidate %s failed: %s", url, e)

        self.portal_url = self.original_base_url
        logger.warning("Could not positively identify load.php, using base URL: %s", self.portal_url)
        return self.portal_url

    # ------------- step 2: handshake / token -------------

    def handshake(self) -> str:
        portal = self.resolve_portal_url()
        params = {
            "type": "stb",
            "action": "handshake",
            "JsHttpRequest": "1-xml",
        }
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=False)

        r = self.session.get(
            portal,
            params=params,
            headers=headers,
            cookies=self._cookies(),
            proxies=proxies,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        try:
            token = data["js"]["token"]
        except Exception as exc:
            raise MacPortalError(f"Handshake without token: {exc}")
        self.token = token
        logger.debug("MAC portal token acquired")
        return token

    # ------------- step 3: expiry / account info -------------

    def get_expires(self) -> Optional[str]:
        """
        Fetch expiry-like info from account_info/get_main_info.
        STB-Proxy uses 'phone' field for that.
        """
        if not self.token:
            self.handshake()
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=True)

        r = self.session.get(
            portal,
            params={
                "type": "account_info",
                "action": "get_main_info",
                "JsHttpRequest": "1-xml",
            },
            headers=headers,
            cookies=self._cookies(),
            proxies=proxies,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("js") or {}
        return data.get("phone")  # may contain expiry-like info

    # ------------- step 4: channels -------------

    def get_all_channels_raw(self) -> List[dict]:
        if not self.token:
            self.handshake()
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=True)

        r = self.session.get(
            portal,
            params={
                "type": "itv",
                "action": "get_all_channels",
                "JsHttpRequest": "1-xml",
            },
            headers=headers,
            cookies=self._cookies(),
            proxies=proxies,
            timeout=20,
        )
        r.raise_for_status()
        js = r.json().get("js") or {}
        return js.get("data") or []

    def _extract_stream_url(self, cmd: str) -> Optional[str]:
        if not cmd:
            return None
        parts = cmd.split()
        for p in parts:
            if p.startswith("http://") or p.startswith("https://"):
                return p
        return None

    def get_channels(self) -> List[dict]:
        """Return normalized channels list."""
        raw_list = self.get_all_channels_raw()
        normalized: List[dict] = []
        for ch in raw_list:
            ch_id = ch.get("id")
            name = ch.get("name") or f"Channel {ch_id}"
            group_title = ch.get("tv_genre_title") or ch.get("genre_title") or "MAC"
            cmd = ch.get("cmd") or ""
            url = self._extract_stream_url(cmd)
            if not url:
                continue
            normalized.append(
                {
                    "id": ch_id,
                    "name": name,
                    "group": group_title,
                    "url": url,
                    "raw": ch,
                }
            )
        return normalized
