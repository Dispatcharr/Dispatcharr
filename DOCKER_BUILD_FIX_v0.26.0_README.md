# Dispatcharr v0.26.0 - Docker Build Fix

## Problem
```
ModuleNotFoundError: No module named 'django_db_geventpool'
```

Das Django-Backend für PostgreSQL mit gevent-Support konnte nicht geladen werden.

## Root Cause
1. **Multi-Stage Build Problem**: Im DispatcharrBase wurde ein Multi-Stage Build verwendet, wobei beim Kopieren des Python venv von Builder→Final Pakete verloren gingen
2. **Keine Version in pyproject.toml**: `django-db-geventpool` hatte keine Versionsspezifikation
3. **Registry-Prefix**: Dockerfile verwendete `ghcr.io/` statt lokale Images zu verwenden

## Lösung

### 1. Zurück zu Single-Stage Build (wie v25.0)

**Vorher (Multi-Stage - fehlerhaft):**
```dockerfile
FROM ffmpeg AS builder
RUN install packages
COPY --from=builder /venv /venv  # ❌ Pakete gehen verloren
```

**Nachher (Single-Stage - funktioniert):**
```dockerfile
FROM ffmpeg
RUN install packages  # ✓ Alles bleibt erhalten
RUN cleanup system packages
```

### 2. Explizite Installation kritischer Pakete

```dockerfile
# Nach uv sync explizit installieren
RUN uv pip install --python $UV_PROJECT_ENVIRONMENT/bin/python \
    django-db-geventpool>=4.0.8 \
    drf-spectacular>=0.29.0
```

### 3. Dockerfile verwendet lokale Images

```dockerfile
# Vorher:
FROM ghcr.io/${REPO_OWNER}/${REPO_NAME}:${BASE_TAG}

# Nachher:
FROM ${REPO_OWNER}/${REPO_NAME}:${BASE_TAG}
# Docker findet automatisch lokale Images zuerst
```

### 4. Fallback-Installation im Dockerfile

Falls Pakete trotzdem fehlen, werden sie nachinstalliert:

```dockerfile
RUN /dispatcharrpy/bin/python -c "import django_db_geventpool" || \
    uv pip install --python /dispatcharrpy/bin/python django-db-geventpool>=4.0.8
```

## Betroffene Dateien

1. **docker/DispatcharrBase**
   - Von Multi-Stage zu Single-Stage
   - Explizite Installation kritischer Pakete
   - Verifizierung nach Installation
   - Kein ENTRYPOINT (erlaubt direktes Testen)
   - Kein `uv pip uninstall build pip` (vermeidet venv-Beschädigung)

2. **docker/Dockerfile**
   - Verwendet lokale Images ohne Registry-Prefix
   - Verifizierung + Fallback-Installation
   - Finale Verifizierung (Build schlägt fehl bei Fehlern)

3. **pyproject.toml**
   - `django-db-geventpool>=4.0.8` statt `django-db-geventpool`

## Build-Anleitung

### Vollständiger Build

```bash
# 1. Base Image bauen
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .

# 2. Base Image testen
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ SUCCESS')"

# 3. Final Image bauen
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
  --build-arg BASE_TAG=base \
  --build-arg REPO_OWNER=sbeimel \
  --build-arg REPO_NAME=dispatcharr .

# 4. AIO starten
cd docker
docker-compose -f docker-compose.aio.yml up -d
```

### Mit dem bereitgestellten Script

```bash
chmod +x BUILD_AND_TEST_AIO.sh
./BUILD_AND_TEST_AIO.sh
```

## Verifizierung

### Erwartete Build-Ausgaben

**Base Image:**
```
✓ django-db-geventpool
✓ drf-spectacular
✓ gevent
✓ psycopg
```

**Final Image:**
```
✓ django-db-geventpool in final
✓ django-db-geventpool available
✓ drf-spectacular available
```

### Container-Test

```bash
# Django Check sollte erfolgreich sein
docker run --rm -e USE_SQLITE=true sbeimel/dispatcharr:0.26.0 \
  /dispatcharrpy/bin/python manage.py check
```

**Erwartete Ausgabe:**
```
System check identified no issues (0 silenced).
```

**NICHT mehr:**
```
ModuleNotFoundError: No module named 'django_db_geventpool'
```

## Vergleich v25.0 vs v26.0

### Was ist gleich geblieben:
- ✅ Single-Stage Build Ansatz (bewährt)
- ✅ `uv sync` für Paketinstallation
- ✅ Cleanup von System-Paketen am Ende

### Was ist neu in v26.0:
- ✅ psycopg3 statt psycopg2
- ✅ django-db-geventpool für besseres Connection Pooling
- ✅ Explizite Paket-Verifizierung
- ✅ Fallback-Installation im Dockerfile
- ✅ Keine ENTRYPOINT im Base Image (besseres Testing)

## Bekannte Probleme

### HTTP 512 Fehler von Xtream Codes Server

```
HTTPError: 512 Server Error: Server Error for url: http://kralvip007.xyz:8080/...
```

Das ist **KEIN Docker-Problem**, sondern ein Problem mit dem Provider-Server. Der Server antwortet mit HTTP 512 (Custom Server Error). Das ist normal bei überlasteten oder wartenden IPTV-Servern.

## Image-Größe

```
sbeimel/dispatcharr:base     ~1.9 GB
sbeimel/dispatcharr:0.26.0   ~2.1 GB
```

Der Größenunterschied zum Multi-Stage Build (~100MB) ist minimal und das Ergebnis ist stabil und funktioniert.

## Troubleshooting

### Problem: Base Image Test schlägt fehl

```bash
# Prüfe, ob Paket wirklich installiert ist
docker run --rm sbeimel/dispatcharr:base \
  uv pip list --python /dispatcharrpy/bin/python | grep geventpool
```

### Problem: Final Image findet Base Image nicht

```bash
# Prüfe lokale Images
docker images | grep sbeimel/dispatcharr

# Sollte zeigen:
# sbeimel/dispatcharr   base    ...
# sbeimel/dispatcharr   0.26.0  ...
```

### Problem: Paket ist im Base, aber nicht im Final

Das sollte durch die Fallback-Installation behoben werden. Prüfe die Build-Logs:

```
Installing missing django-db-geventpool...
```

Falls das erscheint, funktioniert der Fallback.

## Credits

Basiert auf dem v25.0 Single-Stage Ansatz, der sich als stabil und zuverlässig erwiesen hat.

## Patch anwenden

```bash
# Patch-Datei ist bereits angewendet in den Dateien:
# - docker/DispatcharrBase
# - docker/Dockerfile  
# - pyproject.toml

# Zum manuellen Anwenden (falls nötig):
patch -p0 < dispatcharr_v0.26.0_docker_build_fix.patch
```
