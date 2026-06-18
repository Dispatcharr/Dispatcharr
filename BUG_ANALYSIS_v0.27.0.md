# Bug Analysis Report - Dispatcharr v0.27.0
## Critical and High-Priority Bugs Identified

**Analysis Date**: 2026-06-18  
**Scope**: Profile failover, stream cooldown, HTTP proxy, buffer timeout failover  
**Status**: 🔴 8 Critical/High Bugs Found

---

## Executive Summary

Analyzed all implemented features in v0.26.0 and v0.27.0 for logic errors, race conditions, and bugs.
Found **8 significant issues** requiring immediate attention:

- **3 Critical** - Can cause system failures or infinite loops
- **3 High** - Race conditions and resource leaks
- **2 Medium** - Error handling gaps

---

## 🔴 CRITICAL BUG #1: Last Resort Doesn't Clear tried_combinations

**File**: `apps/proxy/live_proxy/input/manager.py`  
**Lines**: ~2130-2150 (Last Resort section in `_try_next_stream()`)

### Problem

The Last Resort logic clears Redis cooldown keys but **DOES NOT clear `self.tried_combinations` set**.
This means after Last Resort triggers, the system still thinks all combinations have been tried!

### Code Evidence
```python
# Last Resort clears Redis cooldowns
if deleted > 0:
    logger.warning("LAST RESORT: Cleared {deleted} cooldowns...")
    # ❌ BUG: Missing tried_combinations.clear() here!
    # self.tried_combinations.clear()  # THIS LINE IS MISSING!
    untried_combinations = alternate_streams  # Uses full list
```

### Impact
- **Infinite loops still possible** - the exact problem cooldown was supposed to fix
- After Last Resort, filtering logic at line ~2050 still excludes "tried" combinations
- System clears cooldowns but then immediately skips all profiles anyway
- Cooldown system becomes completely ineffective

### Reproduction
1. All profiles fail → cooldowns set + tried_combinations filled
2. Last Resort clears Redis cooldowns
3. `untried_combinations = alternate_streams` (full list restored)
4. Loop starts at line ~2094: `for next_stream in untried_combinations:`
5. **BUG**: Line ~2099 immediately adds to tried_combinations: `self.tried_combinations.add((stream_id, profile_id))`
6. Next iteration → tried_combinations is full again → Last Resort triggers again → LOOP!

### Fix Required
```python
if deleted > 0:
    logger.warning("LAST RESORT: Cleared cooldowns...")
    self.tried_combinations.clear()  # ← ADD THIS LINE!
    untried_combinations = alternate_streams
```

---

## 🔴 CRITICAL BUG #2: Health Monitor Race Condition

**File**: `apps/proxy/live_proxy/input/manager.py`  
**Lines**: ~1470-1530 (`_monitor_health()` method)

### Problem
Health monitor sets `needs_reconnect` and `needs_stream_switch` flags, but main `run()` loop checks them
**without thread synchronization**. Multiple greenlets can read/write these flags simultaneously.


### Code Evidence
```python
# _monitor_health() greenlet:
if not self.needs_reconnect:
    self.needs_reconnect = True  # ← WRITE (no lock)
    self.last_health_action_time = now

# run() greenlet (main loop):
if self.needs_reconnect:  # ← READ (no lock)
    self._attempt_reconnect()
    self.needs_reconnect = False  # ← WRITE (no lock)
```

### Impact
- **Race condition**: Health monitor sets flag → main loop reads old value → flag not processed
- **Double execution**: Both greenlets might trigger reconnect/failover simultaneously
- **Lost updates**: Flag changes can be overwritten
- **Unpredictable behavior**: Depends on gevent scheduling

### Scenarios
1. Health monitor sets `needs_reconnect = True`
2. Before main loop reads it, health monitor detects health restored
3. Health monitor sets `needs_reconnect = False` (line ~1515)
4. Main loop never processes reconnect (missed signal)

### Fix Required
Use gevent-safe `threading.Event` or `gevent.event.Event`:
```python
# In __init__:
self.needs_reconnect = gevent.event.Event()
self.needs_stream_switch = gevent.event.Event()

# Health monitor:
self.needs_reconnect.set()

# Main loop:
if self.needs_reconnect.is_set():
    self._attempt_reconnect()
    self.needs_reconnect.clear()
```

