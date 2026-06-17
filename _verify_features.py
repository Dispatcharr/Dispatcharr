#!/usr/bin/env python3
"""Verify all features in Dispatcharr-0.27.0"""
import os

base = 'Dispatcharr-0.27.0'
results = []

def check(name, path, search, found_msg, missing_msg):
    full = os.path.join(base, path)
    if not os.path.exists(full):
        results.append((name, 'FILE NOT FOUND', missing_msg))
        return
    with open(full, 'r', encoding='utf-8', errors='replace') as f:
        c = f.read()
    if search in c:
        results.append((name, 'OK', found_msg))
    else:
        results.append((name, 'MISSING', missing_msg))

# F1: Docker Build Fix
check('F1: Docker Build Fix', 'pyproject.toml', 'django-db-geventpool>=4.0.8',
      'pyproject.toml has django-db-geventpool>=4.0.8', 'django-db-geventpool missing')

# F2: Profile Failover Fix 
check('F2: Profile Failover (current_profile_id)', 'apps/proxy/live_proxy/url_utils.py', 'current_profile_id',
      'current_profile_id parameter in get_alternate_streams()', 'Missing current_profile_id param')
check('F2: Profile Failover (no stream skip)', 'apps/proxy/live_proxy/url_utils.py', 'Do NOT skip the current stream',
      'Stream skip bug fixed', 'Stream skip bug STILL present')
check('F2: Profile Failover (all profiles)', 'apps/proxy/live_proxy/url_utils.py', 'Try ALL profiles',
      'All profiles per stream tried', 'Still only first profile tried')

# F3: HTTP Proxy Support
check('F3: HTTP Proxy field', 'apps/m3u/models.py', 'proxy = models.CharField',
      'proxy field in M3UAccount', 'proxy field missing')

# F4: proxy_for_api
check('F4: proxy_for_api field', 'apps/m3u/models.py', 'proxy_for_api = models.BooleanField',
      'proxy_for_api field present', 'proxy_for_api field missing')
check('F4: get_proxy_for_api()', 'apps/m3u/models.py', 'def get_proxy_for_api',
      'get_proxy_for_api() method present', 'get_proxy_for_api() missing')

# F5: Extended Timeouts
with open(os.path.join(base, 'core/models.py'), 'r', encoding='utf-8', errors='replace') as f:
    core_models = f.read()
timeout_settings = ['buffering_timeout', 'channel_shutdown_delay', 'channel_init_grace_period',
                    'max_retries', 'url_switch_timeout', 'connection_timeout',
                    'failover_grace_period', 'chunk_timeout', 'health_check_interval',
                    'stream_cooldown_enabled', 'stream_cooldown_minutes']
found_all = all(s in core_models for s in timeout_settings)
if found_all:
    results.append(('F5: Extended Timeouts', 'OK', f'All {len(timeout_settings)} settings in get_proxy_settings()'))
else:
    missing = [s for s in timeout_settings if s not in core_models]
    results.append(('F5: Extended Timeouts', 'MISSING', f'Missing: {missing}'))

# F6: build_command Proxy-Fix
check('F6: build_command proxy param', 'core/models.py', 'proxy=None',
      'proxy=None parameter in build_command()', 'Missing proxy=None param')
check('F6: http_proxy injection', 'core/models.py', '-http_proxy',
      'ffmpeg -http_proxy injection present', 'Missing -http_proxy injection')

# F7: UUID Validation
check('F7: UUID Validation', 'core/utils.py', 'uuid as uuid_module',
      'uuid_module.UUID() check in log_system_event()', 'Missing UUID validation')

# F8: Adaptive Health Monitor
check('F8: Adaptive Health (last_stream_switch_time)', 'apps/proxy/live_proxy/input/manager.py', 'last_stream_switch_time = 0',
      'last_stream_switch_time initialized', 'Missing last_stream_switch_time')
check('F8: Adaptive Health (last_health_action_time)', 'apps/proxy/live_proxy/input/manager.py', 'last_health_action_time',
      'last_health_action_time tracking present', 'Missing last_health_action_time')

# F9: HTTP Proxy Timeout Failover
check('F9: HTTP Proxy Timeout (error_occurred)', 'apps/proxy/live_proxy/input/http_streamer.py', 'error_occurred',
      'error_occurred flag present', 'Missing error_occurred flag')

