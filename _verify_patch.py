import re, sys

# ============================================================
# NACH JEDER IMPLEMENTIERUNG AUSFÜHREN: python _verify_patch.py
# Prüft alle Punkte aus dispatcharr_v0.21.1_enhancements.patch
# ============================================================

def check(pattern, filepath, label):
    try:
        with open(filepath, encoding='utf-8') as f:
            content = f.read()
        m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if m:
            line = content[:m.start()].count('\n') + 1
            print('  OK  L%-4d %s' % (line, label))
            return True
        else:
            print('FAIL        %s  [%s]' % (label, pattern[:60]))
            return False
    except FileNotFoundError:
        print('MISS        %s  [%s]' % (label, filepath))
        return False

r = []

# ============================================================
# ⚠️  BUGFIX 2 - WURDE ZWEIMAL VERGESSEN - IMMER ZUERST PRÜFEN
# ============================================================
# get_alternate_streams() darf den aktuellen Stream NICHT komplett
# ueberspringen. Nur die aktuelle Stream+Profil-Kombination ueberspringen.
# Symptom wenn vergessen: "No alternate streams found" obwohl Profile vorhanden.
print('--- BUGFIX2 (kritisch - wurde zweimal vergessen) ---')
r.append(check(r'Do NOT skip the current stream entirely', 'apps/proxy/ts_proxy/url_utils.py', 'BUGFIX2: kein full-stream skip in get_alternate_streams'))
r.append(check(r'stream\.id == current_stream_id and profile\.id == current_profile_id', 'apps/proxy/ts_proxy/url_utils.py', 'BUGFIX2: nur Kombination ueberspringen (nicht ganzen Stream)'))
# Sicherstellen dass der alte fehlerhafte continue NICHT mehr da ist
old_skip = check(r'if current_stream_id and stream\.id == current_stream_id:\s*\n\s*logger\.debug.*Skipping current stream', 'apps/proxy/ts_proxy/url_utils.py', 'BUGFIX2: alter fehlerhafter Stream-Skip (sollte FAIL = gut sein)')
if old_skip:
    print('  FEHLER: Alter fehlerhafter Stream-Skip ist noch vorhanden!')
    r.append(False)
else:
    print('  OK       BUGFIX2: alter fehlerhafter continue korrekt entfernt')
    r.append(True)
print()

# Feature 1: Logo Timeout
print('--- Feature 1: Logo Timeout ---')
r.append(check(r'timeout=\(10, 15\)', 'apps/channels/api_views.py', 'F1a: Logo timeout api_views'))
r.append(check(r'timeout=\(10, 15\)', 'apps/channels/tasks.py', 'F1b: Logo timeout tasks.py'))
print()

# Feature 2: Basic Auth
print('--- Feature 2: Basic Auth ---')
r.append(check(r'import base64', 'apps/output/views.py', 'F2a: import base64'))
r.append(check(r'from apps\.accounts\.models import User', 'apps/output/views.py', 'F2b: import User'))
r.append(check(r'def get_basic_auth_user', 'apps/output/views.py', 'F2c: get_basic_auth_user()'))
r.append(check(r'def require_basic_auth', 'apps/output/views.py', 'F2d: require_basic_auth()'))
r.append(check(r'user = get_basic_auth_user\(request\)', 'apps/output/views.py', 'F2e: Basic Auth in m3u_endpoint'))
r.append(check(r'def epg_endpoint.*?user = get_basic_auth_user', 'apps/output/views.py', 'F2f: Basic Auth in epg_endpoint'))
print()

# Feature 3: HTTP Proxy
print('--- Feature 3: HTTP Proxy ---')
r.append(check(r'proxy = models\.CharField', 'apps/m3u/models.py', 'F3a: proxy model field'))
r.append(check(r'"proxy"', 'apps/m3u/serializers.py', 'F3b: proxy in serializer fields'))
r.append(check(r'def build_command\(self.*proxy=None\)', 'core/models.py', 'F3c: build_command(proxy=None)'))
r.append(check(r'replacements\["\{proxy\}"\] = proxy', 'core/models.py', 'F3d: {proxy} replacement'))
r.append(check(r'def __init__\(self.*proxy=None\)', 'apps/proxy/ts_proxy/http_streamer.py', 'F3e: HTTPStreamReader proxy param'))
r.append(check(r'session\.proxies\s*=', 'apps/proxy/ts_proxy/http_streamer.py', 'F3f: session.proxies configured'))
r.append(check(r'Using proxy.*for channel', 'apps/proxy/ts_proxy/stream_manager.py', 'F3g: proxy in transcode path'))
r.append(check(r'Using HTTP proxy.*for channel', 'apps/proxy/ts_proxy/stream_manager.py', 'F3h: proxy in HTTP path'))
r.append(check(r'RunPython', 'apps/m3u/migrations/0020_m3uaccount_proxy.py', 'F3i: migration idempotent'))
r.append(check(r"proxy:\s*''", 'frontend/src/components/forms/M3U.jsx', 'F3j: proxy in initialValues'))
r.append(check(r'proxy:\s*m3uAccount\.proxy', 'frontend/src/components/forms/M3U.jsx', 'F3k: proxy in setValues'))
r.append(check(r'HTTP Proxy', 'frontend/src/components/forms/M3U.jsx', 'F3l: TextInput HTTP Proxy'))
print()