---

## 🔴 CRITICAL BUG #3: FFmpeg Proxy Injection Fails

**File**: `core/models.py`  
**Lines**: ~143-148 (`build_command()` in StreamProfile)

### Problem
Automatic `-http_proxy` injection for ffmpeg fails when the `-i` flag is **missing** from parameters.
The code has `try/except ValueError` but then does **nothing** (empty `pass` block).

### Code Evidence
```python
if proxy and self.command.lower() == 'ffmpeg' and '{proxy}' not in self.parameters:
    try:
        i_index = cmd.index('-i')
        cmd.insert(i_index, proxy)
        cmd.insert(i_index, '-http_proxy')
    except ValueError:
        # ❌ BUG: No -i found, but proxy is NOT injected anywhere else!
        pass  # Kein -i gefunden, füge am Ende hinzu
```

### Impact
- **Proxy completely ignored** for ffmpeg commands without `-i` flag
- **Streams bypass proxy** unexpectedly
- **Silent failure** - no error, no warning, proxy just doesn't work
- User thinks proxy is configured but it's not being used

### Affected Commands
- Custom ffmpeg commands that read from stdin instead of `-i`
- ffmpeg profiles using pipe:0 or other input methods
- Any non-standard ffmpeg parameter string

### Fix Required
```python
except ValueError:
    # No -i flag found - append proxy at end or beginning
    logger.warning(f"FFmpeg command has no -i flag, appending -http_proxy at end")
    cmd.extend(['-http_proxy', proxy])
```

---

## 🟠 HIGH BUG #4: HTTPStreamReader Race Condition on Shutdown

**File**: `apps/proxy/live_proxy/input/http_streamer.py`  
**Lines**: ~115-120 (`_read_stream()` exception handling)


### Problem
The `_read_stream()` method catches `AttributeError` assuming it's from `self.response` being None during
shutdown. However, comment says "Catch race condition" but the fix is incomplete.

### Code Evidence
```python
except (AttributeError, OSError) as e:
    # Catch race condition during shutdown - response might be None
    if self.running:
        logger.error(f"HTTP reader error: {e}")
        self.error_occurred = True
    # ❌ BUG: If NOT running, error is silently ignored
    # But we don't know if it was the expected race condition or a real bug!
```

**In stop() method:**
```python
# Do NOT set self.response = None here (race condition fix)
# ❌ PROBLEM: Comment acknowledges race but doesn't fully prevent it
if self.response:
    try:
        self.response.close()  # ← Can throw if response is in weird state
    except:
        pass  # Silently ignored
```

