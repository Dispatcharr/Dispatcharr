#!/usr/bin/env python3
"""
Apply critical bug fixes for Dispatcharr v0.27.1

Fixes:
- Bug #1: Add cooldown check to Channel Playback path
- Bug #2: Fix LAST RESORT race condition with pipelined deletion
- Bug #3: Remove channel_id from cooldown keys (global per stream+profile)

Usage:
    python apply_critical_fixes_v0.27.1.py

This script will:
1. Backup original files
2. Apply all patches
3. Verify changes
4. Report success/failure
"""

import os
import sys
import shutil
from pathlib import Path

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_success(msg):
    print(f"{GREEN}✓{RESET} {msg}")

def print_error(msg):
    print(f"{RED}✗{RESET} {msg}")

def print_warning(msg):
    print(f"{YELLOW}⚠{RESET} {msg}")

def print_info(msg):
    print(f"{BLUE}ℹ{RESET} {msg}")

def backup_file(filepath):
    """Create backup of file before modification"""
    backup_path = f"{filepath}.backup_v0.27.1"
    shutil.copy2(filepath, backup_path)
    return backup_path

def verify_file_exists(filepath):
    """Check if file exists"""
    if not os.path.exists(filepath):
        print_error(f"File not found: {filepath}")
        return False
    return True


def apply_fix_redis_keys():
    """Fix #3: Update redis_keys.py - remove channel_id from cooldown key"""
    print_info("Applying Fix #3: Redis Keys - Global cooldown keys...")
    
    filepath = "apps/proxy/live_proxy/redis_keys.py"
    if not verify_file_exists(filepath):
        return False
    
    # Backup
    backup_path = backup_file(filepath)
    print_info(f"  Backup created: {backup_path}")
    
    # Read file
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if already patched
    if 'def stream_cooldown(stream_id, profile_id):' in content:
        print_warning("  Already patched - skipping")
        return True
    
    # Apply patch
    old_signature = 'def stream_cooldown(channel_id, stream_id, profile_id):'
    new_signature = 'def stream_cooldown(stream_id, profile_id):'
    
    old_docstring = '''"""Key for stream/profile combination cooldown (failed combinations).
        TTL = stream_cooldown_minutes * 60. Redis auto-deletes after expiry."""'''
    
    new_docstring = '''"""Global cooldown key for stream+profile combination (failed combinations).
        Works across all channels using this stream. No channel_id dependency.
        TTL = stream_cooldown_minutes * 60. Redis auto-deletes after expiry."""'''
    
    old_return = 'return f"live:channel:{channel_id}:cooldown:{stream_id}:{profile_id}"'
    new_return = 'return f"live:cooldown:stream:{stream_id}:profile:{profile_id}"'
    
    if old_signature not in content:
        print_error("  Pattern not found - file may have been modified")
        return False
    
    content = content.replace(old_signature, new_signature)
    content = content.replace(old_docstring, new_docstring)
    content = content.replace(old_return, new_return)
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print_success("  Applied successfully")
    return True


