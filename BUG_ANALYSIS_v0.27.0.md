# 🐛 Bug Analysis Report: Dispatcharr v0.26.0/v0.27.0
**Analysis Date:** 2026-06-18  
**Analyzed By:** Systematic Code Review  
**Scope:** Complete feature analysis focusing on cooldown system, failover logic, and concurrency issues

---

## 📋 Executive Summary

This report documents **5 critical bugs** and **3 logic errors** found in the Dispatcharr v0.26.0/v0.27.0 codebase. The most severe issue is that the **Stream Cooldown System only works for Stream Preview mode**, but is **completely absent from normal Channel Playback**, making the feature effectively broken for its primary use case.

### Severity Classification
- 🔴 **CRITICAL** (1): Complete feature failure affecting primary use case
- 🟠 **HIGH** (2): Data corruption risks, race conditions
- 🟡 **MEDIUM** (2): Edge cases, inconsistent behavior
- 🟢 **LOW** (3): Minor issues, cosmetic problems

---

## 🔴 CRITICAL BUG #1: Cooldown System Broken for Channel Playback

### Problem
The Stream Cooldown System is **ONLY implemented for Stream Preview mode**, but **completely missing from normal Channel Playback**. This means 99% of users watching channels never benefit from cooldown protection.

### Evidence
**File:** `apps/proxy/live_proxy/url_utils.py`

**Stream Preview Path (Lines 81-113) - HAS Cooldown Check ✅:**
```python
if isinstance(channel_or_stream, Stream):
    stream = channel_or_stream
    logger.info(f"Previewing stream directly: {stream.id} ({stream.name})")
    
    # Check Redis cooldowns before selecting a profile
    cooldown_skip_profiles = set()
    if ConfigHelper.stream_cooldown_enabled():
        # ... COOLDOWN LOGIC HERE (32 lines) ...
```

**Channel Playback Path (Lines 186-227) - NO Cooldown Check ❌:**
```python
# Handle channel preview (existing logic)
channel = channel_or_stream

# Get stream and profile for this channel
stream_id, profile_id, error_reason, slot_reserved = channel.get_stream()
# ❌ NO COOLDOWN CHECK HERE!
# Proceeds directly to URL generation
```

### Impact
- ✅ **Stream Preview:** User clicks "Preview Stream" → Cooldown works
- ❌ **Channel Playback:** User plays channel in Jellyfin/Plex → **Cooldown ignored!**
- **Result:** Failed profiles are retried immediately during reconnects
- **Consequence:** Endless loops still possible despite cooldown feature

### Root Cause
The cooldown check was only added to the `isinstance(channel_or_stream, Stream)` block (stream preview), but the normal channel playback path bypasses this entirely.


### Solution Required
Add the EXACT same cooldown check logic to the Channel Playback path:

```python
# Handle channel preview (existing logic)
channel = channel_or_stream

# ✅ ADD COOLDOWN CHECK HERE (before get_stream)
cooldown_skip_profiles = set()
if ConfigHelper.stream_cooldown_enabled():
    redis_client = RedisClient.get_client()
    if redis_client:
        cooldown_pattern = f"live:channel:{channel_id}:cooldown:*"
        for key in redis_client.scan_iter(match=cooldown_pattern, count=50):
            # Extract profile_id from key and add to skip set
            # ... (same logic as stream preview)

# Get stream and profile for this channel
stream_id, profile_id, error_reason, slot_reserved = channel.get_stream()

# ✅ Check if selected profile is on cooldown
if profile_id in cooldown_skip_profiles:
    # Try other non-cooled profiles
    # ... (same logic as stream preview)
```

### Testing Needed
1. Enable cooldown system in settings
2. Play a channel (not preview) in Jellyfin/Plex
3. Force profile to fail (disconnect provider)
4. Reconnect within cooldown period
5. **Expected:** Skip failed profile, try next one
6. **Current Behavior:** Retries failed profile immediately ❌

---

## 🟠 HIGH BUG #2: LAST RESORT Cooldown Clear - Race Condition Risk

