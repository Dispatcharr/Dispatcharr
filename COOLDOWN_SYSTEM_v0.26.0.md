# Stream Cooldown System - v0.26.0

## Übersicht

Das **Stream Cooldown System** verhindert Endlosschleifen beim Profile Failover, indem fehlgeschlagene Stream+Profile Kombinationen für eine konfigurierbare Zeit blockiert werden.

---

## Problem: Endlosschleifen ohne Cooldown

### Vorher (v0.26.0 ohne Cooldown):
```
Profile 340 → fehlgeschlagen → zu tried_combinations hinzugefügt
Profile 341 → fehlgeschlagen → zu tried_combinations hinzugefügt
Profile 342 → fehlgeschlagen → zu tried_combinations hinzugefügt
... alle Profile durch ...
tried_combinations bleibt für immer bestehen
ENDLOSSCHLEIFE: Keine neuen Profile verfügbar, System steckt fest!
```

### Nachher (v0.26.0 mit Cooldown):
```
Profile 340 → fehlgeschlagen → 10min Cooldown + tried_combinations
Profile 341 → fehlgeschlagen → 10min Cooldown + tried_combinations
Profile 342 → fehlgeschlagen → 10min Cooldown + tried_combinations
... alle Profile durch ...
ALLE Profile auf Cooldown → LAST RESORT:
  1. Lösche ALLE Cooldowns für diesen Channel
  2. tried_combinations.clear()
  3. Versuche ALLES nochmal von vorne
  4. Wenn wieder alle fehlschlagen → gibt auf (return False)
```

**Ergebnis:** Maximal 2 komplette Durchläufe, dann gibt das System auf statt endlos zu loopen.

---

## Wie funktioniert das Cooldown-System?

### 1. Cooldown bei Fehler setzen

Wenn ein Stream+Profile fehlschlägt:
```python
if ConfigHelper.stream_cooldown_enabled():
    cooldown_key = RedisKeys.stream_cooldown(channel_id, stream_id, profile_id)
    redis_client.setex(cooldown_key, cooldown_seconds, f"{failed_at}:{retry_at}")
```

**Redis-Key:**
```
live:channel:{channel_id}:cooldown:{stream_id}:{profile_id}
```

**TTL (Time To Live):** 10 Minuten (konfigurierbar)

### 2. Cooldown-Check bei get_alternate_streams

Vor dem Versuch einer Kombination:
```python
if ConfigHelper.stream_cooldown_enabled():
    for combination in untried_combinations:
        cooldown_key = RedisKeys.stream_cooldown(channel_id, stream_id, profile_id)
        if redis_client.exists(cooldown_key):
            # Überspringe diese Kombination
            continue
```

### 3. Last Resort - Alle Cooldowns löschen

Wenn alle Kombinationen auf Cooldown sind:
```python
if no_untried_combinations and alternate_streams:
    # Lösche ALLE Cooldowns für diesen Channel
    cooldown_pattern = f"live:channel:{channel_id}:cooldown:*"
    deleted_keys = redis_client.scan_delete(cooldown_pattern)
    
    # Reset tried_combinations
    self.tried_combinations.clear()
    
    # Versuche alle Kombinationen nochmal
    untried_combinations = alternate_streams
```

---

## Konfiguration

### Backend (Python)

**Datei:** `apps/proxy/config.py`

```python
{
    "stream_cooldown_enabled": False,    # Standard: deaktiviert
    "stream_cooldown_minutes": 10,       # Standard: 10 Minuten
}
```

**Helper-Methoden:** `apps/proxy/live_proxy/config_helper.py`

```python
ConfigHelper.stream_cooldown_enabled()   # → bool
ConfigHelper.stream_cooldown_seconds()   # → int (Minuten * 60)
```

### Frontend (React)

**Datei:** `frontend/src/constants.js`

```javascript
export const PROXY_SETTINGS_OPTIONS = {
  // ... andere Einstellungen ...
  stream_cooldown_enabled: {
    label: 'Stream Cooldown Enabled',
    description: 'Enable cooldown system to prevent rapid retries of failed stream/profile combinations',
  },
  stream_cooldown_minutes: {
    label: 'Stream Cooldown Duration (minutes)',
    description: 'How long to wait before retrying a failed stream/profile combination (prevents endless loops)',
  },
};
```

