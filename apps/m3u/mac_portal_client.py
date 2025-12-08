import logging
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List 
from json import JSONDecodeError

import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)


class MacPortalError(Exception):
    """Error while accessing MAC/STB portal."""

    pass


class MacPortalClient:
    """
    Client for Stalker-/STB portals with MAC login.
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
        self.genres_by_id: Dict[str, str] = {}
        self.handshake_method: Optional[str] = None

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

    def _cookies(self, force_london: bool = False) -> dict:
        """Erzeugt Cookies, optional mit erzwungener Europe/London Zeitzone."""
        # Prüfe den erfolgreichen Handshake-Stil, falls nicht explizit London erzwungen wird
        use_london = force_london or self.handshake_method == "stb_london_macreplay"
        tz = "Europe/London" if use_london else self.timezone
        return {
            "mac": self.mac,
            "stb_lang": "en",
            "timezone": tz,
        }

    # ------------- step 1: resolve portal url (Unverändert) -------------

    def resolve_portal_url(self) -> str:
        # ... (Logik bleibt unverändert, aber muss in der finalen Datei vorhanden sein)
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
                if r.status_code < 400:
                    self.portal_url = url
                    logger.info("MAC portal load.php detected: %s", url)
                    return self.portal_url
            except Exception as e:
                logger.debug("Portal candidate %s failed: %s", url, e)

        self.portal_url = self.original_base_url
        logger.warning(
            "Could not positively identify load.php, using base URL: %s",
            self.portal_url,
        )
        return self.portal_url

    # ------------- step 2: handshake / token (Logik für Handshake-Stile bleibt) -------------
    
    def _handshake_stb_london_macreplay(self) -> str:
        # ... (Logik bleibt) ...
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=False)
        params = {
            "type": "stb",
            "action": "handshake",
            "JsHttpRequest": "1-xml",
        }
        r = self.session.get(
            portal,
            params=params,
            headers=headers,
            cookies=self._cookies(force_london=True), 
            proxies=proxies,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        try:
            token = data["js"]["token"]
        except Exception as exc:
            raise MacPortalError(f"STB London Handshake ohne Token: {exc}")
        logger.debug("STB London MAC portal token acquired")
        return token

    def _handshake_plugin_style(self) -> str:
        # ... (Logik bleibt) ...
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=False)
        params = {
            "type": "stb",
            "action": "handshake",
            "JsHttpRequest": "1-xml",
        }
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
            raise MacPortalError(f"Plugin-Handshake ohne Token: {exc}")
        logger.debug("Plugin-Stil (configured TZ) MAC portal token acquired")
        return token
        
    def _handshake_0120_style(self) -> str:
        return self._handshake_plugin_style()

    def _handshake_mac_portal_style(self) -> str:
        # ... (Logik bleibt) ...
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=False)
        params = {
            "type": "stb",
            "action": "handshake",
            "mac": self.mac,
            "JsHttpRequest": "1-xml",
        }
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
        js = data.get("js") or {}
        token = js.get("token") or data.get("token")
        if not token:
            raise MacPortalError("mac_portal_client-style handshake did not return a token")
        logger.debug("mac_portal_client-style MAC portal token acquired")
        return token

    def _handshake_portals_style(self) -> str:
        # ... (Logik bleibt) ...
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=False)
        params_token = {
            "type": "stb",
            "action": "handshake",
            "mac": self.mac,
            "JsHttpRequest": "1-xml",
        }
        r = self.session.get(
            portal,
            params=params_token,
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
            raise MacPortalError(f"Portals-style handshake without token: {exc}")

        self.token = token
        headers_action = self._default_headers(with_auth=True)
        params_action = {
            "type": "stb",
            "action": "handshake",
            "token": self.token,
            "mac": self.mac,
            "JsHttpRequest": "1-xml",
        }
        try:
            r2 = self.session.get(
                portal,
                params=params_action,
                headers=headers_action,
                cookies=self._cookies(),
                proxies=proxies,
                timeout=10,
            )
            r2.raise_for_status()
        except Exception as exc:
            logger.debug("Secondary STB handshake (portals-style) failed/ignored: %s", exc)

        logger.debug("Portals-style MAC portal token acquired")
        return token
        
    def _detect_portal_error_v5(self, response: requests.Response) -> None:
        # ... (Logik bleibt) ...
        try:
            text = response.text or ""
        except Exception:
            text = ""
        lowered = text.lower()
        markers = [
            "user not found", "user not exists", "mac address blocked", "account blocked", 
            "account disabled", "your account is banned", "hmac failed", "wrong signature", 
            "not authorized", "authorization failed", "maximum number of connections", 
            "too many connections", "maintenance",
        ]
        for marker in markers:
            if marker in lowered:
                raise MacPortalError(f"Portal error detected (v5): {marker}")
        
    def _default_headers_v5(self, with_auth: bool = False) -> dict:
        # ... (Logik bleibt) ...
        mag_ua_pool = [
            ("Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/538.1 (KHTML, like Gecko) MAG254 Safari/538.1"),
            ("Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/537.36 (KHTML, like Gecko) MAG255 Safari/537.36"),
            ("Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG250 Safari/533.3"),
        ]
        try:
            idx = abs(hash(self.mac)) % len(mag_ua_pool)
        except Exception:
            idx = 0
        ua = mag_ua_pool[idx]

        portal = self.portal_url or self.original_base_url
        parsed = urlparse(portal)
        host = parsed.netloc
        referer = portal

        headers = {
            "User-Agent": ua,
            "X-User-Agent": "Model: MAG254; Link: Ethernet",
            "Accept": ("application/json,application/javascript,text/javascript,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "Keep-Alive",
            "X-Requested-With": "XMLHttpRequest",
            "stb_lang": "en",
        }
        if host:
            headers["Host"] = host
        if referer:
            headers["Referer"] = referer
        if with_auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
        
    def _handshake_v5_style(self) -> str:
        # ... (Logik bleibt) ...
        portal = self.resolve_portal_url()
        params = {
            "type": "stb",
            "action": "handshake",
            "mac": self.mac,
            "JsHttpRequest": "1-xml",
        }
        proxies = self._get_proxies()

        last_error: Optional[Exception] = None
        for attempt in range(2):
            headers = self._default_headers_v5(with_auth=False)
            try:
                r = self.session.get(
                    portal,
                    params=params,
                    headers=headers,
                    cookies=self._cookies(),
                    proxies=proxies,
                    timeout=10,
                )
                r.raise_for_status()
                self._detect_portal_error_v5(r)
                data = r.json().get("js") or {}
                token = data.get("token")
                if not token:
                    raise MacPortalError("v5-style handshake did not return a token")
                logger.info(
                    "v5-style handshake succeeded on attempt %s, token acquired",
                    attempt + 1,
                )
                return token
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "v5-style handshake attempt %s failed: %s", attempt + 1, exc
                )

        raise MacPortalError(f"v5-style handshake failed after retries: {last_error}")

    def _handshake_plus_style(self) -> str:
        # ... (Logik bleibt) ...
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=False)
        params = {
            "type": "stb",
            "action": "handshake",
            "mac": self.mac,
            "JsHttpRequest": "1-xml",
        }

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
        js = data.get("js") or {}
        token = js.get("token") or data.get("token")
        if not token:
            raise MacPortalError("plus-style fallback handshake did not return a token")
        logger.debug("Plus-style fallback MAC portal token acquired")
        return token
        
    def handshake(self) -> str:
        # ... (Logik bleibt, nur die interne Struktur wird beibehalten) ...
        if self.token and self.handshake_method:
            return self.token

        errors = []

        styles: List[tuple] = [
            ("stb_london_macreplay", self._handshake_stb_london_macreplay), 
            ("plugin_macreplay", self._handshake_plugin_style),             
            ("0.12.0-03", self._handshake_0120_style),             
            ("mac_portal_client", self._handshake_mac_portal_style),
            ("portals", self._handshake_portals_style),
            ("v5", self._handshake_v5_style),
            ("plus", self._handshake_plus_style),
        ]

        for name, func in styles:
            try:
                token = func()
                if not token:
                    raise MacPortalError(f"{name} handshake did not return a token")

                old_token = self.token
                old_method = self.handshake_method

                self.token = token
                self.handshake_method = name

                try:
                    self._verify_after_handshake()
                except MacPortalError as ve:
                    logger.debug(
                        "Handshake verification failed for style %s: %s",
                        name,
                        ve,
                    )
                    self.token = old_token
                    self.handshake_method = old_method
                    errors.append(f"{name}-verify: {ve}")
                    continue

                logger.info("MAC portal handshake succeeded via %s style", name)
                return token

            except Exception as exc:
                errors.append(f"{name}: {exc}")
                logger.debug("Handshake via %s style failed: %s", name, exc)

        raise MacPortalError("All handshake variants failed: " + " | ".join(errors))

    def _verify_after_handshake(self) -> None:
        # ... (Logik bleibt) ...
        if not self.token:
            raise MacPortalError("Handshake verification called without token")

        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=True)
        
        cookies = self._cookies() 

        r = self.session.get(
            portal,
            params={
                "type": "account_info",
                "action": "get_main_info",
                "JsHttpRequest": "1-xml",
            },
            headers=headers,
            cookies=cookies, 
            proxies=proxies,
            timeout=10,
        )
        r.raise_for_status()

        try:
            data = r.json()
        except (ValueError, JSONDecodeError) as exc:
            raise MacPortalError(
                f"Handshake verification failed: invalid JSON: {exc}"
            )

        js = data.get("js") or {}
        if not isinstance(js, dict) or not js:
            raise MacPortalError(
                "Handshake verification failed: empty or invalid 'js' payload"
            )

        logger.debug("MAC portal handshake verification succeeded")

    # ------------- NEU (Wiederhergestellt): step 3: expiry / account info -------------

    def get_expires(self) -> Optional[str]:
        """
        Fetches expiry-like info from account_info/get_main_info.
        Wird für die aufrufende Logik benötigt (tasks.py).
        """
        if not self.token:
            self.handshake()
            
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=True)
        
        # Verwende die Cookies des erfolgreich verwendeten Handshake-Stils
        cookies = self._cookies() 

        try:
            r = self.session.get(
                portal,
                params={
                    "type": "account_info",
                    "action": "get_main_info",
                    "JsHttpRequest": "1-xml",
                },
                headers=headers,
                cookies=cookies, 
                proxies=proxies,
                timeout=10,
            )
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get expiry info: {e}")
            return None
            
        try:
            data = r.json().get("js") or {}
            # Häufig wird das Ablaufdatum in Feldern wie 'phone', 'expiry' oder 'expire' gespeichert.
            # Wir verwenden 'phone' als gängigen Platzhalter, wie es in einigen Implementierungen üblich ist.
            return data.get("phone") or data.get("expiry") or data.get("expire")
        except Exception as e:
            logger.error(f"Failed to parse expiry info JSON: {e}")
            return None


    # ------------- step 4: Kanalliste mit neuem Parameter (Logik bleibt) -------------

    def get_genres_map(self) -> Dict[str, str]:
        # ... (Logik bleibt unverändert, aber muss in der finalen Datei vorhanden sein)
        if self.genres_by_id:
            return self.genres_by_id

        if not self.token:
            self.handshake()
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=True)

        cookies = self._cookies()

        for action in ("get_genres", "get_genres_short"):
            try:
                r = self.session.get(
                    portal,
                    params={
                        "type": "itv",
                        "action": action,
                        "JsHttpRequest": "1-xml",
                    },
                    headers=headers,
                    cookies=cookies, 
                    proxies=proxies,
                    timeout=10,
                )
                r.raise_for_status()
                js = r.json().get("js")
                if not isinstance(js, list):
                    continue

                mapping: Dict[str, str] = {}
                for item in js:
                    try:
                        gid = item.get("id")
                        title = item.get("title") or item.get("name")
                        if gid is None or not title:
                            continue
                        mapping[str(gid)] = str(title)
                    except Exception:
                        continue

                if mapping:
                    self.genres_by_id = mapping
                    logger.info(
                        "Loaded %s MAC genres via %s", len(mapping), action
                    )
                    return self.genres_by_id
            except Exception as e:
                logger.debug("Failed to load MAC genres via %s: %s", action, e)

        logger.warning(
            "Could not load MAC genres mapping; will fall back to numeric Group IDs"
        )
        self.genres_by_id = {}
        return self.genres_by_id

    def get_all_channels_raw(self):
        # ... (Logik bleibt unverändert, inklusive des neuen Parameters)
        if not self.token:
            self.handshake()
        portal = self.resolve_portal_url()
        proxies = self._get_proxies()
        headers = self._default_headers(with_auth=True)

        cookies = self._cookies()

        actions = ["get_all_channels"]
        last_error: Optional[Exception] = None

        for action in actions:
            try:
                params = {
                    "type": "itv",
                    "action": action,
                    "force_ch_link_check": "false",
                    "JsHttpRequest": "1-xml",
                }
                
                r = self.session.get(
                    portal,
                    params=params,
                    headers=headers,
                    cookies=cookies, 
                    proxies=proxies,
                    timeout=20,
                )
                r.raise_for_status()

                payload = r.json()
                js = payload.get("js") or {}
                data = js.get("data") or []

                if not isinstance(data, list) or not data:
                    last_error = MacPortalError(f"no usable channel data for action {action}")
                    continue
                
                logger.info("Loaded %s MAC channels via action %s", len(data), action)
                return data

            except Exception as exc:
                last_error = exc

        raise MacPortalError(
            f"get_all_channels failed for actions {actions}: {last_error}"
        )
        
    def create_link(self, cmd: str) -> str:
        # ... (Logik bleibt unverändert) ...
        if not cmd:
            raise MacPortalError("Missing cmd for create_link")

        if not self.token:
            self.handshake()

        portal = self.resolve_portal_url()
        proxies = self._get_proxies()

        styles: List[tuple] = [
             (
                "stb_london_full",
                self._default_headers(with_auth=True),
                True,
                False,
                True,   
                True,   
            ),
            (
                "plugin_style",
                self._default_headers(with_auth=True),
                True,
                False,
                False,  
                False,  
            ),
            (
                "stb_js_full_fallback", 
                self._default_headers(with_auth=True),
                True,
                False,
                True,
                False,
            ),
        ]

        errors = []
        last_error: Optional[Exception] = None

        for style_name, headers, use_js, use_v5_detection, full_params, force_london_tz in styles:
            
            cookies = self._cookies(force_london=force_london_tz)

            params = {
                "type": "itv",
                "action": "create_link",
                "cmd": cmd,
            }
            if full_params:
                params.update({
                    "series": "0",
                    "forced_storage": "false",
                    "disable_ad": "false",
                    "download": "false",
                    "force_ch_link_check": "false",
                })
                
            if use_js:
                params["JsHttpRequest"] = "1-xml"

            try:
                r = self.session.get(
                    portal,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                    proxies=proxies,
                    timeout=10,
                )
                r.raise_for_status()

                if use_v5_detection:
                    self._detect_portal_error_v5(r)

                payload = r.json()
                js = payload.get("js") or {}
                
                cmd_value = js.get("cmd") or js.get("link")
                if not cmd_value or not isinstance(cmd_value, str):
                    last_error = MacPortalError(f"create_link via {style_name} response without cmd/link field")
                    errors.append(str(last_error))
                    continue

                url = self._extract_stream_url(cmd_value)
                if not url:
                    last_error = MacPortalError(f"create_link via {style_name} could not extract stream URL")
                    errors.append(str(last_error))
                    continue

                logger.info("Resolved stream URL via %s for MAC %s: %s", style_name, self.mac, url)
                return url

            except Exception as exc:
                last_error = exc
                errors.append(f"{style_name}: {exc}")
                continue

        msg = "All create_link variants failed for MAC %s: %s" % (self.mac, " | ".join(errors))
        logger.error(msg)
        raise MacPortalError(msg)

    def _extract_stream_url(self, cmd: str) -> Optional[str]:
        # ... (Logik bleibt unverändert) ...
        if not cmd:
            return None
        parts = cmd.split()
        for p in parts:
            if p.startswith("http://") or p.startswith("https://"):
                return p
        return None

    def _detect_group_title(self, ch: Dict[str, Any]) -> str:
        # ... (Logik bleibt unverändert) ...
        candidates = [
            "tv_genre_title", "genre_title", "category_name", "cat_name", "group_name", "group_title", "genre_name",
        ]
        for key in candidates:
            val = ch.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

        genres = ch.get("genres") or ch.get("categories")
        if isinstance(genres, list) and genres:
            first = genres[0]
            if isinstance(first, dict):
                for key in ("title", "name", "genre_title", "category_name"):
                    val = first.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()

        genre_id = (
            ch.get("tv_genre_id")
            or ch.get("genre_id")
            or ch.get("cat_id")
        )
        if genre_id is not None:
            try:
                genres_map = self.get_genres_map()
            except MacPortalError:
                genres_map = self.genres_by_id or {}
            label = genres_map.get(str(genre_id))
            if label:
                return label
            return f"Group {genre_id}"

        return "MAC"
    
    def get_channels(self):
        # ... (Logik bleibt unverändert) ...
        raw_list = self.get_all_channels_raw()
        normalized = []
        for ch in raw_list:
            ch_id = ch.get("id")
            name = ch.get("name") or f"Channel {ch_id}"

            group_title = self._detect_group_title(ch)

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
        logger.info("Normalized %s MAC channels into groups", len(normalized))
        return normalized
