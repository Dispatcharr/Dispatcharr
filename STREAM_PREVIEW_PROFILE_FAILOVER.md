# Stream Preview Profile Failover Implementation

## Problem

Aktuell funktioniert Profile Failover NICHT für Stream Preview (direkter Stream-Zugriff):

```python
# In get_alternate_streams():
if isinstance(channel, Stream):
    logger.error(f"Stream is not a channel")
    return []  # ← LEER! Keine Profile für Failover
```

**Beispiel**: 
- Stream Preview URL: `http://dispatcharr/stream/{stream_hash}/stream.m3u8`
- Stream hat 3 Profile (3402, 3403, 3404)
- Wenn Profil 3402 fehlschlägt → Gibt auf statt 3403 zu probieren

## Lösung

Wir müssen `get_alternate_streams()` erweitern, um bei einem Stream-Objekt **alle Profile dieses Streams** zurückzugeben.

### Code-Änderung

**Datei**: `apps/proxy/live_proxy/url_utils.py`  
**Funktion**: `get_alternate_streams()`  
**Zeilen**: ~300-305

#### Aktuell (FALSCH):
```python
# Get channel object
channel = get_stream_object(channel_id)
if isinstance(channel, Stream):
    logger.error(f"Stream is not a channel")
    return []  # ← Gibt auf!
```

#### NEU (RICHTIG):
```python
# Get channel or stream object
channel_or_stream = get_stream_object(channel_id)

# Handle Stream Preview: Return all profiles for THIS stream only
if isinstance(channel_or_stream, Stream):
    stream = channel_or_stream
    logger.info(f"Stream preview: Getting alternate profiles for stream {stream.id}")
    
    # Get all profiles for this specific stream
    m3u_account = stream.m3u_account
    if not m3u_account:
        logger.warning(f"Stream {stream.id} has no M3U account")
        return []
    
    if not m3u_account.is_active:
        logger.warning(f"M3U account {m3u_account.id} is inactive")
        return []
    
    # Get all active profiles
    m3u_profiles = m3u_account.profiles.filter(is_active=True)
    default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)
    
    if not default_profile:
        logger.warning(f"M3U account {m3u_account.id} has no default profile")
        return []
    
    # Order: default first, then others
    profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]
    
    alternate_profiles = []
    redis_client = RedisClient.get_client()
    
    for profile in profiles:
        # Skip the currently failing profile
        if current_profile_id and profile.id == current_profile_id:
            logger.debug(f"Skipping current failing profile {profile.id} for stream {stream.id}")
            continue
        
        # Check connection availability (same logic as channel)
        if redis_client:
            profile_connections_key = f"profile_connections:{profile.id}"
            current_connections = int(redis_client.get(profile_connections_key) or 0)
            
            # For stream preview, we don't check "already using" since it's the same stream
            if profile.max_streams == 0 or current_connections < profile.max_streams:
                logger.debug(f"Found available profile {profile.id} for stream {stream.id}: {current_connections}/{profile.max_streams}")
                alternate_profiles.append({
                    'stream_id': stream.id,
                    'profile_id': profile.id,
                    'name': stream.name
                })
            else:
                logger.debug(f"Profile {profile.id} at max connections: {current_connections}/{profile.max_streams}")
        else:
            # No Redis, add all profiles
            alternate_profiles.append({
                'stream_id': stream.id,
                'profile_id': profile.id,
                'name': stream.name
            })
    
    if alternate_profiles:
        profile_ids = ', '.join([str(p['profile_id']) for p in alternate_profiles])
        logger.info(f"Found {len(alternate_profiles)} alternate profiles for stream preview: [{profile_ids}]")
    else:
        logger.warning(f"No alternate profiles found for stream preview {stream.id}")
    
    return alternate_profiles

# Handle Channel (existing logic)
channel = channel_or_stream
redis_client = RedisClient.get_client()
# ... rest of existing code ...
```

## Vollständige Implementierung

### Datei: `apps/proxy/live_proxy/url_utils.py`

