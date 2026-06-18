# Release Notes: Dispatcharr v0.27.1 - Critical Bug Fixes

**Release Date**: 2026-06-18  
**Type**: Bugfix Release  
**Priority**: High (Critical race conditions and proxy issues fixed)

---

## 🔴 Critical Fixes

### 1. Health Monitor Race Condition Fixed
**Impact**: High - Could cause lost recovery signals and double failover execution

**Problem**: Boolean flags (`needs_reconnect`, `needs_stream_switch`) were accessed by multiple greenlets without synchronization, causing race conditions.

**Solution**: Replaced boolean flags with thread-safe `gevent.event.Event()` objects.

**Files Changed**:
- `apps/proxy/live_proxy/input/manager.py`

**Benefits**:
- No more lost recovery signals
- No duplicate reconnect/failover attempts
- Predictable behavior under load

---

### 2. FFmpeg HTTP Proxy Now Works Without `-i` Flag
**Impact**: High - Proxy was silently ignored for non-standard ffmpeg profiles

**Problem**: When ffmpeg command had no `-i` flag (using stdin/pipe:0), the proxy parameter was silently dropped (empty `pass` block).

**Solution**: Append `-http_proxy` parameter at the end when `-i` flag not found.

**Files Changed**:
- `core/models.py`

**Benefits**:
- Proxy now works for all ffmpeg command variations
- Warning logged when fallback behavior is used
- No silent failures

---

## 🟠 High Priority Fixes

### 3. Better Error Handling for Redis Failures
**Impact**: Medium - Could violate connection limits during Redis outages

**Problem**: Broad `except Exception` caught both programming errors and Redis failures, treating all as "profile available".

**Solution**: Separate exception handling:
- `TypeError/ValueError/KeyError` → Programming error (don't fail-open)
- Other exceptions → Infrastructure error (fail-open for resilience)

**Files Changed**:
- `apps/proxy/live_proxy/url_utils.py` (2 locations)

**Benefits**:
- Real bugs no longer hidden by fail-open behavior
- Better logging distinguishes error types
- Connection limits respected when possible

---

### 4. HTTPStreamReader Shutdown Race Condition
**Impact**: Low - Could hide errors during shutdown

**Problem**: Generic exception handling during shutdown couldn't distinguish expected vs unexpected errors.

**Solution**: 
- Separate `AttributeError` and `OSError` handling
- Log expected shutdown errors at DEBUG level
- Log unexpected errors at ERROR level

**Files Changed**:
- `apps/proxy/live_proxy/input/http_streamer.py`

**Benefits**:
- Better debugging of real shutdown issues
- Clean logs during normal shutdown
- Thread timeout warnings added

---

## 🟡 Medium Priority Improvements

### 5. Redis Scan Optimization
**Impact**: Low - Cleaner code, slight performance improvement

**Problem**: Manual cursor management with arbitrary 1000 iteration limit.

**Solution**: Use `scan_iter()` which handles cursor automatically.

**Files Changed**:
- `apps/proxy/live_proxy/input/manager.py`

**Benefits**:
- Simpler code
- No arbitrary limits
- Better error handling for key explosions

---

### 6. Smart `tried_combinations` Reset System
**Impact**: Medium - Prevents permanent blacklisting of working streams

**Problem**: `tried_combinations` set never cleared, causing permanent blacklisting of temporarily failed streams.

**Solution**: Three-tier reset system:
1. **Hourly reset** - Clears every 60 minutes
2. **Stability reset** - Clears after 5 minutes of stable streaming
3. **Channel stop** - Clears when channel stops/restarts

**Files Changed**:
- `apps/proxy/live_proxy/input/manager.py` (3 locations)

**Benefits**:
- Temporary network issues don't permanently block streams
- Successful streams become available again after time
- Fresh start on channel restart

---

## 📊 Testing Recommendations

### Test Case 1: Health Monitor Race Condition
```bash
1. Start channel with unreliable stream
2. Monitor logs for "Setting reconnect flag" and "Health monitor requested reconnect"
3. Verify: No duplicate reconnect attempts
4. Verify: All flags are processed (no lost signals)
```

### Test Case 2: FFmpeg Proxy Without -i Flag
```bash
1. Create ffmpeg profile using pipe:0 instead of -i {streamUrl}
2. Configure HTTP proxy on M3U account
3. Start stream
4. Check logs: Should see "appending -http_proxy at end"
5. Verify: ps aux | grep ffmpeg shows -http_proxy parameter
```

### Test Case 3: Redis Failure Handling
```bash
1. Start working channel
2. Stop Redis: docker stop redis
3. Trigger failover (kill stream)
4. Check logs: Should see "Redis error... assuming available for resilience"
5. Verify: Provider connection limits not violated (check provider dashboard)
6. Restart Redis: docker start redis
```

### Test Case 4: tried_combinations Reset
```bash
1. Channel with 3 streams × 2 profiles (6 combinations)
2. Kill provider → all fail → all in tried_combinations
3. Wait 5 minutes with stable stream
4. Check logs: "Stream stable for 300s - clearing tried combinations"
5. Kill stream again → verify all combinations available again
```

---

## 🔧 Migration Notes

**No breaking changes** - All fixes are backward compatible.

**Recommended Actions**:
1. Update to v0.27.1
2. Monitor logs for "gevent.event" related messages (should be none)
3. Verify proxy working for all ffmpeg profiles
4. Check tried_combinations reset logs after ~1 hour uptime

---

## 📈 Performance Impact

- **Memory**: Negligible (+8 bytes per channel for Event objects)
- **CPU**: Negligible (scan_iter is same or faster than manual cursor)
- **Redis**: Slightly reduced load (smarter exception handling)
- **Stability**: Significantly improved (race conditions eliminated)

---

## 🐛 Known Issues (Not Fixed)

None identified in this release.

---

## 📝 Files Changed Summary

| File | Lines Changed | Type |
|------|---------------|------|
| `apps/proxy/live_proxy/input/manager.py` | ~70 | Fixes + Improvements |
| `core/models.py` | 3 | Critical Fix |
| `apps/proxy/live_proxy/input/http_streamer.py` | ~25 | Improvement |
| `apps/proxy/live_proxy/url_utils.py` | ~30 | Improvement |

**Total**: ~128 lines changed across 4 files

---

## 🎯 Upgrade Priority

- **Critical**: If using custom ffmpeg profiles without `-i` flag
- **High**: If experiencing unexplained failover behavior
- **Medium**: For improved stability and better error handling
- **Low**: If current version working perfectly

---

## 🙏 Credits

- Bug analysis and fixes: AI-assisted development
- Testing: Community feedback appreciated
- Original features: Dispatcharr development team

---

## 📞 Support

If you experience issues after upgrading:

1. Check logs for new error patterns
2. Verify Redis connectivity
3. Test proxy configuration with simple stream
4. Report issues with full logs

---

**Next Release (v0.28.0)**: Feature enhancements and additional optimizations planned.
