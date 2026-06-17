#!/usr/bin/env python
import py_compile
import sys

files_to_check = [
    'apps/proxy/live_proxy/input/manager.py',
    'apps/proxy/live_proxy/url_utils.py',
    'apps/proxy/live_proxy/config_helper.py',
    'apps/proxy/live_proxy/redis_keys.py',
]

errors = []
for file in files_to_check:
    try:
        py_compile.compile(file, doraise=True)
        print(f"✓ {file}")
    except py_compile.PyCompileError as e:
        print(f"✗ {file}: {e}")
        errors.append((file, e))

if errors:
    print(f"\n{len(errors)} file(s) have syntax errors")
    sys.exit(1)
else:
    print(f"\nAll {len(files_to_check)} files passed syntax check")
    sys.exit(0)
