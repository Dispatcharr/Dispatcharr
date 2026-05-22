# Fix: django_redis ModuleNotFoundError

**Fehler:** `ModuleNotFoundError: No module named 'django_redis'`

**Ursache:** Das `django-redis` Paket ist nicht installiert, obwohl es in `pyproject.toml` definiert ist.

**Status:** ⚠️ DEPENDENCY PROBLEM (nicht mit v0.25.0 Enhancements verbunden)

---

## 🔧 Lösung

### Option 1: Docker Container neu bauen (EMPFOHLEN)

```bash
# 1. Docker Image neu bauen
docker build -t dispatcharr:latest .

# 2. Container stoppen und entfernen
docker stop dispatcharr
docker rm dispatcharr

# 3. Container neu starten
docker run -d --name dispatcharr dispatcharr:latest
```

### Option 2: Dependencies manuell installieren

```bash
# Im Container
docker exec -it dispatcharr bash

# Dependencies installieren
pip install django-redis

# Container neustarten
exit
docker restart dispatcharr
```

### Option 3: uv verwenden (wenn verfügbar)

```bash
# Im Container
docker exec -it dispatcharr bash

# Mit uv installieren
uv pip install django-redis

# Container neustarten
exit
docker restart dispatcharr
```

### Option 4: Alle Dependencies neu installieren

```bash
# Im Container
docker exec -it dispatcharr bash

# Alle Dependencies aus pyproject.toml installieren
pip install -e .

# ODER mit uv
uv pip install -e .

# Container neustarten
exit
docker restart dispatcharr
```

---

## ✅ Verifikation

Nach der Installation prüfen:

```bash
# 1. Prüfe ob django-redis installiert ist
docker exec dispatcharr pip show django-redis

# Erwartete Ausgabe:
# Name: django-redis
# Version: X.X.X
# ...

# 2. Prüfe ob Django startet
docker exec dispatcharr python manage.py check

# Erwartete Ausgabe:
# System check identified no issues (0 silenced).

# 3. Prüfe Migration
docker exec dispatcharr python manage.py showmigrations m3u

# Sollte 0020_m3uaccount_proxy zeigen
```

---

## 📋 Checkliste

- [ ] Docker Image neu gebaut
- [ ] Container neu gestartet
- [ ] `django-redis` installiert
- [ ] `python manage.py check` erfolgreich
- [ ] Migration 0020 sichtbar
- [ ] Keine Fehler in Logs

---

## 🐛 Wenn Problem weiterhin besteht

### Prüfe pyproject.toml

```bash
# Prüfe ob django-redis in Dependencies ist
cat pyproject.toml | grep django-redis

# Sollte zeigen:
# "django-redis",
```

### Prüfe Python Version

```bash
# Im Container
docker exec dispatcharr python --version

# Sollte sein: Python 3.13.x
```

### Prüfe pip/uv Installation

```bash
# Im Container
docker exec dispatcharr which pip
docker exec dispatcharr which uv

# Mindestens eines sollte vorhanden sein
```

### Dockerfile prüfen

Stelle sicher, dass Dockerfile Dependencies installiert:

```dockerfile
# Sollte enthalten:
RUN pip install -e .
# ODER
RUN uv pip install -e .
```

---

## 💡 Hinweis

**Dieser Fehler ist NICHT mit den v0.25.0 Enhancements verbunden!**

Die v0.25.0 Enhancements ändern:
- ✅ Python Code (Models, Views, Tasks)
- ✅ Frontend Code (React Components)
- ✅ Konfiguration (Settings)

Sie ändern NICHT:
- ❌ Dependencies (pyproject.toml)
- ❌ Docker Setup
- ❌ Installation Process

Der Fehler tritt auf, weil:
1. Docker Image nicht neu gebaut wurde
2. Dependencies nicht installiert wurden
3. Alte Container-Version läuft

---

## 🚀 Nach dem Fix

Sobald `django-redis` installiert ist, kannst du mit dem v0.25.0 Deployment fortfahren:

```bash
# 1. Migration ausführen
docker exec dispatcharr python manage.py migrate

# 2. Verifikation
docker logs -f dispatcharr | grep -E "proxy|profile|failover"

# 3. WebUI testen
# - M3U Account öffnen
# - Proxy Feld sollte sichtbar sein
```

---

**Status:** ⚠️ DEPENDENCY ISSUE  
**Lösung:** Docker Image neu bauen  
**Impact:** Blockiert Deployment bis behoben

