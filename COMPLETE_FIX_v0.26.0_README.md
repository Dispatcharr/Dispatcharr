# Dispatcharr v0.26.0 Complete Fix - README

## Übersicht

Dieser Patch behebt **zwei kritische Probleme** in Dispatcharr v0.26.0:

1. **Docker Build Problem**: `ModuleNotFoundError: No module named 'django_db_geventpool'`
2. **Profile Failover Problem**: Failover funktioniert nicht bei einem Stream mit mehreren Profilen

## Problem 1: Docker Build

### Symptom
```
ModuleNotFoundError: No module named 'django_db_geventpool'
```

### Ursache
Multi-Stage Docker Build verliert Python-Pakete beim Kopieren vom Builder zur Final Stage.

### Lösung
- Zurück zu Single-Stage Build (wie v0.25.0)
- Explizite Installation und Verifikation von `django-db-geventpool>=4.0.8`
- Fallback-Installation in Final Stage
- Lokale Images ohne Registry-Prefix

## Problem 2: Profile Failover

### Symptom
```log
2026-06-10 09:08:29,053 INFO live_proxy.manager Trying to find alternative stream for channel 66600e30-..., current stream ID: 708953, current profile ID: 3402
2026-06-10 09:08:29,053 WARNING live_proxy.url_utils No alternate streams with available connections found
2026-06-10 09:08:29,053 INFO live_proxy.manager Found 0 potential alternate stream+profile combinations
```

### Beispiel-Szenario
- Channel: **ZDF**
- Stream: **"ZDF Raw"** von Provider "XC Club"
- Profile: **3402, 3403, 3404** (3 Profile beim selben Provider)
- **Problem**: Wenn Profil 3402 fehlschlägt, gibt es auf statt 3403 zu versuchen

### Ursache (3 Bugs)

#### Bug 1: `get_alternate_streams()` überspringt ganzen Stream
```python
# FALSCH (v0.26.0 vor Fix):
if current_stream_id and stream.id == current_stream_id:
    continue  # ← Überspringt den GANZEN Stream!
```

#### Bug 2: Nur EIN Profil pro Stream wird zurückgegeben
```python
# FALSCH (v0.26.0 vor Fix):
selected_profile = None
for profile in profiles:
    if available:
        selected_profile = profile
        break  # ← Stoppt nach erstem Profil!
```

#### Bug 3: `current_profile_id` wird nie aus Redis geladen
```python
# FALSCH (v0.26.0 vor Fix):
if stream_id:
    self.tried_stream_ids.add(stream_id)
    # ← current_profile_id bleibt None!
```

### Lösung
Alle 3 Dateien wurden korrigiert:

1. **`apps/proxy/live_proxy/url_utils.py`**:
   - Überspringt nur die aktuelle Stream+Profil-Kombination (nicht den ganzen Stream)
   - Gibt ALLE verfügbaren Profile für jeden Stream zurück
   
2. **`apps/proxy/live_proxy/views.py`**:
   - Übergibt `m3u_profile_id` an `get_alternate_streams()`
   
3. **`apps/proxy/live_proxy/input/manager.py`**:
   - Lädt `current_profile_id` aus Redis
   - Übergibt `current_profile_id` an `get_alternate_streams()`

## Betroffene Dateien

### Docker Build Fix
- `docker/DispatcharrBase` - Single-Stage Build, explizite Package-Installation
- `docker/Dockerfile` - Lokale Image-Referenzen, Fallback-Installation
- `pyproject.toml` - Version-Pin für `django-db-geventpool>=4.0.8`

### Profile Failover Fix
- `apps/proxy/live_proxy/url_utils.py` - Logik-Fix in `get_alternate_streams()`
- `apps/proxy/live_proxy/views.py` - Parameter `m3u_profile_id` hinzugefügt
- `apps/proxy/live_proxy/input/manager.py` - Redis-Loading von `current_profile_id`

## Installation

### Variante 1: Patch anwenden (empfohlen)
```bash
cd /path/to/Dispatcharr
patch -p1 < dispatcharr_v0.26.0_COMPLETE_FIX.patch
```

### Variante 2: Manuell kopieren
Kopiere die Änderungen aus dem Patch manuell in die entsprechenden Dateien.

### Variante 3: Git apply
```bash
git apply dispatcharr_v0.26.0_COMPLETE_FIX.patch
```

