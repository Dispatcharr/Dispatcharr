#!/usr/bin/env python3
"""
Create patch file for v0.27.1 bug fixes
Includes all 6 critical/high/medium bug fixes
"""

import os
import subprocess
from pathlib import Path

def create_patch():
    """Create unified patch file with all bug fixes"""
    
    print("Creating v0.27.1 bug fix patch...")
    
    # Files that were modified
    modified_files = [
        "apps/proxy/live_proxy/input/manager.py",
        "apps/proxy/live_proxy/input/http_streamer.py",
        "apps/proxy/live_proxy/url_utils.py",
        "core/models.py"
    ]
    
    patch_content = """# Dispatcharr v0.27.1 Bug Fixes Patch
# Date: 2026-06-18
# 
# This patch fixes 6 critical/high/medium bugs:
# 1. Health Monitor Race Condition (gevent.event.Event)
# 2. FFmpeg Proxy Injection without -i flag
# 3. Redis Failure Error Handling
# 4. HTTPStreamReader Shutdown Race Condition
# 5. Redis Scan Optimization (scan_iter)
# 6. Smart tried_combinations Reset System
#
# Apply with: git apply v0.27.1_bugfixes.patch
# Or manually review and apply changes

"""
    
    # Check if we're in a git repo
    if not os.path.exists('.git'):
        print("Not in a git repository. Creating manual patch guide...")
        return create_manual_patch_guide()
    
    try:
        # Try to create git diff
        result = subprocess.run(
            ['git', 'diff', '--'] + modified_files,
            capture_output=True,
            text=True,
            check=True
        )
        
        if result.stdout.strip():
            patch_content += result.stdout
            
            # Write patch file
            patch_file = "dispatcharr_v0.27.1_bugfixes.patch"
            with open(patch_file, 'w', encoding='utf-8') as f:
                f.write(patch_content)
            
            print(f"✅ Created patch file: {patch_file}")
            print(f"📦 Size: {len(patch_content)} bytes")
            print(f"\nTo apply:")
            print(f"  git apply {patch_file}")
            return patch_file
        else:
            print("⚠️  No changes detected in git. Files may already be committed.")
            print("Creating manual patch documentation instead...")
            return create_manual_patch_guide()
            
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"⚠️  Git not available: {e}")
        print("Creating manual patch documentation...")
        return create_manual_patch_guide()

