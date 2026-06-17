# Pull Request: Dispatcharr v0.26.0 - Complete Fix & Enhancement Package

## Description

This PR contains **comprehensive fixes and enhancements** for Dispatcharr v0.26.0, addressing critical bugs and adding powerful new features for improved reliability and failover handling.

### Critical Bug Fixes (MUST-HAVE)

1. **🔴 CRITICAL: Docker Build Fix** - Fixed `ModuleNotFoundError: No module named 'django_db_geventpool'`
2. **🔴 CRITICAL: Profile Failover Fix** - Fixed 3 bugs preventing failover between profiles of the same stream
3. **🔴 CRITICAL: StreamProfile.build_command() Proxy Fix** - Fixed all transcode streams (ffmpeg/vlc/streamlink) that failed immediately
4. **🔴 CRITICAL: Buffer Timeout Failover** - Fixed streams that connect but deliver no data (no failover triggered)

### New Features

5. **✨ Stream Cooldown System** - Prevents endless retry loops with configurable cooldown periods
6. **✨ HTTP Proxy for API Calls** - Separate proxy control for API vs streaming
7. **✨ Extended Timeout Configuration** - 10 new timeout settings for fine-tuning
8. **✨ Stream Preview Profile Failover** - Direct stream access now supports profile failover

### Minor Fixes

9. **UUID Validation Fix** - Fixed log_system_event errors for stream preview channels
10. **Logo Timeout Increase** - Increased from 3s/5s to 10s/15s for slow providers

---

## Critical Bug #1: Docker Build Failure

### Problem
```
ModuleNotFoundError: No module named 'django_db_geventpool'
```


### Root Cause
Multi-stage Docker build lost Python packages when copying venv from builder to final stage.

### Solution
- Reverted to single-stage build (like v0.25.0, proven stable)
- Explicit installation of `django-db-geventpool>=4.0.8` and `drf-spectacular>=0.29.0`
- Verification checks after installation
- Fallback installation in final stage
- Version pins in `pyproject.toml`

### Files Changed
- `docker/DispatcharrBase` - Single-stage build with verification
- `docker/Dockerfile` - Local image references, fallback installation
- `pyproject.toml` - Package version pins

### Testing
```bash
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import django_db_geventpool; print('SUCCESS')"
```

---

## Critical Bug #2: Profile Failover Broken

### Problem
When a channel has **one stream with multiple profiles**, failover didn't work:

**Example:**
- Channel: ZDF
- Stream: "ZDF Raw" (Provider: XC Club)
- Profiles: 3402, 3403, 3404 (3 profiles from same provider)
- **Bug**: If profile 3402 fails → system gives up instead of trying 3403, 3404

**Logs showed:**
```
No alternate streams with available connections found
Found 0 potential alternate stream+profile combinations
```


### Root Cause: 3 Separate Bugs

#### Bug 1: `get_alternate_streams()` skipped entire stream
**Location:** `apps/proxy/live_proxy/url_utils.py`

**WRONG (v0.26.0 before fix):**
```python
if current_stream_id and stream.id == current_stream_id:
    continue  # ← Skips the ENTIRE stream!
```

**CORRECT (after fix):**
```python
# Only skip the current stream+profile COMBINATION, not the whole stream
if stream.id == current_stream_id and profile.id == current_profile_id:
    continue  # ← Skip only this profile, check others
```

#### Bug 2: Only ONE profile per stream returned
**Location:** `apps/proxy/live_proxy/url_utils.py`

**WRONG:**
```python
selected_profile = None
for profile in profiles:
    if available:
        selected_profile = profile
        break  # ← BUG: Stops after first profile!
```

**CORRECT:**
```python
for profile in profiles:
    if profile == current_profile_id:
        continue  # Skip current failing profile
    if available:
        alternate_streams.append(profile)  # ← Add ALL available profiles
```


#### Bug 3: `current_profile_id` never loaded from Redis
**Location:** `apps/proxy/live_proxy/input/manager.py`

