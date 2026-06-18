#!/usr/bin/env python3
"""Quick fix for manager.py cooldown bugs"""

import re

# Read the file
with open('apps/proxy/live_proxy/input/manager.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix #1: Update cooldown key creation (remove channel_id)
old_pattern1 = r'cooldown_key = RedisKeys\.stream_cooldown\(self\.channel_id, self\.current_stream_id, self\.current_profile_id\)'
new_pattern1 = r'cooldown_key = RedisKeys.stream_cooldown(self.current_stream_id, self.current_profile_id)'
content = re.sub(old_pattern1, new_pattern1, content)

# Fix #2: Update cooldown key checking (remove channel_id)
old_pattern2 = r'cooldown_key = RedisKeys\.stream_cooldown\(self\.channel_id, s\[\'stream_id\'\], s\[\'profile_id\'\]\)'
new_pattern2 = r"cooldown_key = RedisKeys.stream_cooldown(s['stream_id'], s['profile_id'])"
content = re.sub(old_pattern2, new_pattern2, content)

# Fix #3: Update cooldown pattern in LAST RESORT
old_pattern3 = r'cooldown_pattern = f"live:channel:\{self\.channel_id\}:cooldown:\*"'
new_pattern3 = r'cooldown_pattern = f"live:cooldown:stream:{stream_id}:profile:*"'
content = re.sub(old_pattern3, new_pattern3, content)

# Write back
with open('apps/proxy/live_proxy/input/manager.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ manager.py updated successfully")
