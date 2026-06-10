# Profile Failover Behavior - Mit vs Ohne Cooldown

## Überblick

Dieses Dokument erklärt wie Profile Failover in v0.26.0 funktioniert, mit und ohne Cooldown-System.

---

## Scenario: Channel mit 2 Streams, je 3 Profiles

```
Channel: ZDF
├── Stream 1 (ID: 708953)
│   ├── Profile 340 (default)
│   ├── Profile 341
│   └── Profile 342
└── Stream 2 (ID: 708954) [BACKUP]
    ├── Profile 343 (default)
    ├── Profile 344
    └── Profile 345
```

---

## Failover-Reihenfolge (IMMER gleich)

Die Reihenfolge ist **UNABHÄNGIG von Cooldown** immer gleich:

```python
# get_alternate_streams() liefert:
[
    {'stream_id': 708953, 'profile_id': 340},  # Stream 1, Profile 1 (default)
    {'stream_id': 708953, 'profile_id': 341},  # Stream 1, Profile 2
    {'stream_id': 708953, 'profile_id': 342},  # Stream 1, Profile 3
    {'stream_id': 708954, 'profile_id': 343},  # Stream 2, Profile 1 (default)
    {'stream_id': 708954, 'profile_id': 344},  # Stream 2, Profile 2
    {'stream_id': 708954, 'profile_id': 345},  # Stream 2, Profile 3
]
```

**Grund:** `streams.order_by('channelstream__order')` + Profile in Reihenfolge (default zuerst)

---

## OHNE Cooldown (Default in v0.26.0)

### Versuch 1: Alle Profile von Stream 1 fehlschlagen

```
Profile 340 → Fehler → zu tried_combinations hinzugefügt
Profile 341 → Fehler → zu tried_combinations hinzugefügt
Profile 342 → Fehler → zu tried_combinations hinzugefügt
→ Wechsel zu Stream 2 (Backup)
Profile 343 → Fehler → zu tried_combinations hinzugefügt
Profile 344 → Fehler → zu tried_combinations hinzugefügt
Profile 345 → Fehler → zu tried_combinations hinzugefügt
→ Keine weiteren Streams
→ tried_combinations = {(708953,340), (708953,341), (708953,342), (708954,343), (708954,344), (708954,345)}
```

### Versuch 2: System versucht erneut zu failovern

```
get_alternate_streams() liefert wieder:
[
    (708953, 340), (708953, 341), (708953, 342),
    (708954, 343), (708954, 344), (708954, 345)
]

untried_combinations = [Alle] - tried_combinations = []
→ LEER! Keine untried combinations
→ return False
→ Channel stoppt
```

**Problem:** `tried_combinations` bleibt für immer bestehen!

### Was fehlt?

❌ Kein Reset von `tried_combinations`  
❌ Nach 10 Minuten könnte Provider sich erholt haben, aber System probiert nicht mehr  
❌ Bei Channel-Neustart werden tried_combinations resettet, aber das ist manuell  

---

## MIT Cooldown (Opt-In Feature)

### Versuch 1: Alle Profile von Stream 1 fehlschlagen

```
Profile 340 → Fehler 
  → zu tried_combinations hinzugefügt
  → 10min Cooldown in Redis: live:channel:{UUID}:cooldown:708953:340
  
Profile 341 → Fehler
  → zu tried_combinations hinzugefügt
  → 10min Cooldown in Redis: live:channel:{UUID}:cooldown:708953:341
  
Profile 342 → Fehler
  → zu tried_combinations hinzugefügt
  → 10min Cooldown in Redis: live:channel:{UUID}:cooldown:708953:342

→ Wechsel zu Stream 2 (Backup)

Profile 343 → Fehler
  → zu tried_combinations hinzugefügt
  → 10min Cooldown in Redis: live:channel:{UUID}:cooldown:708954:343
  
Profile 344 → Fehler
  → zu tried_combinations hinzugefügt
  → 10min Cooldown in Redis: live:channel:{UUID}:cooldown:708954:344
  
Profile 345 → Fehler
  → zu tried_combinations hinzugefügt
  → 10min Cooldown in Redis: live:channel:{UUID}:cooldown:708954:345

→ Keine weiteren Streams
→ tried_combinations = {alle 6 Kombinationen}
→ Alle 6 Kombinationen auf Cooldown in Redis
```

