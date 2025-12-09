import logging
import json
import hashlib
import time
import random
import string
from urllib.parse import urlparse, quote, unquote
from typing import Optional, Dict, List, Any

import requests
from requests.adapters import HTTPAdapter, Retry

# Importiere JSONDecodeError explizit für die verbesserte Fehlerbehandlung
from json.decoder import JSONDecodeError

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
        # Stellen Sie sicher, dass SSL-Prüfung deaktiviert ist, wie im Original
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
        """
        Sendet eine Anfrage und implementiert eine verbesserte Fehlerbehandlung,
        insbesondere für JSONDecodeError und HTTP-Fehler.
        """
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
                    data=data,
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

            r.raise_for_status() # Löst HTTPError für 4xx/5xx Statuscodes aus

            # 🛠️ NEUE LOGIK: Verbessertes JSON-Dekodieren
            try:
                return r.json()
            except JSONDecodeError as e:
                # Wenn das Dekodieren fehlschlägt, ist die Antwort kein JSON.
                # Wir geben den rohen Text weiter, um zu sehen, was stattdessen gesendet wurde.
                raw_text = r.text[:250].strip()
                error_message = f"JSONDecodeError: {e}. Raw response snippet: '{raw_text}'"
                raise MacPortalError(error_message)

        except MacPortalError:
             # Werfe MacPortalError, wenn er von der JSONDecodeError-Behandlung stammt
             raise
        except Exception as e:
            # Fängt alle anderen Fehler (ConnectionError, HTTPError von raise_for_status, Timeouts)
            error_msg = str(e)
            
            # Bei HTTP-Fehlern den Rohtext hinzufügen, falls vorhanden
            if hasattr(e, 'response') and e.response is not None:
                try:
                    raw_text = e.response.text[:250].strip()
                    if raw_text:
                        error_msg += f". Raw response snippet: '{raw_text}'"
                except:
                    pass # falls .text fehlschlägt

            raise MacPortalError(error_msg)

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
                # Verwende einen einfachen GET, um die URL zu überprüfen, ohne _request
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
        
        # Prüfen auf generische Fehler
        if js.get("status") == "ERROR" or js.get("error"):
            msg = js.get("message", "Authorization failed during profile retrieval.")
            raise MacPortalError(f"Authorization failed: {msg}")


    def _get_account_info(self):
        """
        Get account info, including expiry date, using the simple and standard Stalker POST method.
        Wirft MacPortalError, wenn das Konto blockiert/abgelaufen ist, und bettet das Datum in die Fehlermeldung ein.
        """
        self.expiry_date = None
        try:
            # 1. Standard POST request for account info (wie in Version 4)
            data = self._request(self.portal_url, "POST", {
                "type": "stb",
                "action": "get_account_info",  # Standard Stalker action
                "mac": self.mac,
            }, auth=True)
            
            js_data = data.get("js", {})

            # 2. Fehlerprüfung: Wenn der Portal-Status 'ERROR' ist, werfen wir einen Fehler
            if js_data.get("status") == "ERROR" or js_data.get("error"):
                msg = js_data.get("message", "Authorization failed during account info retrieval.")
                raise MacPortalError(f"Authorization/Account Info Error: {msg}")

            # 3. Ablaufdatum aus dem Standardfeld 'expire' abrufen
            expiry = js_data.get("expire")
            self.expiry_date = expiry 

            # 4. Prüfen auf explizite Statuscodes (0 ist oft "blocked" oder "expired")
            status = js_data.get("status")
            if status in ["0", 0] or js_data.get("access_status") in ["0", 0]:
                 error_msg = f"Authorization failed: Account expired or blocked (Status: {status})."
                 if expiry:
                     # Wichtig: Datum im Fehlertext platzieren, damit die Task-Datei es speichert.
                     error_msg += f" [Expiry Date: {expiry}]"
                 raise MacPortalError(error_msg)
            
            # 5. Protokollierung bei Erfolg
            if self.expiry_date:
                logger.info("Account Info: Ablaufdatum=%s", self.expiry_date)
            else:
                logger.warning("Account-Informationen abgerufen, aber Ablaufdatum fehlt (MAC:%s).", self.mac)
                
        except MacPortalError:
             # Werfe den spezifischen Fehler, der oben erstellt wurde
             raise
        except Exception:
            logger.exception("Unerwarteter Fehler beim Abrufen des Ablaufdatums (MAC:%s).", self.mac)
            self.expiry_date = None


    def get_expires(self) -> Optional[str]:
        """
        Gibt das während der Profilabfrage gespeicherte Ablaufdatum zurück.
        Wird von der Anwendung (tasks.py) erwartet.
        """
        # connect() ruft bereits _get_account_info() auf. Wir geben nur das Ergebnis zurück.
        return self.expiry_date

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
            # Re-Authentifizierungslogik
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
