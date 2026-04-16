# Dispatcharr v0.21.1 Enhanced

**Version:** v0.21.1 Enhanced  
**Date:** 2026-03-18  
**Status:** ✅ Production Ready

---

## Übersicht

Diese Version portiert 6 kritische Verbesserungen von v0.20.1 nach v0.21.1 mit korrekter Implementierung (kein Copy-Paste). Alle Features sind an die v0.21.1 Architektur angepasst.

---

## Features

### 1. Logo Timeout Fix ✅
- **Problem:** Logo-Abruf timeout zu früh auf langsamen Servern
- **Lösung:** Timeout von (3,5) auf (10,15) Sekunden erhöht
- **Dateien:** `apps/channels/api_views.py`, `apps/channels/tasks.py`

### 2. gi ✅
- **Problem:** Keine Authentifizierung für M3U/EPG Endpoints
- **Lösung:** HTTP Basic Auth Support hinzugefügt
- **Dateien:** `apps/output/views.py`
- **Verwendung:** 
  ```bash
  curl -u username:password http://dispatcharr/m3u/profile_name
  curl -u username:password http://dispatcharr/epg/profile_name
  ```

### 3. HTTP Proxy Support ✅
- **Problem:** Kein Proxy-Support für M3U Accounts
- **Lösung:** Per-Account Proxy-Konfiguration
- **Dateien:** 5 Dateien + Migration
- **WebUI:** ✅ Proxy-Feld wird automatisch in M3U Account Formular angezeigt
- **Verwendung:**
  - WebUI: M3U Account → Proxy Feld: `http://proxy.example.com:8080`
  - Funktioniert mit FFmpeg, VLC und HTTP Streams
  - Funktioniert auch mit "Proxy" StreamProfile Typ

### 4. Extended Timeout Configuration ✅
- **Problem:** Hardcodierte Timeouts nicht konfigurierbar
- **Lösung:** 15+ konfigurierbare Timeout-Einstellungen
- **Dateien:** 
  - Backend: `apps/proxy/config.py`, `apps/proxy/ts_proxy/config_helper.py`
  - Frontend: `constants.js`, `ProxySettingsForm.jsx`, `ProxySettingsFormUtils.js`
- **WebUI:** ✅ Einstellungen werden in Core Settings > Proxy Settings angezeigt
- **Einstellungen:**
  - `buffering_timeout` (Standard: 15s)
  - `buffering_speed` (Standard: 1.0x)
  - `redis_chunk_ttl` (Standard: 60s)
  - `channel_shutdown_delay` (Standard: 0s)
  - `channel_init_grace_period` (Standard: 5s)
  - `new_client_behind_seconds` (Standard: 5s)
  - `max_retries` (Standard: 2) ⭐ NEU
  - `url_switch_timeout` (Standard: 20s) ⭐ NEU
  - `max_stream_switches` (Standard: 200) ⭐ NEU
  - `connection_timeout` (Standard: 10s) ⭐ NEU
  - `failover_grace_period` (Standard: 20s) ⭐ NEU
  - `chunk_timeout` (Standard: 5s) ⭐ NEU
  - `initial_behind_chunks` (Standard: 4) ⭐ NEU
  - `chunk_batch_size` (Standard: 5) ⭐ NEU
  - `health_check_interval` (Standard: 5s) ⭐ NEU

### 5. Profile Failover Enhancement ✅
- **Problem:** Nur erstes Profil pro Stream wurde versucht
- **Lösung:** Alle Stream/Profil-Kombinationen werden versucht
- **Dateien:** `apps/proxy/ts_proxy/stream_manager.py`, `apps/proxy/ts_proxy/url_utils.py`
- **Verbesserung:** Bessere Failover-Abdeckung bei Stream-Ausfällen