## Build-Anleitung

### 1. Base Image bauen
```bash
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
```

**Wichtig**: Achte auf die Ausgabe:
```
=== Verifying critical packages ===
✓ django-db-geventpool
✓ drf-spectacular
✓ gevent
✓ psycopg
```

### 2. Final Image bauen
```bash
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile .
```

**Wichtig**: Achte auf die Ausgabe:
```
=== Verifying packages in final stage ===
✓ django-db-geventpool in final
=== Final verification ===
✓ django-db-geventpool available
✓ drf-spectacular available
```

### 3. Starten (AIO mit docker-compose)
```bash
docker-compose -f docker/docker-compose.aio.local.yml up -d
```

## Verifikation

### Docker Build
```bash
# Test ob django-db-geventpool verfügbar ist
docker run --rm sbeimel/dispatcharr:0.26.0 \
  /dispatcharrpy/bin/python -c "import django_db_geventpool; print('SUCCESS')"
```

**Erwartete Ausgabe**: `SUCCESS`

### Profile Failover
Schaue in die Logs nach einem Stream-Fehler:

**Vorher (v0.26.0 kaputt)**:
```log
WARNING live_proxy.url_utils No alternate streams with available connections found
INFO live_proxy.manager Found 0 potential alternate stream+profile combinations
```

**Nachher (v0.26.0 mit Fix)**:
```log
DEBUG live_proxy.url_utils Skipping current failing stream+profile combination: stream=708953, profile=3402
DEBUG live_proxy.url_utils Found available profile 3403 for stream 708953
DEBUG live_proxy.url_utils Found available profile 3404 for stream 708953
INFO live_proxy.url_utils Found 2 alternate streams with available connections
INFO live_proxy.manager Found 2 potential alternate stream+profile combinations
```

## Vergleich mit v0.25.0

| Feature | v0.25.0 | v0.26.0 (original) | v0.26.0 (mit Fix) |
|---------|---------|--------------------|--------------------|
| Docker Build | ✅ Funktioniert | ❌ Kaputt | ✅ Funktioniert |
| Profile Failover (Channel) | ✅ Funktioniert | ❌ Kaputt | ✅ Funktioniert |
| Profile Failover (Stream Preview) | ❌ Fehlt | ❌ Fehlt | ❌ Fehlt |
| Multi-Stream Failover | ✅ Funktioniert | ❌ Kaputt | ✅ Funktioniert |

## Bekannte Einschränkungen

### Stream Preview hat KEIN Profile Failover
Wenn du direkt einen Stream über Hash aufrufst:
```
http://dispatcharr/stream/{stream_hash}/stream.m3u8
```

Dann funktioniert Profile Failover **nicht**. Dies ist auch in v0.25.0 der Fall.

**Grund**: In `get_alternate_streams()`:
```python
if isinstance(channel, Stream):
    logger.error(f"Stream is not a channel")
    return []  # ← Keine Alternativ-Profile bei Stream Preview
```

**Workaround**: Verwende Channel-URLs statt Stream-Preview-URLs:
```
http://dispatcharr/live/{channel_uuid}/stream.m3u8
```

## Zusätzliche Dokumentation

- `PROFILE_FAILOVER_FIX.md` - Detaillierte Erklärung des Profile-Failover-Problems
- `PROFILE_FAILOVER_COMPARISON_v25.0_vs_v26.0.md` - Vergleich v0.25.0 vs v0.26.0
- `DOCKER_BUILD_FIX_v0.26.0_README.md` - Detaillierte Erklärung des Docker-Problems

## Zusammenfassung

✅ **Docker Build funktioniert wieder**  
✅ **Profile Failover funktioniert wie in v0.25.0**  
✅ **Multi-Stream Failover funktioniert**  
✅ **HTTP Proxy wird korrekt verwendet**  
✅ **Alle Provider-Fehler (HTTP 512, 509, Timeouts) sind normal und werden behandelt**

## Support

Bei Problemen:
1. Prüfe die Build-Logs auf Verifikations-Meldungen
2. Prüfe die Runtime-Logs auf Profile-Failover-Meldungen
3. Vergleiche mit den erwarteten Outputs oben

---

**Version**: v0.26.0 Complete Fix  
**Datum**: 2026-06-10  
**Status**: ✅ Getestet und funktioniert
