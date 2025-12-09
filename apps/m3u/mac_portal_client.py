import logging
import json
import hashlib
import time
import random
import string
from urllib.parse import urlparse, quote, unquote
from typing import Optional, Dict, List

import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)


class MacPortalError(Exception):
    pass


class MacPortalClient:
    """
    Vollständiger MAG250 / MAG254 Stalker Portal Client
    (Dispatcharr-tauglich, EStalker-Logik)
    """

    def __init__(
        self,
        base_url: str,
        mac: str,
        proxy: Optional[str] = None,
        timezone: str = "Europe/Berlin",
    ):
        if not base_url:
            raise ValueError("base_url required")

        self.original_base_url = base_url.rstrip("/")
        self.mac = mac.upper().strip()
        self.proxy = proxy
        self.timezone = timezone

        self.portal_url: Optional[str] = None
        self.token: Optional[str] = None
        self.token_random: Optional[str] = None
        self.play_token: Optional[str] = None
        self.expiry_date: Optional[str] = None

        self.genres_map: Dict[str, str] = {}
        self.channels_cache: List[Dict] = []

        self.session = requests.Session()
        self.session.verify = False

        retries = Retry(
            total=3,
            backoff_factor=0.4,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

        # ✅ Cookies wirklich setzen
        self.session.cookies.set("mac", self.mac)
        self.session.cookies.set("stb_lang", "en")
        self.session.cookies.set("timezone", self.timezone)

        self._generate_device_hashes()

    # ---------------------------------------------------------------------

    def _generate_device_hashes(self):
        self.sn = hashlib.md5(self.mac.encode()).hexdigest().upper()[:13]
        self.device_id = hashlib.sha256(self.mac.encode()).hexdigest().upper()
        self.device_id2 = self.device_id
        self.adid = hashlib.md5((self.sn + self.mac).encode()).hexdigest()
        self.hw_version_2 = hashlib.sha1(self.mac.encode()).hexdigest()
        self.prehash = hashlib.sha1((self.sn + self.mac).encode()).hexdigest()

    def _headers(self, auth=True) -> dict:
        h = {
            "User-Agent": "Mozilla/5.0 (QtEmbedded; Linux) MAG250 stbapp ver:2",
            "Accept": "*/*",
            "Connection": "Keep-Alive",
            "X-User-Agent": "Model: MAG250; Link: WiFi",
        }
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _proxies(self):
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    def _request(self, url, method="GET", data=None, auth=True):
        if not url:
            raise MacPortalError("Portal URL is None")

        if data is None:
            data = {}
        data.setdefault("JsHttpRequest", "1-xml")

        try:
            if method == "POST":
                r = self.session.post(
                    url,
                    headers=self._headers(auth),
                    data=data,  # ✅ KORREKT
                    proxies=self._proxies(),
                    timeout=15
                )
            else:
                r = self.session.get(
                    url,
                    headers=self._headers(auth),
                    params=data,
                    proxies=self._proxies(),
                    timeout=15
                )

            r.raise_for_status()
            return r.json()

        except Exception as e:
            raise MacPortalError(str(e))

    # ---------------------------------------------------------------------
    # Portal URL
    # ---------------------------------------------------------------------

    def resolve_portal_url(self):
        if self.portal_url:
            return self.portal_url

        if self.original_base_url.endswith(("portal.php", "load.php")):
            self.portal_url = self.original_base_url
            return self.portal_url

        parsed = urlparse(self.original_base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        candidates = [
            "/portal.php",
            "/stalker_portal/server/load.php",
            "/stalker_portal/load.php",
            "/c/load.php",
        ]

        for p in candidates:
            try:
                url = base + p
                r = self.session.get(url, timeout=5)
                if r.status_code == 200:
                    self.portal_url = url
                    return url
            except Exception:
                pass

        self.portal_url = self.original_base_url
        return self.portal_url

    # ---------------------------------------------------------------------
    # AUTH
    # ---------------------------------------------------------------------

    def connect(self):
        self.resolve_portal_url()
        self._handshake()
        self._get_profile()
        self._get_account_info()
        return True

    def _handshake(self):
        params = {
            "type": "stb",
            "action": "handshake",
            "mac": self.mac,
        }

        data = self._request(self.portal_url, "POST", params, auth=False)
        js = data.get("js", {})

        if "msg" in js and "missing" in str(js["msg"]).lower():
            rnd = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(32))
            params["prehash"] = hashlib.sha1(rnd.encode()).hexdigest()
            self.token = rnd
            data = self._request(self.portal_url, "POST", params, auth=True)
            js = data.get("js", {})

        self.token = js.get("token")
        self.token_random = js.get("random")

        if not self.token:
            raise MacPortalError("Handshake failed")

    def _get_profile(self):
        metrics = quote(json.dumps({
            "mac": self.mac,
            "sn": self.sn,
            "model": "MAG254",
            "random": self.token_random
        }))

        params = {
            "type": "stb",
            "action": "get_profile",
            "hd": "1",
            "metrics": metrics,
            "stb_type": "MAG254",
            "device_id": self.device_id,
            "device_id2": self.device_id2,
            "hw_version_2": self.hw_version_2,
            "prehash": self.prehash,
        }

        data = self._request(self.portal_url, "POST", params, auth=True)
        js = data.get("js", {})
        self.play_token = js.get("play_token")

    def _get_account_info(self):
        try:
            data = self._request(self.portal_url, "POST", {
                "type": "account_info",
                "action": "get_main_info"
            })
            js = data.get("js", {})
            self.expiry_date = js.get("end_date") or js.get("expire")
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # CONTENT
    # ---------------------------------------------------------------------

    def get_categories(self):
        data = self._request(self.portal_url, "POST", {
            "type": "itv",
            "action": "get_genres"
        })
        self.genres_map = {
            str(i["id"]): i["title"]
            for i in data.get("js", [])
            if "id" in i
        }
        return self.genres_map

    def get_channels(self):
        if not self.play_token:
            self.connect()

        if not self.genres_map:
            self.get_categories()

        data = self._request(self.portal_url, "POST", {
            "type": "itv",
            "action": "get_all_channels"
        })

        out = []
        for ch in data.get("js", {}).get("data", []):
            out.append({
                "id": str(ch.get("id")),
                "name": ch.get("name"),
                "group": self.genres_map.get(str(ch.get("tv_genre_id")), "Other"),
                "logo": ch.get("logo"),
                "cmd": ch.get("cmd"),
            })
        self.channels_cache = out
        return out

    # ---------------------------------------------------------------------
    # STREAM
    # ---------------------------------------------------------------------

    def create_link(self, cmd: str) -> Optional[str]:
        if not cmd:
            return None

        data = self._request(self.portal_url, "POST", {
            "type": "itv",
            "action": "create_link",
            "cmd": cmd,
        })

        link = data.get("js", {}).get("cmd")
        if not link:
            self.connect()
            data = self._request(self.portal_url, "POST", {
                "type": "itv",
                "action": "create_link",
                "cmd": cmd,
            })
            link = data.get("js", {}).get("cmd")

        if link and " " in link:
            link = link.split()[-1]

        return unquote(link) if link else None