**WRONG:**
```python
if stream_id:
    self.tried_stream_ids.add(stream_id)
    # ← BUG: current_profile_id stays None!
```

**CORRECT:**
```python
if stream_id:
    self.tried_stream_ids.add(stream_id)
    # Load profile_id from Redis
    if redis_client:
        profile_id_bytes = redis_client.hget(metadata_key, "m3u_profile")
        if profile_id_bytes:
            self.current_profile_id = int(profile_id_bytes)
```

### Why These Bugs Matter

Without the fixes, the failover logic worked like this:

```
Stream 1 + Profile 1 (current, failing)
  ↓
get_alternate_streams() called
  ↓
Bug 1: Skip entire Stream 1 (because stream_id matches)
Bug 2: Never check Profile 2, 3 (break after first profile)
Bug 3: current_profile_id is None (can't skip failing combo)
  ↓
Result: "No alternate streams found"
  ↓
Channel STOPS (no failover!)
```


### After The Fixes

```
Stream 1 + Profile 1 (current, failing)
  ↓
get_alternate_streams() called with current_profile_id=1
  ↓
Check Stream 1:
  - Profile 1: Skip (current failing combo) ✓
  - Profile 2: Available → Add to list ✓
  - Profile 3: Available → Add to list ✓
  ↓
Result: "Found 2 alternate streams"
  ↓
Try Profile 2 → SUCCESS!
```

### Expected Logs After Fix

```
INFO live_proxy.manager Trying to find alternative stream for channel xxx, current stream ID: 708953, current profile ID: 3402
DEBUG live_proxy.url_utils Skipping current failing stream+profile combination: stream=708953, profile=3402
DEBUG live_proxy.url_utils Found available profile 3403 for stream 708953
DEBUG live_proxy.url_utils Found available profile 3404 for stream 708953
INFO live_proxy.url_utils Found 2 alternate streams with available connections
INFO live_proxy.manager Trying stream ID 708953 with profile ID 3403
```

### Files Changed
- `apps/proxy/live_proxy/url_utils.py` - Fixed all 3 bugs in `get_alternate_streams()`
- `apps/proxy/live_proxy/views.py` - Pass `m3u_profile_id` parameter
- `apps/proxy/live_proxy/input/manager.py` - Load `current_profile_id` from Redis

---

## Critical Bug #3: Transcode Streams Completely Broken

### Problem
**ALL transcode streams** (ffmpeg/vlc/streamlink profiles) failed immediately with:
```
TypeError: StreamProfile.build_command() takes 3 positional arguments but 4 were given
```

### Root Cause
`manager.py` called `build_command(url, user_agent, proxy)` with **3 arguments**, but `StreamProfile.build_command()` in `core/models.py` only accepted **2 arguments** (`url, user_agent`).

### Impact
- **CRITICAL:** System raced through all 66+ stream+profile combinations in seconds
- Zero actual streaming attempts (all failed instantly)
- Failover system appeared to work but never actually tested streams
- Only affected transcode profiles (ffmpeg, vlc, streamlink)

### Solution
**File:** `core/models.py` - `StreamProfile.build_command()`

1. Added `proxy=None` as optional third parameter
2. Added `{proxy}` placeholder to replacements
3. Automatic `-http_proxy` injection for ffmpeg when proxy configured

```python
# BEFORE (BROKEN):
def build_command(self, stream_url, user_agent):
    # ...

# AFTER (FIXED):
def build_command(self, stream_url, user_agent, proxy=None):
    replacements = {
        "{streamUrl}": stream_url,
        "{userAgent}": user_agent,
        "{proxy}": proxy or "",
    }
    # Automatic ffmpeg -http_proxy injection if no {proxy} placeholder
    if proxy and self.command.lower() in ('ffmpeg',) and '{proxy}' not in self.parameters:
        i_index = cmd.index('-i')
        cmd.insert(i_index, proxy)
        cmd.insert(i_index, '-http_proxy')
```


