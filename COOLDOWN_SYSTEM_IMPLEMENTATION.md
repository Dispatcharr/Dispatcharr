# Cooldown System Implementation - v0.27.0

**Status**: ✅ COMPLETE  
**Date**: 2025-01-17  
**Source**: dispatcharr_v0.26.0_cooldown_system.patch + dispatcharr_v0.26.0_ULTIMATE.patch

---

## Overview

Das Cooldown System wurde erfolgreich von v0.26.0 nach v0.27.0 portiert. Es verhindert dass fehlgeschlagene Stream+Profile Kombinationen sofort wieder probiert werden.

---

## Implementation Details

### 1. Core Changes in `manager.py`

#### Initialization (Lines 72-76)
```python
self.current_stream_id = stream_id
self.current_profile_id = None  # Track current profile for failover
self.tried_combinations = set()  # Track (stream_id, profile_id) combinations
self.tried_stream_ids = set()  # Keep for backward compatibility
self.last_stream_switch_time = 0
```

**Critical Fix**: `current_profile_id` tracking added (was always None in v0.27.0 original)

#### Profile ID Loading (Lines 80-92, 110-117)
```python
# Load profile_id from Redis when stream_id is provided
if hasattr(buffer, 'redis_client') and buffer.redis_client:
    metadata_key = RedisKeys.channel_metadata(channel_id)
    profile_id_bytes = buffer.redis_client.hget(metadata_key, "m3u_profile")
    if profile_id_bytes:
        self.current_profile_id = int(profile_id_bytes.decode('utf-8') 
                                      if isinstance(profile_id_bytes, bytes) 
                                      else profile_id_bytes)
```

**Critical Fix**: Profile ID loaded from Redis even when stream_id is provided

---

### 2. Failover Logic in `_try_next_stream()` (Lines 1933-2120)

#### Step 1: Mark Failed Combination + Set Cooldown (Lines 1945-1963)
```python
if self.current_stream_id and self.current_profile_id:
    self.tried_combinations.add((self.current_stream_id, self.current_profile_id))
    
    if ConfigHelper.stream_cooldown_enabled():
        cooldown_secs = ConfigHelper.stream_cooldown_seconds()
        cooldown_key = RedisKeys.stream_cooldown(
            self.channel_id, 
            self.current_stream_id, 
            self.current_profile_id
        )
        failed_at = time.time()
        retry_at = failed_at + cooldown_secs
        self.buffer.redis_client.setex(
            cooldown_key, 
            cooldown_secs, 
            f"{failed_at}:{retry_at}"
        )
        logger.info(f"[COOLDOWN] Set cooldown for stream {self.current_stream_id}/profile "
                   f"{self.current_profile_id} for {mins}m {secs}s")
```

**Key Features**:
- Redis `setex` with TTL (auto-expires)
- Cooldown survives channel restarts
- Format: `failed_at:retry_at` for debugging

#### Step 2: Filter Untried Combinations (Lines 1970-1974)
```python
untried_combinations = [
    s for s in alternate_streams 
    if (s['stream_id'], s['profile_id']) not in self.tried_combinations
]
```

**Critical Change**: Uses `tried_combinations` (tuples) instead of `tried_stream_ids` (integers)

**Before (WRONG)**:
```python
untried_streams = [s for s in alternate_streams if s['stream_id'] not in self.tried_stream_ids]
```
This blocked ALL profiles of a stream if one failed!

**After (CORRECT)**:
```python
untried_combinations = [s for s in alternate_streams 
                        if (s['stream_id'], s['profile_id']) not in self.tried_combinations]
```
This allows trying different profiles of the same stream!

#### Step 3: Cooldown Filter (Lines 1976-1992)
```python
if ConfigHelper.stream_cooldown_enabled():
    cooled_down = []
    for s in untried_combinations:
        cooldown_key = RedisKeys.stream_cooldown(
            self.channel_id, 
            s['stream_id'], 
            s['profile_id']
        )
        if self.buffer.redis_client.exists(cooldown_key):
            ttl = self.buffer.redis_client.ttl(cooldown_key)
            logger.debug(f"[COOLDOWN] Skipping stream {s['stream_id']}/profile "
                        f"{s['profile_id']} - blocked for {mins}m {secs}s more")
        else:
            cooled_down.append(s)
    
    skipped = len(untried_combinations) - len(cooled_down)
    if skipped > 0:
        logger.info(f"[COOLDOWN] Skipped {skipped} combinations on cooldown")
    untried_combinations = cooled_down
```