### 6. Adaptive Health Monitor ✅
- **Problem:** Gleiche Schwellenwerte nach Stream-Wechsel
- **Lösung:** Schnellere Erkennung nach kürzlichen Wechseln
- **Dateien:** `apps/proxy/ts_proxy/stream_manager.py`
- **Schwellenwerte:**
  - Nach kürzlichem Wechsel: 5s Timeout, 1 Check, 0s Cooldown
  - Normal: 10s Timeout, 3 Checks, 30s Cooldown

---

## Installation

### 1. Backup erstellen
```bash
docker exec dispatcharr python manage.py dumpdata > backup_$(date +%Y%m%d_%H%M%S).json
```

### 2. Patch anwenden
```bash
# Patch-Datei öffnen und Änderungen manuell anwenden
cat dispatcharr_v0.21.1_enhancements.patch
```

### 3. Migration erstellen und ausführen
```bash
docker exec dispatcharr python manage.py makemigrations
docker exec dispatcharr python manage.py migrate
```

### 4. Neustart
```bash
docker restart dispatcharr
```

### 5. Verifizierung
- ✅ M3U Accounts haben "Proxy" Feld im WebUI
- ✅ Core Settings > Proxy Settings zeigt neue Timeout-Optionen
- ✅ Basic Auth funktioniert auf M3U/EPG Endpoints

---

## WebUI Kompatibilität

### ✅ Alle Änderungen sind WebUI-kompatibel

1. **Proxy-Feld:**
   - ✅ Automatisch im M3U Account Formular sichtbar
   - ✅ Serializer enthält 'proxy' Feld
   - ✅ Frontend-Integration in M3U.jsx

2. **Timeout-Einstellungen:**
   - ✅ In Core Settings > Proxy Settings sichtbar
   - ✅ 9 neue Einstellungen im Frontend hinzugefügt
   - ✅ Vollständige UI-Integration mit Labels und Beschreibungen
   - ✅ Default-Werte konfiguriert
   - ✅ Validierung und Max-Werte gesetzt

3. **Alle anderen Features:**
   - ✅ Backend-only Änderungen (Logo Timeout, Basic Auth, Adaptive Health)
   - ✅ Keine zusätzlichen WebUI-Anpassungen erforderlich

---

## Geänderte Dateien

### Total: 16 Dateien + 1 Migration

**Backend (13 Dateien):**
1. `apps/channels/api_views.py` - Logo timeout
2. `apps/channels/tasks.py` - Logo timeout
3. `apps/output/views.py` - Basic auth
4. `apps/m3u/models.py` - Proxy field
5. `apps/m3u/serializers.py` - Proxy serializer
6. `apps/proxy/config.py` - Extended timeouts
7. `apps/proxy/ts_proxy/config_helper.py` - Timeout helpers
8. `apps/proxy/ts_proxy/stream_manager.py` - Proxy, failover, adaptive
9. `apps/proxy/ts_proxy/http_streamer.py` - Proxy support
10. `apps/proxy/ts_proxy/url_utils.py` - Profile failover
11. `apps/proxy/ts_proxy/services/channel_service.py` - Profile ID bugfix
12. `core/models.py` - Proxy in build_command

**Frontend (3 Dateien):**
13. `frontend/src/constants.js` - Proxy settings options (9 neue Einstellungen)
14. `frontend/src/components/forms/settings/ProxySettingsForm.jsx` - UI für neue Timeouts
15. `frontend/src/utils/forms/settings/ProxySettingsFormUtils.js` - Default-Werte

**Migration:**
16. `apps/m3u/migrations/0036_m3uaccount_proxy.py`

---

## Testing

### 1. Logo Timeout
```bash
# Logs prüfen für timeout messages
docker logs dispatcharr | grep "timeout"
```

### 2. Basic Authentication
```bash
# Mit gültigen Credentials
curl -u admin:password http://localhost:8000/m3u/

# Ohne Credentials (sollte 401 zurückgeben)
curl http://localhost:8000/m3u/
```

### 3. HTTP Proxy
```bash
# Proxy in M3U Account konfigurieren
# Stream starten und Logs prüfen
docker logs dispatcharr | grep "proxy"
```