def create_manual_patch_guide():
    """Create detailed manual patch guide when git isn't available"""
    
    guide = """# Manual Bug Fix Guide v0.27.1
# Apply these changes to fix 6 critical bugs

## Bug #2: Health Monitor Race Condition

### File: apps/proxy/live_proxy/input/manager.py

#### Change 1: Import and initialize Event objects (~line 1465)
FIND:
```python
        # Add flags for the main loop to check
        self.needs_reconnect = False
        self.needs_stream_switch = False
        self.last_health_action_time = 0
```

REPLACE WITH:
```python
        # Add flags for the main loop to check (using gevent-safe Event objects)
        import gevent.event
        self.needs_reconnect = gevent.event.Event()
        self.needs_stream_switch = gevent.event.Event()
        self.last_health_action_time = 0
```

#### Change 2: Use Event.set() in health monitor (~line 1494)
FIND:
```python
                        if stable_time >= 30:
                            if not self.needs_reconnect:
                                logger.info(f"Setting reconnect flag...")
                                self.needs_reconnect = True
                                self.last_health_action_time = now
                        else:
                            if not self.needs_stream_switch:
                                logger.info(f"Setting stream switch flag...")
                                self.needs_stream_switch = True
                                self.last_health_action_time = now
```

REPLACE WITH:
```python
                        if stable_time >= 30:
                            if not self.needs_reconnect.is_set():
                                logger.info(f"Setting reconnect flag...")
                                self.needs_reconnect.set()
                                self.last_health_action_time = now
                        else:
                            if not self.needs_stream_switch.is_set():
                                logger.info(f"Setting stream switch flag...")
                                self.needs_stream_switch.set()
                                self.last_health_action_time = now
```

#### Change 3: Use Event.clear() when healthy (~line 1509)
FIND:
```python
                    # Clear recovery flags when healthy again
                    self.needs_reconnect = False
                    self.needs_stream_switch = False
```

REPLACE WITH:
```python
                    # Clear recovery flags when healthy again
                    self.needs_reconnect.clear()
                    self.needs_stream_switch.clear()
```

#### Change 4: Use Event.is_set() in main loop (~line 392)
FIND:
```python
                if hasattr(self, 'needs_reconnect') and self.needs_reconnect and not self.url_switching:
                    logger.info(f"Health monitor requested reconnect...")
                    self.needs_reconnect = False
```

REPLACE WITH:
```python
                if hasattr(self, 'needs_reconnect') and self.needs_reconnect.is_set() and not self.url_switching:
                    logger.info(f"Health monitor requested reconnect...")
                    self.needs_reconnect.clear()
```

FIND:
```python
                        self.needs_stream_switch = True

                if hasattr(self, 'needs_stream_switch') and self.needs_stream_switch and not self.url_switching:
                    logger.info(f"Health monitor requested stream switch...")
                    self.needs_stream_switch = False
```

REPLACE WITH:
```python
                        self.needs_stream_switch.set()

                if hasattr(self, 'needs_stream_switch') and self.needs_stream_switch.is_set() and not self.url_switching:
                    logger.info(f"Health monitor requested stream switch...")
                    self.needs_stream_switch.clear()
```

#### Change 5: Update while condition (~line 435)
FIND:
```python
                while self.running and self.retry_count < self.max_retries and not url_failed and not self.needs_stream_switch:
```

REPLACE WITH:
```python
                while self.running and self.retry_count < self.max_retries and not url_failed and not self.needs_stream_switch.is_set():
```

#### Change 6: Update if condition (~line 475)
FIND:
```python
                            if self.needs_stream_switch:
```

REPLACE WITH:
```python
                            if self.needs_stream_switch.is_set():
```

#### Change 7: Update _process_stream_data (~line 1262)
FIND:
```python
            while self.running and self.connected and not self.stop_requested and not self.needs_stream_switch:
```

REPLACE WITH:
```python
            while self.running and self.connected and not self.stop_requested and not self.needs_stream_switch.is_set():
```

---

## Bug #3: FFmpeg Proxy Injection

### File: core/models.py (~line 148)

FIND:
```python
            except ValueError:
                # Kein -i gefunden, füge am Ende hinzu
                pass
```

REPLACE WITH:
```python
            except ValueError:
                # No -i flag found - append -http_proxy at end
                logger.warning(f"FFmpeg command has no -i flag, appending -http_proxy at end")
                cmd.extend(['-http_proxy', proxy])
```

---

## Bug #4: HTTPStreamReader Shutdown

### File: apps/proxy/live_proxy/input/http_streamer.py (~line 128)

FIND:
```python
        except (AttributeError, OSError) as e:
            # Catch race condition during shutdown - response might be None
            if self.running:
                logger.error(f"HTTP reader error: {e}")
                self.error_occurred = True
            # If not running, this is expected during cleanup
```

REPLACE WITH:
```python
        except AttributeError as e:
            if self.running:
                logger.error(f"HTTP reader AttributeError (unexpected): {e}")
                self.error_occurred = True
            else:
                logger.debug(f"HTTP reader AttributeError during shutdown (expected): {e}")
        except OSError as e:
            if self.running:
                logger.error(f"HTTP reader OSError: {e}")
                self.error_occurred = True
            else:
                logger.debug(f"HTTP reader OSError during shutdown (expected): {e}")
```

### Also in stop() method (~line 159):

FIND:
```python
        # Close response (but keep reference)
        if self.response:
            try:
                self.response.close()
            except:
                pass
```

REPLACE WITH:
```python
        # Close response (thread-safe check)
        if self.response:
            try:
                self.response.close()
                logger.debug("HTTP response closed successfully")
            except Exception as e:
                logger.debug(f"Error closing HTTP response (expected during shutdown): {e}")
```

ADD after thread.join():
```python
            if self.thread.is_alive():
                logger.warning("HTTP stream reader thread did not stop within timeout")
```

---

## Bug #5: Redis Error Handling

### File: apps/proxy/live_proxy/url_utils.py

#### Location 1: Stream preview profiles (~line 370)

FIND:
```python
                    except Exception as e:
                        # Redis error - assume profile is available (fail-open for resilience)
                        logger.warning(f"Redis error checking profile {profile.id} connections: {e}, assuming available")
                        alternate_profiles.append({
                            'stream_id': stream.id,
                            'profile_id': profile.id,
                            'name': stream.name
                        })
```

REPLACE WITH:
```python
                    except (TypeError, ValueError, KeyError) as e:
                        # Programming error - should not happen, fail loudly
                        logger.error(f"Programming error checking profile {profile.id}: {e}", exc_info=True)
                        # Don't add profile - this is a real bug that needs attention
                    except Exception as e:
                        # Redis connection error or other infrastructure issue - fail-open for resilience
                        logger.error(f"Redis error checking profile {profile.id} connections: {e}, assuming available for resilience")
                        alternate_profiles.append({
                            'stream_id': stream.id,
                            'profile_id': profile.id,
                            'name': stream.name
                        })
```

#### Location 2: Channel profiles (~line 478)

FIND:
```python
                            alternate_streams.append({
                                'stream_id': stream.id,
                                'profile_id': profile.id,
                                'name': stream.name
                            })
                            # DON'T break - continue to check other profiles!
```

REPLACE WITH:
```python
                            try:
                                current_connections = get_profile_connection_count(
                                    profile, redis_client
                                )
                                # BUGFIX: Don't break here - add ALL available profiles!
                                logger.debug(
                                    f"Found available profile {profile.id} for stream {stream.id}: "
                                    f"{current_connections}/{profile.max_streams} "
                                    f"(already using: {channel_using_profile})"
                                )
                                alternate_streams.append({
                                    'stream_id': stream.id,
                                    'profile_id': profile.id,
                                    'name': stream.name
                                })
                                # DON'T break - continue to check other profiles!
                            except (TypeError, ValueError, KeyError) as e:
                                # Programming error - should not happen
                                logger.error(f"Programming error checking profile {profile.id} for stream {stream.id}: {e}", exc_info=True)
                            except Exception as e:
                                # Redis or infrastructure error - fail-open for resilience
                                logger.error(f"Redis error checking profile {profile.id} for stream {stream.id}: {e}, assuming available for resilience")
                                alternate_streams.append({
                                    'stream_id': stream.id,
                                    'profile_id': profile.id,
                                    'name': stream.name
                                })
```

---

## Bug #7: Redis Scan Optimization

### File: apps/proxy/live_proxy/input/manager.py (~line 2056)

FIND:
```python
                        cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
                        cursor = 0
                        deleted = 0
                        max_iterations = 1000
                        iterations = 0
                        
                        while iterations < max_iterations:
                            cursor, keys = self.buffer.redis_client.scan(cursor, match=cooldown_pattern, count=100)
                            if keys:
                                self.buffer.redis_client.delete(*keys)
                                deleted += len(keys)
                            if cursor == 0:
                                break
                            iterations += 1
                        
                        if iterations >= max_iterations:
                            logger.warning(f"Last resort scan reached max iterations ({max_iterations}) for channel {self.channel_id}")
```

REPLACE WITH:
```python
                        cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
                        deleted = 0
                        
                        # Use scan_iter for safer iteration (handles cursor automatically)
                        for key in self.buffer.redis_client.scan_iter(match=cooldown_pattern, count=100):
                            self.buffer.redis_client.delete(key)
                            deleted += 1
                            
                            # Safety limit - if we're deleting more than 1000 keys, something is wrong
                            if deleted > 1000:
                                logger.error(f"Last resort deleted {deleted} cooldowns - possible key explosion! Stopping cleanup.")
                                break
```

---

## Bug #8: tried_combinations Reset

### File: apps/proxy/live_proxy/input/manager.py

#### Change 1: Initialize reset timer (~line 76)

FIND:
```python
        self.tried_combinations = set()
        self.tried_stream_ids = set()
        self.last_stream_switch_time = 0
```

REPLACE WITH:
```python
        self.tried_combinations = set()
        self.tried_stream_ids = set()
        self.last_stream_switch_time = 0
        self.tried_combinations_reset_time = time.time() + 3600  # Reset every hour
```

#### Change 2: Add hourly reset in run() loop (~line 388)

FIND:
```python
                # Check for stuck switching state
                if self.url_switching and time.time() - self.url_switch_start_time > self.url_switch_timeout:
                    logger.warning(f"URL switching state appears stuck...")
                    self._reset_url_switching_state()

                # NEW: Check for health monitor recovery requests
```

REPLACE WITH:
```python
                # Check for stuck switching state
                if self.url_switching and time.time() - self.url_switch_start_time > self.url_switch_timeout:
                    logger.warning(f"URL switching state appears stuck...")
                    self._reset_url_switching_state()

                # Periodic reset of tried_combinations (every hour)
                if time.time() > self.tried_combinations_reset_time and len(self.tried_combinations) > 0:
                    logger.info(f"Hourly tried_combinations reset for channel {self.channel_id} - clearing {len(self.tried_combinations)} entries")
                    self.tried_combinations.clear()
                    self.tried_combinations_reset_time = time.time() + 3600

                # NEW: Check for health monitor recovery requests
```

#### Change 3: Add stability reset in _process_stream_data (~line 1262)

FIND:
```python
    def _process_stream_data(self):
        """Process stream data until disconnect or error - unified path for both transcode and HTTP"""
        try:
            # Both transcode and HTTP now use the same subprocess/socket approach
            # This gives us perfect control: check flags between chunks, timeout just returns False
            while self.running and self.connected and not self.stop_requested and not self.needs_stream_switch.is_set():
                if self.fetch_chunk():
                    self.last_data_time = time.time()
                else:
```

REPLACE WITH:
```python
    def _process_stream_data(self):
        """Process stream data until disconnect or error - unified path for both transcode and HTTP"""
        try:
            # Both transcode and HTTP now use the same subprocess/socket approach
            # This gives us perfect control: check flags between chunks, timeout just returns False
            stable_streaming_reset_done = False  # Track if we've done the success-based reset
            
            while self.running and self.connected and not self.stop_requested and not self.needs_stream_switch.is_set():
                if self.fetch_chunk():
                    self.last_data_time = time.time()
                    
                    # Success-based reset: clear tried_combinations after 5 minutes of stable streaming
                    if not stable_streaming_reset_done and len(self.tried_combinations) > 0:
                        connection_duration = self.last_data_time - getattr(self, 'connection_start_time', self.last_data_time)
                        if connection_duration > 300:  # 5 minutes
                            logger.info(f"Stream stable for {connection_duration:.0f}s - clearing {len(self.tried_combinations)} tried combinations for channel {self.channel_id}")
                            self.tried_combinations.clear()
                            stable_streaming_reset_done = True
                else:
```

#### Change 4: Add reset on stop() (~line 1321)

FIND:
```python
    def stop(self):
        """Stop the stream manager and cancel all timers"""
        logger.info(f"Stopping stream manager for channel {self.channel_id}")

        self.stopping = True
        self._invalidate_ownership_cache()
        if self.buffer is not None:
            self.buffer.stopping = True

        # Cancel all buffer check timers
```

REPLACE WITH:
```python
    def stop(self):
        """Stop the stream manager and cancel all timers"""
        logger.info(f"Stopping stream manager for channel {self.channel_id}")

        self.stopping = True
        self._invalidate_ownership_cache()
        if self.buffer is not None:
            self.buffer.stopping = True

        # Clear tried_combinations when channel stops - allow fresh start on restart
        if hasattr(self, 'tried_combinations') and len(self.tried_combinations) > 0:
            logger.info(f"Clearing {len(self.tried_combinations)} tried combinations on channel stop for {self.channel_id}")
            self.tried_combinations.clear()

        # Cancel all buffer check timers
```

---

## Testing After Applying Patches

Run these tests to verify all fixes:

```bash
# 1. Check Python syntax
python3 -m py_compile apps/proxy/live_proxy/input/manager.py
python3 -m py_compile apps/proxy/live_proxy/input/http_streamer.py
python3 -m py_compile apps/proxy/live_proxy/url_utils.py
python3 -m py_compile core/models.py

# 2. Restart Dispatcharr
docker-compose restart  # or your restart method

# 3. Monitor logs
tail -f logs/dispatcharr.log | grep -E "Event|tried_combinations|http_proxy"
```

---

## Verification Checklist

- [ ] All files compile without syntax errors
- [ ] No import errors on startup
- [ ] Health monitor logs show Event operations
- [ ] FFmpeg commands include -http_proxy when configured
- [ ] tried_combinations reset logs appear after 1 hour
- [ ] No race condition warnings in logs
- [ ] Redis errors properly categorized

---

**All changes applied successfully = Ready for v0.27.1! ✅**
"""
    
    guide_file = "MANUAL_BUGFIX_GUIDE_v0.27.1.md"
    with open(guide_file, 'w', encoding='utf-8') as f:
        f.write(guide)
    
    print(f"✅ Created manual patch guide: {guide_file}")
    print(f"📦 Size: {len(guide)} bytes")
    print(f"\nReview the guide and apply changes manually to each file.")
    return guide_file

if __name__ == "__main__":
    result = create_patch()
    print(f"\n🎉 Done! Created: {result}")