```python
def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = None, current_profile_id: Optional[int] = None) -> List[dict]:
    """
    Get alternative streams for a channel OR alternative profiles for a stream when the current stream fails.
    
    For Channels: Returns all stream+profile combinations (profile failover across streams)
    For Stream Preview: Returns all profiles for THIS stream only (profile failover within stream)

    Args:
        channel_id: The UUID of the channel OR stream hash
        current_stream_id: The currently failing stream ID (for channels)
        current_profile_id: The currently failing profile ID to exclude

    Returns:
        List[dict]: List of stream information dictionaries with stream_id and profile_id
    """
    try:
        from core.utils import RedisClient

        # Get channel or stream object
        channel_or_stream = get_stream_object(channel_id)

        # ============================================================
        # STREAM PREVIEW: Return all profiles for THIS stream only
        # ============================================================
        if isinstance(channel_or_stream, Stream):
            stream = channel_or_stream
            logger.info(f"Stream preview: Getting alternate profiles for stream {stream.id}")
            
            # Get all profiles for this specific stream
            m3u_account = stream.m3u_account
            if not m3u_account:
                logger.warning(f"Stream {stream.id} has no M3U account")
                return []
            
            if not m3u_account.is_active:
                logger.warning(f"M3U account {m3u_account.id} is inactive")
                return []
            
            # Get all active profiles
            m3u_profiles = m3u_account.profiles.filter(is_active=True)
            default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)
            
            if not default_profile:
                logger.warning(f"M3U account {m3u_account.id} has no default profile")
                return []
            
            # Order: default first, then others
            profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]
            
            alternate_profiles = []
            redis_client = RedisClient.get_client()
            
            for profile in profiles:
                # Skip the currently failing profile
                if current_profile_id and profile.id == current_profile_id:
                    logger.debug(f"Skipping current failing profile {profile.id} for stream {stream.id}")
                    continue
                
                # Check connection availability
                if redis_client:
                    profile_connections_key = f"profile_connections:{profile.id}"
                    current_connections = int(redis_client.get(profile_connections_key) or 0)
                    
                    # For stream preview, we don't check "channel_using_profile" since it's the same stream
                    if profile.max_streams == 0 or current_connections < profile.max_streams:
                        logger.debug(f"Found available profile {profile.id} for stream {stream.id}: {current_connections}/{profile.max_streams}")
                        alternate_profiles.append({
                            'stream_id': stream.id,
                            'profile_id': profile.id,
                            'name': stream.name
                        })
                    else:
                        logger.debug(f"Profile {profile.id} at max connections: {current_connections}/{profile.max_streams}")
                else:
                    # No Redis, add all profiles
                    alternate_profiles.append({
                        'stream_id': stream.id,
                        'profile_id': profile.id,
                        'name': stream.name
                    })
            
            if alternate_profiles:
                profile_ids = ', '.join([str(p['profile_id']) for p in alternate_profiles])
                logger.info(f"Found {len(alternate_profiles)} alternate profiles for stream preview {stream.id}: [{profile_ids}]")
            else:
                logger.warning(f"No alternate profiles found for stream preview {stream.id}")
            
            return alternate_profiles

        # ============================================================
        # CHANNEL: Return all stream+profile combinations (existing logic)
        # ============================================================
        channel = channel_or_stream
        redis_client = RedisClient.get_client()
        logger.debug(f"Looking for alternate streams for channel {channel_id}, current stream ID: {current_stream_id}")

        # ... Rest of existing channel logic (unchanged) ...
```

## Verhalten nach dem Fix

### Vor dem Fix ❌
```log
# Stream Preview URL schlägt fehl
Stream is not a channel
No alternate streams found
→ Gibt auf
```

### Nach dem Fix ✅
```log
# Stream Preview URL schlägt fehl (Profil 3402)
Stream preview: Getting alternate profiles for stream 708953
Skipping current failing profile 3402 for stream 708953
Found available profile 3403 for stream 708953: 1/3
Found available profile 3404 for stream 708953: 0/3
Found 2 alternate profiles for stream preview 708953: [3403, 3404]
→ Versucht Profil 3403, dann 3404
```

## Test-Szenario

### Setup
1. Ein Stream mit 3 Profilen (z.B. "ZDF Raw" mit Profile 3402, 3403, 3404)
2. Stream Hash: `abc123def456`
3. Preview URL: `http://dispatcharr/stream/abc123def456/stream.m3u8`

### Test
1. Erste Verbindung mit Profil 3402 schlägt fehl
2. System erkennt: Es ist ein Stream (nicht Channel)
3. System ruft `get_alternate_streams(stream_hash, stream_id=708953, profile_id=3402)` auf
4. Funktion gibt Profile 3403 und 3404 zurück
5. System versucht Profil 3403
6. Wenn 3403 fehlschlägt, versucht 3404

### Erwartete Logs
```log
INFO live_proxy.manager Stream is being previewed directly
INFO live_proxy.manager Trying to find alternative stream for stream 708953, current profile ID: 3402
INFO live_proxy.url_utils Stream preview: Getting alternate profiles for stream 708953
DEBUG live_proxy.url_utils Skipping current failing profile 3402 for stream 708953
DEBUG live_proxy.url_utils Found available profile 3403 for stream 708953: 1/3
DEBUG live_proxy.url_utils Found available profile 3404 for stream 708953: 0/3
INFO live_proxy.url_utils Found 2 alternate profiles for stream preview 708953: [3403, 3404]
INFO live_proxy.manager Found 2 potential alternate profile combinations for stream 708953
INFO live_proxy.manager Trying next profile ID 3403 for stream 708953
```

## Wichtige Punkte

