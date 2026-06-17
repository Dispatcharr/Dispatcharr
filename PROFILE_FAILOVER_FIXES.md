# Profile Failover Fixes for Dispatcharr v0.27.0

## Overview

This document describes the critical bug fixes applied to Dispatcharr v0.27.0 to enable **Profile Failover** functionality. These fixes were ported from v0.26.0 patches described in `README_ULTIMATE_WITH_COOLDOWN.md`.

---

## Fixed Bugs

### ✅ Bug #1: `current_profile_id` Never Loaded from Redis (CRITICAL!)

**File:** `Dispatcharr-0.27.0/apps/proxy/live_proxy/input/manager.py`

**Problem:** 
- v0.27.0 tracked `self.current_stream_id` but **NOT** `self.current_profile_id`
- Profile failover requires knowing which profile is currently in use
- Without this tracking, the system couldn't exclude the failing profile and would retry it endlessly

**Fix Applied:**
```python
# Line ~73: Added profile tracking variables
self.current_stream_id = stream_id
self.current_profile_id = None  # BUGFIX: Track current profile for failover
self.tried_combinations = set()  # Track (stream_id, profile_id) combinations
self.tried_stream_ids = set()  # Keep for backward compatibility
self.last_stream_switch_time = 0  # For adaptive health monitor
```

**Fix Applied (when stream_id provided):**
```python
# Line ~81-95: Load profile_id from Redis even when stream_id is provided
if stream_id:
    self.tried_stream_ids.add(stream_id)
    logger.info(f"Initialized stream manager for channel {buffer.channel_id} with stream ID {stream_id}")
    # BUGFIX: Also load profile_id from Redis even when stream_id is provided
    # This was the root cause of profile failover never working - profile_id was always None
    if hasattr(buffer, 'redis_client') and buffer.redis_client:
        try:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            profile_id_bytes = buffer.redis_client.hget(metadata_key, "m3u_profile")
            if profile_id_bytes:
                self.current_profile_id = int(profile_id_bytes.decode('utf-8') if isinstance(profile_id_bytes, bytes) else profile_id_bytes)
                logger.info(f"Loaded profile ID {self.current_profile_id} from Redis for channel {buffer.channel_id}")
            else:
                logger.warning(f"No profile_id found in Redis for channel {channel_id}.")
        except Exception as e:
            logger.warning(f"Error loading profile ID from Redis: {e}")
```

**Fix Applied (else branch):**
```python
# Line ~115: Also load profile_id in the else branch
# BUGFIX: Also load profile_id
profile_id_bytes = buffer.redis_client.hget(metadata_key, "m3u_profile")
if profile_id_bytes:
    self.current_profile_id = int(profile_id_bytes.decode('utf-8') if isinstance(profile_id_bytes, bytes) else profile_id_bytes)
    logger.info(f"Loaded profile ID {self.current_profile_id} from Redis for channel {buffer.channel_id}")
```

---

### ✅ Bug #2: `tried_combinations` Tracking Missing

**File:** `Dispatcharr-0.27.0/apps/proxy/live_proxy/input/manager.py`

**Problem:**
- v0.27.0 only tracked `tried_stream_ids` (which streams were tried)
- Did NOT track `tried_combinations` (which stream+profile combinations were tried)
- This is needed for the Cooldown System (future feature)

**Fix Applied:**
```python
# Line ~75: Added tried_combinations tracking
self.tried_combinations = set()  # Track (stream_id, profile_id) combinations
```

---

### ✅ Bug #3: `get_alternate_streams()` Returns Only ONE Profile per Stream (CRITICAL!)

**File:** `Dispatcharr-0.27.0/apps/proxy/live_proxy/url_utils.py`

**Problem:**
- v0.27.0 used `selected_profile = profile` + `break` logic
- This returned **only the FIRST available profile** for each stream
- Profile failover requires **ALL profiles** to be tried before moving to the next stream

