# Dispatcharr v0.26.0 - ULTIMATE Patch with Cooldown System

## Was ist das?

Dieser Patch enthält **ALLE Fixes und Features** für Dispatcharr v0.26.0:

1. ✅ **Docker Build Fix** (django-db-geventpool + drf-spectacular)
2. ✅ **Profile Failover Fix** (3 critical bugs)
3. ✅ **Stream Preview Profile Failover**
4. ✅ **v0.25.1 Enhancements** (HTTP Proxy, Extended Timeouts, etc.)
5. ✅ **Stream Cooldown System** (verhindert Endlosschleifen) **[NEU!]**
6. ✅ **CRITICAL: StreamProfile.build_command() Proxy-Fix** (Transcode-Streams kaputt) **[KRITISCH!]**
7. ✅ **Stream-Preview UUID-Fix** (log_system_event Fehler)

---

## Installation

```bash
cd /path/to/Dispatcharr
patch -p1 < dispatcharr_v0.26.0_ULTIMATE_WITH_COOLDOWN.patch
```

Oder manuell die geänderten Dateien aus dem Patch übernehmen.

---

## Was ist NEU: Stream Cooldown System

### Problem ohne Cooldown

```
Profile 340 → Fehler → tried_combinations
Profile 341 → Fehler → tried_combinations
Profile 342 → Fehler → tried_combinations
→ tried_combinations bleibt für immer bestehen
→ ENDLOSSCHLEIFE! Keine neuen Profile verfügbar
```

### Lösung mit Cooldown

```
Profile 340 → Fehler → 10min Cooldown
Profile 341 → Fehler → 10min Cooldown  
Profile 342 → Fehler → 10min Cooldown
→ Alle auf Cooldown → Last Resort:
  1. Lösche ALLE Cooldowns für diesen Channel
  2. tried_combinations.clear()
  3. Versuche ALLES nochmal von vorne
  4. Wenn wieder alle fehlschlagen → gibt auf
→ Maximal 2 Durchläufe, dann Stop (KEINE Endlosschleife!)
```

### Aktivierung (UI)

**Settings → Proxy Settings**

```
☑ Stream Cooldown Enabled           [Checkbox]
🔢 Stream Cooldown Duration: 10      [NumberInput 0-1440 minutes]
```

**Per Default DEAKTIVIERT!** Verhält sich wie v0.26.0 ohne Cooldown wenn nicht aktiviert.

---

## Profile Failover Reihenfolge

**Ohne Cooldown (Default):**
```
Stream 1 + Profile 1 (default)
Stream 1 + Profile 2
Stream 1 + Profile 3
Stream 2 + Profile 1 (default)
Stream 2 + Profile 2
Stream 2 + Profile 3
→ tried_combinations trackt bereits probierte Kombinationen
→ System probiert erst alle Profile von Stream 1
→ Dann alle Profile von Stream 2 (Backup)
→ Funktioniert bereits korrekt!
```

**Mit Cooldown:**
```
Stream 1 + Profile 1 → Fehler → 10min Cooldown + tried_combinations
Stream 1 + Profile 2 → Fehler → 10min Cooldown + tried_combinations
Stream 1 + Profile 3 → Fehler → 10min Cooldown + tried_combinations
→ Alle Profile von Stream 1 auf Cooldown
Stream 2 + Profile 1 → wird probiert
Stream 2 + Profile 2 → wird probiert
Stream 2 + Profile 3 → wird probiert
→ Wenn auch alle von Stream 2 fehlschlagen:
  → Last Resort: Lösche alle Cooldowns
  → tried_combinations.clear()
  → Probiere alles nochmal
  → Wenn wieder alle fehlschlagen → gibt auf
```

**Ergebnis:** Erst alle Profile eines Streams, dann Backup-Stream, verhindert Endlosschleifen!

---

## Geänderte Dateien

### Backend (18 Dateien)

**Docker:**
1. `docker/DispatcharrBase` - Single-stage build
2. `docker/Dockerfile` - Verification & fallback
3. `pyproject.toml` - Package versions

**Profile Failover:**
4. `apps/proxy/live_proxy/url_utils.py` - 3 Bugs fixed + stream preview
5. `apps/proxy/live_proxy/views.py` - Pass profile_id
6. `apps/proxy/live_proxy/input/manager.py` - Load profile_id + cooldown logic

