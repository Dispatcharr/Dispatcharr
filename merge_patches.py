#!/usr/bin/env python3
"""Merge all patches into one ultimate patch file"""

patches = [
    'dispatcharr_v0.26.0_COMPLETE_FIX.patch',
    'dispatcharr_v0.25.1_enhancements.patch',
    'dispatcharr_v0.26.0_uuid_logging_fix.patch',
]

output = 'dispatcharr_v0.26.0_ULTIMATE.patch'

with open(output, 'w', encoding='utf-8') as out:
    for patch_file in patches:
        print(f"Adding {patch_file}...")
        with open(patch_file, 'r', encoding='utf-8') as f:
            content = f.read()
            out.write(content)
            out.write('\n\n')
            out.write('='*80)
            out.write('\n\n')

print(f"\nCreated {output}")
print("This file contains ALL fixes and enhancements!")
