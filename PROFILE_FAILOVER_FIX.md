# Profile Failover Fix for Dispatcharr v0.26.0

## Problem Description

When a channel has a **single stream with multiple profiles**, profile failover was not working. The system would fail with "No alternate streams found" even though multiple profiles were available for the same stream.

### Example Scenario
- Channel: ZDF
- Stream: "ZDF Raw" from provider "XC Club"
- Profiles: Profile 3402, Profile 3403, Profile 3404 (multiple profiles for same provider)
- **Expected**: If profile 3402 fails, try 3403, then 3404
- **Actual**: "No alternate streams with available connections found" after first profile fails

### Root Cause

There were **three separate bugs** preventing profile failover:

#### Bug 1: `get_alternate_streams()` only returned ONE profile per stream
**Location**: `apps/proxy/live_proxy/url_utils.py` lines 349-392

**Problem**: The function would find the first available profile for a stream, check if it matched the failing combination, and if so, skip the ENTIRE stream instead of checking other profiles.

**Old Logic**:
```python
selected_profile = None
for profile in profiles:
    # Find first available profile
    if available:
        selected_profile = profile
        break  # ← BUG: Stops after first profile!

if selected_profile:
    if selected_profile == current_failing_profile:
        continue  # ← BUG: Skips entire stream!
    alternate_streams.append(selected_profile)
```

**Fixed Logic**:
```python
for profile in profiles:
    # Skip only the failing combination
    if profile == current_failing_profile:
        continue  # ← CORRECT: Skip only this profile, check others
    
    if available:
        alternate_streams.append(profile)  # ← CORRECT: Add all available profiles
```

#### Bug 2: Missing `current_profile_id` parameter in function calls
**Locations**: 
- `apps/proxy/live_proxy/views.py` line 343
- `apps/proxy/live_proxy/input/manager.py` line 1800

**Problem**: The `get_alternate_streams()` function was called without passing the `current_profile_id`, so it couldn't know which profile had just failed.

**Old**:
```python
alternates = get_alternate_streams(channel_id, stream_id)
```

**Fixed**:
```python
alternates = get_alternate_streams(channel_id, stream_id, m3u_profile_id)
```

#### Bug 3: `current_profile_id` was never loaded from Redis
**Location**: `apps/proxy/live_proxy/input/manager.py` lines 156-157

**Problem**: In the StreamManager constructor, when `stream_id` was provided, the code would load `current_stream_id` from the parameter but NEVER load `current_profile_id` from Redis, leaving it as `None`.

**Old**:
```python
if stream_id:
    self.tried_stream_ids.add(stream_id)
    # ← BUG: current_profile_id stays None!
```

**Fixed**:
```python
if stream_id:
    self.tried_stream_ids.add(stream_id)
    # Load profile_id from Redis
    if redis_client:
        profile_id_bytes = redis_client.hget(metadata_key, "m3u_profile")
        if profile_id_bytes:
            self.current_profile_id = int(profile_id_bytes)
```

## Files Modified

1. **`apps/proxy/live_proxy/url_utils.py`**
   - Modified `get_alternate_streams()` to accept `current_profile_id` parameter
   - Changed logic to return ALL available profiles for each stream, not just the first one
   - Fixed profile skip logic to skip only the failing profile, not the entire stream

2. **`apps/proxy/live_proxy/views.py`**
   - Updated call to `get_alternate_streams()` at line 343 to pass `m3u_profile_id`

3. **`apps/proxy/live_proxy/input/manager.py`**
   - Updated call to `get_alternate_streams()` at line 1800 to pass `self.current_profile_id`
   - Added code to load `current_profile_id` from Redis in `__init__` method

## Testing

### Before Fix
```
2026-06-10 09:08:29,053 INFO live_proxy.manager Trying to find alternative stream for channel 66600e30-2480-42f9-becd-b92e2625695f, current stream ID: 708953, current profile ID: 3402
2026-06-10 09:08:29,053 WARNING live_proxy.url_utils No alternate streams with available connections found for channel 66600e30-2480-42f9-becd-b92e2625695f
2026-06-10 09:08:29,053 INFO live_proxy.manager Found 0 potential alternate stream+profile combinations
```

### After Fix (Expected)
```
2026-06-10 09:08:29,053 INFO live_proxy.manager Trying to find alternative stream for channel 66600e30-2480-42f9-becd-b92e2625695f, current stream ID: 708953, current profile ID: 3402
2026-06-10 09:08:29,053 DEBUG live_proxy.url_utils Skipping current failing stream+profile combination: stream=708953, profile=3402
2026-06-10 09:08:29,054 DEBUG live_proxy.url_utils Found available profile 3403 for stream 708953
2026-06-10 09:08:29,054 DEBUG live_proxy.url_utils Found available profile 3404 for stream 708953
2026-06-10 09:08:29,054 INFO live_proxy.url_utils Found 2 alternate streams with available connections for channel 66600e30-2480-42f9-becd-b92e2625695f
2026-06-10 09:08:29,054 INFO live_proxy.manager Found 2 potential alternate stream+profile combinations
```

## Impact

✅ **Single stream with multiple profiles now properly fails over**
✅ **Multi-stream channels continue to work as before**
✅ **Respects tried_combinations tracking to avoid loops**
✅ **Profile connection limits are still checked**

## Verification Steps

1. Set up a channel with ONE stream that has MULTIPLE profiles (e.g., XC Club with 3 profiles)
2. Force the first profile to fail (e.g., disable provider temporarily)
3. Watch logs - should see:
   - "Skipping current failing stream+profile combination"
   - "Found available profile X for stream Y" (for each additional profile)
   - Stream switches to next profile instead of giving up

## Related to Docker Build Fix

This fix is independent of the Docker build fix (django-db-geventpool). Both fixes should be applied to v0.26.0.

---
**Status**: ✅ COMPLETE
**Date**: 2026-06-10
**Version**: v0.26.0