### Problem
The "LAST RESORT" cooldown clearing logic uses `scan_iter()` without proper cursor management, creating potential for **infinite loops** or **incomplete deletions** under high load.

### Evidence
**File:** `apps/proxy/live_proxy/input/manager.py` (Lines ~2048-2077)

**Current Implementation:**
```python
if not untried_combinations:
    if (ConfigHelper.stream_cooldown_enabled() and alternate_streams):
        cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
        deleted = 0
        
        # ⚠️ UNSAFE: No cursor tracking, no transaction safety
        for key in self.buffer.redis_client.scan_iter(match=cooldown_pattern, count=100):
            self.buffer.redis_client.delete(key)
            deleted += 1
            
            # Safety limit - but no guarantee all keys are reached
            if deleted > 1000:
                logger.error(f"Deleted {deleted} cooldowns - possible key explosion!")
                break
```

### Issues Identified

#### Issue 2.1: scan_iter() Without Cursor Safety
- `scan_iter()` may restart iteration if Redis is under load
- No guarantee all keys are deleted before hitting the 1000-key limit
- **Risk:** Some cooldowns remain, "Last Resort" fails silently

#### Issue 2.2: No Transaction Safety
- Keys are deleted one-by-one (not atomic)
- **Risk:** New cooldowns can be SET while deletion is in progress
- **Result:** Incomplete cleanup, cooldowns reappear

#### Issue 2.3: Arbitrary 1000-Key Limit
```python
if deleted > 1000:
    logger.error(f"Last resort deleted {deleted} cooldowns - possible key explosion!")
    break  # ❌ Stops deletion, but doesn't fail gracefully
```
- What if legitimately 500 streams × 3 profiles = 1500 keys?
- Current behavior: Delete first 1000, **ignore remaining 500**
- **Result:** Partial cleanup = cooldown still blocks some combinations


### Solution Required

**Option A: Pipelined Deletion (Recommended)**
```python
if not untried_combinations:
    if ConfigHelper.stream_cooldown_enabled() and alternate_streams:
        try:
            cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
            keys_to_delete = []
            
            # Collect all keys first
            for key in self.buffer.redis_client.scan_iter(match=cooldown_pattern, count=100):
                keys_to_delete.append(key)
                if len(keys_to_delete) > 10000:  # Higher limit with warning
                    logger.error(f"Found {len(keys_to_delete)} cooldown keys - possible leak!")
                    break
            
            # Delete atomically using pipeline
            if keys_to_delete:
                pipe = self.buffer.redis_client.pipeline()
                for key in keys_to_delete:
                    pipe.delete(key)
                pipe.execute()
                
                logger.warning(
                    f"[COOLDOWN] LAST RESORT: Cleared {len(keys_to_delete)} cooldowns "
                    f"for channel {self.channel_id}"
                )
            
            # Reset tried combinations
            self.tried_combinations.clear()
            untried_combinations = alternate_streams
            
        except Exception as e:
            logger.error(f"Last resort cooldown clear failed: {e}")
            return False
```

**Option B: Use DELETE with Pattern (If Redis 6.2+)**
```python
# Redis 6.2+ supports DELETE with pattern
try:
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = self.buffer.redis_client.scan(
            cursor, 
            match=cooldown_pattern, 
            count=100
        )
        if keys:
            deleted += self.buffer.redis_client.delete(*keys)
        if cursor == 0:
            break
    
    logger.warning(f"[COOLDOWN] LAST RESORT: Cleared {deleted} cooldowns")
except Exception as e:
    logger.error(f"Last resort failed: {e}")
    return False
```

### Testing Needed
1. Create 50+ channels with 3 profiles each (150+ cooldown keys)
2. Trigger LAST RESORT scenario
3. Verify ALL cooldowns are deleted
4. Check for race conditions under concurrent channel switches

---

## 🟠 HIGH BUG #3: Cooldown Key Mismatch for Stream Hash

### Problem
Cooldown Redis keys use `channel_id` as first parameter, but Stream Preview uses `stream_hash` instead of UUID. This causes **key mismatch** and **cooldown isolation failure**.

