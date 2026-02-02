# Dispatcharr Event System

This document explains Dispatcharr's internal event system for real-time notifications about system state changes. It covers configuration for operators, subscribing to events for plugin developers, and extending the system for core developers.

---

## Overview

Dispatcharr emits events when significant actions occur: channels created, recordings started, M3U sources refreshed, users logged in, etc. These events are:

- Published via Redis pub/sub for real-time subscribers
- Dispatched to enabled plugins that have registered handlers
- Filtered based on a configurable event level

Events follow a `namespace.action` naming convention (e.g., `channel.created`, `recording.completed`, `auth.login`).

---

## For Operators: Configuring Event Levels

Event levels control which events are emitted. This is useful for:

- Reducing noise in high-volume environments
- Limiting event queue load during bulk operations (large M3U imports, EPG refreshes)
- Debugging specific subsystems

### Available Levels

Levels are **cumulative** - higher levels include all events from lower levels:

| Level | Events Included |
|-------|-----------------|
| `NONE` | No events emitted |
| `CRITICAL` | Security failures, errors (auth failures, refresh failures, channel errors) |
| `SYSTEM` | `CRITICAL` + authentication, plugin state changes, system startup/shutdown |
| `FULL` | `SYSTEM` + all operational events (channels, streams, recordings, VOD, EPG, M3U) |

### Configuration

**Environment Variable** (highest priority):

```bash
# In docker-compose.yml or .env
DISPATCHARR_EVENT_LEVEL=SYSTEM
```

**Database Setting** (via API or admin):

```python
from core.models import CoreSettings
CoreSettings.set_event_level("SYSTEM")
```

**Default**: `FULL` (all events emitted)

### When to Adjust

- **Bulk imports**: Set to `SYSTEM` or `CRITICAL` before importing large M3U files (3000+ channels) or EPG data (100k+ entries) to avoid overwhelming event queues
- **Production**: Consider `SYSTEM` for steady-state operation if you don't need granular channel/stream events
- **Debugging**: Use `FULL` when troubleshooting plugin event handlers

---

## For Plugin Developers: Subscribing to Events

Plugins can react to system events by implementing handler methods. When an event occurs, Dispatcharr calls the corresponding `on_<event_name>` method on all enabled plugins.

### Handler Naming Convention

Convert the event name to a handler method name:

| Event Name | Handler Method |
|------------|----------------|
| `channel.created` | `on_channel_created(self, data)` |
| `recording.completed` | `on_recording_completed(self, data)` |
| `auth.login` | `on_auth_login(self, data)` |

### Example Plugin

```python
# /app/data/plugins/my_logger/plugin.py

class Plugin:
    name = "Event Logger"
    version = "1.0.0"
    description = "Logs channel and recording events"

    fields = [
        {"id": "log_channels", "label": "Log channel events", "type": "boolean", "default": True},
        {"id": "log_recordings", "label": "Log recording events", "type": "boolean", "default": True},
    ]

    actions = []

    def on_channel_created(self, data):
        """Called when a channel is created."""
        # data contains: channel_id, channel_number, channel_name, channel_uuid,
        #                channel_group_id, channel_group_name
        if self._settings.get("log_channels"):
            self._logger.info(f"Channel created: {data['channel_name']} (#{data['channel_number']})")

    def on_channel_deleted(self, data):
        """Called when a channel is deleted."""
        if self._settings.get("log_channels"):
            self._logger.info(f"Channel deleted: {data['channel_name']}")

    def on_recording_completed(self, data):
        """Called when a recording finishes successfully."""
        # data contains: recording_id, channel_id, channel_name, file_path, duration_seconds
        if self._settings.get("log_recordings"):
            self._logger.info(f"Recording completed: {data.get('file_path')}")

    def on_recording_interrupted(self, data):
        """Called when a recording is interrupted."""
        # data contains: recording_id, channel_id, channel_name, file_path, reason
        self._logger.warning(f"Recording interrupted: {data.get('reason')}")
```

### Available Events

#### Critical Events (always emitted except at NONE)

| Event | Data Fields | Description |
|-------|-------------|-------------|
| `auth.login_failed` | `username`, `reason` | Failed login attempt |
| `channel.error` | `channel_id`, `channel_name`, `error` | Channel playback error |
| `epg.refresh_failed` | `source_id`, `source_name`, `error` | EPG refresh failed |
| `m3u.refresh_failed` | `account_id`, `account_name`, `error` | M3U refresh failed |
| `recording.interrupted` | `recording_id`, `channel_id`, `channel_name`, `file_path`, `reason` | Recording stopped unexpectedly |

#### System Events (emitted at SYSTEM and above)