**UI-Komponenten:**
- **Checkbox** für `stream_cooldown_enabled`
- **NumberInput** für `stream_cooldown_minutes` (0-1440 Minuten = 0-24 Stunden)

---

## Vorteile des Cooldown-Systems

### ✅ Verhindert Endlosschleifen
- Maximal 2 komplette Durchläufe durch alle Kombinationen
- System gibt auf wenn alle Kombinationen zweimal fehlgeschlagen sind

### ✅ Reduziert Provider-Last
- Verhindert sofortiges erneutes Probieren fehlerhafter Streams
- Provider bekommt Zeit sich zu erholen (10 Minuten)

### ✅ Überlebt Channel-Restarts
- Redis-basiert, nicht in-memory
- Cooldowns bleiben bestehen auch wenn Channel neu gestartet wird

### ✅ Automatische Cleanup
- Redis TTL löscht Keys automatisch nach Ablauf
- Keine manuelle Cleanup-Logik nötig

### ✅ Konfigurierbar
- Kann in UI aktiviert/deaktiviert werden
- Cooldown-Dauer frei einstellbar (0-1440 Minuten)

### ✅ Per Default deaktiviert
- Keine Breaking Changes für bestehende Installationen
- Opt-In Feature

---

## Verhalten im Detail

### Szenario 1: Cooldown aktiviert, Provider temporär down

1. **Erste Runde:**
   - Profile 340 → Fehler → 10min Cooldown
   - Profile 341 → Fehler → 10min Cooldown
   - Profile 342 → Fehler → 10min Cooldown
   - Alle Profile auf Cooldown

2. **Last Resort triggert:**
   - Lösche alle Cooldowns
   - `tried_combinations.clear()`
   - Versuche alle nochmal

3. **Zweite Runde:**
   - Profile 340 → Fehler → 10min Cooldown
   - Profile 341 → Fehler → 10min Cooldown
   - Profile 342 → Fehler → 10min Cooldown
   - Alle Profile wieder auf Cooldown

4. **Last Resort triggert nochmal:**
   - Lösche alle Cooldowns
   - `tried_combinations.clear()`
   - Versuche alle nochmal

5. **Dritte Runde:**
   - Wenn wieder alle fehlschlagen → **gibt auf** (return False)
   - Channel wird gestoppt, keine Endlosschleife

### Szenario 2: Cooldown deaktiviert (wie vorher)

1. **Erste Runde:**
   - Profile 340 → Fehler → zu `tried_combinations`
   - Profile 341 → Fehler → zu `tried_combinations`
   - Profile 342 → Fehler → zu `tried_combinations`
   - Keine Cooldowns gesetzt

2. **Problem:**
   - `tried_combinations` bleibt für immer bestehen
   - Keine neuen Profile verfügbar
   - **Potentielle Endlosschleife** wenn System immer wieder probiert

### Szenario 3: Ein Profile erholt sich

1. **Erste Runde:**
   - Profile 340 → Fehler → 10min Cooldown
   - Profile 341 → Fehler → 10min Cooldown
   - Profile 342 → Erfolg! → Stream läuft

2. **Nach 10 Minuten Stream läuft stabil:**
   - Cooldowns für 340 und 341 sind abgelaufen (Redis hat Keys gelöscht)
   - Falls Profile 342 später fehlschlägt:
     - Profile 340 wieder verfügbar (Cooldown abgelaufen)
     - Profile 341 wieder verfügbar (Cooldown abgelaufen)
     - **Failover zu 340 oder 341 möglich!**

---

## Geänderte Dateien

### Backend (5 Dateien)

1. **apps/proxy/config.py**
   - Defaults hinzugefügt: `stream_cooldown_enabled: False`, `stream_cooldown_minutes: 10`

2. **apps/proxy/live_proxy/config_helper.py**
   - Neue Methoden: `stream_cooldown_enabled()`, `stream_cooldown_seconds()`

3. **apps/proxy/live_proxy/redis_keys.py**
   - Neue Methode: `stream_cooldown(channel_id, stream_id, profile_id)`

4. **apps/proxy/live_proxy/input/manager.py**
   - `_try_next_stream()` erweitert mit Cooldown-Logik:
     - Cooldown setzen bei Fehler
     - Cooldown-Check vor Versuch
     - Last Resort: Alle Cooldowns löschen + tried_combinations.clear()

