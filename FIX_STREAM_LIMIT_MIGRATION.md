# Fix: Missing stream_limit Column

**Problem:** `column accounts_user.stream_limit does not exist`  
**Ursache:** Migration `0006_user_stream_limit.py` wurde nicht ausgeführt  
**Lösung:** Migration manuell ausführen

---

## Lösung 1: Django Migration ausführen (Empfohlen)

### Schritt 1: Container-Shell öffnen
```bash
docker exec -it dispatcharr bash
```

### Schritt 2: Migrations prüfen
```bash
python manage.py showmigrations accounts
```

**Erwartete Ausgabe:**
```
accounts
 [X] 0001_initial
 [X] 0002_remove_user_channel_groups_user_channel_profiles_and_more
 [X] 0003_alter_user_custom_properties
 [X] 0004_user_api_key
 [X] 0005_alter_user_managers
 [ ] 0006_user_stream_limit  ← Nicht ausgeführt!
```

### Schritt 3: Migration ausführen
```bash
python manage.py migrate accounts
```

**Erwartete Ausgabe:**
```
Running migrations:
  Applying accounts.0006_user_stream_limit... OK
```

### Schritt 4: Verifizieren
```bash
python manage.py showmigrations accounts
```

**Jetzt sollte sein:**
```
 [X] 0006_user_stream_limit  ← Jetzt ausgeführt!
```

### Schritt 5: Container neu starten
```bash
exit
docker restart dispatcharr
```

---

## Lösung 2: Direkte SQL-Ausführung (Falls Migration fehlschlägt)

### Schritt 1: PostgreSQL-Shell öffnen
```bash
docker exec -it dispatcharr-db psql -U dispatcharr -d dispatcharr
```

### Schritt 2: Spalte hinzufügen
```sql
-- Spalte hinzufügen
ALTER TABLE accounts_user 
ADD COLUMN stream_limit INTEGER DEFAULT 0;

-- Verifizieren
\d accounts_user
```

### Schritt 3: Migration als ausgeführt markieren
```bash
docker exec -it dispatcharr bash
python manage.py migrate accounts --fake 0006
```

### Schritt 4: Container neu starten
```bash
exit
docker restart dispatcharr
```

---

## Lösung 3: Alle Migrationen ausführen (Sicherste Methode)

```bash
# 1. Container-Shell öffnen
docker exec -it dispatcharr bash

# 2. Alle ausstehenden Migrationen ausführen
python manage.py migrate

# 3. Container neu starten
exit
docker restart dispatcharr
```

---

## Verifizierung

Nach der Ausführung sollte der Login funktionieren:

```bash
# Logs prüfen
docker logs dispatcharr -f

# Erwartetes Ergebnis: Keine Fehler mehr bei Login
```

---

## Warum ist das passiert?

Die Migration `0006_user_stream_limit.py` wurde in einer neueren Dispatcharr-Version hinzugefügt, aber:
- Entweder wurde `python manage.py migrate` nicht ausgeführt
- Oder die Datenbank wurde von einer älteren Version wiederhergestellt

**Das `stream_limit` Feld:**
- Begrenzt die Anzahl gleichzeitiger Streams pro User
- Standard: 0 (unbegrenzt)
- Wird im User-Model benötigt

---

## Schnellfix (One-Liner)

```bash
docker exec dispatcharr python manage.py migrate accounts && docker restart dispatcharr
```

---

**Erstellt:** 2026-04-16  
**Problem:** Missing stream_limit column  
**Status:** Lösbar mit Migration