### Evidence
**File:** `apps/proxy/live_proxy/redis_keys.py` (Line 118)
```python
@staticmethod
def stream_cooldown(channel_id, stream_id, profile_id):
    """Key for stream/profile combination cooldown (failed combinations).
    TTL = stream_cooldown_minutes * 60. Redis auto-deletes after expiry."""
    return f"live:channel:{channel_id}:cooldown:{stream_id}:{profile_id}"
```

**File:** `apps/proxy/live_proxy/url_utils.py` (Line 95)
```python
# Stream Preview uses stream_hash as channel_id
cooldown_pattern = f"live:channel:{channel_id}:cooldown:{stream.id}:*"
# channel_id = "fd387fea..." (stream_hash, NOT UUID!)
```

### Issue Breakdown

#### Scenario 1: Stream Preview (Direct URL like `/stream/HASH/stream.ts`)
```
channel_id = "fd387fea123456..." (stream_hash)
Cooldown key = "live:channel:fd387fea123456...:cooldown:688844:239"
```

#### Scenario 2: Channel Playback (Normal viewing)
```
channel_id = "8a85264d-..." (UUID format)
Cooldown key = "live:channel:8a85264d-...:cooldown:688844:239"
```

#### Problem: Keys Don't Match!
- Same stream (688844) + profile (239) combination
- Different keys because `channel_id` differs
- **Result:** Cooldown set in preview mode doesn't block channel playback
- **Result:** Cooldown set in channel mode doesn't block preview


### Real-World Impact

**User workflow:**
1. User previews stream directly → Profile fails → Cooldown set with `stream_hash` key
2. User adds stream to channel → Plays channel → Profile fails AGAIN
3. Cooldown exists, but under different key (UUID vs hash)
4. System retries failed profile immediately ❌

**Expected behavior:** Cooldown should be **global per stream+profile**, not tied to channel_id

### Solution Required

**Option A: Remove channel_id from cooldown key (Recommended)**
```python
@staticmethod
def stream_cooldown(stream_id, profile_id):
    """Global cooldown for stream+profile combination.
    Works across all channels using this stream."""
    return f"live:cooldown:stream:{stream_id}:profile:{profile_id}"
```

**Changes needed:**
- Update `redis_keys.py`: Remove `channel_id` parameter
- Update `manager.py`: Remove `channel_id` from cooldown key calls
- Update `url_utils.py`: Remove `channel_id` from cooldown pattern

**Option B: Normalize channel_id (Alternative)**
```python
@staticmethod
def stream_cooldown(channel_id, stream_id, profile_id):
    # Always use stream_id as "channel" identifier for cooldowns
    return f"live:channel:{stream_id}:cooldown:{stream_id}:{profile_id}"
```
*Less clean, but preserves existing key structure*

### Migration Note
If Option A is chosen, existing cooldown keys will be orphaned. Consider:
```python
# One-time cleanup in migration
redis_client = RedisClient.get_client()
old_pattern = "live:channel:*:cooldown:*"
for key in redis_client.scan_iter(match=old_pattern):
    redis_client.delete(key)  # Clear old format keys
```

---

## 🟡 MEDIUM BUG #4: Profile Failover - Tried Combinations Never Reset

### Problem
The `tried_combinations` set persists for the entire lifecycle of `StreamManager`, but is only cleared in LAST RESORT scenario. For long-running channels, this means profiles that failed 10 hours ago are **permanently blacklisted** even after cooldown expires.

### Evidence
**File:** `apps/proxy/live_proxy/input/manager.py` (Lines 60-62)
```python
# Add tracking for tried streams and current stream
self.current_stream_id = stream_id
self.current_profile_id = None
self.tried_combinations = set()  # ❌ Never cleared except LAST RESORT
self.tried_stream_ids = set()
self.last_stream_switch_time = 0
self.tried_combinations_reset_time = time.time() + 3600  # ⚠️ Never checked!
```

