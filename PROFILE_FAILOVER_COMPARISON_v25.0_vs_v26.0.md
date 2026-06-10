# Profile Failover Vergleich: v25.0 vs v26.0

## Zusammenfassung

✅ **v25.0 hat Profile Failover bereits VOLLSTÄNDIG implementiert**  
❌ **v26.0 hatte 3 kritische Bugs, die Profile Failover komplett verhindert haben**

---

## Detaillierter Vergleich

### 1. `url_utils.py` - `get_alternate_streams()` Funktion

#### v25.0 (KORREKT) ✅
```python
def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = None, 
                         current_profile_id: Optional[int] = None) -> List[dict]:
    """
    Get alternative streams/profiles for a channel when the current stream fails.
    Includes profile failover: returns all available profiles for each stream.
    """
    
    for stream in streams:
        # RICHTIG: Stream wird NICHT übersprungen
        
        profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]
        
        for profile in profiles:
            # RICHTIG: Nur die aktuelle Kombination wird übersprungen
            if stream.id == current_stream_id and profile.id == current_profile_id:
                logger.debug(f"Skipping current combination stream {stream.id} + profile {profile.id}")
                continue  # ← Springt nur DIESES Profil über, nicht den ganzen Stream!
            
            # Prüfe Verbindungen für JEDES Profil
            if available:
                alternate_streams.append({
                    'stream_id': stream.id,
                    'profile_id': profile.id,
                    'name': stream.name
                })
```

**Kommentar in v25.0**:
```python
# NOTE: Do NOT skip the current stream entirely - it may have other profiles available.
# The current stream+profile combination is skipped inside the profile loop below.
```

#### v26.0 (BUGGY - VOR FIX) ❌
```python
def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = None, 
                         current_profile_id: Optional[int] = None) -> List[dict]:
    
    for stream in streams:
        # BUG 1: Stream wird komplett übersprungen!
        if current_stream_id and stream.id == current_stream_id:
            continue  # ← FALSCH: Überspringt den ganzen Stream!
        
        profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]
        
        selected_profile = None
        for profile in profiles:
            if available:
                selected_profile = profile
                break  # ← BUG 2: Stoppt nach erstem Profil!
        
        if selected_profile:
            alternate_streams.append({
                'stream_id': stream.id,
                'profile_id': selected_profile.id,  # ← Nur EIN Profil pro Stream!
                'name': stream.name
            })
```

**Problem**: 
1. Der aktuelle Stream wurde komplett übersprungen (Zeilen 320-322)
2. Es wurde nur EIN Profil pro Stream zurückgegeben (break nach erstem Fund)
3. Profile failover funktionierte nicht

---

### 2. `views.py` - Aufruf von `get_alternate_streams()`

#### v25.0 ❌ (FEHLT profile_id Parameter)
```python
# Zeile 343 in v25.0
alternates = get_alternate_streams(channel_id, stream_id)
#                                                         ↑ fehlt: m3u_profile_id
```

**Status**: **AUCH IN v25.0 IST DIESER BUG!**  
Der Parameter fehlt, aber es funktioniert trotzdem, weil:
- Die Funktion `current_profile_id=None` als Default hat
- Die Logik in `get_alternate_streams()` auch ohne profile_id funktioniert
- Es wird dann einfach das erste verfügbare Profil des aktuellen Streams mit zurückgegeben

#### v26.0 (NACH FIX) ✅
```python
# Zeile 343 in v26.0 (nach unserem Fix)
alternates = get_alternate_streams(channel_id, stream_id, m3u_profile_id)
#                                                         ↑ jetzt übergeben
```

---

### 3. `manager.py` - Aufruf von `get_alternate_streams()`

#### v25.0 ✅ (KORREKT)
```python
# Zeilen 1822-1826 in v25.0
alternate_streams = get_alternate_streams(
    self.channel_id,
    self.current_stream_id,
    self.current_profile_id  # ← RICHTIG: Profil-ID wird übergeben
)
```

#### v26.0 (VOR FIX) ❌
```python
# Zeile 1800 in v26.0 (vor dem Fix)
alternate_streams = get_alternate_streams(
    self.channel_id,
    self.current_stream_id
    # ← FEHLT: current_profile_id Parameter
)
```

#### v26.0 (NACH FIX) ✅
```python
# Zeile 1800 in v26.0 (nach dem Fix)
alternate_streams = get_alternate_streams(
    self.channel_id,
    self.current_stream_id,
    self.current_profile_id  # ← Jetzt korrekt übergeben
)
```