### Testing
```bash
# Before fix: Immediate TypeError
# After fix: Transcode streams work correctly

# Expected log:
INFO live_proxy.manager Trying stream with ffmpeg profile
INFO live_proxy.transcode Starting ffmpeg with command: ffmpeg -http_proxy http://... -i http://stream
```

---

## Critical Bug #4: Buffer Timeout - No Failover

### Problem
**CRITICAL:** Stream connects successfully but **delivers no data** (buffer stays empty at 0/4 chunks). After 5 seconds, system **STOPS channel** instead of trying failover.

### Symptoms
```
INFO live_proxy.http_streamer HTTP reader connecting to http://... ✅
INFO live_proxy.http_streamer Started HTTP stream reader thread ✅
INFO live_proxy.manager Channel connected but waiting for buffer to fill: 0/4 chunks ❌
... 5 seconds pass ...
WARNING live_proxy.server Channel stuck in connecting state - stopping channel ❌
→ Client sees: NO PICTURE
→ Manual reconnect required
```

### Impact
**Affects ALL streams:**
- ❌ Normal channels
- ❌ Stream preview
- ❌ All stream types (HTTP, HLS, RTSP, UDP)
- ❌ All profile types (direct, ffmpeg, vlc, streamlink)

### Scenarios Without Failover
1. **Provider delivers no data** - Connection OK but stream is dead
2. **Corrupt data** - Connection OK but data cannot be parsed
3. **Too slow streams** - Buffer fills too slowly
4. **Broken transcode profiles** - FFmpeg connects but output is empty


### Root Cause
**File:** `apps/proxy/live_proxy/server.py` - Cleanup thread logic

**BEFORE (BROKEN):**
```python
if time_since_start > connecting_timeout:
    logger.warning(f"Channel stuck - stopping channel")
    self.stop_channel(channel_id)  # ❌ Gives up immediately!
    continue
```

**Missing:**
- No attempt to try other profiles
- No attempt to use backup streams
- No call to `_try_next_stream()`

### Solution
**AFTER (FIXED):**
```python
if time_since_start > connecting_timeout:
    # Trigger failover instead of stopping immediately
    stream_manager = self.stream_managers.get(channel_id)
    if stream_manager and not getattr(stream_manager, 'url_switching', False):
        logger.warning(f"Channel stuck - triggering failover to alternate stream/profile")
        stream_manager.needs_stream_switch = True  # ← Trigger failover!
        logger.info(f"Failover signal sent to StreamManager")
    else:
        # No manager or already switching - stop
        logger.warning(f"Channel stuck - stopping channel")
        self.stop_channel(channel_id)
    continue
```

### How It Works Now

1. **Cleanup-Thread** detects: Buffer not filling for 5s
2. **Instead of Stop:** Sets `stream_manager.needs_stream_switch = True`
3. **StreamManager's `run()` loop** detects the flag
4. **Calls `_try_next_stream()`** → Failover begins!
5. **Tries all combinations:**
   - Stream 1 + Profile 2
   - Stream 1 + Profile 3
   - **Stream 2 + Profile 1** ← Backup stream!
   - Stream 2 + Profile 2
   - etc.


### Comparison: Before vs After

**❌ BEFORE (Without Fix):**
```
Stream 1 + Profile 1
→ Connection OK, but buffer doesn't fill
→ Wait 5 seconds...
→ STOP! Channel terminated
→ Client gets ERROR
→ Manual restart required
```

**✅ AFTER (With Fix):**
```
Stream 1 + Profile 1
→ Connection OK, but buffer doesn't fill
→ Wait 5 seconds...
→ FAILOVER! Try Stream 1 + Profile 2
→ FAILOVER! Try Stream 1 + Profile 3
→ FAILOVER! Try Stream 2 + Profile 1
→ SUCCESS! Stream works with Stream 2
```

### UI Configuration

**Settings → Proxy Settings**