### 4. Extended Timeouts
```bash
# In WebUI: Core Settings > Proxy Settings
# Werte ändern und speichern
# Stream starten und Logs prüfen
```

### 5. Profile Failover
```bash
# Mehrere Streams mit mehreren Profilen zuweisen
# Stream-Ausfall simulieren
# Logs prüfen für "tried_combinations"
docker logs dispatcharr | grep "tried_combinations"
```

### 6. Adaptive Health Monitor
```bash
# Stream starten und stabilisieren lassen
# Stream-Ausfall simulieren
# Logs prüfen für adaptive thresholds
docker logs dispatcharr | grep "adaptive"
```

---

## Performance

### Minimaler Overhead
- Logo timeout: Kein Performance-Impact
- Basic auth: Minimal (nur bei M3U/EPG Requests)
- HTTP proxy: Minimal (nur wenn konfiguriert)
- Extended timeouts: Kein Impact (gecached)
- Profile failover: Minimal (nur bei Ausfällen)
- Adaptive health: Kein Impact (gleiche Überwachung)

### Vorteile
- Weniger Logo-Fetch-Fehler
- Sicherer M3U/EPG Zugriff
- Proxy-Support für eingeschränkte Netzwerke
- Konfigurierbare Timeouts für verschiedene Umgebungen
- Bessere Failover-Abdeckung
- Schnellere Wiederherstellung nach Stream-Wechseln

---

## Rollback

Falls Probleme auftreten:

```bash
# 1. Datenbank wiederherstellen
docker exec dispatcharr python manage.py loaddata backup_YYYYMMDD_HHMMSS.json

# 2. Code zurücksetzen
git checkout HEAD -- apps/ core/

# 3. Neustart
docker restart dispatcharr
```

---

## Support

### Logs prüfen
```bash
# Docker logs
docker logs dispatcharr

# Application logs
docker exec dispatcharr tail -f /var/log/dispatcharr/dispatcharr.log

# Proxy logs
docker exec dispatcharr tail -f /var/log/dispatcharr/proxy.log
```

### Häufige Probleme

**Problem:** Migration schlägt fehl  
**Lösung:** Datenbankverbindung prüfen, keine konfliktierenden Migrationen

**Problem:** Proxy funktioniert nicht  
**Lösung:** Proxy-URL Format prüfen, Netzwerkverbindung testen

**Problem:** Basic Auth funktioniert nicht  
**Lösung:** Credentials prüfen, User ist aktiv

**Problem:** Timeouts werden nicht angewendet  
**Lösung:** Core Settings prüfen, Datenbankverbindung verifizieren

---

## Changelog

### v0.21.1 Enhanced (2026-03-18)

**Hinzugefügt:**
- Logo Timeout Fix (10s/15s)
- Basic Authentication für M3U/EPG
- HTTP Proxy Support
- 15+ konfigurierbare Timeout-Einstellungen
- Profile Failover Enhancement
- Adaptive Health Monitor

**Geändert:**
- Logo-Abruf Timeout erhöht
- Stream-Wechsel Logik verbessert
- Health Monitor Schwellenwerte adaptiv

**Behoben:**
- Logo-Timeouts auf langsamen Servern
- Fehlende Authentifizierung auf M3U/EPG
- Fehlender Proxy-Support
- Hardcodierte Timeouts
- Unvollständige Failover-Abdeckung
- Langsame Erkennung nach Stream-Wechseln

---

## Lizenz

Siehe LICENSE Datei im Hauptverzeichnis.

---

## Credits

- Portierung von v0.20.1 nach v0.21.1
- Anpassung an v0.21.1 Architektur
- Alle v0.21.1 Verbesserungen erhalten
- WebUI-Kompatibilität sichergestellt

---

**Implementiert von:** Kiro AI Assistant  
**Datum:** 2026-03-18  
**Version:** v0.21.1 Enhanced