---

### 4. `manager.py` - Laden der `current_profile_id` aus Redis

#### v25.0 ✅ (KORREKT)
```python
# v25.0 lädt profile_id aus Redis im __init__
if stream_id:
    self.tried_stream_ids.add(stream_id)
    # Lädt auch profile_id aus Redis
    if redis_client:
        profile_id_bytes = redis_client.hget(metadata_key, "m3u_profile")
        if profile_id_bytes:
            self.current_profile_id = int(profile_id_bytes)
            logger.info(f"Loaded profile ID {self.current_profile_id}")
```

#### v26.0 (VOR FIX) ❌
```python
# v26.0 (vor dem Fix) - profile_id wurde NIE geladen!
if stream_id:
    self.tried_stream_ids.add(stream_id)
    logger.info(f"Initialized stream manager with stream ID {stream_id}")
    # ← BUG: current_profile_id bleibt None!
```

---

## Stream Preview (Direct Stream Zugriff)

### Beide Versionen: Profile Failover funktioniert NICHT für Preview ❌

**Problem**: Wenn man direkt einen Stream über Stream-Hash aufruft (Preview):
```
http://dispatcharr/stream/{stream_hash}/stream.m3u8
```

Dann wird in `url_utils.py` `generate_stream_url()` erkannt, dass es ein `Stream` Objekt ist:

```python
if isinstance(channel_or_stream, Stream):
    stream = channel_or_stream
    logger.info(f"Previewing stream directly: {stream.id} ({stream.name})")
    # ... nutzt nur DEFAULT Profil, kein Failover
```

**UND** in `get_alternate_streams()`:
```python
channel = get_stream_object(channel_id)
if isinstance(channel, Stream):
    logger.error(f"Stream is not a channel")
    return []  # ← LEER! Kein Failover bei Stream Preview
```

**Status in beiden Versionen**: Stream Preview hat **KEIN Profile Failover**

---

## Bugs-Übersicht

| Bug | v25.0 | v26.0 (vor Fix) | v26.0 (nach Fix) |
|-----|-------|-----------------|------------------|
| **Bug 1**: Stream wird komplett übersprungen statt nur Profil | ✅ Behoben | ❌ Vorhanden | ✅ Behoben |
| **Bug 2**: Nur ein Profil pro Stream statt alle | ✅ Behoben | ❌ Vorhanden | ✅ Behoben |
| **Bug 3**: `current_profile_id` wird nicht aus Redis geladen | ✅ Behoben | ❌ Vorhanden | ✅ Behoben |
| **Bug 4**: `views.py` übergibt keine `profile_id` | ❌ Vorhanden | ❌ Vorhanden | ✅ Behoben |
| **Bug 5**: Stream Preview hat kein Profile Failover | ❌ Vorhanden | ❌ Vorhanden | ❌ Vorhanden |

---

## Fazit

### v25.0
- ✅ Profile Failover für **Channels** funktioniert **fast vollständig**
- ⚠️ Kleiner Bug in `views.py` (profile_id fehlt), aber nicht kritisch
- ❌ Stream Preview hat kein Profile Failover

### v26.0 (vor Fix)
- ❌ Profile Failover **komplett kaputt** durch 3 schwerwiegende Bugs
- ❌ Stream wurde komplett übersprungen
- ❌ Nur ein Profil pro Stream wurde zurückgegeben
- ❌ `current_profile_id` wurde nie geladen
- ❌ Stream Preview hat kein Profile Failover

### v26.0 (nach unserem Fix)
- ✅ Profile Failover für **Channels** funktioniert **vollständig**
- ✅ Alle 4 Bugs in Channel-Failover behoben
- ❌ Stream Preview hat immer noch kein Profile Failover (wie v25.0)

---

## Empfehlung

**v25.0 Code sollte die Basis für Profile Failover sein!**

Der Code in v25.0 ist deutlich besser und hat die richtige Logik für Profile Failover bereits implementiert. In v26.0 wurden versehentlich mehrere Regressions eingeführt.

**Unser Fix für v26.0** stellt den Stand von v25.0 wieder her und verbessert ihn sogar noch durch:
1. Korrekten `profile_id` Parameter-Durchreichung in `views.py`
2. Bessere Code-Dokumentation

---

**Erstellt**: 2026-06-10  
**Status**: ✅ Analyse komplett