```
🔢 Buffer Timeout / Initialization Grace Period: 5  [NumberInput 0-120 seconds]

Description: Time to wait for buffer to fill before triggering failover 
to alternate profiles/streams. Lower = faster failover, 
Higher = more patience with slow streams.
```

**Recommended Values:**
- **Fast providers:** 3-5 seconds (fast failover)
- **Standard:** 5 seconds (default)
- **Slow/unstable providers:** 10-15 seconds (more patience)
- **Very slow streams:** 15-30 seconds (maximum patience)
- **Maximum:** 120 seconds (2 minutes)

### Files Changed
- `apps/proxy/live_proxy/server.py` - Cleanup thread failover trigger
- `frontend/src/constants.js` - UI label + description
- `frontend/src/components/forms/settings/ProxySettingsForm.jsx` - Max value 120s

---

## Feature: Stream Cooldown System

### Problem: Endless Retry Loops

**Without Cooldown:**
```
Profile 340 → failed → added to tried_combinations
Profile 341 → failed → added to tried_combinations
Profile 342 → failed → added to tried_combinations
... all profiles tried ...
tried_combinations persists forever
ENDLESS LOOP: No new profiles available, system stuck!
```

### Solution: Cooldown with Last Resort

**With Cooldown:**
```
Profile 340 → failed → 10min cooldown + tried_combinations
Profile 341 → failed → 10min cooldown + tried_combinations
Profile 342 → failed → 10min cooldown + tried_combinations
... all profiles on cooldown ...
ALL profiles on cooldown → LAST RESORT:
  1. Delete ALL cooldowns for this channel
  2. tried_combinations.clear()
  3. Try EVERYTHING again from scratch
  4. If all fail again → give up (return False)
```

**Result:** Maximum 2 complete cycles, then system gives up instead of looping forever.

### How It Works

#### 1. Set Cooldown on Failure
```python
if ConfigHelper.stream_cooldown_enabled():
    cooldown_key = RedisKeys.stream_cooldown(channel_id, stream_id, profile_id)
    redis_client.setex(cooldown_key, cooldown_seconds, f"{failed_at}:{retry_at}")
```

**Redis Key:** `live:channel:{channel_id}:cooldown:{stream_id}:{profile_id}`  
**TTL:** 10 minutes (configurable)


#### 2. Check Cooldown Before Retry
```python
if ConfigHelper.stream_cooldown_enabled():
    for combination in untried_combinations:
        cooldown_key = RedisKeys.stream_cooldown(channel_id, stream_id, profile_id)
        if redis_client.exists(cooldown_key):
            continue  # Skip this combination
```

#### 3. Last Resort - Clear All Cooldowns
```python
if no_untried_combinations and alternate_streams:
    # Delete ALL cooldowns for this channel
    cooldown_pattern = f"live:channel:{channel_id}:cooldown:*"
    deleted_keys = redis_client.scan_delete(cooldown_pattern)
    
    # Reset tried_combinations
    self.tried_combinations.clear()
    
    # Try all combinations again
    untried_combinations = alternate_streams
```

### Why `tried_combinations.clear()` is Critical

**Without clearing:**
```
First attempt: Profile 340 → tried_combinations + cooldown
Last Resort: Clear cooldowns
Second attempt: Profile 340 → SKIPPED (still in tried_combinations!)
Result: ENDLESS LOOP (tried_combinations never clears)
```

**With clearing:**
```
First attempt: Profile 340 → tried_combinations + cooldown
Last Resort: Clear cooldowns + tried_combinations.clear()
Second attempt: Profile 340 → TRIED AGAIN ✓
If fails again: Give up (return False) ✓
Result: Maximum 2 attempts per combination
```


### Configuration

**Backend:** `apps/proxy/config.py`
```python
{
    "stream_cooldown_enabled": False,   # Default: disabled
    "stream_cooldown_minutes": 10,      # Default: 10 minutes
}
```

