# Build & Test Workflow für v0.26.0

## Schritt 1: Base Image bauen

```bash
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
```

**Erwartete Ausgaben (prüfe diese!):**
```
✓ django-db-geventpool
✓ drf-spectacular
✓ gevent
✓ psycopg
```

## Schritt 2: Base Image DIREKT testen (WICHTIG!)

```bash
# Test 1: Teste django-db-geventpool direkt im Base Image
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ SUCCESS: django-db-geventpool works in base image')"
```

**Erwartetes Ergebnis:**
```
✓ SUCCESS: django-db-geventpool works in base image
```

**Falls FEHLER:**
- Das Problem liegt im Base-Image Build
- `uv sync` installiert das Paket nicht
- Aber die explizite Installation sollte es jetzt fixen

```bash
# Test 2: Liste alle installierten Pakete
docker run --rm sbeimel/dispatcharr:base uv pip list --python /dispatcharrpy/bin/python | grep -i geventpool
```

**Erwartetes Ergebnis:**
```
django-db-geventpool    4.x.x
```

## Schritt 3: Finale Image bauen

```bash
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
  --build-arg BASE_TAG=base \
  --build-arg REPO_OWNER=sbeimel \
  --build-arg REPO_NAME=dispatcharr .
```

**Erwartete Ausgaben (prüfe diese!):**
```
=== Verifying packages in final stage ===
✓ django-db-geventpool in final
=== Final verification ===
✓ django-db-geventpool available
✓ drf-spectacular available
```

**Falls "WARNING: django-db-geventpool NOT found":**
- Die Fallback-Installation wird ausgeführt
- Dann sollte die finale Verifizierung erfolgreich sein

## Schritt 4: Finales Image testen

```bash
# Test: Kann Django starten?
docker run --rm \
  -e USE_SQLITE=true \
  -e DISPATCHARR_LOG_LEVEL=DEBUG \
  sbeimel/dispatcharr:0.26.0 \
  /dispatcharrpy/bin/python manage.py check
```

**Erwartetes Ergebnis:**
```
System check identified no issues (0 silenced).
```

**NICHT mehr:**
```
ModuleNotFoundError: No module named 'django_db_geventpool'
```

## Schritt 5: Vollständiger Container-Test

```bash
# Teste mit docker-compose
cd docker
docker-compose -f docker-compose.aio.yml up -d

# Prüfe Logs
docker-compose -f docker-compose.aio.yml logs -f dispatcharr
```

**Erwartete Ausgabe:**
- Keine ModuleNotFoundError
- Django startet erfolgreich
- Datenbank-Verbindung funktioniert

## Debugging bei Fehlern

### Problem: Base Image Build schlägt fehl bei Verifizierung

```bash
# Prüfe, was uv sync installiert hat
docker run --rm sbeimel/dispatcharr:base bash -c "
  uv pip list --python /dispatcharrpy/bin/python | grep -E 'django|gevent|psycopg'
"
```

### Problem: Paket ist im Base Image, aber nicht im Final Image

Das bedeutet, dass beim `FROM docker.io/sbeimel/dispatcharr:base` etwas schiefgeht.

```bash
# Prüfe, ob das richtige Base Image verwendet wird
docker inspect sbeimel/dispatcharr:0.26.0 | grep -A 5 "Parent"
```

### Problem: Dockerfile findet das Base Image nicht

Stelle sicher, dass das Base Image den richtigen Tag hat:

```bash
docker images | grep sbeimel/dispatcharr
```

Sollte zeigen:
```
sbeimel/dispatcharr   base     <image-id>   X minutes ago   X.XXgB
sbeimel/dispatcharr   0.26.0   <image-id>   X minutes ago   X.XXgB
```

## Alternative: Verwende lokales Registry-Prefix

Falls `docker.io/sbeimel/...` nicht funktioniert, ändere das Dockerfile:

```dockerfile
# Statt:
FROM docker.io/${REPO_OWNER}/${REPO_NAME}:${BASE_TAG}

# Verwende:
FROM ${REPO_OWNER}/${REPO_NAME}:${BASE_TAG}
```

Dann baue so:

```bash
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
  --build-arg BASE_TAG=base \
  --build-arg REPO_OWNER=sbeimel \
  --build-arg REPO_NAME=dispatcharr .
```

## Schnelltest

Ein komplettes Script zum Testen:

```bash
#!/bin/bash
set -e

echo "=== Building Base Image ==="
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .

echo ""
echo "=== Testing Base Image ==="
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "
import django_db_geventpool
import drf_spectacular
import gevent
import psycopg
print('✓ All packages available in base image')
"

echo ""
echo "=== Building Final Image ==="
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
  --build-arg BASE_TAG=base \
  --build-arg REPO_OWNER=sbeimel \
  --build-arg REPO_NAME=dispatcharr .

echo ""
echo "=== Testing Final Image ==="
docker run --rm -e USE_SQLITE=true sbeimel/dispatcharr:0.26.0 \
  /dispatcharrpy/bin/python manage.py check

echo ""
echo "✓✓✓ ALL TESTS PASSED! ✓✓✓"
```

Speichere das als `test-build.sh` und führe aus:

```bash
chmod +x test-build.sh
./test-build.sh
```