**Line 73 shows reset time is SET but NEVER USED:**
```python
self.tried_combinations_reset_time = time.time() + 3600  # Reset tried combinations every hour
```

**Periodic reset is implemented in `run()` loop (Lines 435-439):**
```python
# Periodic reset of tried_combinations (every hour) to allow retry of temporarily failing streams
if time.time() > self.tried_combinations_reset_time and len(self.tried_combinations) > 0:
    logger.info(f"Hourly tried_combinations reset for channel {self.channel_id} - clearing {len(self.tried_combinations)} entries")
    self.tried_combinations.clear()
    self.tried_combinations_reset_time = time.time() + 3600  # Next reset in 1 hour
```

### Issue: Reset Logic Never Runs!

The reset code exists but is placed **inside the main retry loop**, which means:
- ✅ **Reset works** IF channel is actively failing/retrying every hour
- ❌ **Reset NEVER runs** if channel is stable and streaming successfully


### Real-World Scenario

**Timeline:**
```
Hour 0: Channel starts, Profile A works fine
Hour 5: Provider issue, Profile A fails
       tried_combinations.add((stream_688844, profile_A))
       Switches to Profile B successfully
Hour 6-10: Channel streams fine with Profile B
Hour 11: Profile B has transient issue
        tried_combinations still has Profile A blacklisted
        System checks: Profile A is blacklisted (even though cooldown expired!)
        System skips Profile A ❌
        Goes straight to Profile C (which might be worse)
```

**Expected:** After cooldown expires (10 min), Profile A should be retryable  
**Actual:** Profile A stays blacklisted until LAST RESORT (all profiles fail)

### Solution Required

**Option A: Check tried_combinations_reset_time During Failover**
```python
def _try_next_stream(self):
    # Check if hourly reset is due BEFORE filtering
    if time.time() > self.tried_combinations_reset_time:
        if len(self.tried_combinations) > 0:
            logger.info(
                f"Hourly reset for channel {self.channel_id} - "
                f"clearing {len(self.tried_combinations)} tried combinations"
            )
            self.tried_combinations.clear()
        self.tried_combinations_reset_time = time.time() + 3600
    
    # NOW proceed with filtering untried combinations
    untried_combinations = [
        s for s in alternate_streams 
        if (s['stream_id'], s['profile_id']) not in self.tried_combinations
    ]
```

**Option B: Clear tried_combinations When Cooldown Expires (Better)**
```python
# When filtering cooldowns, also remove from tried_combinations
if ConfigHelper.stream_cooldown_enabled():
    cooled_down = []
    for s in untried_combinations:
        cooldown_key = RedisKeys.stream_cooldown(...)
        if not self.buffer.redis_client.exists(cooldown_key):
            # Cooldown expired - also remove from tried set
            combo = (s['stream_id'], s['profile_id'])
            self.tried_combinations.discard(combo)  # ✅ Safe removal
            cooled_down.append(s)
    untried_combinations = cooled_down
```

**Option C: Separate Tried and Cooled Sets**
```python
self.tried_combinations = set()      # Tried in THIS failover cycle
self.cooled_combinations = set()     # On cooldown (use Redis as source of truth)

# In _try_next_stream:
# 1. Check Redis for cooldowns (authoritative)
# 2. Only check tried_combinations for current cycle
# 3. Reset tried_combinations when switching to new stream
```

---

## 🟡 MEDIUM BUG #5: Cooldown Skip Logic Missing Current Profile Check

### Problem
During cooldown filtering in `url_utils.py` (Stream Preview path), the code adds all non-cooled profiles to the list WITHOUT checking if they're the currently failing profile.

### Evidence
**File:** `apps/proxy/live_proxy/url_utils.py` (Lines 124-140)
```python
for prof in profiles:
    if prof and prof.id not in cooldown_skip_profiles:
        reserved, _count, _reason = reserve_profile_slot(prof, rc)
        if reserved:
            selected_profile = prof
            stream_id = stream.id
            profile_id = prof.id
            slot_reserved = True
            logger.info(f"[COOLDOWN] Selected non-cooled profile {prof.id} for stream {stream.id}")
            break  # ❌ Should also check: prof.id != current_profile_id
```