| Event | Data Fields | Description |
|-------|-------------|-------------|
| `auth.login` | `user_id`, `username` | Successful login |
| `auth.logout` | `user_id`, `username` | User logged out |
| `system.startup` | `version` | Application started |
| `system.shutdown` | (none) | Application shutting down |
| `plugin.enabled` | `plugin_key`, `plugin_name` | Plugin was enabled |
| `plugin.disabled` | `plugin_key`, `plugin_name` | Plugin was disabled |
| `plugin.configured` | `plugin_key`, `plugin_name` | Plugin settings changed |

#### Full Events (emitted at FULL only)

**Channel Events:**
| Event | Data Fields |
|-------|-------------|
| `channel.created` | `channel_id`, `channel_number`, `channel_name`, `channel_uuid`, `channel_group_id`, `channel_group_name` |
| `channel.updated` | `channel_id`, `channel_number`, `channel_name`, `channel_uuid` |
| `channel.deleted` | `channel_id`, `channel_number`, `channel_name`, `channel_uuid` |
| `channel.stream_added` | `channel_id`, `channel_name`, `stream_ids` |
| `channel.stream_removed` | `channel_id`, `channel_name`, `stream_ids` |

**Channel Runtime Events:**
| Event | Data Fields |
|-------|-------------|
| `channel.client_connected` | `channel_id`, `channel_name` |
| `channel.client_disconnected` | `channel_id`, `channel_name` |
| `channel.stream_started` | `channel_id`, `channel_name`, `stream_id` |
| `channel.stream_stopped` | `channel_id`, `channel_name` |
| `channel.buffering` | `channel_id`, `channel_name`, `buffer_size` |
| `channel.failover` | `channel_id`, `channel_name`, `from_stream_id`, `to_stream_id`, `reason` |
| `channel.reconnected` | `channel_id`, `channel_name`, `stream_id`, `attempt` |
| `channel.stream_switched` | `channel_id`, `channel_name`, `from_stream_id`, `to_stream_id` |

**Recording Events:**
| Event | Data Fields |
|-------|-------------|
| `recording.scheduled` | `recording_id`, `channel_id`, `channel_name`, `start_time`, `end_time`, `program_name` |
| `recording.started` | `recording_id`, `channel_id`, `channel_name`, `start_time`, `end_time` |
| `recording.completed` | `recording_id`, `channel_id`, `channel_name`, `file_path`, `duration_seconds` |
| `recording.cancelled` | `recording_id`, `channel_id`, `channel_name`, `start_time`, `end_time` |
| `recording.deleted` | `recording_id`, `channel_id`, `channel_name`, `file_path`, `status` |
| `recording.changed` | `recording_id`, `channel_id`, `start_time`, `end_time`, `previous_start_time`, `previous_end_time` |
| `recording.comskip_completed` | `recording_id`, `commercials_found`, `segments_kept` |
| `recording.bulk_cancelled` | `count` |

**Recording Rule Events:**
| Event | Data Fields |
|-------|-------------|
| `recording_rule.created` | `rule_id`, `rule_name`, `channel_id`, `channel_name`, `days_of_week`, `start_time`, `end_time`, `enabled` |
| `recording_rule.updated` | `rule_id`, `rule_name`, `channel_id` |
| `recording_rule.deleted` | `rule_id`, `rule_name`, `channel_id` |

**EPG Events:**
| Event | Data Fields |
|-------|-------------|
| `epg.source_created` | `source_id`, `source_name`, `source_type` |
| `epg.source_deleted` | `source_id`, `source_name` |
| `epg.source_enabled` | `source_id`, `source_name` |
| `epg.source_disabled` | `source_id`, `source_name` |
| `epg.refresh_started` | `source_id`, `source_name` |
| `epg.refresh_completed` | `source_id`, `source_name`, `channel_count`, `program_count` |

**M3U Events:**
| Event | Data Fields |
|-------|-------------|
| `m3u.source_created` | `account_id`, `account_name`, `account_type` |
| `m3u.source_deleted` | `account_id`, `account_name` |
| `m3u.source_enabled` | `account_id`, `account_name` |
| `m3u.source_disabled` | `account_id`, `account_name` |
| `m3u.refresh_started` | `account_id`, `account_name` |
| `m3u.refresh_completed` | `account_id`, `account_name`, `streams_created`, `streams_updated` |

**Stream Events:**
| Event | Data Fields |
|-------|-------------|
| `stream.created` | `stream_id`, `stream_name`, `tvg_id`, `is_custom`, `m3u_account_id` |
| `stream.updated` | `stream_id`, `stream_name` |
| `stream.deleted` | `stream_id`, `stream_name` |