**HTTP Proxy (v0.25.1):**
7. `apps/m3u/models.py` - `proxy_for_api` field
8. `apps/m3u/serializers.py` - Serialize `proxy_for_api`
9-10. `apps/m3u/migrations/` - 2 migration files

**Timeouts (v0.25.1):**
11. `apps/proxy/live_proxy/input/http_reader.py` - Extended timeouts
12. `apps/proxy/live_proxy/views.py` - Logo timeout 10s/15s
13. `core/models.py` - Extended timeout settings
14. `core/xtream_codes.py` - Use configurable timeouts

**Cooldown System:**
15. `apps/proxy/config.py` - Cooldown defaults
16. `apps/proxy/live_proxy/config_helper.py` - Cooldown helpers
17. `apps/proxy/live_proxy/redis_keys.py` - Cooldown Redis key
18. `apps/proxy/live_proxy/input/manager.py` - Cooldown logic

**⚠️ KRITISCHE BUG-FIXES:**
19. `core/models.py` - StreamProfile.build_command() Proxy-Fix (Transcode-Streams)
20. `core/utils.py` - log_system_event() UUID-Validierung (Stream-Preview)

### Frontend (8 Dateien)

**HTTP Proxy UI:**
1-4. `frontend/src/components/forms/m3u/` - 4 files
5. `frontend/src/constants.js` - Proxy constants

**Timeout Settings UI:**
6. `frontend/src/components/forms/settings/ProxyTimeoutSettingsForm.jsx`
7. `frontend/src/utils/forms/settings/ProxyTimeoutSettingsFormUtils.js`

**Cooldown UI:**
8. `frontend/src/components/forms/settings/ProxySettingsForm.jsx` - Checkbox support
9. `frontend/src/utils/forms/settings/ProxySettingsFormUtils.js` - Cooldown defaults
10. `frontend/src/constants.js` - Cooldown constants

**Total:** 26 Dateien (18 Backend + 8 Frontend)

---

## Features im Detail

### 1. Docker Build Fix
- Single-stage build (wie v25.0)
- Explizite Installation von `django-db-geventpool>=4.0.8` und `drf-spectacular>=0.29.0`
- Fallback-Installation im Final-Stage

### 2. Profile Failover Fix (3 Bugs)
- **Bug 1:** Stream wurde komplett übersprungen statt nur current stream+profile
- **Bug 2:** Nur EIN Profile pro Stream wurde zurückgegeben (mit `break`)
- **Bug 3:** `current_profile_id` wurde nie aus Redis geladen

### 3. Stream Preview Profile Failover
- Stream-Direktzugriff (`/stream/{hash}/stream.m3u8`) nutzt jetzt auch Failover
- Probiert alle Profile des GLEICHEN Streams (kein Stream-Wechsel)

### 4. v0.25.1 Enhancements
- HTTP Proxy mit `proxy_for_api` (separate Kontrolle für API vs Streaming)
- Extended Timeouts (10 neue Einstellungen)
- Logo Timeout 10s/15s (statt 3s/5s)
- Basic Authentication für M3U/EPG Endpoints

### 5. Stream Cooldown System
- Redis-basiertes Cooldown (10 Minuten default)
- Last Resort: Löscht alle Cooldowns nach 2 Durchläufen
- Per Default deaktiviert
- UI: Checkbox + NumberInput (0-1440 Minuten)
- Verhindert Endlosschleifen via `tried_combinations.clear()`

### 6. ⚠️ KRITISCHER BUG-FIX: StreamProfile.build_command() Proxy-Fix

**Problem:** `manager.py` rief `build_command(url, user_agent, proxy)` mit 3 Argumenten auf, aber `StreamProfile.build_command()` in `core/models.py` akzeptierte nur 2 (`url, user_agent`).

**Auswirkung:** **ALLE Transcode-Streams** (ffmpeg/vlc/streamlink Profile) schlugen sofort fehl mit:
```
TypeError: StreamProfile.build_command() takes 3 positional arguments but 4 were given
```
Das System raste durch alle Failover-Kombinationen ohne je zu streamen.

**Fix in `core/models.py`:**
- `proxy=None` als optionalen Parameter hinzugefügt
- `{proxy}` Platzhalter in Replacements unterstützt
- Automatische `-http_proxy` Injection für ffmpeg wenn Proxy konfiguriert