### Impact
- **Real errors hidden** during shutdown (hard to debug)
- **Resource leaks possible** if response.close() fails silently
- **Unclear what exceptions are expected** - catches all AttributeErrors, not just response=None
- **No logging** when shutdown race occurs (can't verify fix works)

### Fix Required
```python
except AttributeError as e:
    if self.running:
        logger.error(f"HTTP reader AttributeError (unexpected): {e}")
        self.error_occurred = True
    else:
        # Expected during shutdown - response might be None
        logger.debug(f"HTTP reader AttributeError during shutdown (expected): {e}")
except OSError as e:
    if self.running:
        logger.error(f"HTTP reader OSError: {e}")
        self.error_occurred = True
```

**Better solution**: Use a lock around response access:
```python
import threading
self.response_lock = threading.Lock()

# In _read_stream():
with self.response_lock:
    if self.response:
        for chunk in self.response.iter_content(...):
            ...

# In stop():
with self.response_lock:
    if self.response:
        self.response.close()
        self.response = None
```

---

## 🟠 HIGH BUG #5: Redis Failure in get_alternate_streams Fails Open

**File**: `apps/proxy/live_proxy/url_utils.py`  
**Lines**: ~310-330 (profile availability checking)

### Problem
When Redis connection fails while checking profile availability, the code **assumes profile is available**
with a generic `except Exception`. This "fail-open" behavior could violate connection limits.

### Code Evidence
```python
try:
    profile_connections_key = f"profile_connections:{profile.id}"
    current_connections = int(redis_client.get(profile_connections_key) or 0)
    
    if profile.max_streams == 0 or current_connections < profile.max_streams:
        alternate_profiles.append(...)
except Exception as e:
    # ❌ BUG: ANY error causes fail-open!
    logger.warning(f"Redis error checking profile {profile.id} connections: {e}, assuming available")
    alternate_profiles.append(...)  # Adds profile regardless
```

### Impact
- **Connection limits violated** when Redis fails
- **Provider gets overloaded** during Redis downtime
- **Hides real bugs** - catches programming errors (TypeError, KeyError) and treats them as "available"
- **No circuit breaker** - keeps trying Redis every iteration

### Scenarios
1. Redis password changed → authentication error → all profiles "available" → overload
2. Network issue → timeout on every profile check → slow failover
3. Redis maxclients reached → connection refused → all profiles used simultaneously

### Fix Required
```python
try:
    profile_connections_key = f"profile_connections:{profile.id}"
    current_connections = int(redis_client.get(profile_connections_key) or 0)
    
    if profile.max_streams == 0 or current_connections < profile.max_streams:
        alternate_profiles.append(...)
    else:
        logger.debug(f"Profile {profile.id} at max connections")
except redis.RedisError as e:
    # Redis-specific errors - fail-open but log clearly
    logger.error(f"Redis error checking profile {profile.id}: {e}, assuming available for resilience")
    alternate_profiles.append(...)
except (TypeError, ValueError, KeyError) as e:
    # Programming errors - these should NOT happen, fail loudly
    logger.error(f"Programming error checking profile {profile.id}: {e}", exc_info=True)
    # Don't add profile - this is a real bug
```

**Better solution**: Cache "Redis is down" state to avoid repeated failures:
```python
if not hasattr(self, '_redis_failure_until'):
    self._redis_failure_until = 0

if time.time() < self._redis_failure_until:
    # Redis known to be down, skip checks for 60 seconds
    alternate_profiles.append(...)
    continue

try:
    # ... Redis check ...
except redis.RedisError as e:
    logger.error(f"Redis down: {e}")
    self._redis_failure_until = time.time() + 60  # Circuit breaker
    alternate_profiles.append(...)  # Fail-open
```

---

## 🟠 HIGH BUG #6: Buffer Timeout Failover Missing State Reset

**File**: `apps/proxy/live_proxy/server.py`  
**Lines**: ~1855-1870 (cleanup thread buffer timeout check)


### Problem
When buffer timeout triggers failover, the code sets `needs_stream_switch = True` but **doesn't reset
the timer**. This means if failover fails and buffer still doesn't fill, the system will trigger
failover AGAIN immediately on the next cleanup iteration (5 seconds later).

### Code Evidence
```python
if time_since_start > connecting_timeout:
    stream_manager = self.stream_managers.get(channel_id)
    if stream_manager and not getattr(stream_manager, 'url_switching', False):
        logger.warning(f"Channel stuck - triggering failover")
        stream_manager.needs_stream_switch = True  # ← Set flag
        logger.info(f"Failover signal sent")
        # ❌ BUG: No state reset! connection_start_time unchanged
    else:
        logger.warning(f"Channel stuck - stopping channel")
        self.stop_channel(channel_id)
    continue  # ← Loop continues with same connection_start_time
```

### Impact
- **Failover spam**: System tries failover every 5 seconds instead of waiting for result
- **Rapid stream switching**: Cycles through all profiles in ~30 seconds
- **No time for streams to stabilize**: Each profile only gets 5 seconds to start
- **Cooldown system bypassed**: Multiple failovers before cooldown even applies
- **Log spam**: Repeated "Channel stuck" warnings

### Timeline
```
T=0s:   Stream starts, connection_start_time = 0
T=5s:   Cleanup detects stuck (5 > 5s threshold) → needs_stream_switch = True
T=7s:   Failover starts (new stream connecting...)
T=10s:  Cleanup runs again, still stuck (10 > 5s) → needs_stream_switch = True AGAIN!
T=12s:  First failover completes
T=15s:  Cleanup triggers ANOTHER failover (15 > 5s)
→ Rapid failover cycling
```

### Fix Required
```python
if stream_manager and not getattr(stream_manager, 'url_switching', False):
    logger.warning(f"Channel stuck - triggering failover")
    stream_manager.needs_stream_switch = True
    
    # Reset timer to give failover time to complete
    if hasattr(stream_manager, 'connection_start_time'):
        stream_manager.connection_start_time = time.time()
    
    logger.info(f"Failover signal sent, timer reset")
```

---

## 🟡 MEDIUM BUG #7: Redis Scan Infinite Loop Protection Missing


**File**: `apps/proxy/live_proxy/input/manager.py`  
**Lines**: ~2140-2160 (Last Resort Redis scan loop)

### Problem
The Last Resort cooldown clearing uses `redis.scan()` with a `max_iterations` limit of 1000, but this limit
is **arbitrary** and could still cause issues. If `cursor` never returns to 0, the loop will iterate 1000 times
unnecessarily.

### Code Evidence
```python
cursor = 0
deleted = 0
max_iterations = 1000  # ❌ Why 1000? Based on what?
iterations = 0

while iterations < max_iterations:
    cursor, keys = self.buffer.redis_client.scan(cursor, match=cooldown_pattern, count=100)
    if keys:
        self.buffer.redis_client.delete(*keys)
        deleted += len(keys)
    if cursor == 0:  # ← Correct exit
        break
    iterations += 1

if iterations >= max_iterations:
    logger.warning(f"Last resort scan reached max iterations ({max_iterations})")
    # ❌ BUG: What now? Are there still cooldowns left?
```

### Impact
- **Incomplete cleanup**: If 1000 iterations not enough, some cooldowns remain
- **Unpredictable behavior**: Depends on Redis keyspace size
- **Performance issue**: 1000 iterations × 100 keys = checking 100,000 keys worst case
- **No clear failure mode**: Warning logged but process continues

### Expected Key Count
- 1 channel × 10 streams × 3 profiles = 30 cooldown keys maximum
- Scan with count=100 should complete in 1 iteration
- 1000 iterations is overkill for normal case

### Fix Required
Use `scan_iter()` which handles cursor automatically:
```python
try:
    cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
    deleted = 0
    
    # Use scan_iter - no manual cursor handling needed
    for key in self.buffer.redis_client.scan_iter(match=cooldown_pattern, count=100):
        self.buffer.redis_client.delete(key)
        deleted += 1
        
        # Safety limit based on expected maximum
        if deleted > 1000:
            logger.error(f"Last resort deleted {deleted} cooldowns - possible key explosion!")
            break
    
    if deleted > 0:
        logger.warning(f"LAST RESORT: Cleared {deleted} cooldown(s)")
        self.tried_combinations.clear()
        untried_combinations = alternate_streams
except Exception as e:
    logger.error(f"Last resort cooldown clear failed: {e}")
```

---

## 🟡 MEDIUM BUG #8: tried_combinations Never Cleared on Success

**File**: `apps/proxy/live_proxy/input/manager.py`  
**Lines**: Throughout `_try_next_stream()` and stream lifecycle

### Problem
`self.tried_combinations` is a **permanent set** that grows forever. Even when a stream works successfully
for hours, the combinations remain in `tried_combinations`. This means:

1. Channel starts with Stream 1 Profile 1 → works for 6 hours
2. Stream 1 Profile 1 fails → added to tried_combinations
3. Failover to Stream 1 Profile 2 → works for 6 hours
4. Stream 1 Profile 2 fails → added to tried_combinations
5. Now **Stream 1 Profile 1 is still in tried_combinations** even though it might work again!

### Code Evidence
```python
# In _try_next_stream():
self.tried_combinations.add((self.current_stream_id, self.current_profile_id))
# ❌ BUG: Never removed, even after hours of successful streaming
```

**No cleanup anywhere:**
- Not cleared on successful stream (no code path)
- Not cleared after time window (no TTL)
- Not cleared when channel stopped/restarted
- Only cleared in Last Resort (emergency measure)

### Impact
- **Reduces failover options over time**: Working combinations become "tried"
- **Permanent blacklisting**: Temporary network issues mark profiles as failed forever
- **Forces Last Resort prematurely**: System hits "all tried" state when profiles might work
- **Memory leak**: Set grows unbounded (though small - only stream ID tuples)

### Timeline Example
```
Day 1: Channel uses Stream 1 Profile 1 (works 20 hours)
       Brief outage → failover to Stream 1 Profile 2
       tried_combinations = {(1,1)}

Day 2: Stream 1 Profile 2 works all day (24 hours)
       Brief outage → cannot use Profile 1 (still in tried_combinations!)
       
Day 3: Profile 2 fails → all combinations "tried" → Last Resort
```

### Fix Required - Option 1: Time-based reset
```python
# In __init__:
self.tried_combinations_reset_time = time.time() + 3600  # Reset every hour

# In run() loop:
if time.time() > self.tried_combinations_reset_time:
    logger.info(f"Hourly tried_combinations reset")
    self.tried_combinations.clear()
    self.tried_combinations_reset_time = time.time() + 3600
```

### Fix Required - Option 2: Success-based reset
```python
# In _process_stream_data() after successful streaming:
if self.connected and time.time() - self.connection_start_time > 300:
    # Stream has been stable for 5 minutes
    if len(self.tried_combinations) > 0:
        logger.info(f"Stream stable for 5 minutes, clearing {len(self.tried_combinations)} tried combinations")
        self.tried_combinations.clear()
```

**Recommended**: Combine both - reset after 5 minutes of stable streaming OR after 1 hour elapsed time.

---

## Summary Table

| # | Severity | Component | Issue | Impact |
|---|----------|-----------|-------|--------|
| 1 | 🔴 Critical | Cooldown | Last Resort doesn't clear tried_combinations | Infinite loops still possible |
| 2 | 🔴 Critical | Health Monitor | Race condition on flags (no locks) | Lost signals, double execution |
| 3 | 🔴 Critical | HTTP Proxy | FFmpeg injection fails without -i flag | Proxy silently ignored |
| 4 | 🟠 High | HTTP Reader | Shutdown race condition | Resource leaks, hidden errors |
| 5 | 🟠 High | Profile Check | Redis failure fails open | Connection limits violated |
| 6 | 🟠 High | Buffer Timeout | No timer reset after failover | Failover spam, rapid cycling |
| 7 | 🟡 Medium | Redis Scan | Arbitrary iteration limit | Incomplete cleanup possible |
| 8 | 🟡 Medium | Failover | tried_combinations never cleared | Permanent blacklisting |

---

## Additional Observations (Not Bugs)

### 1. Missing HTTP Proxy Timeout Configuration
The HTTPStreamReader uses hardcoded timeouts:
```python
timeout=(5, 30),  # 5s connect, 30s read
```

This should be configurable via proxy settings (like other timeouts).

### 2. No Metrics for Cooldown System
No way to monitor:
- How many cooldowns are active
- How often Last Resort triggers
- Average time between failovers
- Success rate after cooldown expires

### 3. Cooldown Duration Not Adaptive
Fixed 10-minute cooldown regardless of:
- How long stream worked before failure (5 seconds vs 5 hours)
- Time of day / load patterns
- Failure reason (network vs provider vs encoding issue)

### 4. No Exponential Backoff
When a stream fails repeatedly, the system doesn't increase cooldown duration.
First failure = 10 minutes, tenth failure = still 10 minutes.

---

## Testing Recommendations

### Test Case 1: Last Resort Bug
1. Configure channel with 3 streams × 2 profiles each = 6 combinations
2. Enable cooldown (10 minutes)
3. Kill provider → all profiles fail → all on cooldown
4. Wait for Last Resort to trigger
5. **Expected bug**: System still can't try any profiles (tried_combinations not cleared)
6. Check logs for "Skipping... still in tried_combinations" or similar

### Test Case 2: Health Monitor Race
1. Start channel that works initially
2. Kill provider → stream becomes unhealthy
3. Monitor logs for `needs_reconnect` and `needs_stream_switch` messages
4. **Look for**: Double reconnect attempts, missed flags, out-of-order execution
5. Use `logger.debug` to add timestamps: `logger.debug(f"Flag check at {time.time()}: reconnect={self.needs_reconnect}")`

### Test Case 3: FFmpeg Proxy Injection
1. Create ffmpeg profile **WITHOUT** `-i` flag (use `pipe:0` or stdin)
2. Configure HTTP proxy on M3U account
3. Start stream with that profile
4. **Check**: Is `-http_proxy` in the ffmpeg command? (check logs or `ps aux | grep ffmpeg`)
5. **Expected bug**: Proxy missing from command

### Test Case 4: Buffer Timeout Spam
1. Configure buffer timeout = 5 seconds (Settings → Proxy → Buffer Timeout)
2. Start stream that connects but delivers NO data
3. Watch cleanup thread logs
4. **Expected bug**: "Channel stuck - triggering failover" every 5 seconds (instead of waiting for failover to complete)

### Test Case 5: Redis Failure Handling
1. Start channel (working fine)
2. Stop Redis: `docker stop redis` or `systemctl stop redis`
3. Trigger failover (kill stream)
4. **Check logs**: Are all profiles marked "available"? (fail-open bug)
5. **Check provider**: Are connection limits violated?

---

## Recommended Fix Priority

### Immediate (Critical)
1. **Bug #1**: Add `self.tried_combinations.clear()` in Last Resort
2. **Bug #3**: Fix ffmpeg proxy injection fallback

### High Priority
3. **Bug #2**: Replace boolean flags with gevent.event.Event
4. **Bug #6**: Reset connection_start_time after failover trigger


### Medium Priority  
5. **Bug #5**: Improve Redis error handling with circuit breaker
6. **Bug #8**: Implement time-based or stability-based tried_combinations reset

### Low Priority
7. **Bug #4**: Add proper locking to HTTPStreamReader
8. **Bug #7**: Use `scan_iter()` for Last Resort cleanup

---

## Code Quality Issues

### 1. Magic Numbers Everywhere
- Hardcoded timeouts: `(5, 30)`, `action_cooldown = 30`, `stable_time >= 30`
- Should be constants or config settings

### 2. Inconsistent Error Handling
- Some places: `except Exception` (too broad)
- Some places: `except:` (even worse - catches KeyboardInterrupt!)
- Some places: Proper specific exceptions

**Recommendation**: Use specific exceptions everywhere, log at appropriate level.

### 3. Missing Type Hints
Methods like `_try_next_stream()` return `bool` but not typed:
```python
def _try_next_stream(self):  # ❌ No return type
```

Should be:
```python
def _try_next_stream(self) -> bool:
```

### 4. Long Methods
`_try_next_stream()` is ~180 lines (too long for one function)

Should be split:
- `_mark_current_failed()` - Add to tried_combinations + set cooldown
- `_get_next_untried()` - Filter and sort candidates
- `_switch_to_stream()` - Perform the actual switch
- `_try_next_stream()` - Orchestrate the above

### 5. Comments in German
```python
# Automatische ffmpeg -http_proxy Injection wenn proxy vorhanden und kein {proxy} Platzhalter
# Kein -i gefunden, füge am Ende hinzu
```

Should be English for international collaboration.

---

## Conclusion

Found **8 significant bugs** across critical systems:
- 3 can cause system failures or infinite loops (Critical)
- 3 cause race conditions or resource leaks (High)
- 2 have incomplete error handling (Medium)

**Most Critical**: Bug #1 (Last Resort) and Bug #2 (Health Monitor Race) should be fixed immediately.

**Root Causes**:
1. Incomplete understanding of concurrency (gevent greenlets)
2. Missing state cleanup after operations
3. Over-broad exception handling hiding real errors
4. Lack of defensive programming (no guards against Redis failure)


**Overall Assessment**:  
The implemented features are **architecturally sound** but have **implementation bugs** that prevent them from
working correctly in edge cases. The cooldown system especially needs immediate attention - it's close to working
but the missing `tried_combinations.clear()` makes it ineffective.

---

**Analysis completed**: 2026-06-18  
**Files analyzed**: 8 (manager.py, http_streamer.py, server.py, url_utils.py, models.py, redis_keys.py, config.py, config_helper.py)  
**Lines reviewed**: ~2,500  
**Bugs found**: 8 (3 Critical, 3 High, 2 Medium)

