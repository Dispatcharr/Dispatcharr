import logging
import json
import hashlib
import time
import random
import string
import re
from urllib.parse import urlparse, parse_qsl, urlunparse, quote, unquote
from typing import Optional, Dict, List, Any, Tuple

import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)

class MacPortalError(Exception):
    """Custom error for MAC Portal issues."""
    pass

class MacPortalClient:
    """
    Advanced Client for Stalker-/STB portals with MAC login.
    Implements full MAG250/254 emulation based on Enigma2 plugin logic.
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
        self.mac = mac.upper().strip()
        self.timezone = timezone
        self.proxy = proxy

        # Initialize Session
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

        # State Variables
        self.portal_url: Optional[str] = None
        self.token: Optional[str] = None          # Auth token
        self.token_random: Optional[str] = None   # Random seed from handshake
        self.play_token: Optional[str] = None     # Token needed for streams
        self.profile_status: int = 0
        self.expiry_date: Optional[str] = None
        
        # Cache
        self.genres_map: Dict[str, str] = {}
        self.channels_cache: List[Dict] = []

        # Generate Device Hashes (once, on init)
        self._generate_device_hashes()

    def _generate_device_hashes(self):
        """Generates STB-like serials and IDs based on MAC."""
        self.sn = hashlib.md5(self.mac.encode()).hexdigest().upper()[:13]
        self.device_id = hashlib.sha256(self.mac.encode()).hexdigest().upper()
        self.device_id2 = self.device_id
        self.adid = hashlib.md5((self.sn + self.mac).encode()).hexdigest()
        self.hw_version_2 = hashlib.sha1(self.mac.encode()).hexdigest()
        self.prehash = hashlib.sha1((self.sn + self.mac).encode()).hexdigest()

    def _get_proxies(self) -> Optional[dict]:
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    def _get_headers(self, auth: bool = True) -> dict:
        """mimics MAG250/254 headers."""
        headers = {
            "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG250 stbapp ver: 2 rev: 369 Safari/533.3",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "X-User-Agent": "Model: MAG250; Link: WiFi",
            "Connection": "Keep-Alive", # Stalker likes Keep-Alive
            "Pragma": "no-cache",
        }
        
        # Cookie construction
        cookies = [f"mac={self.mac}", "stb_lang=en", f"timezone={self.timezone}"]
        
        # Some portals require adid in cookie if it's a specific path
        if self.portal_url and "/stalker_portal/" in self.portal_url:
             cookies.append(f"adid={self.adid}")
        
        headers["Cookie"] = "; ".join(cookies)

        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            
        return headers

    def _make_request(self, url: str, method: str = "GET", params: dict = None, auth: bool = True) -> dict:
        """Central request handler."""
        proxies = self._get_proxies()
        headers = self._get_headers(auth=auth)
        
        # Ensure JsHttpRequest is always present
        if params is None:
            params = {}
        if "JsHttpRequest" not in params:
            params["JsHttpRequest"] = "1-xml"

        try:
            if method.upper() == "POST":
                # Stalker often sends params in query string even for POST, 
                # but let's stick to requests param handling which puts them in URL for get
                # For POST in utils.py they often put params in url or body. 
                # Requests 'params' puts them in URL, 'data' in body. 
                # Stalker usually expects them in the URL/QueryString even for POST.
                r = self.session.post(url, headers=headers, params=params, proxies=proxies, timeout=15, verify=False)
            else:
                r = self.session.get(url, headers=headers, params=params, proxies=proxies, timeout=15, verify=False)
            
            r.raise_for_status()
            
            # Handle potential JSON decode errors
            try:
                data = r.json()
            except json.JSONDecodeError:
                # Fallback: sometimes they return text/html with errors
                raise MacPortalError(f"Invalid JSON response from {url}: {r.text[:100]}")
            
            return data

        except requests.RequestException as e:
            raise MacPortalError(f"Request failed: {e}")

    # =========================================================================
    # 1. URL Resolution (Logic from utils.py/playlists.py)
    # =========================================================================

    def resolve_portal_url(self) -> str:
        """Finds the correct API endpoint (load.php or portal.php)."""
        if self.portal_url:
            return self.portal_url

        # Check if user provided the full API URL already
        if self.original_base_url.endswith(("load.php", "portal.php")):
            self.portal_url = self.original_base_url
            return self.portal_url

        parsed = urlparse(self.original_base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        # Priority list from utils.py
        candidates = [
            "/stalker_portal/server/load.php",
            "/stalker_portal/load.php",
            "/c/load.php",
            "/portal.php",
            "/stalker_portal/c/", 
            "/c/"
        ]

        logger.info(f"Probing portal URL for {base}...")

        proxies = self._get_proxies()
        headers = self._get_headers(auth=False)

        for path in candidates:
            url = base + path
            try:
                # Use HEAD or GET. GET is safer for detection.
                r = self.session.get(url, headers=headers, proxies=proxies, timeout=5, verify=False)
                
                # FIX: Accept redirects (3xx) as success too
                if r.status_code < 400:
                    self.portal_url = url
                    logger.info(f"Resolved Portal URL: {self.portal_url}")
                    return self.portal_url
            except Exception:
                pass
        
        # Fallback
        logger.warning("Could not automatically resolve URL. Using fallback.")
        self.portal_url = self.original_base_url
        return self.portal_url

    # =========================================================================
    # 2. Authentification (Handshake + Get Profile)
    # =========================================================================

    def connect(self) -> bool:
        """Main method to establish connection."""
        try:
            self.resolve_portal_url()
            self._handshake()
            self._get_profile()
            self._get_account_info() # For expiry
            return True
        except MacPortalError as e:
            logger.error(f"Connection failed: {e}")
            return False

    def _handshake(self):
        """Step 1: Get initial token."""
        if not self.portal_url:
            raise MacPortalError("Portal URL not set")

        params = {
            "type": "stb",
            "action": "handshake",
            "mac": self.mac, # Fallback param
        }
        
        # First attempt: Standard POST
        data = self._make_request(self.portal_url, method="POST", params=params, auth=False)
        js = data.get("js", {})

        # Logic from utils.py: Handle "missing" msg by generating random token
        if "msg" in js and "missing" in str(js.get("msg")).lower():
            logger.info("Handshake requested specific token generation...")
            random_token = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(32))
            prehash = hashlib.sha1(random_token.encode()).hexdigest()
            
            # Update headers manually for this request
            self.token = random_token # Temp set for header generation
            
            params["mac"] = self.mac
            params["prehash"] = prehash
            
            data = self._make_request(self.portal_url, method="POST", params=params, auth=True)
            js = data.get("js", {})

        self.token = js.get("token")
        self.token_random = js.get("random")

        if not self.token:
            raise MacPortalError("Handshake failed: No token received.")
        
        logger.debug(f"Handshake successful. Token: {self.token}")

    def _get_profile(self):
        """Step 2: Send metrics and get play_token (The 'Super Logic')."""
        if not self.token:
            raise MacPortalError("Cannot get profile without token.")

        timestamp = str(round(time.time()))
        
        # Prepare Metrics JSON
        if "/stalker_portal/" in self.portal_url:
            host_metrics = {
                "type": "stb",
                "model": "MAG254",
                "mac": self.mac,
                "sn": self.sn,
                "uid": "",
                "random": self.token_random
            }
            # Specifics for stalker_portal
            stb_type = "MAG254"
            image_version = "218"
            ver_str = "ImageDescription: 0.2.18-r14-pub-250; ImageDate: Fri Jan 15 15:20:44 EET 2016; PORTAL version: 5.3.0; API Version: JS API version: 328; STB API version: 134; Player Engine version: 0x566"
        else:
            host_metrics = {
                "mac": self.mac,
                "sn": self.sn,
                "type": "STB",
                "model": "MAG250",
                "uid": "",
                "random": ""
            }
            stb_type = "MAG250"
            image_version = "218"
            ver_str = ""

        # JSON Dump -> Quote (URL Encode)
        metrics_json = json.dumps(host_metrics)
        encoded_metrics = quote(metrics_json)

        params = {
            "type": "stb",
            "action": "get_profile",
            "mac": self.mac,
            "hd": "1",
            "ver": ver_str,
            "num_banks": "2",
            "sn": self.sn,
            "stb_type": stb_type,
            "client_type": "STB",
            "image_version": image_version,
            "video_out": "hdmi",
            "device_id": self.device_id,
            "device_id2": self.device_id2,
            "signature": "",
            "auth_second_step": "1",
            "hw_version": "1.7-BD-00",
            "hw_version_2": self.hw_version_2,
            "not_valid_token": "0",
            "metrics": encoded_metrics, # The encoded JSON
            "timestamp": timestamp,
            "api_signature": "261",
            "prehash": self.prehash
        }

        # Clean empty keys if standard portal
        if "/stalker_portal/" not in self.portal_url:
             # Basic params for standard
             params = {
                "type": "stb",
                "action": "get_profile",
                 "hd": "1",
                 "sn": self.sn,
                 "stb_type": stb_type,
                 "client_type": "STB",
                 "image_version": image_version,
                 "device_id": "",
                 "device_id2": "",
                 "hw_version": "1.7-BD-00",
                 "metrics": encoded_metrics,
                 "timestamp": timestamp
             }

        data = self._make_request(self.portal_url, method="POST", params=params, auth=True)
        js = data.get("js", {})

        self.play_token = js.get("play_token")
        self.profile_status = js.get("status", 0)
        
        if not self.play_token:
            # Fallback for some servers that return it differently or implicitly
            logger.warning("No play_token in profile response. Streaming might fail.")
        else:
             logger.info("Profile acquired. Play Token received.")

    def _get_account_info(self):
        """Fetch expiry date."""
        params = {
            "type": "account_info",
            "action": "get_main_info"
        }
        try:
            data = self._make_request(self.portal_url, method="POST", params=params, auth=True)
            js = data.get("js", {})
            # 'phone' often misused for expiry in stalker
            self.expiry_date = js.get("phone") or js.get("end_date")
            logger.info(f"Account Info: Expiry={self.expiry_date}")
        except Exception:
            logger.warning("Could not fetch account info/expiry.")

    # =========================================================================
    # 3. Content (Categories & Channels)
    # =========================================================================

    def get_categories(self) -> Dict[str, str]:
        """Fetches categories (Genres) and caches them."""
        params = {
            "type": "itv",
            "action": "get_genres"
        }
        
        try:
            data = self._make_request(self.portal_url, params=params)
            js = data.get("js", [])
            
            self.genres_map = {}
            for item in js:
                if isinstance(item, dict):
                    gid = str(item.get("id"))
                    title = item.get("title")
                    if gid and title:
                        self.genres_map[gid] = title
            return self.genres_map
        except Exception as e:
            logger.error(f"Failed to fetch genres: {e}")
            return {}

    def get_channels(self) -> List[Dict]:
        """Fetches all channels and normalizes them."""
        if not self.play_token:
            self.connect()

        # Ensure categories are loaded for mapping
        if not self.genres_map:
            self.get_categories()

        params = {
            "type": "itv",
            "action": "get_all_channels"
        }
        
        data = self._make_request(self.portal_url, params=params)
        raw_channels = data.get("js", {}).get("data", [])
        
        normalized = []
        for ch in raw_channels:
            ch_id = str(ch.get("id"))
            name = ch.get("name")
            cmd = ch.get("cmd")
            genre_id = str(ch.get("tv_genre_id"))
            
            group_name = self.genres_map.get(genre_id, "Other")
            
            if not ch_id or not cmd:
                continue

            normalized.append({
                "id": ch_id,
                "name": name,
                "group": group_name,
                "logo": ch.get("logo"),
                "cmd": cmd, # Important: keep raw cmd for create_link
            })
            
        self.channels_cache = normalized
        return normalized

    # =========================================================================
    # 4. Stream Generation
    # =========================================================================

    def get_stream_url(self, cmd: str) -> Optional[str]:
        """
        Converts a channel 'cmd' (e.g. 'ffmpeg http://...') into a real URL.
        Logic from live.py createLink.
        """
        if not cmd:
            return None

        # Check if cmd is already a URL
        if "http" in cmd and "localhost" not in cmd and "///" not in cmd:
             # Basic extraction if it looks like a direct link
             parts = cmd.split()
             for p in parts:
                 if p.startswith("http"):
                     return p

        # API Call to create_link
        params = {
            "type": "itv",
            "action": "create_link",
            "cmd": cmd,
            "series": "0",
            "forced_storage": "0",
            "disable_ad": "0",
            "download": "0",
            "force_ch_link_check": "0"
        }
        
        try:
            data = self._make_request(self.portal_url, method="POST", params=params)
            js = data.get("js", {})
            
            link = js.get("cmd")
            
            # If retry logic is needed (token expired), connect() again and retry once
            if not link:
                 logger.info("create_link returned empty, re-authenticating...")
                 self.connect()
                 data = self._make_request(self.portal_url, method="POST", params=params)
                 link = data.get("js", {}).get("cmd")

            if link:
                 # Clean up the link (sometimes has extra spaces or params)
                 if " " in link:
                     link = link.split()[1] # usually "ffmpeg http://url" -> take http://url
                 return link
            
        except Exception as e:
            logger.error(f"Error creating link for cmd {cmd}: {e}")
            
        return None