# Feature 4: Extended Timeouts
print('--- Feature 4: Extended Timeouts ---')
r.append(check(r'"max_retries":\s*2', 'apps/proxy/config.py', 'F4a: max_retries default'))
r.append(check(r'"url_switch_timeout":\s*20', 'apps/proxy/config.py', 'F4b: url_switch_timeout default'))
r.append(check(r'"max_stream_switches":\s*200', 'apps/proxy/config.py', 'F4c: max_stream_switches default'))
r.append(check(r'"connection_timeout":\s*10', 'apps/proxy/config.py', 'F4d: connection_timeout default'))
r.append(check(r'"failover_grace_period":\s*20', 'apps/proxy/config.py', 'F4e: failover_grace_period default'))
r.append(check(r'"chunk_timeout":\s*5', 'apps/proxy/config.py', 'F4f: chunk_timeout default'))
r.append(check(r'"initial_behind_chunks":\s*4', 'apps/proxy/config.py', 'F4g: initial_behind_chunks default'))
r.append(check(r'"health_check_interval":\s*5', 'apps/proxy/config.py', 'F4h: health_check_interval default'))
r.append(check(r'"stream_cooldown_enabled"', 'apps/proxy/config.py', 'F4i: stream_cooldown_enabled default'))
r.append(check(r'"stream_cooldown_minutes"', 'apps/proxy/config.py', 'F4j: stream_cooldown_minutes default'))
r.append(check(r'def connection_timeout', 'apps/proxy/ts_proxy/config_helper.py', 'F4k: connection_timeout DB-backed'))
r.append(check(r'def max_retries', 'apps/proxy/ts_proxy/config_helper.py', 'F4l: max_retries DB-backed'))
r.append(check(r'def max_stream_switches', 'apps/proxy/ts_proxy/config_helper.py', 'F4m: max_stream_switches DB-backed'))
r.append(check(r'def url_switch_timeout', 'apps/proxy/ts_proxy/config_helper.py', 'F4n: url_switch_timeout DB-backed'))
r.append(check(r'def failover_grace_period', 'apps/proxy/ts_proxy/config_helper.py', 'F4o: failover_grace_period DB-backed'))
r.append(check(r'def initial_behind_chunks', 'apps/proxy/ts_proxy/config_helper.py', 'F4p: initial_behind_chunks DB-backed'))
r.append(check(r'def chunk_timeout', 'apps/proxy/ts_proxy/config_helper.py', 'F4q: chunk_timeout DB-backed'))
r.append(check(r'def health_check_interval', 'apps/proxy/ts_proxy/config_helper.py', 'F4r: health_check_interval DB-backed'))
r.append(check(r'def stream_cooldown_enabled', 'apps/proxy/ts_proxy/config_helper.py', 'F4s: stream_cooldown_enabled()'))
r.append(check(r'def stream_cooldown_seconds', 'apps/proxy/ts_proxy/config_helper.py', 'F4t: stream_cooldown_seconds()'))
print()

# Feature 5: Profile Failover
print('--- Feature 5: Profile Failover ---')
r.append(check(r'self\.tried_combinations\s*=\s*set\(\)', 'apps/proxy/ts_proxy/stream_manager.py', 'F5a: tried_combinations set'))
r.append(check(r'self\.current_profile_id\s*=\s*None', 'apps/proxy/ts_proxy/stream_manager.py', 'F5b: current_profile_id init'))
r.append(check(r'Loaded profile ID', 'apps/proxy/ts_proxy/stream_manager.py', 'F5c: profile_id loaded from Redis'))
r.append(check(r'def get_alternate_streams.*current_profile_id', 'apps/proxy/ts_proxy/url_utils.py', 'F5d: get_alternate_streams has current_profile_id'))
r.append(check(r'Do NOT skip the current stream entirely', 'apps/proxy/ts_proxy/url_utils.py', 'F5e: BUGFIX2 no full-stream skip'))
r.append(check(r'def get_stream_info_for_profile', 'apps/proxy/ts_proxy/url_utils.py', 'F5f: get_stream_info_for_profile()'))
r.append(check(r'not in self\.tried_combinations', 'apps/proxy/ts_proxy/stream_manager.py', 'F5g: tried_combinations filter'))
r.append(check(r'get_stream_info_for_profile', 'apps/proxy/ts_proxy/stream_manager.py', 'F5h: uses get_stream_info_for_profile'))
print()