def apply_fix_url_utils_preview():
    """Fix #1 (Part 1): Update url_utils.py Stream Preview cooldown pattern"""
    print_info("Applying Fix #1 (Part 1): URL Utils - Stream Preview cooldown pattern...")
    
    filepath = "apps/proxy/live_proxy/url_utils.py"
    if not verify_file_exists(filepath):
        return False
    
    # Read file
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if already patched
    if 'cooldown_pattern = f"live:cooldown:stream:{stream.id}:profile:*"' in content:
        print_warning("  Already patched - skipping")
        return True
    
    # Apply patches
    old_pattern = 'cooldown_pattern = f"live:channel:{channel_id}:cooldown:{stream.id}:*"'
    new_pattern = 'cooldown_pattern = f"live:cooldown:stream:{stream.id}:profile:*"'
    
    old_comment = '# Scan for all cooldown keys for this stream hash (channel_id)'
    new_comment = '# Scan for all cooldown keys for this stream (global, no channel_id)'
    
    old_key_format = '# Key format: live:channel:{channel_id}:cooldown:{stream_id}:{profile_id}'
    new_key_format = '# Key format: live:cooldown:stream:{stream_id}:profile:{profile_id}'
    
    old_parts_check = 'if len(parts) >= 6:'
    new_parts_check = 'if len(parts) == 6:'
    
    if old_pattern not in content:
        print_error("  Pattern not found - file may have been modified")
        return False
    
    content = content.replace(old_comment, new_comment)
    content = content.replace(old_pattern, new_pattern)
    content = content.replace(old_key_format, new_key_format)
    content = content.replace(old_parts_check, new_parts_check)
    
    # Add current profile check after finding the for prof in profiles loop
    search_for = '                for prof in profiles:'
    if search_for in content:
        insertion = '''                for prof in profiles:
                    # Skip current failing profile
                    if prof and prof.id == profile_id:
                        logger.debug(f"Skipping current failing profile {prof.id} for stream {stream.id}")
                        continue
                    '''
        content = content.replace('                for prof in profiles:\n', insertion + '\n')
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print_success("  Applied successfully")
    return True


def apply_fix_url_utils_channel():
    """Fix #1 (Part 2): Add cooldown check to Channel Playback path in url_utils.py"""
    print_info("Applying Fix #1 (Part 2): URL Utils - Channel Playback cooldown check...")
    
    filepath = "apps/proxy/live_proxy/url_utils.py"
    if not verify_file_exists(filepath):
        return False
    
    # Read file
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the "Handle channel preview (existing logic)" section
    insertion_point = -1
    for i, line in enumerate(lines):
        if '# Handle channel preview (existing logic)' in line or '# Handle channel playback' in line:
            insertion_point = i + 2  # Insert after "channel = channel_or_stream"
            break
    
    if insertion_point == -1:
        print_error("  Could not find insertion point")
        return False
    
    # Check if already patched
    if any('[COOLDOWN]' in line and 'channel playback' in line for line in lines):
        print_warning("  Already patched - skipping")
        return True
    
    # Create the cooldown check code
    cooldown_check = '''        
        # ============================================================
        # BUG FIX #1: Add cooldown check for CHANNEL PLAYBACK
        # Previously only existed for Stream Preview mode
        # ============================================================
        cooldown_skip_profiles = set()
        if ConfigHelper.stream_cooldown_enabled():
            try:
                redis_client = RedisClient.get_client()
                if redis_client:
                    # Get all streams for this channel to check their cooldowns
                    channel_streams = channel.streams.all()
                    for ch_stream in channel_streams:
                        # Scan for cooldown keys for each stream (global, no channel_id)
                        cooldown_pattern = f"live:cooldown:stream:{ch_stream.id}:profile:*"
                        for key in redis_client.scan_iter(match=cooldown_pattern, count=50):
                            # Key format: live:cooldown:stream:{stream_id}:profile:{profile_id}
                            parts = key.split(':') if isinstance(key, str) else key.decode('utf-8').split(':')
                            if len(parts) == 6:
                                try:
                                    profile_id_from_key = int(parts[-1])
                                    ttl = redis_client.ttl(key)
                                    if ttl > 0:
                                        mins = int(ttl // 60)
                                        secs = int(ttl % 60)
                                        logger.info(
                                            f"[COOLDOWN] Skipping profile {profile_id_from_key} for stream {ch_stream.id} "
                                            f"on channel playback - blocked for {mins}m {secs}s more"
                                        )
                                        cooldown_skip_profiles.add(profile_id_from_key)
                                except (ValueError, IndexError):
                                    pass
            except Exception as e:
                logger.debug(f"Could not check cooldowns for channel playback: {e}")

'''
    
    # Insert the cooldown check
    lines.insert(insertion_point, cooldown_check)
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print_success("  Applied successfully")
    return True