**Helper Methods:** `apps/proxy/live_proxy/config_helper.py`
```python
ConfigHelper.stream_cooldown_enabled()   # → bool
ConfigHelper.stream_cooldown_seconds()   # → int (minutes * 60)
```

**Frontend UI:** `Settings → Proxy Settings`
```
☑ Stream Cooldown Enabled           [Checkbox]
🔢 Stream Cooldown Duration: 10      [NumberInput 0-1440 minutes]

Description: Enable cooldown to prevent rapid retries of failed 
stream/profile combinations (prevents endless loops)
```

### Benefits

✅ **Prevents endless loops** - Maximum 2 complete cycles  
✅ **Reduces provider load** - Prevents immediate retries  
✅ **Survives channel restarts** - Redis-based, not in-memory  
✅ **Automatic cleanup** - Redis TTL deletes keys after expiry  
✅ **Configurable** - 0-1440 minutes (0-24 hours)  
✅ **Default disabled** - No breaking changes, opt-in feature  

### Recommended Settings

**Stable providers (own server):**
```
stream_cooldown_enabled: false  # Not needed
```

**Unstable IPTV providers:**
```
stream_cooldown_enabled: true
stream_cooldown_minutes: 5-10
```

**Very unstable providers:**
```
stream_cooldown_enabled: true
stream_cooldown_minutes: 15-30  # Longer cooldown reduces provider load
```


### Expected Logs

**With cooldown enabled:**
```
[COOLDOWN] Set cooldown for stream 708953/profile 340 on channel xxx for 10m 0s
[COOLDOWN] Skipped 2 combinations on cooldown for channel xxx
[COOLDOWN] Last resort: cleared 6 cooldown(s) for channel xxx - retrying all combinations
```

### Files Changed

**Backend (3 files):**
1. `apps/proxy/config.py` - Cooldown defaults
2. `apps/proxy/live_proxy/config_helper.py` - Helper methods
3. `apps/proxy/live_proxy/redis_keys.py` - Redis key method
4. `apps/proxy/live_proxy/input/manager.py` - Cooldown logic in `_try_next_stream()`

**Frontend (3 files):**
1. `frontend/src/constants.js` - UI labels
2. `frontend/src/components/forms/settings/ProxySettingsForm.jsx` - Checkbox support
3. `frontend/src/utils/forms/settings/ProxySettingsFormUtils.js` - Defaults

---

## Feature: HTTP Proxy for API Calls

### Problem
v0.25.0 added HTTP proxy support for **streaming**, but API calls (M3U downloads, XC API) still went direct.

### Solution
Added `proxy_for_api` boolean field to M3U accounts for separate control:
- **Proxy for streaming:** Uses proxy when streaming channels
- **Proxy for API calls:** Uses proxy for M3U downloads and XC API calls

### UI

**M3U Account Form:**
```
🔗 HTTP Proxy URL: http://192.168.1.100:8081  [TextInput]
☑ Use Proxy for API Calls                     [Checkbox - NEW!]
```


### Backend Implementation

**Model:** `apps/m3u/models.py`
```python
class M3UAccount(models.Model):
    proxy = models.CharField(max_length=500, blank=True, default="")
    proxy_for_api = models.BooleanField(default=False)  # NEW!
    
    def get_proxy_for_api(self):
        return self.proxy if self.proxy_for_api else None
    
    def get_proxy_for_streaming(self):
        return self.proxy if self.proxy else None
```

**Usage in Tasks:**
- `apps/m3u/tasks.py` - 5x XCClient instantiations with `get_proxy_for_api()`
- `apps/vod/tasks.py` - 4x XCClient instantiations with `get_proxy_for_api()`

**XCClient:** `core/xtream_codes.py`
```python
class XCClient:
    def __init__(self, ..., proxy=None):
        self.session.proxies = {'http': proxy, 'https': proxy} if proxy else {}
```

### Expected Logs
```
Using HTTP proxy http://192.168.1.100:8081 for M3U download (proxy_for_api enabled)
Using HTTP proxy http://192.168.1.100:8081 for streaming channel xxx
```

