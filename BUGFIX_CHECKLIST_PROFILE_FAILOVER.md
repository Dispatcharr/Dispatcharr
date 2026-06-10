# 🔍 Bugfix-Checkliste: Profile Failover

## ⚠️ KRITISCHE FEHLER DIE VERMIEDEN WERDEN MÜSSEN

Diese Checkliste zeigt dir, was beim Profile Failover **immer** geprüft werden muss.

---

## ✅ CHECKLISTE FÜR `get_alternate_streams()`

### 1. ❌ **NIEMALS** den aktuellen Stream komplett überspringen!

**FALSCH** ❌:
```python
for stream in streams:
    # FEHLER: Überspringt den GANZEN Stream!
    if current_stream_id and stream.id == current_stream_id:
        continue
```

**RICHTIG** ✅:
```python
for stream in streams:
    # Stream NICHT überspringen - hat evtl. andere Profile!
    # Nur die aktuelle Stream+Profil-Kombination wird übersprungen
    
    for profile in profiles:
        # Hier wird nur die fehlgeschlagene Kombination übersprungen
        if stream.id == current_stream_id and profile.id == current_profile_id:
            continue
```

**Warum?** Ein Stream kann mehrere Profile haben. Wenn das erste Profil fehlschlägt, müssen die anderen Profile probiert werden!

---

### 2. ❌ **NIEMALS** nach dem ersten verfügbaren Profil mit `break` stoppen!

**FALSCH** ❌:
```python
selected_profile = None
for profile in profiles:
    if available:
        selected_profile = profile
        break  # ← FEHLER: Stoppt nach erstem Profil!

if selected_profile:
    alternate_streams.append(selected_profile)
```

**RICHTIG** ✅:
```python
# Kein "selected_profile" - stattdessen ALLE Profile prüfen
for profile in profiles:
    if available:
        # Jedes verfügbare Profil direkt hinzufügen
        alternate_streams.append({
            'stream_id': stream.id,
            'profile_id': profile.id,
            'name': stream.name
        })
```

**Warum?** Profile Failover bedeutet, dass ALLE Profile eines Streams verfügbar sein sollen!

---

### 3. ❌ **NIEMALS** vergessen, `current_profile_id` Parameter zu übergeben!

**FALSCH** ❌:
```python
# In views.py oder manager.py
alternates = get_alternate_streams(channel_id, stream_id)
#                                                         ↑ fehlt!
```

**RICHTIG** ✅:
```python
# In views.py
alternates = get_alternate_streams(channel_id, stream_id, m3u_profile_id)

# In manager.py  
alternates = get_alternate_streams(self.channel_id, self.current_stream_id, self.current_profile_id)
```

**Warum?** Ohne `current_profile_id` kann die Funktion nicht wissen, welches Profil gerade fehlgeschlagen ist!

---

### 4. ❌ **NIEMALS** vergessen, `current_profile_id` aus Redis zu laden!

**FALSCH** ❌:
```python
# In manager.py __init__
if stream_id:
    self.current_stream_id = stream_id
    self.tried_stream_ids.add(stream_id)
    # ← FEHLER: current_profile_id bleibt None!
```

**RICHTIG** ✅:
```python
# In manager.py __init__
if stream_id:
    self.current_stream_id = stream_id
    self.tried_stream_ids.add(stream_id)
    
    # Auch profile_id aus Redis laden!
    if hasattr(buffer, 'redis_client') and buffer.redis_client:
        try:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            profile_id_bytes = buffer.redis_client.hget(metadata_key, "m3u_profile")
            if profile_id_bytes:
                self.current_profile_id = int(profile_id_bytes.decode('utf-8') if isinstance(profile_id_bytes, bytes) else profile_id_bytes)
                logger.info(f"Loaded profile ID {self.current_profile_id}")
        except Exception as e:
            logger.warning(f"Error loading profile ID: {e}")
```

**Warum?** Ohne geladene `current_profile_id` ist sie `None` und die Logik kann das fehlgeschlagene Profil nicht überspringen!

---

## 📋 SCHNELL-PRÜFUNG

### Wenn du an Profile Failover arbeitest, prüfe:

1. ✅ **`url_utils.py`**: Wird der aktuelle Stream NICHT komplett übersprungen?
2. ✅ **`url_utils.py`**: Werden ALLE Profile zurückgegeben (kein `break` nach erstem)?
3. ✅ **`views.py`**: Wird `m3u_profile_id` an `get_alternate_streams()` übergeben?
4. ✅ **`manager.py`**: Wird `self.current_profile_id` an `get_alternate_streams()` übergeben?
5. ✅ **`manager.py`**: Wird `self.current_profile_id` aus Redis geladen?

