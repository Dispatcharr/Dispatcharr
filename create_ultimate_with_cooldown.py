#!/usr/bin/env python3
"""
Merge all patches including cooldown system into ONE ultimate patch
"""

import os

# List of patch files to merge (in order)
PATCH_FILES = [
    "dispatcharr_v0.26.0_COMPLETE_FIX.patch",
    "dispatcharr_v0.25.1_enhancements.patch",
    "dispatcharr_v0.26.0_cooldown_system.patch",
]

OUTPUT_FILE = "dispatcharr_v0.26.0_ULTIMATE_WITH_COOLDOWN.patch"

def main():
    merged_content = []
    
    for patch_file in PATCH_FILES:
        if not os.path.exists(patch_file):
            print(f"WARNING: {patch_file} not found, skipping...")
            continue
            
        print(f"Adding {patch_file}...")
        with open(patch_file, 'r', encoding='utf-8') as f:
            content = f.read()
            merged_content.append(f"\n# ===== FROM: {patch_file} =====\n")
            merged_content.append(content)
    
    # Write merged patch
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(''.join(merged_content))
    
    print(f"\nCreated {OUTPUT_FILE}")
    print("This file contains ALL fixes, enhancements AND cooldown system!")

if __name__ == "__main__":
    main()