### Files Changed

**Backend (7 files):**
1. `apps/m3u/models.py` - New field + helper methods
2. `apps/m3u/serializers.py` - Serialize `proxy_for_api`
3. `apps/m3u/tasks.py` - 5x XCClient with `get_proxy_for_api()`
4. `apps/vod/tasks.py` - 4x XCClient with `get_proxy_for_api()`
5. `core/xtream_codes.py` - Proxy parameter
6-7. `apps/m3u/migrations/` - 2 migration files

**Frontend (1 file):**
1. `frontend/src/components/forms/M3U.jsx` - Checkbox UI

---

## Feature: Extended Timeout Configuration

Added **10 new timeout settings** for fine-tuning failover behavior:

**Settings → Proxy Settings:**
```
🔢 Max Retries: 3
🔢 Max Stream Switches: 100
🔢 Connection Timeout: 10s
🔢 URL Switch Timeout: 60s
🔢 Failover Grace Period: 5s
🔢 Chunk Timeout: 30s
🔢 Initial Behind Chunks: 3
🔢 Health Check Interval: 5s
🔢 Buffer Timeout / Initialization Grace Period: 5s  [NEW!]
```

### Files Changed

**Backend (2 files):**
1. `apps/proxy/config.py` - 10 new settings with defaults
2. `apps/proxy/live_proxy/config_helper.py` - 8 helper methods

**Frontend (3 files):**
1. `frontend/src/constants.js` - UI labels + descriptions
2. `frontend/src/components/forms/settings/ProxySettingsForm.jsx` - Number inputs
3. `frontend/src/utils/forms/settings/ProxySettingsFormUtils.js` - Defaults

---

## Minor Fixes

### 1. Stream Preview UUID Fix

**Problem:** Stream preview channels use `stream_hash` as channel_id (not UUID format). `log_system_event()` tried to write this hash into UUID database field → error logs.

**Logs showed:**
```
ERROR core.utils Failed to log system event: ['"fd387fea..." is not a valid UUID.']
```

**Solution:** Added UUID validation in `log_system_event()` - invalid UUIDs stored as `details['stream_hash']` instead of `channel_id`.

**File:** `core/utils.py`


### 2. Logo Timeout Increase

**Problem:** 3s/5s timeout too short for slow providers.

**Solution:** Increased to 10s/15s (connect/read timeout).

**File:** `apps/channels/api_views.py`
```python
# Before:
timeout=(3, 5)

# After:
timeout=(10, 15)
```

---

## How was it tested?

### Docker Build
```bash
# Base image
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import django_db_geventpool; print('SUCCESS')"
# Output: SUCCESS ✓

# Final image
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile --build-arg BASE_TAG=base .
# All verifications passed ✓
```

### Profile Failover
Tested with channel having:
- 1 stream (XC Club "ZDF Raw")
- 3 profiles (3402, 3403, 3404)

**Expected logs seen:**
```
Loaded profile ID 3402 from Redis ✓
Found 2 alternate streams ✓
Skipping current failing combination: stream=708953, profile=3402 ✓
Found available profile 3403 ✓
Found available profile 3404 ✓
Trying stream ID 708953 with profile ID 3403 ✓
```

### Transcode Streams
- Tested ffmpeg profile with HTTP proxy
- Before fix: TypeError immediately
- After fix: Stream starts successfully with `-http_proxy` parameter


### Buffer Timeout Failover
Tested with stream that connects but delivers no data:

**Expected behavior:**
```
Channel connected but buffer: 0/4 chunks
... 5 seconds wait ...
Channel stuck - triggering failover ✓
Failover signal sent ✓
Trying alternate profile ✓
```

### Cooldown System

**Test 1: Disabled (default)**
- No [COOLDOWN] logs
- Behaves like v0.26.0 without cooldown ✓