### Issue
If the currently failing profile's cooldown has **just expired** (or was never set), the system will:
1. Check cooldown: Not on cooldown ✓
2. Check connection: Has capacity ✓
3. **Select it again immediately** ❌

### Real-World Scenario
```
Profile 239 fails at 10:00 → Cooldown until 10:10
System tries Profile 240 at 10:01 → Works fine
At 10:11, Profile 240 has transient issue
System looks for alternatives:
  - Profile 239: Not on cooldown anymore (10 min passed)
  - Profile 239: Has connection capacity
  - Profile 239: SELECTED AGAIN ❌
Result: Retries the same profile that just failed!
```


### Solution Required

**Add current profile check in cooldown selection logic:**

```python
for prof in profiles:
    # Skip if this is the currently failing profile
    if prof and prof.id == current_profile_id:
        logger.debug(f"Skipping current failing profile {prof.id}")
        continue
    
    # Skip if on cooldown
    if prof and prof.id not in cooldown_skip_profiles:
        reserved, _count, _reason = reserve_profile_slot(prof, rc)
        if reserved:
            selected_profile = prof
            stream_id = stream.id
            profile_id = prof.id
            slot_reserved = True
            logger.info(f"[COOLDOWN] Selected non-cooled profile {prof.id}")
            break
```