### LAST RESORT triggert

```
if not untried_combinations and alternate_streams:
    # Alle Kombinationen probiert, aber es gibt Streams
    if ConfigHelper.stream_cooldown_enabled():
        # Lösche ALLE Cooldowns für diesen Channel
        redis_client.scan_delete("live:channel:{UUID}:cooldown:*")
        # → 6 Keys gelöscht
        
        # Reset tried_combinations
        tried_combinations.clear()
        # → Jetzt leer: set()
        
        # Retry mit allen Kombinationen
        untried_combinations = alternate_streams
        # → Alle 6 Kombinationen wieder verfügbar
```

### Versuch 2: Alles nochmal probieren

```
Profile 340 → Fehler → 10min Cooldown + tried_combinations
Profile 341 → Fehler → 10min Cooldown + tried_combinations
Profile 342 → Fehler → 10min Cooldown + tried_combinations
Profile 343 → Fehler → 10min Cooldown + tried_combinations
Profile 344 → Fehler → 10min Cooldown + tried_combinations
Profile 345 → Fehler → 10min Cooldown + tried_combinations
→ Wieder alle auf Cooldown
```

### LAST RESORT triggert NOCHMAL

```
# Lösche wieder alle Cooldowns
redis_client.scan_delete("live:channel:{UUID}:cooldown:*")
# → 6 Keys gelöscht

# Reset tried_combinations
tried_combinations.clear()

# Retry mit allen Kombinationen
untried_combinations = alternate_streams
```

### Versuch 3: Letzte Chance

```
Profile 340 → Fehler
Profile 341 → Fehler
Profile 342 → Fehler
Profile 343 → Fehler
Profile 344 → Fehler
Profile 345 → Fehler
→ Alle fehlgeschlagen

# Jetzt gibt es KEINE Last Resort mehr
→ return False
→ Channel stoppt
```

**Ergebnis:** Maximal 3 Durchläufe (1 initial + 2x Last Resort), dann gibt System auf

### Was bringt das?

✅ Reset von `tried_combinations` via Last Resort  
✅ Verhindert Endlosschleifen (max. 3 Durchläufe)  
✅ Nach 10 Minuten sind Cooldowns automatisch abgelaufen → System kann wieder probieren  
✅ Provider bekommt Zeit sich zu erholen  

---

## Was passiert wenn ein Profile sich erholt?

### Scenario: Profile 340 erholt sich nach 2 Minuten

**OHNE Cooldown:**
```
Profile 340 fehlgeschlagen → tried_combinations = {(708953,340), ...}
→ System probiert Profile 341, 342, 343, 344, 345
→ Alle fehlschlagen → gibt auf
→ Nach 2 Minuten erholt sich Profile 340
→ System probiert NICHT nochmal (tried_combinations bleibt bestehen)
→ Channel bleibt tot
```

**MIT Cooldown:**
```
Profile 340 fehlgeschlagen → 10min Cooldown + tried_combinations
→ System probiert Profile 341, 342, 343, 344, 345
→ Alle fehlschlagen → Last Resort
→ Lösche alle Cooldowns + tried_combinations.clear()
→ Probiere Profile 340 nochmal (nach 2 Minuten)
→ Erfolg! Stream läuft
```

**Oder nach 10 Minuten:**
```
Profile 340 fehlgeschlagen → 10min Cooldown
→ System probiert andere Profiles
→ Alle fehlschlagen
→ Nach 10 Minuten: Cooldown für Profile 340 automatisch abgelaufen (Redis TTL)
→ Bei nächstem Failover: Profile 340 wieder verfügbar!
→ tried_combinations wird ignoriert wenn Cooldown abgelaufen ist
```

---

## Vergleich: tried_combinations vs Cooldown

### tried_combinations (OHNE Cooldown)

**Vorteile:**
- Einfach
- Kein Redis nötig
- Keine Config nötig

**Nachteile:**
- ❌ Bleibt für immer bestehen
- ❌ Kein Reset-Mechanismus
- ❌ Provider kann sich nicht erholen
- ❌ Potentielle Endlosschleifen

### Cooldown (MIT Cooldown)