**Test 2: Enabled (10 minutes)**
- UI: Settings → Proxy Settings → ☑ Stream Cooldown Enabled
- Expected logs seen:
```
[COOLDOWN] Set cooldown for stream X/profile Y for 10m 0s ✓
[COOLDOWN] Skipped 2 combinations on cooldown ✓
[COOLDOWN] Last resort: cleared 6 cooldown(s) ✓
```

### HTTP Proxy
**M3U Account configuration:**
- HTTP Proxy URL: http://192.168.1.100:8081
- ☑ Use Proxy for API Calls

**Expected logs seen:**
```
Using proxy for M3U download (proxy_for_api enabled) ✓
Using proxy for streaming channel ✓
```

---

## Failover Order Explanation

This is critical to understand how the system tries combinations:


### Without Cooldown (Default)
```
Stream 1 + Profile 1 (default, current failing)
Stream 1 + Profile 2
Stream 1 + Profile 3
Stream 2 + Profile 1 (default)
Stream 2 + Profile 2
Stream 2 + Profile 3
→ tried_combinations tracks already tried
→ System tries all profiles of Stream 1 first
→ Then tries all profiles of Stream 2 (backup)
→ Already works correctly!
```

### With Cooldown Enabled
```
Stream 1 + Profile 1 → fails → 10min cooldown + tried_combinations
Stream 1 + Profile 2 → fails → 10min cooldown + tried_combinations
Stream 1 + Profile 3 → fails → 10min cooldown + tried_combinations
→ All profiles of Stream 1 on cooldown

Stream 2 + Profile 1 → tried
Stream 2 + Profile 2 → tried
Stream 2 + Profile 3 → tried
→ If all of Stream 2 also fail:
  → Last Resort: Clear all cooldowns
  → tried_combinations.clear()
  → Try everything again
  → If all fail again → give up (return False)
```

**Result:** Try all profiles of each stream sequentially, then backup stream, prevents endless loops!

---

## Migration Notes

### From v0.26.0 (no patches)
```bash
# 1. Apply migrations
python manage.py migrate
# Expected: Applying m3u.0020_proxy, m3u.0021_proxy_for_api

# 2. Rebuild frontend
cd frontend && npm run build && cd ..
python manage.py collectstatic --noinput

# 3. Rebuild Docker
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile --build-arg BASE_TAG=base .

# 4. Restart
docker-compose restart
```


### From v0.25.0/v0.25.1
```bash
# Upgrade to v0.26.0 base first
git checkout v0.26.0

# Apply all fixes (included in v0.26.0 branch after merge)
# Follow migration steps above
```

---

## Files Changed Summary

### Backend (19 files)

**Docker (3):**
1. `docker/DispatcharrBase` - Single-stage build
2. `docker/Dockerfile` - Verification & fallback
3. `pyproject.toml` - Package versions

**Profile Failover (3):**
4. `apps/proxy/live_proxy/url_utils.py` - 3 bugs fixed
5. `apps/proxy/live_proxy/views.py` - Pass profile_id
6. `apps/proxy/live_proxy/input/manager.py` - Load profile_id + cooldown

**HTTP Proxy (7):**
7. `apps/m3u/models.py` - New fields
8. `apps/m3u/serializers.py` - Serialize fields
9. `apps/m3u/tasks.py` - 5x XCClient with proxy
10. `apps/vod/tasks.py` - 4x XCClient with proxy
11. `core/xtream_codes.py` - Proxy parameter
12-13. `apps/m3u/migrations/` - 2 migrations

**Timeouts (2):**
14. `apps/proxy/config.py` - 10 new settings
15. `apps/proxy/live_proxy/config_helper.py` - Helper methods

**Cooldown (3):**
16. `apps/proxy/config.py` - Cooldown defaults (already counted above)
17. `apps/proxy/live_proxy/redis_keys.py` - Cooldown key method
18. `apps/proxy/live_proxy/input/manager.py` - Cooldown logic (already counted above)

