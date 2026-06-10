# Docker Build Fix - Zusammenfassung

## Das Problem
```
ModuleNotFoundError: No module named 'django_db_geventpool'
```

Das Django-basierte Dispatcharr konnte nicht starten, weil das `django-db-geventpool` Paket im Docker Image fehlte.

## Root Cause Analysis

1. **Fehlende uv.lock Datei**: Das Projekt verwendet `uv` als Package Manager, aber es existiert keine `uv.lock` Datei
2. **Falscher uv Befehl**: `uv sync --frozen` erfordert eine Lock-Datei und schlägt ohne diese fehl
3. **Fallback funktionierte nicht**: Der Fallback zu `uv sync` (ohne --frozen) installierte die Pakete nicht zuverlässig
4. **Keine Versionspinning**: `django-db-geventpool` hatte keine Version in pyproject.toml angegeben

## Die Lösung

### Geänderte Dateien:

#### 1. `pyproject.toml`
```diff
- "django-db-geventpool",
+ "django-db-geventpool>=4.0.8",
```
**Warum**: Explizite Versionsspezifikation stellt sicher, dass eine kompatible Version installiert wird.

#### 2. `docker/DispatcharrBase` (Builder Stage)
```diff
- RUN uv sync --python 3.13 --no-cache --no-install-project --no-dev --frozen || \
-     uv sync --python 3.13 --no-cache --no-install-project --no-dev
+ RUN uv venv --python 3.13 $UV_PROJECT_ENVIRONMENT
+ RUN uv pip compile /tmp/build/pyproject.toml -o /tmp/requirements.txt --python-version 3.13 && \
+     uv pip install --python $UV_PROJECT_ENVIRONMENT/bin/python -r /tmp/requirements.txt
```
**Warum**: 
- `uv venv` erstellt explizit das virtuelle Environment
- `uv pip compile` generiert requirements.txt aus pyproject.toml (benötigt keine Lock-Datei)
- `uv pip install -r` installiert aus dem generierten requirements.txt
- Dieser Ansatz ist robuster und funktioniert ohne uv.lock

#### 3. `docker/DispatcharrBase` (Final Stage)
```diff
+ # Ensure django-db-geventpool and other critical packages are present
+ RUN cd /tmp && \
+     /dispatcharrpy/bin/python -c "import django_db_geventpool" 2>/dev/null || \
+     uv pip install --python /dispatcharrpy/bin/python django-db-geventpool>=4.0.8 && \
+     /dispatcharrpy/bin/python -c "import drf_spectacular" 2>/dev/null || \
+     uv pip install --python /dispatcharrpy/bin/python drf-spectacular>=0.29.0
+ 
+ # Final verification
+ RUN /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ django-db-geventpool available')"
```
**Warum**: 
- Fallback-Mechanismus falls Pakete beim Kopieren des venv verloren gehen
- Finale Verifizierung stellt sicher, dass der Build fehlschlägt, wenn Pakete fehlen
- Früher Fehler ist besser als Laufzeit-Fehler

## Build-Prozess

### Vorher:
```
1. Builder: uv sync --frozen  ❌ (schlägt fehl, keine uv.lock)
2. Builder: uv sync (Fallback) ⚠️ (installiert unzuverlässig)
3. Copy venv to final         ❌ (unvollständiges venv)
4. Runtime error              💥 (Module not found)
```

### Nachher:
```
1. Builder: uv venv            ✅ (explizit venv erstellen)
2. Builder: uv pip compile     ✅ (requirements.txt aus pyproject.toml)
3. Builder: uv pip install     ✅ (zuverlässige Installation)
4. Builder: Verify imports     ✅ (frühe Fehlerkennung)
5. Copy venv to final          ✅ (vollständiges venv)
6. Final: Fallback install     ✅ (Sicherheitsnetz)
7. Final: Verify imports       ✅ (finale Validierung)
8. Runtime                     ✅ (alle Module verfügbar)
```

## Wie man das Image baut

```bash
# Vollständiger Build
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase . && \
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
  --build-arg BASE_TAG=base \
  --build-arg REPO_OWNER=sbeimel \
  --build-arg REPO_NAME=dispatcharr .
```

## Verifizierung

Nach dem Build können Sie verifizieren:

```bash
# Test im Base Image
docker run --rm sbeimel/dispatcharr:base \
  /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ OK')"

# Test im Final Image
docker run --rm sbeimel/dispatcharr:0.26.0 \
  /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ OK')"

# Vollständige Package-Liste
docker run --rm sbeimel/dispatcharr:base \
  /dispatcharrpy/bin/python -c "import pkg_resources; [print(d) for d in pkg_resources.working_set]"
```

## Debug-Tools

Ein Debug-Script wurde erstellt: `docker/debug_packages.sh`

```bash
# Im laufenden Container
docker exec <container-id> bash /app/docker/debug_packages.sh

# Beim Start
docker run --rm sbeimel/dispatcharr:base bash /app/docker/debug_packages.sh
```

## Zusätzliche Hinweise

### Warum nicht einfach requirements.txt verwenden?
Das Projekt verwendet `pyproject.toml` als Single Source of Truth für Dependencies. Eine separate requirements.txt würde:
- Duplizierung erzeugen
- Sync-Probleme verursachen
- PEP 621 Best Practices ignorieren

### Warum uv statt pip?
- `uv` ist deutlich schneller als pip
- Besseres Dependency Resolution
- Vom Projekt bereits verwendet

### Zukunftssichere Lösung
Für langfristige Stabilität sollte das Projekt eine `uv.lock` Datei committen:
```bash
uv lock
git add uv.lock
git commit -m "Add uv.lock for reproducible builds"
```

Dann kann im Dockerfile wieder `uv sync --frozen` verwendet werden.