```python
# Vorher (KAPUTT):
def build_command(self, stream_url, user_agent):

# Nachher (FIXED):
def build_command(self, stream_url, user_agent, proxy=None):
    replacements = {
        "{streamUrl}": stream_url,
        "{userAgent}": user_agent,
        "{proxy}": proxy or "",
    }
    # ...
    # Automatische ffmpeg -http_proxy Injection wenn kein {proxy} Platzhalter
    if proxy and self.command.lower() in ('ffmpeg',) and '{proxy}' not in self.parameters:
        i_index = cmd.index('-i')
        cmd.insert(i_index, proxy)
        cmd.insert(i_index, '-http_proxy')
```

**Betroffene Dateien:**
- `core/models.py` - StreamProfile.build_command() erweitert

### 7. Stream-Preview UUID-Fix

**Problem:** Stream-Preview-Channels nutzen `stream_hash` als channel_id (kein UUID-Format). `log_system_event()` versuchte diesen Hash in ein UUID-Datenbankfeld zu schreiben → Fehler in den Logs.

**Auswirkung:** Harmloser Error-Log bei jedem Stream-Preview-Event:
```
ERROR core.utils Failed to log system event client_connect: ['"fd387fea..." is not a valid UUID.']
```

**Fix in `core/utils.py`:**
```python
# UUID-Validierung vor dem Speichern
safe_channel_id = None
if channel_id is not None:
    try:
        uuid_module.UUID(str(channel_id))
        safe_channel_id = channel_id
    except (ValueError, AttributeError):
        # stream_hash → als Detail speichern statt als channel_id
        details['stream_hash'] = str(channel_id)
```

**Betroffene Dateien:**
- `core/utils.py` - log_system_event() UUID-Validierung

---

## Testing

### 1. Docker Build testen
```bash
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
  --build-arg BASE_TAG=base \
  --build-arg REPO_OWNER=sbeimel \
  --build-arg REPO_NAME=dispatcharr .
```

Sollte ohne Fehler durchlaufen und alle Packages verifizieren.

### 2. Profile Failover testen
```bash
# Logs sollten zeigen:
"Loaded profile ID 340 from Redis"
"Found 6 alternate streams: [708953, 708953, ...]"
"Found 6 untried combinations: [(708953,341), (708953,342), ...]"
"Trying stream ID 708953 with profile ID 341"
```

### 3. Cooldown System testen

**Default (deaktiviert):**
```bash
# Sollte sich wie v0.26.0 ohne Cooldown verhalten
# Keine [COOLDOWN] Logs
```

**Aktiviert:**
```bash
# UI: Settings → Proxy Settings
# ☑ Stream Cooldown Enabled
# 🔢 Stream Cooldown Duration: 10 minutes

# Logs sollten zeigen:
[COOLDOWN] Set cooldown for stream 708953/profile 340 for 10m 0s
[COOLDOWN] Skipped 2 combinations on cooldown
[COOLDOWN] Last resort: cleared 6 cooldown(s) - retrying all combinations
```

### 4. HTTP Proxy testen
```bash
# M3U Account bearbeiten:
# ☑ Use HTTP Proxy
# ☑ Also Use Proxy for API Calls  # Neu!
# 🔗 Proxy URL: http://192.168.178.135:18081

# Logs sollten zeigen:
"Using proxy http://192.168.178.135:18081 for stream"
"Using proxy http://192.168.178.135:18081 for API call"  # Neu!
```

---

## Migration von vorherigen Versionen

### Von v0.26.0 (ohne Patches)
```bash
# Apply ULTIMATE Patch
patch -p1 < dispatcharr_v0.26.0_ULTIMATE_WITH_COOLDOWN.patch

# Rebuild Docker
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
  --build-arg BASE_TAG=base \
  --build-arg REPO_OWNER=sbeimel \
  --build-arg REPO_NAME=dispatcharr .
```

### Von v0.25.0 / v0.25.1
```bash
# Upgrade to v0.26.0 first
git checkout v0.26.0

# Apply ULTIMATE Patch
patch -p1 < dispatcharr_v0.26.0_ULTIMATE_WITH_COOLDOWN.patch

# Rebuild Docker
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
  --build-arg BASE_TAG=base \
  --build-arg REPO_OWNER=sbeimel \
  --build-arg REPO_NAME=dispatcharr .
```