### Frontend (3 Dateien)

1. **frontend/src/constants.js**
   - Neue Einstellungen zu `PROXY_SETTINGS_OPTIONS` hinzugefügt

2. **frontend/src/components/forms/settings/ProxySettingsForm.jsx**
   - Checkbox-Support für Boolean-Felder
   - NumberInput-Support für `stream_cooldown_minutes` (max 1440)

3. **frontend/src/utils/forms/settings/ProxySettingsFormUtils.js**
   - Defaults hinzugefügt: `stream_cooldown_enabled: false`, `stream_cooldown_minutes: 10`

---

## Testing

### 1. Cooldown deaktiviert (Default)
```bash
# Sollte sich wie v0.26.0 ohne Cooldown verhalten
# tried_combinations bleibt bestehen
```

### 2. Cooldown aktiviert (10 Minuten)
```bash
# UI: Settings → Proxy Settings
# ✅ Stream Cooldown Enabled
# 🔢 Stream Cooldown Duration: 10 minutes

# Logs sollten zeigen:
[COOLDOWN] Set cooldown for stream 708953/profile 340 on channel ... for 10m 0s
[COOLDOWN] Skipped 2 combinations on cooldown for channel ...
[COOLDOWN] Last resort: cleared 6 cooldown(s) for channel ... - retrying all combinations
```

### 3. Last Resort Trigger
```bash
# Alle Profile fehlschlagen lassen
# Nach 2-3 Durchläufen sollte Last Resort triggern
# Logs: "[COOLDOWN] Last resort: cleared X cooldown(s)"
# Logs: "Cleared tried_combinations"
```

---

## Migration von v25.0

**Keine Migration nötig!**

- Feature ist per Default deaktiviert (`stream_cooldown_enabled: false`)
- Verhält sich genau wie v25.0 wenn deaktiviert
- Opt-In via UI aktivierbar

---

## Empfohlene Einstellungen

### Für stabile Provider (z.B. eigener Server)
```
stream_cooldown_enabled: false
```
→ Nicht nötig, da Streams selten fehlschlagen

### Für instabile IPTV-Provider
```
stream_cooldown_enabled: true
stream_cooldown_minutes: 5-10
```
→ Verhindert sofortiges Retry, gibt Provider Zeit sich zu erholen

### Für sehr instabile Provider (viele Streams/Profiles)
```
stream_cooldown_enabled: true
stream_cooldown_minutes: 15-30
```
→ Längere Cooldowns reduzieren Provider-Last

---

## FAQ

**Q: Was passiert wenn ich die Cooldown-Zeit während laufendem Channel ändere?**  
A: Bereits gesetzte Cooldowns behalten ihre ursprüngliche TTL. Neue Cooldowns verwenden die neue Zeit.

**Q: Was passiert wenn ich Cooldown während laufendem Channel deaktiviere?**  
A: Bestehende Cooldowns in Redis bleiben bestehen bis TTL abläuft, aber werden nicht mehr gecheckt.

**Q: Kann ich Cooldowns manuell löschen?**  
A: Ja, via Redis CLI: `redis-cli --scan --pattern "live:channel:*:cooldown:*" | xargs redis-cli del`

**Q: Verhindert das System wirklich Endlosschleifen?**  
A: Ja! Maximal 2 komplette Durchläufe, dann gibt das System auf. Ohne Cooldown war `tried_combinations` permanent, jetzt wird es via Last Resort gecleared.

**Q: Was ist mit Stream Preview (direkter Stream-Zugriff)?**  
A: Cooldown funktioniert auch für Stream Preview! Gleiche Logik, nur dass Profile des GLEICHEN Streams probiert werden statt verschiedener Streams.

---

## Zusammenfassung

✅ **Cooldown-System implementiert** (portiert von v22.1/v23.0)  
✅ **Endlosschleifen verhindert** via Last Resort + tried_combinations.clear()  
✅ **Frontend-UI fertig** (Checkbox + NumberInput)  
✅ **Per Default deaktiviert** (keine Breaking Changes)  
✅ **Redis-basiert** (überlebt Restarts)  
✅ **Automatische TTL** (self-cleaning)  
✅ **Konfigurierbar** (0-1440 Minuten)  

**Nächster Schritt:** Docker Image neu bauen und testen!
