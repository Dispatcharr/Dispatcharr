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
- Verbesserte Abhängigkeitsinstallation mit `uv sync`
- Hinzugefügt: Verifizierung der kritischen Pakete nach der Installation
- Fallback-Mechanismus falls `--frozen` fehlschlägt

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

### v0.26.0 Fixes
- ✅ `django-db-geventpool>=4.0.8` zu pyproject.toml hinzugefügt
- ✅ Verifizierung der Installation kritischer Pakete
- ✅ Fallback-Mechanismus für uv sync
- ✅ Detaillierte Fehlerausgabe bei fehlenden Modulen
