"""Opaque HLS capability-URL sessions.

Playlist and segment URLs carry a random token, not a channel uuid or
XC credentials. Redis maps token -> channel_id + client_id with the same
TTL as the live client record.
"""

import secrets
import time

from ...config_helper import ConfigHelper
from ...redis_keys import RedisKeys

# 24 bytes -> 32 url-safe chars; enough to be unguessable as a capability URL.
_HLS_SESSION_TOKEN_BYTES = 24

# Response header on the HLS mint redirect. Intentionally not HLS-prefixed so
# a later non-HLS mint can reuse the same header name.
SESSION_TOKEN_HEADER = "X-Dispatcharr-Session-Token"

# Key shapes inlined into Lua below. Keep in sync with RedisKeys.
assert RedisKeys.client_metadata("C", "X") == "live:channel:C:clients:X"
assert RedisKeys.clients("C") == "live:channel:C:clients"
assert RedisKeys.channel_stopping("C") == "live:channel:C:stopping"
assert RedisKeys.client_stop("C", "X") == "live:channel:C:client:X:stop"
assert RedisKeys.hls_session("T") == "live:hls:session:T"

# Only write the session and client hls_token when the client hash still
# exists. Also drop any previous capability URL for this client so a remint
# cannot leave an orphan token alive until TTL.
_LUA_MINT_IF_CLIENT_EXISTS = """
local client_key = KEYS[1]
local session_key = KEYS[2]
if redis.call('EXISTS', client_key) == 0 then
  return 0
end
local old = redis.call('HGET', client_key, 'hls_token')
if old and old ~= false and old ~= ARGV[3] then
  redis.call('DEL', 'live:hls:session:' .. old)
end
redis.call(
  'HSET', session_key,
  'channel_id', ARGV[1],
  'client_id', ARGV[2],
  'user_id', ARGV[5]
)
redis.call('EXPIRE', session_key, tonumber(ARGV[4]))
redis.call('HSET', client_key, 'hls_token', ARGV[3])
redis.call('EXPIRE', client_key, tonumber(ARGV[4]))
return 1
"""

# Resolve the capability URL and refresh the live client in one eval so every
# playlist/segment poll is a single Redis round trip. Stop/liveness checks run
# before any HSET/SADD so a concurrent remove_client cannot be interleaved into
# a phantom consumer. The token must still be the one stored on the client hash
# so a replaced capability URL cannot keep refreshing after remint. Return codes:
# 0 expired, 1 stopped, 2 lapsed, 3 + channel_id + client_id + HGETALL fields.
_LUA_TOUCH_SESSION = """
local session_key = KEYS[1]
local channel_id = redis.call('HGET', session_key, 'channel_id')
local client_id = redis.call('HGET', session_key, 'client_id')
if (not channel_id) or channel_id == false or (not client_id) or client_id == false then
  redis.call('DEL', session_key)
  return {0}
end
local client_key = 'live:channel:' .. channel_id .. ':clients:' .. client_id
local clients_key = 'live:channel:' .. channel_id .. ':clients'
local stopping_key = 'live:channel:' .. channel_id .. ':stopping'
local client_stop_key = 'live:channel:' .. channel_id .. ':client:' .. client_id .. ':stop'
if redis.call('EXISTS', stopping_key) == 1 or redis.call('EXISTS', client_stop_key) == 1 then
  redis.call('DEL', session_key)
  return {1}
end
local hash = redis.call('HGETALL', client_key)
if #hash == 0 then
  redis.call('SREM', clients_key, client_id)
  redis.call('DEL', session_key)
  return {2}
end
local bound = redis.call('HGET', client_key, 'hls_token')
if bound ~= ARGV[3] then
  redis.call('DEL', session_key)
  return {0}
end
local ttl = tonumber(ARGV[2])
redis.call('HSET', client_key, 'last_active', ARGV[1])
redis.call('EXPIRE', client_key, ttl)
redis.call('SADD', clients_key, client_id)
redis.call('EXPIRE', clients_key, ttl)
redis.call('EXPIRE', session_key, ttl)
local reply = {3, channel_id, client_id}
for i = 1, #hash do
  reply[#reply + 1] = hash[i]
end
return reply
"""

# EVALSHA handles keyed by (redis client id, script name).
_script_cache = {}


def _script(redis_client, name, source):
    """EVALSHA handle cached per Redis client (script body sent once)."""
    cache_key = (id(redis_client), name)
    script = _script_cache.get(cache_key)
    if script is None:
        script = redis_client.register_script(source)
        _script_cache[cache_key] = script
    return script


def _lua_hash(fields):
    """Turn a Lua HGETALL array (or a mapping) into a dict."""
    if not fields:
        return {}
    if isinstance(fields, dict):
        return fields
    iterator = iter(fields)
    return dict(zip(iterator, iterator))


def mint_hls_session(redis_client, channel_id, client_id, user_id=None):
    """Create an opaque playlist/segment token bound to this live client.

    Returns the token, or None when Redis is unavailable or the client
    record is already gone. Also stores the token on the client hash so
    teardown can delete the session key. ``user_id`` is stored on the
    session hash for authenticated stop (anonymous uses ``"0"``).
    """
    if not redis_client:
        return None
    client_key = RedisKeys.client_metadata(channel_id, client_id)
    token = secrets.token_urlsafe(_HLS_SESSION_TOKEN_BYTES)
    ttl = ConfigHelper.get("CLIENT_RECORD_TTL", 60)
    session_key = RedisKeys.hls_session(token)
    user_id_str = str(user_id) if user_id is not None else "0"
    created = _script(redis_client, "mint", _LUA_MINT_IF_CLIENT_EXISTS)(
        keys=[client_key, session_key],
        args=[str(channel_id), str(client_id), token, int(ttl), user_id_str],
    )
    if not created:
        return None
    return token


def get_hls_session(redis_client, token):
    """Return the session hash for ``token``, or None if missing/incomplete."""
    if not redis_client or not token:
        return None
    data = redis_client.hgetall(RedisKeys.hls_session(token))
    if not data:
        return None
    if not data.get("channel_id") or not data.get("client_id"):
        return None
    return data


def hls_session_owned_by(session, user_id):
    """True when a loaded session hash belongs to ``user_id``.

    Missing, anonymous (``0``), or unparsable ``user_id`` is not owned.
    """
    if not session:
        return False
    try:
        return int(session.get("user_id") or "") == int(user_id)
    except (TypeError, ValueError):
        return False


def touch_hls_session(redis_client, token):
    """Resolve a capability URL and refresh its live client in one round trip.

    Returns ((channel_id, client_id, client_hash), None) on success.
    Returns (None, "expired"|"stopped"|"lapsed") on failure.

    Never recreates a missing client hash.
    """
    result = _script(redis_client, "touch", _LUA_TOUCH_SESSION)(
        keys=[RedisKeys.hls_session(token)],
        args=[
            str(time.time()),
            int(ConfigHelper.get("CLIENT_RECORD_TTL", 60)),
            str(token),
        ],
    )
    if not result:
        return None, "expired"
    status = int(result[0])
    if status == 0:
        return None, "expired"
    if status == 1:
        return None, "stopped"
    if status != 3 or len(result) < 3:
        return None, "lapsed"
    channel_id, client_id = result[1], result[2]
    return (channel_id, client_id, _lua_hash(result[3:])), None