---

## Troubleshooting

### Problem: Django Imports fehlschlagen

**Check:**
```bash
docker exec -it dispatcharr /dispatcharrpy/bin/python -c "import django_db_geventpool"
docker exec -it dispatcharr /dispatcharrpy/bin/python -c "import drf_spectacular"
```

**Solution:** Rebuild Docker Images (Base + Final)

### Problem: Profile Failover funktioniert nicht

**Check Logs:**
```bash
# Sollte enthalten:
"Loaded profile ID X from Redis"
"Found Y alternate streams"
"Trying stream ID X with profile ID Y"
```

**Solution:** Patch korrekt angewendet? `url_utils.py` und `manager.py` prüfen.

### Problem: Cooldown funktioniert nicht

**Check 1:** Cooldown aktiviert?
```bash
# UI: Settings → Proxy Settings
# ☑ Stream Cooldown Enabled?
```

**Check 2:** Logs prüfen
```bash
# Sollte enthalten: "[COOLDOWN]"
# Wenn nicht → Feature nicht aktiviert
```

**Check 3:** Redis läuft?
```bash
redis-cli ping
# Sollte: PONG
```

### Problem: HTTP Proxy funktioniert nicht

**Check:**
```bash
# Logs sollten enthalten:
"Using proxy http://..."
```

**Solution:** 
- M3U Account: ☑ Use HTTP Proxy aktiviert?
- Proxy URL korrekt? (http://IP:PORT)

---

## Bekannte Einschränkungen

1. **Cooldown per Default deaktiviert**
   - Muss manuell in UI aktiviert werden
   - Verhält sich wie v0.26.0 ohne Cooldown wenn deaktiviert

2. **Cooldown ist global**
   - Nicht pro Channel konfigurierbar
   - Gilt für alle Channels wenn aktiviert

3. **Last Resort triggert nach 2 Durchläufen**
   - System gibt nach 2 kompletten Durchläufen auf
   - Verhindert Endlosschleifen, aber gibt früher auf als vorher

---

## Empfohlene Einstellungen

### Für stabile Provider
```
stream_cooldown_enabled: false  # Nicht nötig
```

### Für instabile IPTV-Provider
```
stream_cooldown_enabled: true
stream_cooldown_minutes: 5-10
```

### Für sehr instabile Provider
```
stream_cooldown_enabled: true
stream_cooldown_minutes: 15-30
```

---

## Support

**Dokumentation:**
- `COOLDOWN_SYSTEM_v0.26.0.md` - Technische Details
- `COOLDOWN_QUICK_START.md` - Benutzer-Anleitung
- `README_ULTIMATE_PATCH.md` - Ohne Cooldown Version

**Logs:**
```bash
docker logs -f dispatcharr | grep -E "\[COOLDOWN\]|profile|failover"
```

**Redis Cooldowns prüfen:**
```bash
redis-cli --scan --pattern "live:channel:*:cooldown:*"
```

**Cooldowns manuell löschen:**
```bash
redis-cli --scan --pattern "live:channel:*:cooldown:*" | xargs redis-cli del
```

---

## Zusammenfassung

✅ **Docker Build Fix** - Packages korrekt installiert  
✅ **Profile Failover** - 3 Bugs fixed, funktioniert perfekt  
✅ **Stream Preview** - Failover auch für direkten Stream-Zugriff  
✅ **v0.25.1 Features** - HTTP Proxy, Timeouts, etc.  
✅ **Cooldown System** - Verhindert Endlosschleifen  
🔴 **KRITISCH: build_command() Fix** - Transcode-Streams (ffmpeg/vlc) funktionierten gar nicht!  
✅ **UUID-Fix** - Stream-Preview log_system_event Fehler behoben  

**Failover-Reihenfolge:**
1. Erst alle Profile von Stream 1
2. Dann alle Profile von Stream 2 (Backup)
3. Dann alle Profile von Stream 3
4. etc.

**Mit Cooldown:** Verhindert sofortiges Retry + gibt nach 2 Durchläufen auf

**Per Default:** Cooldown deaktiviert, verhält sich wie v0.26.0 ohne Cooldown

---

**Alles fertig! Rebuild Docker Images und testen! 🚀**