**Expected Behavior:**
```
Stream 1 + Profile 1 (default)
Stream 1 + Profile 2
Stream 1 + Profile 3
Stream 2 + Profile 1 (default)  ← Only after Stream 1 exhausted
Stream 2 + Profile 2
Stream 2 + Profile 3
```

**Actual Behavior (before fix):**
```
Stream 1 + Profile 1 (default)
Stream 2 + Profile 1 (default)  ← Skipped profiles 2 & 3 of Stream 1!
Stream 3 + Profile 1 (default)
```

**Fix Applied:**

1. **Added `current_profile_id` parameter:**
```python
def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = None, current_profile_id: Optional[int] = None) -> List[dict]:
```

2. **Skip only the failing (stream_id, profile_id) combination:**
```python
# BUGFIX: Do NOT skip the current stream entirely - we may want to try different profiles!
# Only skip the specific (stream_id, profile_id) combination that failed

# Skip the current stream+profile combination that just failed
if current_stream_id and stream.id == current_stream_id and current_profile_id and profile.id == current_profile_id:
    logger.debug(f"Skipping current failing stream+profile combination: stream={current_stream_id}, profile={current_profile_id}")
    continue
```

3. **Removed `break` statement - return ALL profiles:**
```python
# BUGFIX: Try ALL profiles for this stream, not just the first available one!
for profile in profiles:
    # ... connection checks ...
    
    if profile_available_for_channel_switch(...):
        # BUGFIX: Don't break here - add ALL available profiles!
        alternate_streams.append({
            'stream_id': stream.id,
            'profile_id': profile.id,
            'name': stream.name
        })
        # DON'T break - continue to check other profiles!
```

4. **Updated logging to show stream+profile pairs:**
```python
stream_profile_pairs = ', '.join([f"({s['stream_id']},{s['profile_id']})" for s in alternate_streams])
logger.info(f"Found {len(alternate_streams)} alternate stream+profile combinations for channel {channel_id}: [{stream_profile_pairs}]")
```

---

### ✅ Bug #4: `_resolve_live_stream_url()` - No Fix Needed!

**File:** `Dispatcharr-0.27.0/apps/proxy/live_proxy/url_utils.py`

**Status:** ✅ Already correctly implemented in v0.27.0

**Implementation (lines 23-51):**
```python
def _resolve_live_stream_url(stream, m3u_account, m3u_profile):
    """
    Build the upstream URL for live playback.

    XC accounts use current transformed credentials plus provider stream_id so
    playback matches the account login (not a stale stream.url from an old sync).
    STD/M3U accounts keep using the URL stored on the stream row.
    """
    if (
        m3u_account.account_type == M3UAccount.Types.XC
        and stream.stream_id
    ):
        from apps.m3u.tasks import get_transformed_credentials

        server_url, username, password = get_transformed_credentials(
            m3u_account, m3u_profile
        )
        if server_url and username and password:
            base = server_url.rstrip("/")
            return f"{base}/live/{username}/{password}/{stream.stream_id}.ts"

    return transform_url(
        stream.url or "",
        m3u_profile.search_pattern,
        m3u_profile.replace_pattern,
    )
```

---

### ✅ Bug #5: `generate_stream_url()` Return Signature - No Fix Needed!

**File:** `Dispatcharr-0.27.0/apps/proxy/live_proxy/url_utils.py`

**Status:** ✅ Already correctly implemented in v0.27.0

**v0.26.0 Signature (old):**
```python
return (url, user_agent, transcode, profile_id)  # 4 values
```

**v0.27.0 Signature (correct):**
```python
return (url, user_agent, transcode, profile_id, slot_reserved, error_reason)  # 6 values
```

**Reason:** v0.27.0 uses the Connection Pool system (`apps/m3u/connection_pool.py`) which requires `slot_reserved` and `error_reason` in the return tuple.

---

## Summary