**Vorteile:**
- ✅ Automatischer Reset via Last Resort
- ✅ Verhindert Endlosschleifen (max. 3 Durchläufe)
- ✅ Redis TTL: Nach 10 Minuten sind Cooldowns weg
- ✅ Provider bekommt Zeit sich zu erholen
- ✅ Konfigurierbar (0-1440 Minuten)

**Nachteile:**
- Braucht Redis (aber ist sowieso vorhanden)
- Braucht Config (aber hat UI)
- Komplexer Code

---

## Wann welches System?

### OHNE Cooldown (Default)

**Geeignet für:**
- Stabile Provider (eigener Server)
- Wenige Streams/Profiles
- Testing/Debugging
- Wenn schnelles Failover wichtig ist

**Risiko:**
- Endlosschleifen möglich
- tried_combinations bleibt bestehen

### MIT Cooldown

**Geeignet für:**
- Instabile IPTV-Provider
- Viele Streams/Profiles
- Produktions-Umgebung
- Wenn Provider-Last reduziert werden soll

**Vorteil:**
- Keine Endlosschleifen
- Provider-freundlich
- Automatische Recovery

---

## Code-Beispiel: Cooldown-Check

```python
# In _try_next_stream():

# 1. Markiere aktuelle Kombination als fehlgeschlagen
if current_stream_id and current_profile_id:
    tried_combinations.add((current_stream_id, current_profile_id))
    
    # Setze Cooldown (wenn aktiviert)
    if ConfigHelper.stream_cooldown_enabled():
        cooldown_key = RedisKeys.stream_cooldown(channel_id, stream_id, profile_id)
        redis_client.setex(cooldown_key, 600, f"{time.time()}:{time.time()+600}")
        logger.info("[COOLDOWN] Set cooldown for stream X/profile Y for 10m")

# 2. Hole alle alternativ Streams/Profiles
alternate_streams = get_alternate_streams(channel_id, current_stream_id, current_profile_id)

# 3. Filtere bereits probierte Kombinationen
untried_combinations = [
    s for s in alternate_streams 
    if (s['stream_id'], s['profile_id']) not in tried_combinations
]

# 4. Filtere Cooldowns (wenn aktiviert)
if ConfigHelper.stream_cooldown_enabled():
    cooled_down = []
    for s in untried_combinations:
        cooldown_key = RedisKeys.stream_cooldown(channel_id, s['stream_id'], s['profile_id'])
        if not redis_client.exists(cooldown_key):
            cooled_down.append(s)
        else:
            logger.debug("[COOLDOWN] Skipping stream X/profile Y - still on cooldown")
    untried_combinations = cooled_down

# 5. Last Resort wenn keine Kombinationen übrig
if not untried_combinations and alternate_streams:
    if ConfigHelper.stream_cooldown_enabled():
        # Lösche alle Cooldowns
        redis_client.scan_delete(f"live:channel:{channel_id}:cooldown:*")
        # Reset tried_combinations
        tried_combinations.clear()
        # Retry mit allen
        untried_combinations = alternate_streams
        logger.info("[COOLDOWN] Last resort: cleared cooldowns, retrying all")

# 6. Probiere Kombinationen
for combo in untried_combinations:
    # Versuche zu verbinden...
```

---

## Zusammenfassung

| Feature | OHNE Cooldown | MIT Cooldown |
|---------|---------------|--------------|
| **Failover-Reihenfolge** | Stream 1 alle Profiles → Stream 2 alle Profiles | Stream 1 alle Profiles → Stream 2 alle Profiles |
| **tried_combinations** | Bleibt für immer | Reset via Last Resort |
| **Max Durchläufe** | ∞ (potentielle Endlosschleife) | 3 (1 + 2x Last Resort) |
| **Provider Recovery** | Nur bei Channel-Restart | Automatisch nach Cooldown-Zeit |
| **Redis Keys** | Keine | `live:channel:{UUID}:cooldown:{stream}:{profile}` |
| **Config** | Keine | `stream_cooldown_enabled`, `stream_cooldown_minutes` |
| **UI** | Keine | Checkbox + NumberInput |
| **Default** | ✅ Aktiviert | ❌ Deaktiviert (Opt-In) |

**Empfehlung:** 
- Default (ohne Cooldown) für Testing und stabile Provider
- Mit Cooldown für Production und instabile IPTV-Provider

---

**Beide Systeme probieren erst alle Profile eines Streams, dann Backup-Stream! 🚀**