### Was ist anders bei Stream Preview?
1. **Nur DIESER Stream**: Keine anderen Streams werden probiert
2. **Alle Profile**: Alle Profile dieses M3U Accounts werden durchprobiert
3. **Gleiche Logik**: Connection-Limit-Checks funktionieren gleich
4. **Kein "channel_using_profile"**: Check wird übersprungen (ist derselbe Stream)

### Was bleibt gleich?
- Profile werden geordnet (Default first)
- Connection-Limits werden respektiert
- Aktuell fehlgeschlagenes Profil wird übersprungen
- Redis-Tracking funktioniert

## Patch-Datei

**Datei**: `stream_preview_profile_failover.patch`

```diff
--- a/apps/proxy/live_proxy/url_utils.py
+++ b/apps/proxy/live_proxy/url_utils.py
@@ -284,15 +284,82 @@ def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = N
 def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = None, current_profile_id: Optional[int] = None) -> List[dict]:
     """
-    Get alternative streams for a channel when the current stream fails.
+    Get alternative streams for a channel OR alternative profiles for a stream when the current stream fails.
+    
+    For Channels: Returns all stream+profile combinations (profile failover across streams)
+    For Stream Preview: Returns all profiles for THIS stream only (profile failover within stream)
 
     Args:
-        channel_id: The UUID of the channel
-        current_stream_id: The currently failing stream ID
+        channel_id: The UUID of the channel OR stream hash
+        current_stream_id: The currently failing stream ID (for channels)
         current_profile_id: The currently failing profile ID to exclude
 
     Returns:
         List[dict]: List of stream information dictionaries with stream_id and profile_id
     """
     try:
         from core.utils import RedisClient
 
-        # Get channel object
-        channel = get_stream_object(channel_id)
-        if isinstance(channel, Stream):
-            logger.error(f"Stream is not a channel")
-            return []
+        # Get channel or stream object
+        channel_or_stream = get_stream_object(channel_id)
+
+        # ============================================================
+        # STREAM PREVIEW: Return all profiles for THIS stream only
+        # ============================================================
+        if isinstance(channel_or_stream, Stream):
+            stream = channel_or_stream
+            logger.info(f"Stream preview: Getting alternate profiles for stream {stream.id}")
+            
+            # Get all profiles for this specific stream
+            m3u_account = stream.m3u_account
+            if not m3u_account:
+                logger.warning(f"Stream {stream.id} has no M3U account")
+                return []
+            
+            if not m3u_account.is_active:
+                logger.warning(f"M3U account {m3u_account.id} is inactive")
+                return []
+            
+            # Get all active profiles
+            m3u_profiles = m3u_account.profiles.filter(is_active=True)
+            default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)
+            
+            if not default_profile:
+                logger.warning(f"M3U account {m3u_account.id} has no default profile")
+                return []
+            
+            # Order: default first, then others
+            profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]
+            
+            alternate_profiles = []
+            redis_client = RedisClient.get_client()
+            
+            for profile in profiles:
+                # Skip the currently failing profile
+                if current_profile_id and profile.id == current_profile_id:
+                    logger.debug(f"Skipping current failing profile {profile.id} for stream {stream.id}")
+                    continue
+                
+                # Check connection availability
+                if redis_client:
+                    profile_connections_key = f"profile_connections:{profile.id}"
+                    current_connections = int(redis_client.get(profile_connections_key) or 0)
+                    
+                    if profile.max_streams == 0 or current_connections < profile.max_streams:
+                        logger.debug(f"Found available profile {profile.id} for stream {stream.id}: {current_connections}/{profile.max_streams}")
+                        alternate_profiles.append({
+                            'stream_id': stream.id,
+                            'profile_id': profile.id,
+                            'name': stream.name
+                        })
+                    else:
+                        logger.debug(f"Profile {profile.id} at max connections: {current_connections}/{profile.max_streams}")
+                else:
+                    alternate_profiles.append({
+                        'stream_id': stream.id,
+                        'profile_id': profile.id,
+                        'name': stream.name
+                    })
+            
+            if alternate_profiles:
+                profile_ids = ', '.join([str(p['profile_id']) for p in alternate_profiles])
+                logger.info(f"Found {len(alternate_profiles)} alternate profiles for stream preview {stream.id}: [{profile_ids}]")
+            else:
+                logger.warning(f"No alternate profiles found for stream preview {stream.id}")
+            
+            return alternate_profiles
+
+        # ============================================================
+        # CHANNEL: Return all stream+profile combinations
+        # ============================================================
+        channel = channel_or_stream
 
         redis_client = RedisClient.get_client()
```

## Anwendung

```bash
cd /path/to/Dispatcharr
patch -p0 < stream_preview_profile_failover.patch
```

---

**Status**: ✅ Lösung bereit  
**Kompatibilität**: Funktioniert mit v0.26.0 ULTIMATE Patch  
**Test**: Stream Preview mit mehreren Profilen testen
