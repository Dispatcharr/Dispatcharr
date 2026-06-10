# Dispatcharr v0.26.0 - Complete Fix Application Guide

## Übersicht

Dieses Dokument beschreibt, wie du ALLE Fixes und Enhancements auf v0.26.0 anwendest.

## Enthaltene Fixes

### 1. Docker Build Fix ✅
- **Problem**: `ModuleNotFoundError: No module named 'django_db_geventpool'`
- **Lösung**: Single-Stage Build + explizite Package-Installation
- **Dateien**: `docker/DispatcharrBase`, `docker/Dockerfile`, `pyproject.toml`

### 2. Profile Failover Fix ✅
- **Problem**: Failover funktioniert nicht bei einem Stream mit mehreren Profilen
- **Lösung**: 3 kritische Bugs behoben
- **Dateien**: `apps/proxy/live_proxy/url_utils.py`, `apps/proxy/live_proxy/views.py`, `apps/proxy/live_proxy/input/manager.py`

### 3. v0.25.0/v0.25.1 Enhancements ✅
- Logo Timeout Fix
- Basic Authentication
- HTTP Proxy Support (komplett)
- Enhanced Proxy Control (API vs Streaming)
- Extended Timeout Configuration
- Adaptive Health Monitor
- HTTP Proxy Timeout Failover
- HTTP Reader Race Condition Fix

## Anwendungsreihenfolge

Die Patches müssen in dieser Reihenfolge angewendet werden:

```bash
# Schritt 1: v0.25.0 Enhancements (Basis-Features)
patch -p0 < dispatcharr_v0.25.0_enhancements.patch

# Schritt 2: v0.25.1 Enhancements (Enhanced Proxy)
patch -p0 < dispatcharr_v0.25.1_enhancements.patch

# Schritt 3: Docker Build Fix + Profile Failover Fix
patch -p0 < dispatcharr_v0.26.0_COMPLETE_FIX.patch
```

## Alternative: Manuelle Anwendung

Falls die Patches Konflikte haben, kannst du die Änderungen manuell anwenden:

### Schritt 1: Docker Build Fix
Siehe: `DOCKER_BUILD_FIX_v0.26.0_README.md`

### Schritt 2: Profile Failover Fix
Siehe: `PROFILE_FAILOVER_FIX.md`

### Schritt 3: Enhancements
Siehe: Die jeweiligen `.patch` Dateien für Details

## Nach dem Patchen

### 1. Migrationen anwenden
```bash
python manage.py migrate
```

Erwartete Ausgabe:
```
Applying m3u.0020_m3uaccount_proxy... OK
Applying m3u.0021_m3uaccount_proxy_for_api... OK
```

### 2. Frontend bauen
```bash
cd frontend
npm run build
cd ..
python manage.py collectstatic --noinput
```

### 3. Docker Images bauen
```bash
# Base Image
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .

# Final Image
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile .
```

### 4. Starten
```bash
docker-compose -f docker/docker-compose.aio.local.yml up -d
```

## Verifikation

### Docker Build
```bash
docker run --rm sbeimel/dispatcharr:0.26.0 \
  /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ SUCCESS')"
```

### Profile Failover
Schaue in die Logs nach:
```
Found 2 alternate streams with available connections
Skipping current failing stream+profile combination: stream=708953, profile=3402
Found available profile 3403 for stream 708953
```

### HTTP Proxy
Schaue in die Logs nach:
```
Using HTTP proxy http://... for streaming channel ...
Using HTTP proxy http://... for M3U download (proxy_for_api enabled)
```

## Dateien-Übersicht

| Datei | Zweck |
|-------|-------|
| `dispatcharr_v0.25.0_enhancements.patch` | Basis-Features (6 Features) |
| `dispatcharr_v0.25.1_enhancements.patch` | Enhanced Proxy Control |
| `dispatcharr_v0.26.0_COMPLETE_FIX.patch` | Docker + Profile Failover Fix |
| `DOCKER_BUILD_FIX_v0.26.0_README.md` | Docker Fix Anleitung |
| `PROFILE_FAILOVER_FIX.md` | Profile Failover Erklärung |
| `PROFILE_FAILOVER_COMPARISON_v25.0_vs_v26.0.md` | Vergleich der Versionen |
| `BUGFIX_CHECKLIST_PROFILE_FAILOVER.md` | ⭐ Checkliste für Zukunft |

## Wichtige Hinweise

### ⚠️ Reihenfolge ist wichtig!
Die Patches bauen aufeinander auf. Wenn du sie in falscher Reihenfolge anwendest, gibt es Konflikte.

### ⚠️ pyproject.toml
Stelle sicher, dass in `pyproject.toml` steht:
```toml
"django-db-geventpool>=4.0.8",
"drf-spectacular>=0.29.0",
```

### ⚠️ Profile Failover
Nach dem Patch sollte Profile Failover funktionieren wie in v0.25.0.
Teste mit einem Channel, der EINEN Stream mit MEHREREN Profilen hat.

## Support

Bei Problemen:
1. Prüfe `COMPLETE_FIX_v0.26.0_README.md`
2. Prüfe `BUGFIX_CHECKLIST_PROFILE_FAILOVER.md`
3. Schaue in die Logs (Docker: `docker logs dispatcharr`)

## Status

✅ Docker Build funktioniert
✅ django-db-geventpool + drf-spectacular installiert
✅ Profile Failover funktioniert
✅ HTTP Proxy Support komplett
✅ Enhanced Proxy Control (API vs Streaming)
✅ Alle Enhancements aus v0.25.0/v0.25.1 enthalten

---
**Version**: v0.26.0 Complete
**Datum**: 2026-06-10
**Getestet**: ✅ Alle Features verifiziert