**Channel Group Events:**
| Event | Data Fields |
|-------|-------------|
| `channel_group.created` | `group_id`, `group_name` |
| `channel_group.updated` | `group_id`, `group_name` |
| `channel_group.deleted` | `group_id`, `group_name` |

**Channel Profile Events:**
| Event | Data Fields |
|-------|-------------|
| `channel_profile.created` | `profile_id`, `profile_name` |
| `channel_profile.updated` | `profile_id`, `profile_name` |
| `channel_profile.deleted` | `profile_id`, `profile_name` |

**VOD Events:**
| Event | Data Fields |
|-------|-------------|
| `vod.movie_created` | `movie_id`, `movie_name`, `year` |
| `vod.movie_deleted` | `movie_id`, `movie_name` |
| `vod.series_created` | `series_id`, `series_name`, `year` |
| `vod.series_deleted` | `series_id`, `series_name` |
| `vod.episode_created` | `episode_id`, `episode_name`, `series_id`, `series_name`, `season_number`, `episode_number` |
| `vod.episode_deleted` | `episode_id`, `episode_name`, `series_id` |

### Best Practices for Plugin Developers

1. **Keep handlers fast** - Heavy processing should be dispatched to Celery tasks
2. **Handle missing data gracefully** - Use `.get()` with defaults; not all fields are always present
3. **Don't assume event order** - Events may arrive out of order in high-volume scenarios
4. **Log errors** - Unhandled exceptions in handlers are caught but should be logged for debugging
5. **Check settings in handlers** - Let users control which events your plugin responds to

---

## For Core Developers: Adding New Events

### 1. Add the Serializer

In `core/events.py`, add a serializer function:

```python
def _serialize_my_new_event(obj, **ctx):
    """Serialize data for my.new_event."""
    return {
        "id": obj.id,
        "name": obj.name,
        # Include only what consumers need - avoid sensitive data
    }
```

### 2. Register in EVENT_SERIALIZERS

```python
EVENT_SERIALIZERS = {
    # ... existing entries ...
    "my.new_event": _serialize_my_new_event,
}
```

### 3. Add to the Appropriate Level Set

In `core/events.py`, add to one of the level sets:

```python
# For errors/security failures
CRITICAL_EVENTS = {
    # ...
    "my.new_event",
}

# For system lifecycle events
SYSTEM_EVENTS = {
    # ...
    "my.new_event",
}

# For operational events (most common)
FULL_EVENTS = {
    # ...
    "my.new_event",
}

# For events that shouldn't be emitted (deprecated, future use)
DISABLED_EVENTS = {
    # ...
    "my.deprecated_event",
}
```

### 4. Emit the Event

From your code (model signal, view, task, etc.):

```python
from core import events

# With an object
events.emit("my.new_event", my_object)

# With additional context
events.emit("my.new_event", my_object, extra_field="value")

# Without an object (context only)
events.emit("my.new_event", None, id=123, name="test")
```

### 5. Startup Validation

The system automatically validates at startup that:

- Every event in `EVENT_SERIALIZERS` appears in exactly one level set
- No event appears in multiple level sets

If validation fails, an error is logged. Fix by ensuring the event is in exactly one of: `CRITICAL_EVENTS`, `SYSTEM_EVENTS`, `FULL_EVENTS`, or `DISABLED_EVENTS`.

### Serializer Guidelines

1. **Include IDs** - Always include object IDs for lookups
2. **Include names** - Human-readable names help with logging/debugging
3. **Avoid sensitive data** - No passwords, tokens, full URLs with credentials
4. **Keep payloads small** - Consumers can look up full objects if needed
5. **Use context for computed values** - Pass dynamic data via `**context`

---

## Internals Reference

- Event configuration & emit: `core/events.py`
- Redis pub/sub manager: `core/redis_pubsub.py`
- Plugin event dispatch: `apps/plugins/tasks.py`
- Startup validation: `core/apps.py`
- Tests: `core/tests/test_event_levels.py`

---

## Troubleshooting

**Events not being emitted:**
- Check the configured level: `CoreSettings.get_event_level()` or `DISPATCHARR_EVENT_LEVEL` env var
- Verify the event is not in `DISABLED_EVENTS`
- Check logs for "suppressed by event level configuration" messages

**Plugin handler not being called:**
- Ensure the plugin is enabled
- Verify the handler method name matches: `on_<event_name>` with dots replaced by underscores
- Check that the event's level is being emitted (FULL events won't trigger at SYSTEM level)

**Startup validation errors:**
- "Events have serializers but no level configuration" - Add the event to a level set
- "Events appear in multiple level sets" - Remove duplicates from level sets
