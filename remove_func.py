#!/usr/bin/env python
# Remove get_stream_info_for_profile from url_utils.py

with open('apps/proxy/live_proxy/url_utils.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find where get_stream_info_for_profile starts
func_start = -1
for i, line in enumerate(lines):
    if line.strip().startswith('def get_stream_info_for_profile'):
        func_start = i
        break

if func_start > 0:
    # Remove everything from the function start onwards (it was appended at end)
    lines = lines[:func_start-1]  # -1 to also remove the empty line before it
    
    with open('apps/proxy/live_proxy/url_utils.py', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print(f"✓ Removed get_stream_info_for_profile starting at line {func_start+1}")
else:
    print("Function not found or already removed")
