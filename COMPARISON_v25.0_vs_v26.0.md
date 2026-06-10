# Vergleich: Dispatcharr v25.0 vs v26.0 - Dependency Management

## Entscheidende Unterschiede

### 1. Datenbank-Backend & Dependencies

#### v25.0 (funktioniert):
```toml
# pyproject.toml
dependencies = [
    "psycopg2-binary==2.9.12",  # ← Verwendet psycopg2
    "psycogreen",                # ← Für gevent-Patching
    # ... keine django-db-geventpool
]
```

```python
# settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",  # ← Standard Django Backend
        # ...
    }
}
```

#### v26.0 (Problem):
```toml
# pyproject.toml
dependencies = [
    "psycopg[binary]",           # ← Gewechselt zu psycopg3
    "gevent==26.4.0",
    "django-db-geventpool>=4.0.8",  # ← Neues Package
    # ... kein psycogreen mehr
]
```

```python
# settings.py
DATABASES = {
    "default": {
        "ENGINE": "django_db_geventpool.backends.postgresql_psycopg3",  # ← Custom Backend
        "OPTIONS": {
            "MAX_CONNS": 8,
            "REUSE_CONNS": 3,
            "pool": False,  # Disable Django's native pool
        },
    }
}
```

### 2. Docker Build-Methode

#### v25.0 (einfach, funktioniert):
```dockerfile
# DispatcharrBase - SINGLE STAGE
FROM lscr.io/linuxserver/ffmpeg:latest

# Install all dependencies directly
RUN apt-get update && apt-get install -y \
    python3.13 python3.13-dev \
    build-essential gcc g++ \
    libpq-dev libpcre3-dev \
    nginx comskip vlc-bin redis postgresql

# Install Python packages with uv sync
COPY pyproject.toml version.py README.md /tmp/build/
RUN uv sync --python 3.13 --no-cache --no-install-project --no-dev && \
    rm -rf /tmp/build

# Build NumPy wheel
RUN uv pip install build pip && \
    # ... build numpy ... \
    uv pip uninstall build pip

# Clean up build deps
RUN apt-get remove -y build-essential gcc g++ python3.13-dev && \
    apt-get autoremove -y --purge
```

**Vorteile:**
- ✅ Ein einziges Stage - keine Komplexität beim Kopieren
- ✅ `uv sync` funktioniert zuverlässig (auch ohne uv.lock)
- ✅ Alle Pakete bleiben im gleichen Environment
- ✅ Einfaches Cleanup am Ende

#### v26.0 (komplex, Problem):
```dockerfile
# DispatcharrBase - MULTI STAGE
FROM lscr.io/linuxserver/ffmpeg:latest AS builder

# Build stage
RUN apt-get install -y build-essential python3.13-dev
COPY pyproject.toml /tmp/build/
RUN uv sync --python 3.13 --no-cache --no-install-project --no-dev
RUN # ... build numpy ...
RUN uv pip uninstall build pip  # ← Könnte venv beschädigen!

# Final stage
FROM lscr.io/linuxserver/ffmpeg:latest AS final
RUN apt-get install -y python3.13 libpython3.13  # Nur Runtime
COPY --from=builder /dispatcharrpy /dispatcharrpy  # ← Kopieren kann fehlschlagen!
```

**Probleme:**
- ❌ Multi-Stage erhöht Komplexität
- ❌ Kopieren des venv kann Pakete verlieren
- ❌ `uv pip uninstall build pip` könnte Dependencies beschädigen
- ❌ Unterschiedliche System-Libs zwischen Builder und Final
- ❌ Schwerer zu debuggen

### 3. Warum der Wechsel zu psycopg3?

**Motivation (wahrscheinlich):**
- psycopg3 ist die moderne Version (2021+)
- Native async/await Support
- Bessere Performance
- Django 4.2+ unterstützt psycopg3 nativ

**Aber:**
- Benötigt `django-db-geventpool` für gevent-Kompatibilität
- Komplexere Installation
- Zusätzliche Abhängigkeit

### 4. Die Probleme in v26.0

#### Problem 1: Multi-Stage Build
```dockerfile
# Builder Stage
RUN uv sync  # ✅ Installiert Pakete
RUN uv pip uninstall build pip  # ⚠️ Könnte django-db-geventpool entfernen?

# Final Stage  
COPY --from=builder /dispatcharrpy /dispatcharrpy  # ❌ Pakete fehlen!
```

**Warum fehlen Pakete?**
1. `uv pip uninstall` könnte shared dependencies entfernen
2. Beim Kopieren gehen möglicherweise symlinks verloren
3. `/tmp/build` wird gelöscht, könnte Lock-Infos enthalten
4. Unterschiedliche Python-Versionen/Libs zwischen Stages

