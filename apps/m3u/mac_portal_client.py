import logging
import json
import hashlib
import time
import random
import string
import re
from urllib.parse import urlparse, quote, unquote
from typing import Optional, Dict, List, Any, Tuple

import requests
from requests.adapters import HTTPAdapter, Retry

# Setup eines temporären Loggers für die Ausgabe
logger = logging.getLogger(__name__)

class MacPortalError(Exception):
    """Benutzerdefinierter Fehler für MAC Portal Probleme."""
    pass

class MacPortalClient:
    """
    Erweiterter Client für Stalker-/STB-Portale mit MAC-Login.
    Implementiert die vollständige MAG250/254 Emulation.
    """

    def __init__(
        self,
        base_url: str,
        mac: str,
        proxy: Optional[str] = None,
        timezone: str = "Europe/Berlin",
    ) -> None:
        if not base_url:
            raise ValueError("base_url ist erforderlich")
        
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
        self.expiry_date: Optional[str] = None # Speichert das Ablaufdatum
        
        # Cache
        self.genres_map: Dict[str, str] = {}
        self.channels_cache: List[Dict] = []

        # Generate Device Hashes (once, on init)
        self._generate_device_hashes()

    def _generate_device_hashes(self):
        """Generiert STB-ähnliche Seriennummern und IDs basierend auf der MAC."""
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
        """Emuliert MAG250/254 Header."""
        headers = {
            "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG250 stbapp ver: 2 rev: 369 Safari/533.3",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "X-User-Agent": "Model: MAG250; Link: WiFi",
            "Connection": "Keep-Alive", 
            "Pragma": "no-cache",
        }
        
        cookies = [f"mac={self.mac}", "stb_lang=en", f"timezone={self.timezone}"]
        
        if self.portal_url and "/stalker_portal/" in self.portal_url:
             cookies.append(f"adid={self.adid}")
        
        headers["Cookie"] = "; ".join(cookies)

        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            
        return headers

    def _make_request(self, url: str, method: str = "GET", params: dict = None, auth: bool = True) -> dict:
        """Zentraler Request-Handler."""
        proxies = self._get_proxies()
        headers = self._get_headers(auth=auth)
        
        if params is None:
            params = {}
        if "JsHttpRequest" not in params:
            params["JsHttpRequest"] = "1-xml"

        try:
            if method.upper() == "POST":
                r = self.session.post(url, headers=headers, params=params, proxies=proxies, timeout=15, verify=False)
            else:
                r = self.session.get(url, headers=headers, params=params, proxies=proxies, timeout=15, verify=False)
            
            r.raise_for_status()
            
            try:
                data = r.json()
            except json.JSONDecodeError:
                raise MacPortalError(f"Ungültige JSON-Antwort von {url}: {r.text[:100]}")
            
            return data

        except requests.RequestException as e:
            # Fügt Fehlercode zur Fehlerbehandlung im Handshake hinzu
            if hasattr(e.response, 'status_code') and e.response.status_code == 405:
                raise MacPortalError(f"Request fehlgeschlagen: 405 Client Error: Method Not Allowed for url: {url}")
            raise MacPortalError(f"Request fehlgeschlagen: {e}")

    # =========================================================================
    # 1. URL Resolution 
    # =========================================================================

    def resolve_portal_url(self) -> str:
        """Findet den korrekten API-Endpunkt."""
        if self.portal_url:
            return self.portal_url

        if self.original_base_url.endswith(("load.php", "portal.php")):
            self.portal_url = self.original_base_url
            return self.portal_url

        parsed = urlparse(self.original_base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        candidates = [
            "/stalker_portal/server/load.php",
            "/stalker_portal/load.php",
            "/c/load.php",
            "/portal.php",
            "/stalker_portal/c/", 
            "/c/"
        ]

        logger.info(f"Probiere Portal-URL für {base}...")

        proxies = self._get_proxies()
        headers = self._get_headers(auth=False)

        for path in candidates:
            url = base + path
            try:
                r = self.session.get(url, headers=headers, proxies=proxies, timeout=5, verify=False)
                
                # Akzeptiere Statuscodes < 400 (2xx Erfolg oder 3xx Redirect)
                if r.status_code < 400:
                    self.portal_url = url
                    logger.info(f"Aufgelöste Portal-URL: {self.portal_url}")
                    return self.portal_url
            except Exception:
                pass
        
        logger.warning("Konnte URL nicht automatisch auflösen. Verwende Fallback.")
        self.portal_url = self.original_base_url
        return self.portal_url

    # =========================================================================
    # 2. Authentifizierung (Handshake + Get Profile)
    # =========================================================================

    def connect(self) -> bool:
        """Hauptmethode zur Verbindungsherstellung."""
        try:
            self.resolve_portal_url()
            self._handshake()
            self._get_profile()
            self._get_account_info() # Holt Ablaufdatum
            return True
        except MacPortalError as e:
            logger.error(f"Verbindung fehlgeschlagen: {e}")
            return False

    def _handshake(self):
        """Schritt 1: Erhält den anfänglichen Token mit 405-Fallback-Logik."""
        if not self.portal_url:
            raise MacPortalError("Portal URL nicht gesetzt")

        params = {
            "type": "stb",
            "action": "handshake",
            "mac": self.mac, 
        }
        
        # NEU: 405-Fallback-Logik
        attempts = 0
        while attempts < 2:
            try:
                url_to_use = self.portal_url
                if attempts == 1:
                     # Beim zweiten Versuch, wenn der erste 405 war, die URL korrigieren
                     if self.portal_url.endswith("/"):
                        url_to_use = self.portal_url.rstrip("/") + "/load.php"
                        logger.warning(f"Handshake schlug mit 405 auf Verzeichnis fehl. Versuche Fallback-URL: {url_to_use}")
                        self.portal_url = url_to_use

                data = self._make_request(url_to_use, method="POST", params=params, auth=False)
                js = data.get("js", {})
                
                # Token-Generierungslogik
                if "msg" in js and "missing" in str(js.get("msg")).lower():
                    logger.info("Handshake fordert spezifische Token-Generierung an...")
                    random_token = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(32))
                    prehash_val = hashlib.sha1(random_token.encode()).hexdigest()
                    
                    self.token = random_token 
                    
                    params["mac"] = self.mac
                    params["prehash"] = prehash_val
                    
                    data = self._make_request(url_to_use, method="POST", params=params, auth=True)
                    js = data.get("js", {})

                self.token = js.get("token")
                self.token_random = js.get("random")

                if not self.token:
                    raise MacPortalError("Handshake fehlgeschlagen: Kein Token erhalten.")
                
                logger.debug(f"Handshake erfolgreich. Token: {self.token}")
                return # Erfolg, Schleife verlassen

            except MacPortalError as e:
                if "405 Client Error: Method Not Allowed" in str(e) and attempts == 0:
                    attempts += 1
                    continue # Versuche es erneut mit der korrigierten URL
                
                raise e # Bei jedem anderen Fehler oder nach dem Fallback, Fehler auslösen
            
            finally:
                if attempts == 0:
                    attempts += 1
        
        # Sollte nach 2 Versuchen fehlschlagen, falls der Fallback nicht geholfen hat.
        raise MacPortalError(f"Handshake fehlgeschlagen nach Fallback-Versuch für: {self.portal_url}")


    def _get_profile(self):
        """Schritt 2: Sendet Metriken und erhält play_token."""
        if not self.token:
            raise MacPortalError("Profil kann nicht ohne Token abgerufen werden.")

        timestamp = str(round(time.time()))
        
        # Vorbereitung der Metriken und Hashes
        if "/stalker_portal/" in self.portal_url:
            host_metrics = {
                "type": "stb",
                "model": "MAG254",
                "mac": self.mac,
                "sn": self.sn,
                "uid": "",
                "random": self.token_random
            }
            stb_type = "MAG254"
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
            ver_str = ""

        # JSON Dump -> URL Encode (Quote)
        metrics_json = json.dumps(host_metrics)
        encoded_metrics = quote(metrics_json)

        params = {
            "type": "stb",
            "action": "get_profile",
            "hd": "1",
            "sn": self.sn,
            "stb_type": stb_type,
            "client_type": "STB",
            "image_version": "218",
            "hw_version": "1.7-BD-00",
            "metrics": encoded_metrics, 
            "timestamp": timestamp,
        }
        
        # Hinzufügen spezifischer Stalker-Parameter, falls zutreffend
        if "/stalker_portal/" in self.portal_url:
            params.update({
                "mac": self.mac,
                "ver": ver_str,
                "num_banks": "2",
                "video_out": "hdmi",
                "device_id": self.device_id,
                "device_id2": self.device_id2,
                "auth_second_step": "1",
                "hw_version_2": self.hw_version_2,
                "api_signature": "261",
                "prehash": self.prehash
            })


        data = self._make_request(self.portal_url, method="POST", params=params, auth=True)
        js = data.get("js", {})

        self.play_token = js.get("play_token")
        self.profile_status = js.get("status", 0)
        
        if not self.play_token:
            logger.warning("Kein play_token in der Profilantwort erhalten.")
        else:
             logger.info("Profil erfolgreich abgerufen. Play Token erhalten.")

    def _get_account_info(self):
        """Ruft das Ablaufdatum ab."""
        params = {
            "type": "account_info",
            "action": "get_main_info"
        }
        try:
            data = self._make_request(self.portal_url, method="POST", params=params)
            js = data.get("js", {})
            
            # 'phone', 'end_date' oder 'expire' werden oft für das Ablaufdatum verwendet
            self.expiry_date = js.get("phone") or js.get("end_date") or js.get("expire")
            logger.info(f"Account Info: Ablaufdatum={self.expiry_date}")
        except Exception:
            logger.warning("Konnte Account-Informationen/Ablaufdatum nicht abrufen.")
    
    # KORREKTUR: Öffentliche Methode zur Behebung des AttributeError
    def get_expires(self) -> Optional[str]:
        """
        Gibt das während der Verbindung abgerufene Ablaufdatum zurück.
        """
        if not self.expiry_date:
            try:
                self._get_account_info()
            except MacPortalError:
                pass
        return self.expiry_date

    # =========================================================================
    # 3. Content (Categories & Channels)
    # =========================================================================

    def get_categories(self) -> Dict[str, str]:
        """Ruft Kategorien (Genres) ab und cached sie."""
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
            logger.error(f"Fehler beim Abrufen der Genres: {e}")
            return {}

    def get_channels(self) -> List[Dict]:
        """Ruft alle Kanäle ab und normalisiert sie."""
        if not self.play_token:
            self.connect()

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
                "cmd": cmd, 
                "url": cmd, # KORREKTUR: Fügt 'cmd' als 'url' für Anwendungskompatibilität hinzu
            })
            
        self.channels_cache = normalized
        return normalized

    # =========================================================================
    # 4. Stream Generation
    # =========================================================================

    def get_stream_url(self, cmd: str) -> Optional[str]:
        """
        Konvertiert einen Kanal-'cmd' in eine echte URL unter Verwendung von create_link 
        und dekodiert die resultierende URL.
        """
        if not cmd:
            return None

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
            
            # Re-Authentifizierungslogik für abgelaufene Token
            if not link and self.connect(): 
                 logger.info("create_link gab leere Rückgabe. Erneute Authentifizierung war erfolgreich. Versuche es erneut.")
                 data = self._make_request(self.portal_url, method="POST", params=params)
                 link = data.get("js", {}).get("cmd")

            if link:
                 # 1. Bereinige den Link (manchmal ist es "ffmpeg http://url" -> nehme nur die URL)
                 if " " in link:
                     link = link.split()[-1] 
                 
                 # 2. KRITISCHE KORREKTUR: URL-Dekodierung, um die Duplizierung des Hostnamens zu beheben.
                 link = unquote(link) 
                 
                 return link
            
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Links für cmd {cmd}: {e}")
            
        return None