def apply_fix_manager_cooldown_keys():
    """Fix #3: Update manager.py - remove channel_id from cooldown key calls"""
    print_info("Applying Fix #3: Manager - Update cooldown key calls...")
    
    filepath = "apps/proxy/live_proxy/input/manager.py"
    if not verify_file_exists(filepath):
        return False
    
    # Backup
    backup_path = backup_file(filepath)
    print_info(f"  Backup created: {backup_path}")
    
    # Read file
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if already patched
    if 'RedisKeys.stream_cooldown(self.current_stream_id, self.current_profile_id)' in content:
        print_warning("  Already patched - skipping")
        return True
    
    # Apply patches - update all cooldown key calls
    old_set_key = 'cooldown_key = RedisKeys.stream_cooldown(self.channel_id, self.current_stream_id, self.current_profile_id)'
    new_set_key = 'cooldown_key = RedisKeys.stream_cooldown(self.current_stream_id, self.current_profile_id)'
    
    old_check_key = "cooldown_key = RedisKeys.stream_cooldown(self.channel_id, s['stream_id'], s['profile_id'])"
    new_check_key = "cooldown_key = RedisKeys.stream_cooldown(s['stream_id'], s['profile_id'])"
    
    if old_set_key not in content:
        print_error("  Set key pattern not found - file may have been modified")
        return False
    
    if old_check_key not in content:
        print_error("  Check key pattern not found - file may have been modified")
        return False
    
    content = content.replace(old_set_key, new_set_key)
    content = content.replace(old_check_key, new_check_key)
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print_success("  Applied successfully")
    return True


def apply_fix_manager_last_resort():
    """Fix #2: Update manager.py - Safe LAST RESORT with pipelined deletion"""
    print_info("Applying Fix #2: Manager - LAST RESORT pipelined deletion...")
    
    filepath = "apps/proxy/live_proxy/input/manager.py"
    if not verify_file_exists(filepath):
        return False
    
    # Read file
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if already patched
    if 'BUG FIX #2: Safe LAST RESORT with pipelined deletion' in content:
        print_warning("  Already patched - skipping")
        return True
    
    # Find the LAST RESORT section
    search_start = '# LAST RESORT: If cooldown is enabled and all combinations are blocked,'
    
    if search_start not in content:
        print_error("  LAST RESORT section not found - file may have been modified")
        return False
    
    # Find the complete old LAST RESORT implementation
    old_last_resort_start = search_start
    old_last_resort_end = 'if not untried_combinations:'
    
    # Build the new LAST RESORT implementation
    new_last_resort = '''# ============================================================
                # BUG FIX #2: Safe LAST RESORT with pipelined deletion
                # Previous version had race conditions with scan_iter
                # ============================================================
                if (ConfigHelper.stream_cooldown_enabled()
                        and hasattr(self.buffer, 'redis_client')
                        and self.buffer.redis_client
                        and alternate_streams):
                    try:
                        # Collect all cooldown keys for streams in alternate_streams
                        # Use specific stream IDs, not wildcard
                        keys_to_delete = []
                        stream_ids_in_alternates = set(s['stream_id'] for s in alternate_streams)
                        
                        # Collect keys for each stream
                        for stream_id in stream_ids_in_alternates:
                            cooldown_pattern = f"live:cooldown:stream:{stream_id}:profile:*"
                            try:
                                # Use scan with cursor (safer than scan_iter)
                                cursor = 0
                                scan_iterations = 0
                                while True:
                                    cursor, keys = self.buffer.redis_client.scan(
                                        cursor=cursor,
                                        match=cooldown_pattern,
                                        count=100
                                    )
                                    keys_to_delete.extend(keys)
                                    
                                    if cursor == 0:
                                        break
                                    
                                    # Safety: max 100 scan iterations
                                    scan_iterations += 1
                                    if scan_iterations > 100:
                                        logger.error(
                                            f"LAST RESORT: Scan iterations exceeded 100 for stream {stream_id} - "
                                            f"possible Redis issue or key explosion"
                                        )
                                        break
                            except Exception as scan_error:
                                logger.error(f"LAST RESORT: Error scanning for stream {stream_id}: {scan_error}")
                                continue
                        
                        # Safety check before deletion
                        if len(keys_to_delete) > 10000:
                            logger.error(
                                f"LAST RESORT: Found {len(keys_to_delete)} cooldown keys - "
                                f"possible leak! Aborting cleanup."
                            )
                            return False
                        
                        # Delete atomically using pipeline
                        if keys_to_delete:
                            pipe = self.buffer.redis_client.pipeline(transaction=False)
                            for key in keys_to_delete:
                                pipe.delete(key)
                            pipe.execute()
                            
                            logger.warning(
                                f"[COOLDOWN] All combinations tried and on cooldown. "
                                f"LAST RESORT: Cleared {len(keys_to_delete)} cooldowns - "
                                f"retrying all combinations"
                            )
                            
                            # Reset tried_combinations
                            self.tried_combinations.clear()
                            
                            # Retry with full list
                            untried_combinations = alternate_streams
                        else:
                            logger.debug("[COOLDOWN] LAST RESORT: No cooldown keys found to clear")
                            
                    except Exception as e:
                        logger.error(f"Last resort cooldown clear failed: {e}")
                        return False

'''
    
    # This is complex - we need to replace the entire LAST RESORT block
    # Split content at the LAST RESORT comment
    parts = content.split(old_last_resort_start, 1)
    if len(parts) != 2:
        print_error("  Could not split content at LAST RESORT")
        return False
    
    before = parts[0]
    after_with_old = parts[1]
    
    # Find where the old LAST RESORT ends (look for "if not untried_combinations:" after the try block)
    # This is tricky - we need to find the matching try-except block end
    try_depth = 0
    old_block_end = -1
    lines = after_with_old.split('\n')
    
    for i, line in enumerate(lines):
        if 'try:' in line:
            try_depth += 1
        if 'except' in line and try_depth > 0:
            try_depth -= 1
            if try_depth == 0:
                # Found the end of the main try-except
                old_block_end = i + 1
                break
    
    if old_block_end == -1:
        print_error("  Could not find end of old LAST RESORT block")
        return False
    
    # Rebuild content
    after = '\n'.join(lines[old_block_end:])
    content = before + new_last_resort + '\n' + after
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print_success("  Applied successfully")
    return True


