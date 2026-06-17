# psycopg3 Module Error Fix

## Problem

```
ModuleNotFoundError: No module named 'psycopg'
File "/app/dispatcharr/db/backends/postgresql_psycopg3/base.py", line 2, in <module>
    import psycopg
```

## Root Cause

Das Custom Database Backend `dispatcharr/db/backends/postgresql_psycopg3/base.py` versucht `psycopg` (psycopg3) zu importieren, aber das Modul ist zur Runtime nicht verfügbar.

## Mögliche Ursachen

1. **Package nicht installiert**: `psycopg[binary]` fehlt in pyproject.toml oder wurde nicht installiert
2. **Falsches Python Environment**: Die App läuft in einem anderen Python als das Virtual Environment
3. **Import-Path Problem**: psycopg ist installiert aber nicht im sys.path
4. **Build-Stage Copy Issue**: Package wurde in builder stage installiert aber nicht in final stage kopiert

## Diagnose

### Schritt 1: Prüfe pyproject.toml

```bash
cat pyproject.toml | grep psycopg
```

**Erwartet:**
```toml
"psycopg[binary]",
```

**Status:** ✅ Vorhanden in Zeile 10

### Schritt 2: Prüfe ob psycopg im Container vorhanden ist

```bash
docker exec <container> /dispatcharrpy/bin/python -c "import psycopg; print(psycopg.__version__)"
```

### Schritt 3: Prüfe sys.path

```bash
docker exec <container> /dispatcharrpy/bin/python -c "import sys; print('\n'.join(sys.path))"
```

## Lösung 1: Stelle sicher dass psycopg installiert ist

### DispatcharrBase - Zeile 48 erweitern

```dockerfile
# Verify critical packages are installed
RUN echo "=== Verifying critical packages ===" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import django_db_geventpool; print('✓ django-db-geventpool')" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import drf_spectacular; print('✓ drf-spectacular')" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import gevent; print('✓ gevent')" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import psycopg; print('✓ psycopg'); print('Version:', psycopg.__version__)" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import psycopg.pq; print('✓ psycopg.pq (binary)')"
```

### Dockerfile - Fallback Installation hinzufügen (nach Zeile 46)

```dockerfile
# Fallback: Install psycopg if missing
RUN /dispatcharrpy/bin/python -c "import psycopg" 2>/dev/null || \
    (echo "Installing missing psycopg[binary]..." && \
    uv pip install --python /dispatcharrpy/bin/python 'psycopg[binary]>=3.1.0')

# Verify psycopg with detailed output
RUN /dispatcharrpy/bin/python -c "import psycopg; print('✓ psycopg version:', psycopg.__version__); import psycopg.pq; print('✓ psycopg binary driver available')"
```

## Lösung 2: Stelle sicher dass das richtige Python verwendet wird

### entrypoint.sh prüfen

Stelle sicher dass die App mit `/dispatcharrpy/bin/python` gestartet wird, nicht mit system python.

```bash
# In entrypoint.sh sollte stehen:
exec /dispatcharrpy/bin/python manage.py runserver 0.0.0.0:8000
```

## Lösung 3: Alternative - Verwende django.db.backends.postgresql

Falls psycopg3 Custom Backend Probleme macht, kann man auf den Standard PostgreSQL Backend umstellen.

### dispatcharr/settings.py anpassen

```python
# Statt:
DATABASES = {
    'default': {
        'ENGINE': 'dispatcharr.db.backends.postgresql_psycopg3',
        # ...
    }
}

# Verwende:
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        # oder mit geventpool:
        # 'ENGINE': 'django_db_geventpool.backends.postgresql_psycopg3',
        # ...
    }
}
```

**Hinweis:** Wenn geventpool verwendet werden soll, muss `django_db_geventpool` den richtigen Backend bereitstellen.

## Lösung 4: Explizite Installation in pyproject.toml

Stelle sicher dass psycopg EXPLIZIT mit Version angegeben ist:

```toml
dependencies = [
    # ...
    "psycopg[binary]>=3.1.0,<4.0",
    # ...
]
```

## Vollständige Fix-Implementierung

### 1. pyproject.toml aktualisieren

```toml
dependencies = [
    "Django==6.0.5",
    "psycopg[binary]>=3.1.18",  # Explicit version
    "psycopg2-binary>=2.9.9",    # Fallback für legacy code
    # ... rest
]
```

