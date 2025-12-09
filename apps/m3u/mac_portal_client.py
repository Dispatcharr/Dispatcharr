import logging
import json
import hashlib
import time
from urllib.parse import urlparse, quote, unquote
from typing import Optional, Dict, List, Any, Tuple

import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)


class MacPortalError(Exception):
    """Benutzerdefinierter Fehler für MAC Portal Probleme."""

    pass


class MacPortalClient:
    """
    Erweiterter Client für Stalker-/STB-Portale mit MAC-Login.
    Implementiert die vollständige MAG250/254 Emulation und
    die robustere Logik für API-Aufrufe und Stream-Links.
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

        self.portal_url: Optional[str] = None
        self.token: Optional[str] = None
        self.expires_at: Optional[str] = None
        # Cache
        self.genres_by_id: Dict[str, str] = {}
        self.raw_channels: List[Dict] = []

    def _detect_portal_url(self) -> Optional[str]:
        """Versucht, die finale Portal-URL aufzulösen."""
        self.portal_url = self.original_base_url.rstrip('/') + "/stalker_portal/server/load.php"
        return self.portal_url
    
    # ----------------------------------------------------
    # API-HELFER (ZENTRALE ANFRAGEFUNKTION)
    # ----------------------------------------------------

    def _make_request(self, url: str, method: str = "GET", params: Dict[str, Any] = None, headers: Dict[str, str] = None) -> Dict[str, Any]:
        """Generische Funktion zum Ausführen von HTTP-Anfragen mit Token-Handling."""
        
        final_headers = {
            "User-Agent": "Mozilla/5.0 (QtEmbedded; RTV-R3; Linux; ) AppleWebKit/534.34 (KHTML, like Gecko) Qt/4.8.4 Safari/534.34",
            "Accept": "*/*",
            "X-User-Agent": "Mozilla/5.0 (QtEmbedded; RTV-R3; Linux; ) AppleWebKit/534.34 (KHTML, like Gecko) Qt/4.8.4 Safari/534.34",
        }
        
        if self.token:
             # Fügen Sie das Authorization Header nur hinzu, wenn ein Token vorhanden ist
            final_headers["Authorization"] = f"Bearer {self.token}" 

        if headers:
            final_headers.update(headers)
        
        # Basisdaten für die POST-Anfrage
        data = {"mac": self.mac, "hd": "1"}
        if params:
            data.update(params)

        try:
            if method.upper() == "POST":
                response = self.session.post(
                    url,
                    data=data,
                    headers=final_headers,
                    verify=True,
                    timeout=10,
                    proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None
                )
            else:
                response = self.session.get(
                    url,
                    params=data,
                    headers=final_headers,
                    verify=True,
                    timeout=10,
                    proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None
                )
            
            response.raise_for_status()

            if response.text.startswith('<html>'):
                 raise MacPortalError("Antwort ist HTML, erwartet JSON. Mögliche Fehlkonfiguration oder Blockierung.")

            return response.json()
            
        except requests.exceptions.HTTPError as e:
            # Spezifisches Handling für Token-Ablauf (401/403)
            if e.response.status_code in (401, 403):
                 # Token ist möglicherweise abgelaufen. Wir löschen es, um ein Re-Login zu erzwingen.
                self.token = None 
                logger.warning("401/403-Fehler bei API-Aufruf. Token wurde gelöscht.")
                raise MacPortalError(f"Nicht autorisiert (Token abgelaufen?): {e.response.status_code}")
                
            logger.error("HTTP-Fehler bei Anfrage an %s: %s", url, e)
            raise MacPortalError(f"Portal-Antwortfehler: {e}")
        except requests.RequestException as e:
            logger.error("Netzwerkfehler: %s", e)
            raise MacPortalError(f"Netzwerkfehler: {e}")
        except json.JSONDecodeError:
            logger.error("Ungültige JSON-Antwort erhalten: %s", response.text[:200])
            raise MacPortalError("Ungültige JSON-Antwort vom Portal.")

    # ----------------------------------------------------
    # STB-EMULATION / LOGIN (HANDSHAKE)
    # ----------------------------------------------------
    
    # (Der Code für _generate_stb_params bleibt hier unverändert)
    def _generate_stb_params(self, timestamp: int) -> Dict[str, Any]:
        """Generiert detaillierte STB-Parameter und den metrics-Payload."""
        mac_clean = self.mac.replace(":", "").lower()
        mac_bytes = mac_clean.encode('utf-8')

        sn = hashlib.md5(mac_bytes).hexdigest().upper()[:13]
        device_id = hashlib.sha256(mac_bytes).hexdigest().upper()
        device_id2 = hashlib.sha256(mac_bytes).hexdigest().upper() 

        metrics = {
            "stb_type": "MAG250",
            "image_version": "218",
            "version": "0.2.18",
            "language": "en",
            "resolution": "1280x720",
            "screensaver_delay": 1,
            "parental_disabled": 0,
            "profile": "hd",
        }

        metrics_json = json.dumps(metrics, separators=(',', ':'))
        encoded_metrics = quote(metrics_json) 

        host_params = {
            'type': 'stb',
            'action': 'handshake',
            'hd': '1',
            "sn": sn, 
            'stb_type': "MAG250",
            'client_type': 'STB',
            'image_version': '218',
            'hw_version': '1.7-BD-00',
            "metrics": encoded_metrics, 
            "device_id": device_id,
            "device_id2": device_id2,
            'timestamp': str(timestamp),
        }
        
        return host_params


    def connect(self) -> Optional[str]:
        """
        Führt den STB-Login (Handshake) durch und speichert das Token.
        """
        if not self._detect_portal_url():
            raise MacPortalError("Portal-URL konnte nicht aufgelöst werden.")

        timestamp = int(time.time())
        stb_params = self._generate_stb_params(timestamp)
        
        action_name = stb_params.pop('action')
        type_name = stb_params.pop('type')
        
        url = f"{self.portal_url}?type={type_name}&action={action_name}"

        try:
            logger.info("Führe STB-Handshake durch mit MAC: %s", self.mac)
            
            # WICHTIG: Handshake verwendet KEIN Authorization Header, 
            # daher verwenden wir hier direkt session.post statt _make_request.
            response = self.session.post(
                url,
                data=stb_params,
                headers={
                    "User-Agent": "Mozilla/5.0 (QtEmbedded; RTV-R3; Linux; ) AppleWebKit/534.34 (KHTML, like Gecko) Qt/4.8.4 Safari/534.34", 
                    "Accept": "*/*",
                },
                verify=True,
                timeout=10,
                proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None
            )
            response.raise_for_status()

            response_data = response.json()
            js_data = response_data.get('js', {})
            
            play_token = js_data.get('token')
            
            if play_token:
                self.token = play_token
                self.expires_at = js_data.get('expiration_date')
                logger.info("Handshake erfolgreich. Token erhalten.")
                return self.token
            else:
                if response.status_code in (401, 403) or response_data.get('status') == 'ERROR':
                    error_msg = response_data.get('error', f"Fehlercode: {response.status_code}")
                    raise MacPortalError(f"Handshake fehlgeschlagen: MAC nicht autorisiert ({error_msg})")
                    
                raise MacPortalError("Handshake fehlgeschlagen: Kein Token in der Antwort erhalten.")

        except requests.RequestException as e:
            logger.error("Netzwerkfehler beim Handshake: %s", e)
            raise MacPortalError(f"Netzwerkfehler beim Handshake: {e}")

    # ----------------------------------------------------
    # KANAL-OPERATIONEN (ITV-Actions)
    # ----------------------------------------------------

    def get_genres_map(self) -> Dict[str, str]:
        """
        Ruft eine Zuordnung von Genre-ID zu Genre-Titel ab (itv&action=get_genres).
        """
        if self.genres_by_id:
            return self.genres_by_id
        
        logger.info("Rufe Kanalgruppen ab (get_genres)")
        
        # Sicherstellen, dass ein Token vorhanden ist, bevor die API aufgerufen wird
        if not self.token:
            self.connect()

        try:
            # action=get_genres
            data = self._make_request(self.portal_url, method="POST", params={"type": "itv", "action": "get_genres"})
            
            genres_list = data.get('js', [])
            
            # Map the list to a dictionary {id: title}
            self.genres_by_id = {str(g.get('id')): g.get('title') for g in genres_list if g.get('id') and g.get('title')}
            
            # Die Gruppe "Allgemein" (oft ID 1) ist wichtig für die Navigation
            if "1" not in self.genres_by_id:
                 self.genres_by_id["1"] = "Alle Kanäle"
            
            return self.genres_by_id
        except MacPortalError as e:
            logger.error("Fehler beim Abrufen der Genres: %s", e)
            # Im Fehlerfall wird ein leeres Dictionary zurückgegeben, die Navigation muss das behandeln.
            return {}


    def get_all_channels_raw(self) -> List[Dict]:
        """
        Ruft die rohe Kanalliste vom Portal ab (itv&action=get_all_channels).
        """
        if self.raw_channels:
            return self.raw_channels

        logger.info("Rufe alle Kanäle ab (get_all_channels)")
        
        if not self.token:
            self.connect()

        # Parameter, um so viele Kanäle wie möglich auf einmal zu erhalten
        params = {
            "type": "itv", 
            "action": "get_all_channels", 
            "hd": "1", 
            "p": 1, # Seite 1
            "num_items": 9999, # Hohe Zahl für vollständige Liste
        }

        try:
            data = self._make_request(self.portal_url, method="POST", params=params)
            # Die Kanalliste ist oft in data['js']['data']
            self.raw_channels = data.get('js', {}).get('data', [])
            
            if not self.raw_channels:
                 logger.warning("get_all_channels hat keine Daten zurückgegeben.")
            
            return self.raw_channels
        except MacPortalError as e:
            logger.error("Fehler beim Abrufen der Kanalliste: %s", e)
            return []


    def get_channels(self) -> List[Dict]:
        """
        Gibt eine normalisierte Kanalliste zurück, indem die Rohdaten verarbeitet werden.
        """
        # Stelle sicher, dass Genres und Kanäle vorhanden sind, indem die get-Methoden aufgerufen werden
        self.get_genres_map() 
        raw_list = self.get_all_channels_raw()
        
        normalized = []
        for ch in raw_list:
            ch_id = ch.get("id")
            name = ch.get("name") or f"Channel {ch_id}"

            group_title = self._detect_group_title(ch)

            cmd = ch.get("cmd") or ""
            # Wir verwenden hier NICHT _extract_stream_url, da die URL nur der "cmd"-String ist.
            # Die eigentliche abspielbare URL muss über create_link geholt werden.
            
            # Füge den Kanal zur Liste hinzu. Das Feld 'url' ist in dieser Liste
            # nicht die finale Stream-URL, sondern der 'cmd'-String zur Identifikation.
            normalized.append(
                {
                    "id": ch_id,
                    "name": name,
                    "group": group_title,
                    "cmd": cmd, # Behalte den cmd-String für get_stream_url
                    "raw": ch,
                }
            )
        logger.info("Normalized %s MAC channels into groups", len(normalized))
        return normalized

    
    def _detect_group_title(self, ch: Dict[str, Any]) -> str:
        """
        Normalisierungslogik: Sucht nach tv_genre_id, genre_id oder cat_id.
        """
        genre_id = (
            ch.get("tv_genre_id")
            or ch.get("genre_id")
            or ch.get("cat_id")
        )
        if genre_id is not None:
            genres = self.genres_by_id # Verwende den zwischengespeicherten Cache
            label = genres.get(str(genre_id))
            if label:
                return label
            return f"Group {genre_id}"

        return "MAC"
        
        
    def get_stream_url(self, cmd: str) -> Optional[str]:
        """
        Ruft die abspielbare Stream-URL für einen Kanal über action=create_link ab.
        """
        if not cmd:
            return None

        # Sicherstellen, dass ein Token vorhanden ist, bevor die API aufgerufen wird
        if not self.token:
            self.connect()

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
            # Führt nur einen erneuten Versuch durch, wenn der erste Versuch fehlschlug
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
            logger.error(f"Fehler beim Erstellen des Stream-Links für cmd '{cmd[:30]}...': {e}")
            
        return None