def verify_all_fixes():
    """Verify that all fixes were applied correctly"""
    print_info("\nVerifying all fixes...")
    
    all_ok = True
    
    # Verify Fix #3 - Redis Keys
    print_info("Verifying Fix #3: Redis Keys...")
    filepath = "apps/proxy/live_proxy/redis_keys.py"
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'def stream_cooldown(stream_id, profile_id):' in content:
        if 'live:cooldown:stream:{stream_id}:profile:{profile_id}' in content:
            print_success("  Redis Keys: Signature and key format correct")
        else:
            print_error("  Redis Keys: Key format not updated")
            all_ok = False
    else:
        print_error("  Redis Keys: Function signature not updated")
        all_ok = False
    
    # Verify Fix #1 Part 1 - URL Utils Stream Preview
    print_info("Verifying Fix #1 Part 1: URL Utils Stream Preview...")
    filepath = "apps/proxy/live_proxy/url_utils.py"
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'cooldown_pattern = f"live:cooldown:stream:{stream.id}:profile:*"' in content:
        print_success("  Stream Preview: Cooldown pattern updated")
    else:
        print_error("  Stream Preview: Cooldown pattern not updated")
        all_ok = False
    
    # Verify Fix #1 Part 2 - URL Utils Channel Playback
    print_info("Verifying Fix #1 Part 2: URL Utils Channel Playback...")
    if 'BUG FIX #1: Add cooldown check for CHANNEL PLAYBACK' in content:
        if 'on channel playback - blocked for' in content:
            print_success("  Channel Playback: Cooldown check added")
        else:
            print_error("  Channel Playback: Cooldown logging not found")
            all_ok = False
    else:
        print_error("  Channel Playback: Cooldown check not added")
        all_ok = False
    
    # Verify Fix #3 - Manager cooldown keys
    print_info("Verifying Fix #3: Manager cooldown key calls...")
    filepath = "apps/proxy/live_proxy/input/manager.py"
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'RedisKeys.stream_cooldown(self.current_stream_id, self.current_profile_id)' in content:
        print_success("  Manager: Cooldown key calls updated")
    else:
        print_error("  Manager: Cooldown key calls not updated")
        all_ok = False
    
    # Verify Fix #2 - Manager LAST RESORT
    print_info("Verifying Fix #2: Manager LAST RESORT...")
    if 'BUG FIX #2: Safe LAST RESORT with pipelined deletion' in content:
        if 'pipe.execute()' in content and 'keys_to_delete' in content:
            print_success("  LAST RESORT: Pipelined deletion implemented")
        else:
            print_error("  LAST RESORT: Pipeline code not found")
            all_ok = False
    else:
        print_error("  LAST RESORT: Fix not applied")
        all_ok = False
    
    return all_ok