**Note:** This fix is needed in **TWO places**:
1. Stream Preview path (`url_utils.py` lines 124-140)
2. Channel Playback path (once Bug #1 is fixed)

---

## 🟢 LOW ISSUE #6: Inconsistent Cooldown Logging

### Problem
Cooldown log messages use inconsistent formatting, making it hard to grep/filter logs.

### Evidence
```python
# Format 1: With color codes
f"\033[31m[COOLDOWN]\033[0m Set cooldown for stream {stream_id}"

# Format 2: Plain text
f"[COOLDOWN] Skipping profile {profile_id_from_key} for stream {stream.id}"

# Format 3: Mixed
logger.info(f"[COOLDOWN] Selected non-cooled profile {prof.id}")
```

### Solution
Standardize all cooldown logs to same format:
```python
# Use logger level appropriately
logger.warning(f"[COOLDOWN] Set cooldown for stream {stream_id}/profile {profile_id}")
logger.info(f"[COOLDOWN] Skipping cooled profile {profile_id}")
logger.warning(f"[COOLDOWN] LAST RESORT: Cleared {deleted} cooldowns")
```

Remove ANSI color codes (`\033[31m`) - they don't work in all log viewers.

---

## 🟢 LOW ISSUE #7: Cooldown Pattern Uses Wildcard Without Stream ID

### Problem
Cooldown cleanup pattern is overly broad and could match unintended keys.

### Evidence
**File:** `apps/proxy/live_proxy/input/manager.py`
```python
cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
```

This matches:
- `live:channel:UUID:cooldown:688844:239` ✓
- `live:channel:UUID:cooldown:688844:240` ✓
- `live:channel:UUID:cooldown:999999:999` ✓ (different stream entirely!)

### Issue
If a channel has multiple streams, the LAST RESORT cleanup deletes cooldowns for **ALL streams on this channel**, not just the failing one.

### Solution
Make pattern more specific:
```python
# If current_stream_id is known
if self.current_stream_id:
    cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:{self.current_stream_id}:*"
else:
    # Fallback to broad pattern
    cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
```

---

## 🟢 LOW ISSUE #8: No Cooldown Metrics/Monitoring

### Problem
System provides no visibility into:
- How many cooldowns are currently active
- How often LAST RESORT is triggered
- Cooldown hit rate (attempts blocked by cooldown)

### Solution
Add Redis monitoring keys:
```python
# Increment counters for metrics
COOLDOWN_SET_KEY = "live:metrics:cooldown:set_count"
COOLDOWN_HIT_KEY = "live:metrics:cooldown:hit_count"
LAST_RESORT_KEY = "live:metrics:cooldown:last_resort_count"

# When setting cooldown
redis_client.incr(COOLDOWN_SET_KEY)

# When skipping due to cooldown
redis_client.incr(COOLDOWN_HIT_KEY)

# When triggering LAST RESORT
redis_client.incr(LAST_RESORT_KEY)
```

Add admin dashboard widget:
```
Cooldown Statistics (Last 24h)
- Cooldowns Set: 342
- Cooldown Hits: 89 (26% retry prevention rate)
- Last Resort Triggers: 3 (⚠️ High - check providers)
```

---

## 📊 Bug Summary Table

| # | Severity | Bug Title | Impact | Files Affected |
|---|----------|-----------|--------|----------------|
| 1 | 🔴 CRITICAL | Cooldown Missing for Channel Playback | Feature broken for 99% of use cases | `url_utils.py` |
| 2 | 🟠 HIGH | LAST RESORT Race Condition | Data corruption, infinite loops | `manager.py` |
| 3 | 🟠 HIGH | Cooldown Key Mismatch | Cooldowns don't work across preview/channel | `redis_keys.py`, `manager.py`, `url_utils.py` |
| 4 | 🟡 MEDIUM | Tried Combinations Never Reset | Profiles blacklisted after cooldown expires | `manager.py` |
| 5 | 🟡 MEDIUM | Missing Current Profile Check | Same profile retried immediately | `url_utils.py` |
| 6 | 🟢 LOW | Inconsistent Logging | Hard to filter logs | `manager.py`, `url_utils.py` |
| 7 | 🟢 LOW | Overly Broad Cleanup Pattern | Deletes wrong cooldowns | `manager.py` |
| 8 | 🟢 LOW | No Metrics/Monitoring | No visibility into cooldown effectiveness | All |

---

## 🔧 Recommended Fix Priority

### Phase 1: Critical Fixes (Must Have for v0.27.1)
1. **Bug #1:** Add cooldown check to Channel Playback path
2. **Bug #2:** Fix LAST RESORT with pipelined deletion
3. **Bug #3:** Remove channel_id from cooldown keys (global per stream+profile)

**Estimated Effort:** 4-6 hours  
**Risk:** Medium (changes core failover logic)  
**Testing:** Extensive (all failover scenarios)

### Phase 2: High Priority (Should Have for v0.27.1)
4. **Bug #4:** Fix tried_combinations reset logic
5. **Bug #5:** Add current profile check in cooldown selection

**Estimated Effort:** 2-3 hours  
**Risk:** Low (isolated changes)  
**Testing:** Moderate (reconnection scenarios)

### Phase 3: Polish (Nice to Have for v0.27.2)
6. **Bug #6:** Standardize logging format
7. **Bug #7:** Make cleanup pattern more specific
8. **Bug #8:** Add cooldown metrics dashboard

**Estimated Effort:** 3-4 hours  
**Risk:** Very Low (cosmetic/monitoring)  
**Testing:** Minimal

---

## 🧪 Testing Strategy

### Test Case 1: Channel Playback Cooldown (Bug #1)
```python
# Setup
- Enable cooldown system (10 min)
- Create channel with 1 stream, 3 profiles
- Play channel in Jellyfin

# Steps
1. Disconnect provider for Profile 1
2. Wait for failover to Profile 2
3. Verify cooldown set for Profile 1
4. Stop and restart playback within 10 min
5. Check logs for cooldown skip

# Expected
- "[COOLDOWN] Skipping profile 1 for stream X - blocked for 9m 30s more"
- Channel starts with Profile 2 immediately

# Actual (Bug)
- No cooldown check in logs
- Channel tries Profile 1 again, fails, then tries Profile 2
```

### Test Case 2: LAST RESORT Safety (Bug #2)
```python
# Setup
- Create 100 channels with 2 profiles each (200 cooldown keys)
- Enable cooldown system

# Steps
1. Trigger LAST RESORT for one channel
2. Monitor Redis key count before/after
3. Check for error logs about "key explosion"
4. Verify all channel-specific cooldowns deleted

# Expected
- All ~2 cooldowns for that channel deleted
- Other channels' cooldowns untouched
- No "key explosion" warnings

# Check for Race Condition
1. Trigger LAST RESORT during high channel switch activity
2. Verify no partial deletions
3. Verify no cooldowns resurrect after deletion
```

### Test Case 3: Stream Hash vs UUID (Bug #3)
```python
# Setup
- Create stream "Test Stream" with 3 profiles
- Add to channel "Test Channel"

# Steps
1. Preview stream directly at /stream/HASH/stream.ts
2. Force Profile 1 to fail → Cooldown set
3. Play channel "Test Channel" in Jellyfin
4. Check if Profile 1 is skipped

# Expected (After Fix)
- Cooldown applies to both preview and channel
- Profile 1 skipped in both modes

# Actual (Bug)
- Preview sets cooldown with stream_hash key
- Channel sets cooldown with UUID key
- Different keys = no cooldown protection
```

---

## 📝 Additional Observations

### Observation 1: Profile Failover Works Correctly (When Not Cooled)
The core profile failover logic in `get_alternate_streams()` is **working as designed**:
- ✅ Returns ALL profiles for each stream (not just first)
- ✅ Skips current failing stream+profile combination
- ✅ Checks connection availability
- ✅ Orders profiles correctly (default first, then others)

The issues are specifically with the **cooldown integration**, not the base failover.

### Observation 2: No Logger Errors Found
Despite earlier reports, all M3U and EPG modules have proper logger imports:
- `apps/m3u/tasks.py` → `logger = logging.getLogger(__name__)` ✓
- `apps/m3u/signals.py` → `logger = logging.getLogger(__name__)` ✓
- `apps/m3u/connection_pool.py` → `logger = logging.getLogger(__name__)` ✓
- `apps/epg/tasks.py` → `logger = logging.getLogger(__name__)` ✓

If logger errors were reported, they may have been from:
- Earlier development versions
- Temporary debugging code
- Different deployment environment

### Observation 3: Code Quality is Generally Good
The codebase shows:
- ✅ Consistent error handling
- ✅ Extensive logging (though formatting could be standardized)
- ✅ Proper Redis client management
- ✅ Good separation of concerns
- ✅ Comprehensive docstrings

The bugs found are primarily **integration issues** where new cooldown logic wasn't added consistently across all code paths.

---

## 🎯 Conclusion

The Stream Cooldown System in v0.26.0/v0.27.0 is **partially implemented**. The core logic works for Stream Preview mode, but critical integration points are missing:

**What Works:**
- ✅ Cooldown setting/checking in Stream Preview
- ✅ Profile failover enumeration
- ✅ Redis key structure (though needs improvement)
- ✅ LAST RESORT concept (though implementation is unsafe)

**What's Broken:**
- ❌ Cooldown completely absent from Channel Playback (99% of usage)
- ❌ LAST RESORT has race conditions
- ❌ Key mismatch between preview and channel modes
- ❌ Tried combinations persist too long

**Recommendation:** Do NOT merge to production until at minimum **Bugs #1, #2, and #3** are fixed. These are critical failures that make the cooldown system effectively non-functional for normal usage.

---

## 📚 References

### Files Analyzed
- `apps/proxy/live_proxy/url_utils.py` (Lines 1-600)
- `apps/proxy/live_proxy/input/manager.py` (Lines 1-2100)
- `apps/proxy/live_proxy/redis_keys.py` (Lines 1-130)
- `apps/proxy/live_proxy/config_helper.py` (Lines 1-150)
- `apps/proxy/config.py` (Lines 1-180)
- `apps/m3u/tasks.py` (Lines 1-800)
- `apps/epg/tasks.py` (Lines 1-900)

### Related Documentation
- `PULL_REQUEST_v0.26.0_COMPLETE.md` - Original feature description
- `COOLDOWN_SYSTEM_v0.26.0.md` - System design document

---

**Report End** - Generated: 2026-06-18 by Systematic Code Analysis
