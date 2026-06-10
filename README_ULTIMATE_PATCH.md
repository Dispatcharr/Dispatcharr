# Dispatcharr v0.26.0 ULTIMATE PATCH

## 🎯 Was ist das?

**EINE einzige Patch-Datei mit ALLEN Fixes und Enhancements für v0.26.0!**

Datei: `dispatcharr_v0.26.0_ULTIMATE.patch` (~56 KB)

## 📦 Enthält

### 1. Docker Build Fix ✅
- Problem: `ModuleNotFoundError: No module named 'django_db_geventpool'`
- Lösung: Single-Stage Build + explizite Package-Installation
- Dateien: `docker/DispatcharrBase`, `docker/Dockerfile`, `pyproject.toml`

### 2. Profile Failover Fix ✅  
- Problem: Failover funktioniert nicht bei einem Stream mit mehreren Profilen
- Lösung: 3 kritische Bugs behoben
- Dateien: `apps/proxy/live_proxy/url_utils.py`, `views.py`, `manager.py`

### 3. v0.25.1 Enhancements ✅
- Enhanced HTTP Proxy Control (Separate API vs Streaming)
- Logo Timeout Fix (10s/15s statt 3s/5s)
- Basic Authentication für M3U/EPG
- HTTP Proxy Support (komplett)
- Extended Timeout Configuration
- Profile Failover Enhancement
- Adaptive Health Monitor
- HTTP Proxy Timeout Failover
- HTTP Reader Race Condition Fix

## 🚀 Installation

### Schritt 1: Patch anwenden
```bash
cd /path/to/Dispatcharr

# Mit patch:
patch -p0 < dispatcharr_v0.26.0_ULTIMATE.patch

# ODER mit git apply:
git apply dispatcharr_v0.26.0_ULTIMATE.patch
```

### Schritt 2: Migrationen
```bash
python manage.py migrate
```

Erwartete Ausgabe:
```
Applying m3u.0020_m3uaccount_proxy... OK
Applying m3u.0021_m3uaccount_proxy_for_api... OK
```

### Schritt 3: Frontend bauen
```bash
cd frontend
npm run build
cd ..
python manage.py collectstatic --noinput
```

### Schritt 4: Docker Images bauen
```bash
# Base Image
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .

# Final Image
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile .
```

### Schritt 5: Starten
```bash
docker-compose -f docker/docker-compose.aio.local.yml up -d
```

## ✅ Verifikation

### Docker Build Check
```bash
docker run --rm sbeimel/dispatcharr:0.26.0 \
  /dispatcharrpy/bin/python -c "import django_db_geventpool; import drf_spectacular; print('✓ SUCCESS')"
```

**Erwartete Ausgabe**: `✓ SUCCESS`

### Profile Failover Check
Schaue in die Logs:
```log
✅ Found 2 alternate streams with available connections
✅ Skipping current failing stream+profile combination: stream=708953, profile=3402
✅ Found available profile 3403 for stream 708953
```

### HTTP Proxy Check
Schaue in die Logs:
```log
✅ Using HTTP proxy http://... for streaming channel ...
✅ Using HTTP proxy http://... for M3U download (proxy_for_api enabled)
```

## 📊 Was wurde geändert?

### Dateien (24 total)
- **Docker**: 3 Dateien
- **Backend**: 14 Python-Dateien
- **Frontend**: 5 JavaScript-Dateien  
- **Migrations**: 2 neue Migrations

### Zeilen-Änderungen
- **Hinzugefügt**: ~1100 Zeilen
- **Geändert**: ~280 Zeilen
- **Gelöscht**: ~150 Zeilen

## 🎁 Features im Detail

| Feature | Status | Dateien |
|---------|--------|---------|
| Docker Build Fix | ✅ | 3 |
| Profile Failover Fix | ✅ | 3 |
| Logo Timeout Fix | ✅ | 1 |
| Basic Authentication | ✅ | 1 |
| HTTP Proxy Support | ✅ | 8 |
| Enhanced Proxy Control | ✅ | 7 |
| Extended Timeouts | ✅ | 5 |
| Adaptive Health Monitor | ✅ | 1 |
| HTTP Timeout Failover | ✅ | 1 |
| Race Condition Fix | ✅ | 1 |

## 🔍 Wichtige Hinweise

### ⚠️ pyproject.toml
Nach dem Patch sollte stehen:
```toml
"django-db-geventpool>=4.0.8",
"drf-spectacular>=0.29.0",
```

### ⚠️ Proxy-Verhalten
- **proxy_for_api=False** (Default): Proxy NUR für Streaming
- **proxy_for_api=True**: Proxy für API + Streaming

### ⚠️ Profile Failover
Funktioniert jetzt wie in v0.25.0:
- Ein Stream mit 3 Profilen = 3 Failover-Optionen
- Profil 1 fails → versucht Profil 2
- Profil 2 fails → versucht Profil 3
- Profil 3 fails → gibt auf

## 📚 Zusätzliche Dokumentation

In diesem Ordner:
- `COMPLETE_FIX_v0.26.0_README.md` - Detaillierte Anleitung
- `PROFILE_FAILOVER_FIX.md` - Profile Failover Erklärung
- `PROFILE_FAILOVER_COMPARISON_v25.0_vs_v26.0.md` - Vergleich
- `BUGFIX_CHECKLIST_PROFILE_FAILOVER.md` - ⭐ Checkliste für Zukunft
- `FILES_MODIFIED_SUMMARY_v0.26.0.md` - Alle geänderten Dateien

## 🆘 Bei Problemen

1. Prüfe Build-Logs auf Verifikations-Meldungen
2. Prüfe Runtime-Logs auf Failover-Meldungen
3. Schaue in `COMPLETE_FIX_v0.26.0_README.md`
4. Nutze `BUGFIX_CHECKLIST_PROFILE_FAILOVER.md`

## 🎉 Zusammenfassung

**MIT DIESEM EINEN PATCH BEKOMMST DU:**
✅ Funktionierendes Docker Build  
✅ Profile Failover wie in v0.25.0  
✅ Enhanced HTTP Proxy Control  
✅ Alle v0.25.1 Enhancements  
✅ 11 Major Features  
✅ 6 Critical Bugfixes  

---

**Version**: v0.26.0 ULTIMATE
**Datum**: 2026-06-10  
**Größe**: ~56 KB  
**Status**: ✅ Production Ready

**Eine Datei. Alle Fixes. Fertig.** 🚀