### 2. DispatcharrBase erweitern

```dockerfile
# EXPLICIT installation of critical packages
RUN echo "=== Ensuring critical packages with correct versions ===" && \
    uv pip install --python $UV_PROJECT_ENVIRONMENT/bin/python \
    'psycopg[binary]>=3.1.18' \
    django-db-geventpool>=4.0.8 \
    drf-spectacular>=0.29.0

# Verify critical packages with detailed output
RUN echo "=== Verifying critical packages ===" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import django_db_geventpool; print('✓ django-db-geventpool')" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import drf_spectacular; print('✓ drf-spectacular')" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import gevent; print('✓ gevent')" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import psycopg; print('✓ psycopg version:', psycopg.__version__)" && \
    $UV_PROJECT_ENVIRONMENT/bin/python -c "import psycopg.pq; print('✓ psycopg.pq binary driver')" && \
    echo "=== All packages verified successfully ==="
```

### 3. Dockerfile final stage erweitern

```dockerfile
# Fallback: Install psycopg if missing (critical for database connection)
RUN /dispatcharrpy/bin/python -c "import psycopg; import psycopg.pq" 2>/dev/null || \
    (echo "⚠️  psycopg missing! Installing..." && \
    uv pip install --python /dispatcharrpy/bin/python 'psycopg[binary]>=3.1.18')

# Existing fallbacks...
RUN /dispatcharrpy/bin/python -c "import django_db_geventpool" 2>/dev/null || \
    (echo "Installing missing django-db-geventpool..." && \
    uv pip install --python /dispatcharrpy/bin/python django-db-geventpool>=4.0.8)

# Final verification - fail build if packages are still missing
RUN echo "=== Final verification ===" && \
    /dispatcharrpy/bin/python -c "import psycopg; print('✓ psycopg version:', psycopg.__version__)" && \
    /dispatcharrpy/bin/python -c "import psycopg.pq; print('✓ psycopg binary driver')" && \
    /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ django-db-geventpool available')" && \
    /dispatcharrpy/bin/python -c "import drf_spectacular; print('✓ drf-spectacular available')"
```

## Testing

### Nach Docker Build:

```bash
# Test 1: Psycopg import
docker exec dispatcharr /dispatcharrpy/bin/python -c "import psycopg; print('✓ psycopg', psycopg.__version__)"

# Test 2: Binary driver
docker exec dispatcharr /dispatcharrpy/bin/python -c "import psycopg.pq; print('✓ Binary driver OK')"

# Test 3: Database backend
docker exec dispatcharr /dispatcharrpy/bin/python -c "from dispatcharr.db.backends.postgresql_psycopg3.base import DatabaseWrapper; print('✓ Custom backend OK')"

# Test 4: Django setup
docker exec dispatcharr /dispatcharrpy/bin/python manage.py check --database default
```

## Empfohlene Reihenfolge

1. **Aktualisiere pyproject.toml** mit expliziter psycopg Version
2. **Aktualisiere DispatcharrBase** mit verbesserter Verification
3. **Aktualisiere Dockerfile** mit psycopg fallback
4. **Rebuild Base Image**: `docker build -t dispatcharr:base -f docker/DispatcharrBase .`
5. **Rebuild Final Image**: `docker build -t dispatcharr:latest .`
6. **Test**: Führe alle Tests oben aus

## Alternativen wenn nichts hilft

### Option A: Verwende django_db_geventpool Backend

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django_db_geventpool.backends.postgresql_psycopg3',
        # ...
    }
}
```

### Option B: Verwende Standard PostgreSQL Backend ohne Custom Wrapper

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        # ...
    }
}
```

**Hinweis:** Dann gehen geventpool Features verloren!

## Zusammenfassung

Das Problem ist dass `psycopg` zur Runtime nicht verfügbar ist, obwohl es in `pyproject.toml` steht. Die Lösung ist:

1. Explizite Version in pyproject.toml
2. Explizite Installation in DispatcharrBase
3. Fallback Installation in Dockerfile final stage
4. Detaillierte Verification mit Binary Driver Check
5. Rebuild Docker Images

Nach diesen Fixes sollte der Fehler behoben sein! 🚀