---

## 🧪 TEST-SZENARIO

### Teste Profile Failover mit:

**Setup**:
- Ein Channel (z.B. ZDF)
- Ein Stream (z.B. "ZDF Raw" von XC Club)
- Mehrere Profile (z.B. Profile 3402, 3403, 3404)

**Test**:
1. Erste Verbindung schlägt fehl (Profil 3402)
2. Logs prüfen:

**Erwartete Ausgabe**:
```log
INFO live_proxy.manager Trying to find alternative stream for channel ..., current stream ID: 708953, current profile ID: 3402
DEBUG live_proxy.url_utils Skipping current failing stream+profile combination: stream=708953, profile=3402
DEBUG live_proxy.url_utils Found available profile 3403 for stream 708953
DEBUG live_proxy.url_utils Found available profile 3404 for stream 708953
INFO live_proxy.url_utils Found 2 alternate streams with available connections
INFO live_proxy.manager Found 2 potential alternate stream+profile combinations
```

**Wenn du siehst**:
```log
WARNING live_proxy.url_utils No alternate streams with available connections found
INFO live_proxy.manager Found 0 potential alternate stream+profile combinations
```

Dann ist einer der 4 oben genannten Bugs vorhanden!

---

## 🔧 DEBUG-HINWEISE

### Symptom: "No alternate streams found" obwohl Profile vorhanden

**Mögliche Ursachen**:
1. ❌ Stream wird komplett übersprungen → **Prüfe Punkt 1 oben**
2. ❌ Nur ein Profil wird zurückgegeben → **Prüfe Punkt 2 oben**
3. ❌ `current_profile_id` wird nicht übergeben → **Prüfe Punkt 3 oben**
4. ❌ `current_profile_id` ist `None` → **Prüfe Punkt 4 oben**

### Debug-Logging aktivieren

Füge diese Logs hinzu um zu debuggen:
```python
# In get_alternate_streams()
logger.info(f"get_alternate_streams called with: channel_id={channel_id}, current_stream_id={current_stream_id}, current_profile_id={current_profile_id}")

# In der Profil-Schleife
logger.debug(f"Checking profile {profile.id} for stream {stream.id}")
logger.debug(f"Will skip? stream_match={stream.id == current_stream_id}, profile_match={profile.id == current_profile_id}")
```

---

## 📚 REFERENZ-IMPLEMENTIERUNG

**Die korrekte Implementierung findest du in**:
- `Dispatcharr - 25.0/apps/proxy/live_proxy/url_utils.py`
- Aktuelle v0.26.0 (nach dem Fix)

**Merke dir den Kommentar aus v0.25.0**:
```python
# NOTE: Do NOT skip the current stream entirely - it may have other profiles available.
# The current stream+profile combination is skipped inside the profile loop below.
```

---

## ⚡ SCHNELLTEST VOR COMMIT

Führe diese Tests durch:
```bash
# Test 1: Prüfe ob der Stream nicht komplett übersprungen wird
grep -A5 "for stream in streams" apps/proxy/live_proxy/url_utils.py
# → Es darf KEIN "if current_stream_id and stream.id == current_stream_id: continue" geben!

# Test 2: Prüfe ob alle Profile zurückgegeben werden
grep -A10 "for profile in profiles" apps/proxy/live_proxy/url_utils.py
# → Es darf KEIN "selected_profile = ..." mit "break" geben!

# Test 3: Prüfe ob profile_id übergeben wird
grep "get_alternate_streams" apps/proxy/live_proxy/views.py apps/proxy/live_proxy/input/manager.py
# → Alle Aufrufe müssen 3 Parameter haben!

# Test 4: Prüfe ob profile_id geladen wird
grep -A5 "current_profile_id" apps/proxy/live_proxy/input/manager.py
# → Muss aus Redis geladen werden!
```

---

**Erstellt**: 2026-06-10  
**Version**: v1.0  
**Zweck**: Verhindere Regression-Bugs beim Profile Failover

---

## 🎯 WICHTIGSTE REGEL

> **Ein Stream mit mehreren Profilen = Ein Provider mit mehreren Verbindungs-Optionen**
> 
> Wenn Option A fehlschlägt, versuche Option B, dann C, etc.
> 
> **ÜBERSPINGE NIEMALS** den gesamten Stream nur weil ein Profil fehlgeschlagen ist!

✅ Nutze diese Checkliste beim nächsten Update von Dispatcharr!