# Feature 6: Adaptive Health
print('--- Feature 6: Adaptive Health ---')
r.append(check(r'self\.last_stream_switch_time\s*=\s*0', 'apps/proxy/ts_proxy/stream_manager.py', 'F6a: last_stream_switch_time=0'))
r.append(check(r'self\.last_stream_switch_time\s*=\s*time\.time\(\)', 'apps/proxy/ts_proxy/stream_manager.py', 'F6b: last_stream_switch_time set'))
r.append(check(r'recently_switched\s*=\s*time_since_switch\s*<\s*30', 'apps/proxy/ts_proxy/stream_manager.py', 'F6c: adaptive thresholds'))
r.append(check(r'ConfigHelper\.health_check_interval\(\)', 'apps/proxy/ts_proxy/stream_manager.py', 'F6d: health_check_interval DB-backed'))
print()

# Feature 7: Stream Cooldown
print('--- Feature 7: Stream Cooldown ---')
r.append(check(r'def stream_cooldown\(', 'apps/proxy/ts_proxy/redis_keys.py', 'F7a: redis_keys.stream_cooldown()'))
r.append(check(r'COOLDOWN.*blocked for', 'apps/proxy/ts_proxy/stream_manager.py', 'F7b: cooldown set on failure'))
r.append(check(r'COOLDOWN.*Skipping stream', 'apps/proxy/ts_proxy/stream_manager.py', 'F7c: cooldown filter'))
r.append(check(r'Last resort', 'apps/proxy/ts_proxy/stream_manager.py', 'F7d: last resort clear'))
r.append(check(r'cooldown_prefix\s*=', 'apps/proxy/ts_proxy/server.py', 'F7e: server.py protects cooldown keys'))
print()

# Bugfixes
print('--- Bugfixes ---')
r.append(check(r'except \(AttributeError, TypeError\)', 'apps/proxy/ts_proxy/http_streamer.py', 'BF4: race condition fix'))
r.append(check(r'logger\.debug.*continuing to wait', 'apps/proxy/ts_proxy/views.py', 'BF5a: debug not info for wait'))
r.append(check(r'gevent\.sleep\(0\.1\)', 'apps/proxy/ts_proxy/views.py', 'BF5b: gevent.sleep(0.1)'))
r.append(check(r'Pre-set stream ID.*and profile ID', 'apps/proxy/ts_proxy/services/channel_service.py', 'BF6: profile_id before initialize_channel'))
r.append(check(r'COOLDOWN.*Skipping profile', 'apps/channels/models.py', 'BF7: cooldown check in Channel.get_stream() bei Neustart'))
print()

# Frontend
print('--- Frontend ---')
r.append(check(r'max_retries', 'frontend/src/constants.js', 'FE1: max_retries in constants'))
r.append(check(r'stream_cooldown_enabled', 'frontend/src/constants.js', 'FE2: stream_cooldown_enabled in constants'))
r.append(check(r'stream_cooldown_minutes', 'frontend/src/constants.js', 'FE3: stream_cooldown_minutes in constants'))
r.append(check(r'stream_cooldown_minutes.*1440', 'frontend/src/components/forms/settings/ProxySettingsForm.jsx', 'FE4: cooldown max 1440'))
r.append(check(r'isSelectField', 'frontend/src/components/forms/settings/ProxySettingsForm.jsx', 'FE5: isSelectField for cooldown'))
r.append(check(r'Select', 'frontend/src/components/forms/settings/ProxySettingsForm.jsx', 'FE6: Select component'))
r.append(check(r'stream_cooldown_enabled.*false', 'frontend/src/utils/forms/settings/ProxySettingsFormUtils.js', 'FE7: cooldown defaults'))
# chunk_batch_size sollte NICHT mehr vorhanden sein
cb_constants = check(r'chunk_batch_size', 'frontend/src/constants.js', 'FE8: chunk_batch_size (sollte FAIL = entfernt sein)')
cb_utils = check(r'chunk_batch_size', 'frontend/src/utils/forms/settings/ProxySettingsFormUtils.js', 'FE9: chunk_batch_size (sollte FAIL = entfernt sein)')
if cb_constants or cb_utils:
    print('  WARNUNG: chunk_batch_size noch vorhanden - sollte entfernt sein!')
    r.append(False)
else:
    print('  OK       chunk_batch_size korrekt entfernt')
    r.append(True)
print()

# Ergebnis
ok = sum(r)
total = len(r)
print('=' * 60)
print('%d/%d checks passed' % (ok, total))
print('=' * 60)

if ok < total:
    print()
    print('NICHT DEPLOYEN - fehlende Punkte oben beheben!')
    print('Besonders prüfen: BUGFIX2 (wurde zweimal vergessen!)')
    sys.exit(1)
else:
    print()
    print('Alle Checks bestanden - bereit zum Deployen.')
