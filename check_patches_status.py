#!/usr/bin/env python3
"""Verify implemented patches in current directory"""
import os

def check_file(path, search_terms):
    """Check if file exists and contains all search terms"""
    if not os.path.exists(path):
        return False, "FILE NOT FOUND"
    
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        missing = []
        for term in search_terms:
            if term not in content:
                missing.append(term)
        
        if missing:
            return False, f"MISSING: {', '.join(missing[:3])}"
        return True, "OK"
    except Exception as e:
        return False, f"ERROR: {str(e)}"

# Feature checks
features = {
    "F1: Docker redis-django": {
        "file": "docker/DispatcharrBase",
        "terms": ["django-redis", "channels-redis"]
    },
    "F2: Docker redis-django (Dockerfile)": {
        "file": "docker/Dockerfile",
        "terms": ["django-redis", "channels-redis"]
    },
    "F3: M3U Proxy Fields": {
        "file": "apps/m3u/models.py",
        "terms": ["proxy = models.CharField", "proxy_for_api = models.BooleanField"]
    },
    "F4: M3U Proxy Methods": {
        "file": "apps/m3u/models.py",
        "terms": ["def get_proxy_for_api", "def get_proxy_for_streaming"]
    },
    "F5: Profile Failover - tried_combinations": {
        "file": "apps/proxy/live_proxy/input/manager.py",
        "terms": ["tried_combinations", "current_profile_id"]
    },
    "F6: Stream Cooldown - Redis Keys": {
        "file": "apps/proxy/live_proxy/redis_keys.py",
        "terms": ["stream_cooldown"]
    },
    "F7: Stream Cooldown - Manager": {
        "file": "apps/proxy/live_proxy/input/manager.py",
        "terms": ["stream_cooldown", "LAST RESORT"]
    },
    "F8: HTTP Proxy Integration - XC Client": {
        "file": "core/xtream_codes.py",
        "terms": ["proxy=None", "self.proxy"]
    },
    "F9: Extended Timeouts": {
        "file": "core/models.py",
        "terms": ["stream_cooldown_enabled", "stream_cooldown_minutes"]
    },
    "F10: UUID Validation Fix": {
        "file": "core/utils.py",
        "terms": ["uuid_module.UUID", "stream_hash"]
    }
}

print("="*70)
print("PATCH VERIFICATION REPORT")
print("="*70)

passed = 0
failed = 0

for name, config in features.items():
    ok, msg = check_file(config["file"], config["terms"])
    icon = "✅" if ok else "❌"
    print(f"\n{icon} {name}")
    print(f"   File: {config['file']}")
    print(f"   Status: {msg}")
    
    if ok:
        passed += 1
    else:
        failed += 1

print("\n" + "="*70)
print(f"SUMMARY: {passed} passed, {failed} failed out of {len(features)} checks")
print("="*70)

if failed > 0:
    print("\n⚠️  ATTENTION: Not all patches are implemented!")
    print("See failed checks above for details.")
else:
    print("\n🎉 All patches successfully implemented!")