# F10: Race Condition Fix
check('F10: Race Condition (needs_stream_switch)', 'apps/proxy/live_proxy/input/manager.py', 'needs_stream_switch',
      'needs_stream_switch flag present', 'Missing needs_stream_switch')
check('F10: Race Condition (needs_reconnect)', 'apps/proxy/live_proxy/input/manager.py', 'needs_reconnect',
      'needs_reconnect flag present', 'Missing needs_reconnect')

# F11: Stream Cooldown System
check('F11: Cooldown (Redis key)', 'apps/proxy/live_proxy/redis_keys.py', 'def stream_cooldown',
      'stream_cooldown() Redis key method', 'Missing stream_cooldown()')
check('F11: Cooldown (set/check)', 'apps/proxy/live_proxy/input/manager.py', 'stream_cooldown',
      'Cooldown set + check in manager.py', 'Missing cooldown logic')
check('F11: Cooldown (LAST RESORT)', 'apps/proxy/live_proxy/input/manager.py', 'LAST RESORT',
      'LAST RESORT fallback present', 'Missing LAST RESORT fallback')
check('F11: Cooldown (config)', 'core/models.py', 'stream_cooldown_enabled',
      'Cooldown config in get_proxy_settings()', 'Missing cooldown config')
check('F11: Cooldown (ConfigHelper)', 'apps/proxy/live_proxy/config_helper.py', 'stream_cooldown_enabled',
      'ConfigHelper has stream_cooldown_enabled()', 'Missing ConfigHelper methods')

# F12: Logo Timeout Fix
with open(os.path.join(base, 'apps/channels/api_views.py'), 'r', encoding='utf-8', errors='replace') as f:
    api_views = f.read()
if 'timeout=(10, 15)' in api_views:
    results.append(('F12: Logo Timeout Fix', 'OK', 'timeout=(10, 15) - FIXED'))
elif 'timeout=(3, 5)' in api_views:
    results.append(('F12: Logo Timeout Fix', 'MISSING', 'Still timeout=(3, 5) - NOT fixed'))
else:
    results.append(('F12: Logo Timeout Fix', 'UNKNOWN', 'Cannot determine timeout value'))

# F13: Basic Authentication
check('F13: Basic Auth (get_basic_auth_user)', 'apps/output/views.py', 'get_basic_auth_user',
      'get_basic_auth_user() found', 'get_basic_auth_user() missing')
check('F13: Basic Auth (require_basic_auth)', 'apps/output/views.py', 'require_basic_auth',
      'require_basic_auth() found', 'require_basic_auth() missing')

# F14: Stream Preview Profile Failover
# Check if get_alternate_streams has Stream preview support
with open(os.path.join(base, 'apps/proxy/live_proxy/url_utils.py'), 'r', encoding='utf-8', errors='replace') as f:
    url_utils = f.read()
if 'Stream preview' in url_utils or 'Stream Preview' in url_utils or 'stream_hash' in url_utils:
    results.append(('F14: Stream Preview Failover', 'OK', 'Stream preview profile failover found'))
else:
    results.append(('F14: Stream Preview Failover', 'MISSING', 
                    'get_alternate_streams still returns [] for Stream objects'))

# F15: Buffer Timeout Failover
check('F15: Buffer Timeout (chunk_timeout)', 'core/models.py', 'chunk_timeout',
      'chunk_timeout setting present', 'Missing chunk_timeout')
check('F15: Buffer Timeout (buffering_timeout)', 'core/models.py', 'buffering_timeout',
      'buffering_timeout setting present', 'Missing buffering_timeout')

# Print results
print('=' * 70)
print('FEATURE VERIFICATION: Dispatcharr-0.27.0')
print('=' * 70)
total = len(results)
ok = sum(1 for _, s, _ in results if s == 'OK')
missing = sum(1 for _, s, _ in results if s in ('MISSING', 'UNKNOWN', 'FILE NOT FOUND'))

for name, status, msg in results:
    icon = '✅' if status == 'OK' else '❌'
    print(f'{icon} {name}')
    if status != 'OK':
        print(f'   → {msg}')

print()
print('=' * 70)
print(f'SUMMARY: {ok}/{total} checks passed, {missing} failed')
print('=' * 70)