| Bug | File | Status | Description |
|-----|------|--------|-------------|
| #1 | `manager.py` | ✅ Fixed | Added `current_profile_id` tracking and Redis loading |
| #2 | `manager.py` | ✅ Fixed | Added `tried_combinations` set for cooldown system |
| #3 | `url_utils.py` | ✅ Fixed | `get_alternate_streams()` now returns ALL profiles per stream |
| #4 | `url_utils.py` | ✅ No Fix | `_resolve_live_stream_url()` already correct |
| #5 | `url_utils.py` | ✅ No Fix | `generate_stream_url()` return signature already correct |

---

## Testing

### Expected Log Output (After Fixes)

```
Initialized stream manager for channel ... with stream ID 708953
Loaded profile ID 340 from Redis for channel ...
Found 6 alternate stream+profile combinations for channel ...: [(708953,341), (708953,342), (708953,343), (709001,340), (709001,341), (709001,342)]
Trying stream ID 708953 with profile ID 341
```

### Profile Failover Sequence

**Scenario:** Stream 1 has 3 profiles, Stream 2 has 3 profiles

**Expected Behavior:**
```
1. Try Stream 1 + Profile 1 (default)     → Fails
2. Try Stream 1 + Profile 2               → Fails
3. Try Stream 1 + Profile 3               → Fails
4. Try Stream 2 + Profile 1 (default)     → Fails
5. Try Stream 2 + Profile 2               → Fails
6. Try Stream 2 + Profile 3               → Success!
```

**Before Fix:**
```
1. Try Stream 1 + Profile 1 (default)     → Fails
2. Try Stream 2 + Profile 1 (default)     → Skipped profiles 2 & 3 of Stream 1!
```

---

## Compatibility Notes

### v0.27.0 vs v0.26.0 Differences

1. **Connection Pool System:**
   - v0.27.0 uses `apps/m3u/connection_pool.py` for profile connection management
   - v0.26.0 used direct Redis INCR/DECR
   - **Fix preserves v0.27.0's Connection Pool logic**

2. **Return Signatures:**
   - `generate_stream_url()` returns 6 values in v0.27.0 (vs 4 in v0.26.0)
   - `channel.get_stream()` returns 4 values in v0.27.0 (vs 3 in v0.26.0)
   - **Fix keeps v0.27.0's signatures intact**

3. **Profile Availability Checks:**
   - v0.27.0 uses `profile_available_for_channel_switch()` helper
   - v0.26.0 used manual Redis key checks
   - **Fix uses v0.27.0's helper functions**

---

## Files Modified

1. **`Dispatcharr-0.27.0/apps/proxy/live_proxy/input/manager.py`**
   - Added `current_profile_id` tracking
   - Added `tried_combinations` set
   - Added profile_id loading from Redis (both branches)

2. **`Dispatcharr-0.27.0/apps/proxy/live_proxy/url_utils.py`**
   - Updated `get_alternate_streams()` signature with `current_profile_id`
   - Removed `break` statement to return ALL profiles
   - Fixed stream skip logic to only skip failing (stream_id, profile_id) combo
   - Updated logging to show stream+profile pairs

---

## Future Work

These fixes enable the **Cooldown System** to be implemented in the future:

```python
# Cooldown logic (not yet implemented)
if (stream_id, profile_id) in self.tried_combinations:
    cooldown_key = RedisKeys.stream_cooldown(self.channel_id, stream_id, profile_id)
    if self.buffer.redis_client.exists(cooldown_key):
        logger.debug(f"Skipping (stream={stream_id}, profile={profile_id}) - on cooldown")
        continue

# After failure
self.tried_combinations.add((stream_id, profile_id))
cooldown_duration = 600  # 10 minutes
self.buffer.redis_client.setex(cooldown_key, cooldown_duration, "1")
```

---

**Date:** 2025  
**Version:** Dispatcharr v0.27.0  
**Based on:** v0.26.0 ULTIMATE Patch  
**Status:** ✅ Complete