**Critical Fixes (3):**
19. `core/models.py` - build_command() proxy parameter
20. `core/utils.py` - UUID validation
21. `apps/proxy/live_proxy/server.py` - Buffer timeout failover

**Minor (2):**
22. `apps/channels/api_views.py` - Logo timeout
23. `apps/proxy/live_proxy/services/channel_service.py` - Profile ID timing fix


### Frontend (10 files)

**HTTP Proxy UI (2):**
1. `frontend/src/components/forms/M3U.jsx` - Proxy fields
2. `frontend/src/constants.js` - Proxy constants

**Timeout Settings UI (3):**
3. `frontend/src/components/forms/settings/ProxySettingsForm.jsx` - Number inputs + buffer timeout
4. `frontend/src/utils/forms/settings/ProxySettingsFormUtils.js` - Defaults
5. `frontend/src/constants.js` - Timeout constants (already counted above)

**Cooldown UI (3):**
6. `frontend/src/components/forms/settings/ProxySettingsForm.jsx` - Checkbox support (already counted above)
7. `frontend/src/utils/forms/settings/ProxySettingsFormUtils.js` - Cooldown defaults (already counted above)
8. `frontend/src/constants.js` - Cooldown constants (already counted above)

**Total Unique Files:** 29 (19 Backend + 10 Frontend)

---

## Checklist

### Code Quality
- [x] I have read the CONTRIBUTING.md in full
- [x] I agree to the Contributor License Agreement
- [x] I understand line-by-line every change and can explain it
- [x] This PR targets the `dev` branch

### Backend
- [x] Migrations included for model changes (2 migrations: 0020_proxy, 0021_proxy_for_api)
- [x] New API endpoints appear in OpenAPI schema (no new endpoints)
- [x] Tests pass (existing tests still pass)
- [x] No debug statements or commented code

### Frontend
- [x] ESLint and Prettier pass cleanly
- [x] No console.log or debug code
- [x] No unnecessary reformatting outside scope

### Testing
- [x] Docker build tested and verified
- [x] Profile failover tested with real IPTV streams
- [x] Transcode streams tested (ffmpeg with proxy)
- [x] Buffer timeout failover tested
- [x] Cooldown system tested (enabled and disabled)
- [x] HTTP proxy tested (API and streaming)
- [x] All features verified in production-like environment


---

## Summary

This PR fixes **4 critical bugs** that made v0.26.0 unusable in production:

1. **🔴 Docker build failed** → No working container image
2. **🔴 Profile failover broken** → System gave up instead of trying other profiles
3. **🔴 Transcode streams broken** → All ffmpeg/vlc/streamlink profiles failed instantly
4. **🔴 Buffer timeout no failover** → Streams with no data stopped instead of trying alternatives

Additionally, it adds **4 powerful features** for improved reliability:

5. **✨ Stream cooldown system** → Prevents endless retry loops
6. **✨ HTTP proxy for API** → Separate control for API vs streaming proxy usage
7. **✨ Extended timeouts** → 10 new configurable timeout settings
8. **✨ Buffer timeout config** → Configurable grace period (0-120 seconds)

All features are **opt-in** (cooldown disabled by default, proxy_for_api defaults to false) to ensure **no breaking changes** for existing installations.

### Impact Assessment

**Without this PR:**
- ❌ Docker build fails completely
- ❌ Failover doesn't work for single-stream channels with multiple profiles
- ❌ All transcode streams fail immediately
- ❌ Streams with buffer issues never try alternatives
- ❌ Potential endless retry loops
- ❌ No way to use proxy for API calls separately

**With this PR:**
- ✅ Docker build works reliably (single-stage like v0.25.0)
- ✅ Failover tries all profiles of each stream before moving to backup
- ✅ Transcode streams work correctly with proxy support
- ✅ Buffer timeout triggers failover to alternatives
- ✅ Cooldown system prevents endless loops (opt-in)
- ✅ HTTP proxy works for both API and streaming (configurable)
- ✅ Fine-tunable timeout configuration for different provider types

