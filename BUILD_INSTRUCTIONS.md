# Dispatcharr Docker Build Anleitung

## Problem
Das Docker Image hatte Probleme mit fehlenden Python-Paketen, insbesondere:
- `django-db-geventpool` - Wurde nicht korrekt installiert
- `drf-spectacular` - Könnte ebenfalls fehlen

## Lösung
Die folgenden Änderungen wurden vorgenommen:

### 1. pyproject.toml
- Version für `django-db-geventpool` spezifiziert: `>=4.0.8`
- Stellt sicher, dass die neueste kompatible Version installiert wird

### 2. docker/DispatcharrBase
- **HAUPTÄNDERUNG**: Gewechselt von `uv sync` zu `uv pip compile` + `uv pip install`
  - **Grund**: Es existiert keine `uv.lock` Datei im Projekt, daher schlägt `uv sync --frozen` fehl
  - **Lösung**: `uv pip compile` erstellt requirements.txt aus pyproject.toml, dann Installation daraus
- Verbesserte Installationsschritte:
  1. Virtuelles Environment explizit mit `uv venv` erstellen
  2. Requirements aus pyproject.toml kompilieren
  3. Pakete aus den kompilierten Requirements installieren
- Verifizierung der kritischen Pakete im Builder-Stage
- **ZUSÄTZLICHER FALLBACK**: Im Final-Stage werden fehlende Pakete automatisch nachinstalliert
  - Falls beim Kopieren des venv Pakete verloren gehen
  - Explizite Nachinstallation von `django-db-geventpool` und `drf-spectacular`
- Final-Stage Verifizierung stellt sicher, dass alle Pakete im fertigen Image verfügbar sind

### 3. docker/debug_packages.sh (neu)
- Debug-Script zum Überprüfen der installierten Pakete im Container
- Hilfreich für Troubleshooting bei Paketproblemen

## Build-Befehle

### Vollständiger Build (beide Images)
```bash
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase . && docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile --build-arg BASE_TAG=base --build-arg REPO_OWNER=sbeimel --build-arg REPO_NAME=dispatcharr .
```

### Nur Base Image
```bash
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
```

### Nur Final Image (setzt voraus, dass Base existiert)
```bash
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile --build-arg BASE_TAG=base --build-arg REPO_OWNER=sbeimel --build-arg REPO_NAME=dispatcharr .
```

## Verifizierung

Nach dem erfolgreichen Build können Sie verifizieren, dass alle Pakete installiert sind:

```bash
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import django_db_geventpool; import drf_spectacular; import gevent; import psycopg; print('✓ All critical packages installed')"
```

## Troubleshooting

### ModuleNotFoundError: No module named 'django_db_geventpool'
- **Ursache:** Das Paket wurde nicht korrekt installiert
- **Lösung:** Die aktualisierten Dateien stellen sicher, dass die Installation korrekt durchgeführt wird

### Build schlägt beim uv sync fehl
- **Ursache:** Netzwerkprobleme oder Abhängigkeitskonflikte
- **Lösung:** Der Fallback-Mechanismus im Dockerfile sollte dies abfangen

### Andere fehlende Module
- **Ursache:** Nicht alle Abhängigkeiten aus pyproject.toml wurden installiert
- **Lösung:** Die Verifizierungsschritte im Dockerfile zeigen fehlende Pakete sofort an

## Änderungsprotokoll

### v0.26.0 Fixes - Update 2
- ✅ `django-db-geventpool>=4.0.8` zu pyproject.toml hinzugefügt
- ✅ **Gewechselt von `uv sync` zu `uv pip compile` + `uv pip install`** (Hauptfix)
- ✅ Verifizierung der Installation kritischer Pakete im Builder-Stage
- ✅ Fallback-Installation im Final-Stage für fehlende Pakete
- ✅ Detaillierte Fehlerausgabe und Debugging-Informationen
- ✅ Debug-Script für Container-Diagnose hinzugefügt
