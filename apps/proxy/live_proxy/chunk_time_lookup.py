"""Shared Redis helpers for joining a reader behind the buffer head by stream time.

Chunk scores (end-of-chunk PTS/PCR for the input buffer, PublishedClock end for
fMP4) live in one sorted set: chunk index (member) to media seconds (score).
The join runs as a single Lua script (one EVALSHA round trip) instead of a
chain of GET / ZSCORE / ZRANGE calls from Python.

The wall-clock join used when experimental ingest is off is unchanged and lives
in ``StreamBuffer``.
"""

# Chunks retained in a media-score zset. 16 per TTL second covers a high-bitrate
# 1MB chunk cadence for the Redis chunk lifetime without unbounded growth.
MEDIA_SCORE_CHUNKS_PER_TTL_SECOND = 16
MEDIA_SCORE_MIN_KEEP = 64
# How many chunk indexes to step back when the head itself has no score.
HEAD_SCORE_LOOKBACK = 8

# Behind-buffer-head join in one script.
#
# KEYS[1] = score zset (chunk_media_scores or fmp4 scores)
# KEYS[2] = buffer index key (published head)
# KEYS[3] = discontinuities zset (optional; ignored when ARGV[3] == 0)
# ARGV[1] = seconds_behind
# ARGV[2] = head_score_lookback (chunk indexes)
# ARGV[3] = use_discontinuity_era (1 or 0)
#
# Returns {chunk_index, target_media} to position at (caller subtracts 1 for
# last-consumed). target_media is head_score - behind for mid-chunk trim.
# {-2} = no buffer head, {-1} = no scored member in era (after shallow fallback).
FIND_CHUNK_BEHIND_HEAD_LUA = """
local scores_key = KEYS[1]
local index_key = KEYS[2]
local disc_key = KEYS[3]
local behind = tonumber(ARGV[1])
local lookback = tonumber(ARGV[2])
if not lookback or lookback < 0 then
    lookback = 0
end
local use_disc = tonumber(ARGV[3])
if not use_disc then
    use_disc = 0
end

local head_raw = redis.call('GET', index_key)
if not head_raw then
    return {-2}
end
local head = tonumber(head_raw)
if not head or head <= 0 then
    return {-2}
end

local era_floor = 0
if use_disc == 1 then
    if redis.call('EXISTS', disc_key) == 1 then
        local discs = redis.call('ZREVRANGEBYSCORE', disc_key, head, '-inf', 'LIMIT', 0, 1)
        if #discs > 0 then
            era_floor = tonumber(discs[1])
        end
    end
end

local head_score = redis.call('ZSCORE', scores_key, tostring(head))
if not head_score then
    local low = era_floor
    if lookback > 0 then
        local bound = head - lookback
        if bound > low then
            low = bound
        end
    end
    for i = head - 1, low, -1 do
        local s = redis.call('ZSCORE', scores_key, tostring(i))
        if s then
            head_score = s
            break
        end
    end
end
if not head_score then
    return {-1}
end

local target = tonumber(head_score) - behind
local result = redis.call('ZREVRANGEBYSCORE', scores_key, target, '-inf', 'LIMIT', 0, 64)
for _, member in ipairs(result) do
    if tonumber(member) >= era_floor then
        return {tonumber(member), target}
    end
end

local members = redis.call('ZRANGE', scores_key, 0, -1)
local min_idx = nil
for _, member in ipairs(members) do
    local idx = tonumber(member)
    if idx and idx >= era_floor then
        if not min_idx or idx < min_idx then
            min_idx = idx
        end
    end
end
if min_idx then
    return {min_idx, target}
end
return {-1}
"""


def media_score_min_index(chunk_index, chunk_ttl):
    """Lowest chunk index still worth keeping in a media-score zset.

    Writers drop exactly one member per chunk (``min_index - 1``), so pruning
    is O(log N) with no scan of the set.
    """
    keep = max(MEDIA_SCORE_MIN_KEEP, int(chunk_ttl) * MEDIA_SCORE_CHUNKS_PER_TTL_SECOND)
    return max(0, int(chunk_index) - keep)


def behind_head_from_lua_result(result):
    """Map behind-head Lua return to ``(last_consumed, target_media)``.

    ``target_media`` is set when the script returned the join clock (stream-time
    trim). Error codes and legacy scalar returns yield ``(None, None)`` /
    ``(last_consumed, None)``.
    """
    if result is None:
        return None, None
    target = None
    if isinstance(result, (list, tuple)):
        if not result:
            return None, None
        code = int(result[0])
        if len(result) > 1 and result[1] is not None:
            target = float(result[1])
    else:
        code = int(result)
    if code == -2 or code == -1:
        return None, None
    return max(0, code - 1), target


def last_consumed_from_lua_result(result):
    """Map behind-head Lua return to last-consumed index, or None."""
    last_consumed, _target = behind_head_from_lua_result(result)
    return last_consumed