#### Step 4: Last Resort - Clear All Cooldowns (Lines 2002-2027)
```python
if not untried_combinations:
    if alternate_streams and len(self.tried_combinations) > 0:
        # LAST RESORT: Clear all cooldowns and retry everything
        if ConfigHelper.stream_cooldown_enabled():
            cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = self.buffer.redis_client.scan(
                    cursor, 
                    match=cooldown_pattern, 
                    count=100
                )
                if keys:
                    self.buffer.redis_client.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            
            if deleted > 0:
                logger.warning(f"[COOLDOWN] LAST RESORT: Cleared {deleted} cooldowns "
                              f"- retrying all combinations")
                self.tried_combinations.clear()
                untried_combinations = alternate_streams
```

**Last Resort Behavior**:
1. All combinations tried AND on cooldown
2. Delete all cooldown keys for this channel
3. Reset `tried_combinations` set
4. Retry with full list of streams

#### Step 5: Track Tried Combinations (Lines 2036-2037)
```python
# Add to tried combinations
self.tried_combinations.add((stream_id, profile_id))
```

#### Step 6: Update Profile ID (Lines 2074-2079)
```python
# Update stream ID and profile ID tracking
self.current_stream_id = stream_id
self.current_profile_id = profile_id

# Also update tried_stream_ids for backward compatibility with error messages
self.tried_stream_ids.add(stream_id)
```

**Backward Compatibility**: `tried_stream_ids` maintained for error messages only

---

## Configuration

### ConfigHelper Methods (Already Implemented in Task #6)

```python
# From apps/proxy/live_proxy/config_helper.py
ConfigHelper.stream_cooldown_enabled()    # Returns bool
ConfigHelper.stream_cooldown_seconds()    # Returns int (default: 300 = 5 min)
```

### RedisKeys Method (Already Implemented in Task #6)

```python
# From apps/proxy/live_proxy/redis_keys.py
RedisKeys.stream_cooldown(channel_id, stream_id, profile_id)
# Returns: "live:channel:{channel_id}:cooldown:{stream_id}:{profile_id}"
```

---

## Verification Checklist

### ✅ Core Functionality
- [x] `tried_combinations` set tracks (stream_id, profile_id) tuples
- [x] `current_profile_id` loaded from Redis on init
- [x] Profile ID tracked during failover
- [x] Failover filter uses `tried_combinations` (not `tried_stream_ids`)

### ✅ Cooldown System
- [x] Failed combination marked with `tried_combinations.add()`
- [x] Redis cooldown set with `setex` (auto-expires)
- [x] Cooldown filter skips combinations on cooldown
- [x] Last Resort clears all cooldowns when everything blocked

### ✅ Backward Compatibility
- [x] `tried_stream_ids` maintained for error messages
- [x] Error message format unchanged: `"All {len(tried_stream_ids)} stream options failed"`
- [x] `update_url()` still updates `tried_stream_ids`