#### Problem 2: Keine uv.lock Datei
```bash
$ ls -la | grep uv.lock
# Keine Datei!

# Daher:
RUN uv sync --frozen  # ❌ Schlägt fehl
RUN uv sync           # ⚠️ Nicht-deterministisch
```

### 5. Lösungsansätze

#### Option A: Zurück zu v25.0 Ansatz (Empfohlen)
```toml
# pyproject.toml - Zurück zu psycopg2
dependencies = [
    "psycopg2-binary==2.9.12",
    "psycogreen",
    # kein django-db-geventpool
]
```

```python
# settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
    }
}
```

```dockerfile
# DispatcharrBase - Single Stage wie v25.0
FROM lscr.io/linuxserver/ffmpeg:latest
RUN apt-get install python3.13 build-essential
RUN uv sync --python 3.13 --no-cache --no-install-project --no-dev
RUN apt-get remove build-essential && apt-get autoremove
```

**Vorteile:**
- ✅ Bewährt und funktioniert
- ✅ Einfacher Build-Prozess
- ✅ Weniger Dependencies
- ✅ Leichter zu debuggen

#### Option B: v26.0 fixieren (Aktueller Ansatz)
```dockerfile
# Multi-Stage beibehalten, aber robuster
FROM ... AS builder
RUN uv venv --python 3.13 $UV_PROJECT_ENVIRONMENT
RUN uv pip compile pyproject.toml -o requirements.txt
RUN uv pip install -r requirements.txt
# KEIN uv pip uninstall!

FROM ... AS final
COPY --from=builder /dispatcharrpy /dispatcharrpy
# Fallback installation
RUN uv pip install django-db-geventpool>=4.0.8 || true
RUN python -c "import django_db_geventpool"  # Verify
```

**Probleme:**
- ⚠️ Immer noch komplex
- ⚠️ Fallback-Installation ist ein Workaround
- ⚠️ Schwerer zu warten

#### Option C: Single-Stage mit psycopg3 (Best of Both)
```dockerfile
# DispatcharrBase - Single Stage wie v25.0, aber mit psycopg3
FROM lscr.io/linuxserver/ffmpeg:latest

RUN apt-get install python3.13 build-essential libpq-dev
COPY pyproject.toml version.py README.md /tmp/build/
RUN uv sync --python 3.13 --no-cache --no-install-project --no-dev

# Verify critical packages
RUN python -c "import django_db_geventpool; import psycopg"

# Build NumPy (ohne build/pip zu deinstallieren danach!)
RUN cd /tmp && \
    python -m pip download --no-binary numpy --no-deps numpy && \
    tar -xzf numpy-*.tar.gz && \
    cd numpy-*/ && \
    python -m pip wheel . -Csetup-args=-Dcpu-baseline="none" && \
    mv *.whl /opt/ && \
    cd / && rm -rf /tmp/numpy-*

# Clean up (aber nicht uv pip uninstall!)
RUN apt-get remove -y build-essential && apt-get autoremove -y
```

**Vorteile:**
- ✅ Moderne psycopg3
- ✅ Einfacher Single-Stage Build
- ✅ Keine Kopier-Probleme
- ✅ Leichter zu debuggen

## Empfehlung

### Kurzfristig (für v26.0):
Verwende **Option B** (aktueller Fix) - funktioniert, aber nicht ideal.

### Mittelfristig (für v26.1):
Wechsel zu **Option C** (Single-Stage mit psycopg3):
1. Entferne Multi-Stage Build
2. Behalte psycopg3 und django-db-geventpool
3. Deinstalliere NICHT build/pip nach der Installation
4. Cleanup nur System-Pakete, nicht Python-Pakete

### Langfristig:
1. **Erstelle uv.lock**: `uv lock && git add uv.lock`
2. Verwende `uv sync --frozen` für deterministische Builds
3. Dokumentiere Dependencies besser

## Warum v25.0 besser funktionierte

1. **Single-Stage Build**: Keine Komplikationen beim Kopieren
2. **Einfachere Dependencies**: psycopg2 + psycogreen statt psycopg3 + django-db-geventpool
3. **Kein uv pip uninstall**: Venv blieb intakt
4. **Deterministisch**: `uv sync` funktionierte zuverlässig auch ohne Lock-Datei

## Fazit

Der Wechsel von v25.0 zu v26.0 brachte:
- ✅ Modernere psycopg3
- ✅ Besseren Connection Pooling (django-db-geventpool)
- ❌ Aber: Komplexeren Build-Prozess
- ❌ Und: Installation-Probleme durch Multi-Stage

Der aktuelle Fix (Option B) funktioniert, ist aber ein Workaround. 
Für v26.1 sollte auf Single-Stage Build (Option C) gewechselt werden.