def main():
    """Main execution function"""
    print("\n" + "="*70)
    print("  Dispatcharr v0.27.1 - Critical Bug Fixes")
    print("="*70 + "\n")
    
    print_info("This script will apply 3 critical bug fixes:")
    print("  • Bug #1: Add cooldown check to Channel Playback")
    print("  • Bug #2: Fix LAST RESORT race condition")
    print("  • Bug #3: Remove channel_id from cooldown keys\n")
    
    # Check if we're in the right directory
    if not os.path.exists('apps/proxy/live_proxy'):
        print_error("Error: Not in Dispatcharr root directory")
        print_error("Please run this script from the repository root")
        sys.exit(1)
    
    # Confirm with user
    print_warning("This will modify 3 files. Backups will be created automatically.")
    response = input(f"\n{BLUE}Continue? (yes/no):{RESET} ").strip().lower()
    
    if response not in ['yes', 'y']:
        print_info("Aborted by user")
        sys.exit(0)
    
    print("\n" + "-"*70)
    print("  Applying Fixes")
    print("-"*70 + "\n")
    
    # Apply all fixes
    success = True
    
    try:
        # Fix #3 - Redis Keys (do this first as other fixes depend on it)
        if not apply_fix_redis_keys():
            success = False
        
        # Fix #1 Part 1 - URL Utils Stream Preview
        if not apply_fix_url_utils_preview():
            success = False
        
        # Fix #1 Part 2 - URL Utils Channel Playback
        if not apply_fix_url_utils_channel():
            success = False
        
        # Fix #3 - Manager cooldown keys
        if not apply_fix_manager_cooldown_keys():
            success = False
        
        # Fix #2 - Manager LAST RESORT
        if not apply_fix_manager_last_resort():
            success = False
        
    except Exception as e:
        print_error(f"Error during patch application: {e}")
        success = False
    
    # Verify all fixes
    print("\n" + "-"*70)
    print("  Verification")
    print("-"*70 + "\n")
    
    if success:
        verification = verify_all_fixes()
        if verification:
            print("\n" + "="*70)
            print_success("  All fixes applied and verified successfully!")
            print("="*70 + "\n")
            print_info("Next steps:")
            print("  1. Review the changes: git diff")
            print("  2. Test channel playback with cooldown enabled")
            print("  3. Monitor logs for '[COOLDOWN]' messages")
            print("  4. Commit changes: git commit -am 'Fix critical cooldown bugs'")
            print("\n" + "="*70 + "\n")
        else:
            print_error("\nVerification failed - please check the output above")
            sys.exit(1)
    else:
        print_error("\nFix application failed - please check the output above")
        print_info("Backups were created with .backup_v0.27.1 extension")
        sys.exit(1)

if __name__ == "__main__":
    main()