### ✅ Logging
- [x] `[COOLDOWN]` prefix with red color (\033[31m)
- [x] Cooldown set logged with duration
- [x] Skipped combinations logged with count
- [x] Last Resort logged when triggered

---

## Testing Scenarios

### Scenario 1: Profile Failover (Single Stream, Multiple Profiles)
**Setup**: Stream 123 has Profile 1, 2, 3

**Expected Behavior**:
1. Stream 123 + Profile 1 fails → cooldown set
2. Tries Stream 123 + Profile 2 (not blocked!)
3. If fails → tries Stream 123 + Profile 3
4. Cooldown prevents immediate retry of (123, 1)

**Verification**: Logs show `(123,1)`, `(123,2)`, `(123,3)` tried

### Scenario 2: Multi-Stream Failover
**Setup**: 3 streams (123, 456, 789), each with 2 profiles

**Expected Behavior**:
1. Tries all combinations: (123,1), (123,2), (456,1), (456,2), (789,1), (789,2)
2. Each failed combination gets cooldown
3. Cooldown filter blocks already-tried combinations
4. Different streams with same profile work independently

### Scenario 3: Cooldown Expiry
**Setup**: Cooldown duration = 5 minutes

**Expected Behavior**:
1. Combination fails → cooldown set with 5 min TTL
2. After 5 minutes → Redis key auto-expires
3. Combination available again in next failover attempt

### Scenario 4: Last Resort
**Setup**: All combinations tried AND on cooldown

**Expected Behavior**:
1. No untried combinations available
2. All cooldowns cleared via Redis SCAN + DELETE
3. `tried_combinations` set cleared
4. Retry all combinations from scratch
5. Log shows: `"LAST RESORT: Cleared {N} cooldowns"`

---

## Comparison: v0.26.0 vs v0.27.0

| Feature | v0.26.0 | v0.27.0 |
|---------|---------|---------|
| **Profile Tracking** | ✅ Yes | ✅ Yes (after fix) |
| **tried_combinations** | ✅ Set of tuples | ✅ Set of tuples |
| **Cooldown Redis Keys** | ✅ TTL-based | ✅ TTL-based |
| **Cooldown Filter** | ✅ Implemented | ✅ Implemented |
| **Last Resort** | ✅ Clear all cooldowns | ✅ Clear all cooldowns |
| **Architecture** | Simple Failover | Connection Pool System |
| **Implementation** | ~150 lines changed | ~187 lines changed |

**Result**: ✅ Feature parity achieved!

---

## Known Differences from v0.26.0

### 1. Connection Pool System
v0.27.0 uses a different connection management system. The cooldown implementation works within this new architecture.

### 2. get_alternate_streams() Signature
```python
# v0.26.0
get_alternate_streams(channel_id, stream_id, profile_id)

# v0.27.0 (same)
get_alternate_streams(channel_id, stream_id, current_profile_id)
```
✅ Compatible

### 3. Redis Keys Pattern
```python
# Both versions
f"live:channel:{channel_id}:cooldown:{stream_id}:{profile_id}"
```
✅ Identical

---

## Files Modified

1. **apps/proxy/live_proxy/input/manager.py**
   - Lines 72-117: Initialization + Profile Loading
   - Lines 1933-2120: `_try_next_stream()` complete rewrite

**Total Changes**: ~187 lines modified/added

---

## Dependencies

### Already Implemented (from previous tasks)
✅ `RedisKeys.stream_cooldown()` method  
✅ `ConfigHelper.stream_cooldown_enabled()` method  
✅ `ConfigHelper.stream_cooldown_seconds()` method  
✅ `get_alternate_streams()` returns profile_id  
✅ Profile Failover Fix (Bug #1-3)  

### Database Settings (from CoreSettings)
```python
stream_cooldown_enabled = models.BooleanField(default=True)
stream_cooldown_minutes = models.IntegerField(default=5)
```

---

## Performance Considerations

### Redis Operations
- **setex**: O(1) - Set cooldown key with TTL
- **exists**: O(1) - Check if combination on cooldown
- **ttl**: O(1) - Get remaining cooldown time
- **scan**: O(N) - Last Resort only (rare operation)
- **delete**: O(N) - Last Resort only (rare operation)

### Memory Impact
- `tried_combinations`: O(N) where N = number of (stream_id, profile_id) combinations tried
- Typical: 10-50 combinations per channel
- Redis cooldown keys: Auto-expire via TTL (no memory leak)

---

## Error Handling

### Safe Fallbacks
1. If Redis unavailable → cooldown disabled, failover continues
2. If profile_id not in Redis → logs warning, uses None
3. If cooldown_secs invalid → uses default (300 seconds)
4. If SCAN fails → Last Resort aborted, returns False

### Logging Levels
- **INFO**: Cooldown set, combinations skipped
- **WARNING**: No untried combinations, Last Resort triggered
- **DEBUG**: Individual combinations blocked
- **ERROR**: Redis errors, failover errors

---

## Conclusion

✅ **Cooldown System erfolgreich implementiert!**

**Benefits**:
1. ✅ Profile-aware Failover (Stream 123 + Profile 1 ≠ Stream 123 + Profile 2)
2. ✅ Cooldown prevents immediate retry of failed combinations
3. ✅ TTL-based auto-expiry (no manual cleanup needed)
4. ✅ Last Resort prevents infinite blocking
5. ✅ Backward compatible with error messages
6. ✅ Works with v0.27.0 Connection Pool System

**Next Steps**:
- Test in production environment
- Monitor cooldown effectiveness
- Adjust default cooldown duration if needed (currently 5 min)
- Consider frontend UI for cooldown settings
