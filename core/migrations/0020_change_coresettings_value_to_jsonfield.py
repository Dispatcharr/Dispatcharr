# Generated migration to change CoreSettings value field to JSONField and consolidate settings

import json
from django.db import migrations, models


def convert_string_to_json(apps, schema_editor):
    """Convert existing string values to appropriate JSON types before changing column type"""
    CoreSettings = apps.get_model("core", "CoreSettings")

    for setting in CoreSettings.objects.all():
        value = setting.value

        if not value:
            # Empty strings become empty string in JSON
            setting.value = json.dumps("")
            setting.save(update_fields=['value'])
            continue

        # Try to parse as JSON if it looks like JSON (objects/arrays)
        if value.startswith('{') or value.startswith('['):
            try:
                parsed = json.loads(value)
                # Store as JSON string temporarily (column is still CharField)
                setting.value = json.dumps(parsed)
                setting.save(update_fields=['value'])
                continue
            except (json.JSONDecodeError, ValueError):
                pass

        # Try to parse as number
        try:
            # Check if it's an integer
            if '.' not in value and value.lstrip('-').isdigit():
                setting.value = json.dumps(int(value))
                setting.save(update_fields=['value'])
                continue
            # Check if it's a float
            float_val = float(value)
            setting.value = json.dumps(float_val)
            setting.save(update_fields=['value'])
            continue
        except (ValueError, AttributeError):
            pass

        # Check for booleans
        if value.lower() in ('true', 'false', '1', '0', 'yes', 'no', 'on', 'off'):
            bool_val = value.lower() in ('true', '1', 'yes', 'on')
            setting.value = json.dumps(bool_val)
            setting.save(update_fields=['value'])
            continue

        # Default: store as JSON string
        setting.value = json.dumps(value)
        setting.save(update_fields=['value'])


def consolidate_settings(apps, schema_editor):
    """Consolidate individual setting rows into grouped JSON objects."""
    CoreSettings = apps.get_model("core", "CoreSettings")

    # Helper to get setting value
    def get_value(key, default=None):
        try:
            obj = CoreSettings.objects.get(key=key)
            return obj.value if obj.value is not None else default
        except CoreSettings.DoesNotExist:
            return default

    # STREAM SETTINGS
    stream_settings = {
        "default_user_agent": get_value("default-user-agent"),
        "default_stream_profile": get_value("default-stream-profile"),
        "m3u_hash_key": get_value("m3u-hash-key", ""),
        "preferred_region": get_value("preferred-region"),
        "auto_import_mapped_files": get_value("auto-import-mapped-files"),
    }
    CoreSettings.objects.update_or_create(
        key="stream_settings",
        defaults={"name": "Stream Settings", "value": stream_settings}
    )

    # DVR SETTINGS
    dvr_settings = {
        "tv_template": get_value("dvr-tv-template", "TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"),
        "movie_template": get_value("dvr-movie-template", "Movies/{title} ({year}).mkv"),
        "tv_fallback_dir": get_value("dvr-tv-fallback-dir", "TV_Shows"),
        "tv_fallback_template": get_value("dvr-tv-fallback-template", "TV_Shows/{show}/{start}.mkv"),
        "movie_fallback_template": get_value("dvr-movie-fallback-template", "Movies/{start}.mkv"),
        "comskip_enabled": bool(get_value("dvr-comskip-enabled", False)),
        "comskip_custom_path": get_value("dvr-comskip-custom-path", ""),
        "pre_offset_minutes": int(get_value("dvr-pre-offset-minutes", 0) or 0),
        "post_offset_minutes": int(get_value("dvr-post-offset-minutes", 0) or 0),
        "series_rules": get_value("dvr-series-rules", []),
    }
    CoreSettings.objects.update_or_create(
        key="dvr_settings",
        defaults={"name": "DVR Settings", "value": dvr_settings}
    )

    # BACKUP SETTINGS - using underscore keys (not dashes)
    backup_settings = {
        "schedule_enabled": get_value("backup_schedule_enabled") if get_value("backup_schedule_enabled") is not None else True,
        "schedule_frequency": get_value("backup_schedule_frequency") or "daily",
        "schedule_time": get_value("backup_schedule_time") or "03:00",
        "schedule_day_of_week": get_value("backup_schedule_day_of_week") if get_value("backup_schedule_day_of_week") is not None else 0,
        "retention_count": get_value("backup_retention_count") if get_value("backup_retention_count") is not None else 3,
        "schedule_cron_expression": get_value("backup_schedule_cron_expression") or "",
    }
    CoreSettings.objects.update_or_create(
        key="backup_settings",
        defaults={"name": "Backup Settings", "value": backup_settings}
    )

    # SYSTEM SETTINGS
    system_settings = {
        "time_zone": get_value("system-time-zone", "UTC"),
        "max_system_events": int(get_value("max-system-events", 100) or 100),
    }
    CoreSettings.objects.update_or_create(
        key="system_settings",
        defaults={"name": "System Settings", "value": system_settings}
    )

    # Rename proxy-settings to proxy_settings (if it exists with old name)
    try:
        old_proxy = CoreSettings.objects.get(key="proxy-settings")
        old_proxy.key = "proxy_settings"
        old_proxy.save()
    except CoreSettings.DoesNotExist:
        pass

    # Ensure proxy_settings exists with defaults if not present
    proxy_obj, proxy_created = CoreSettings.objects.get_or_create(
        key="proxy_settings",
        defaults={
            "name": "Proxy Settings",
            "value": {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 5,
            }
        }
    )

    # Rename network-access to network_access (if it exists with old name)
    try:
        old_network = CoreSettings.objects.get(key="network-access")
        old_network.key = "network_access"
        old_network.save()
    except CoreSettings.DoesNotExist:
        pass

    # Ensure network_access exists with defaults if not present
    network_obj, network_created = CoreSettings.objects.get_or_create(
        key="network_access",
        defaults={
            "name": "Network Access",
            "value": {}
        }
    )
    # Delete old individual setting rows (keep only the new grouped settings)
    grouped_keys = ["stream_settings", "dvr_settings", "backup_settings", "system_settings", "proxy_settings", "network_access"]
    CoreSettings.objects.exclude(key__in=grouped_keys).delete()


def reverse_migration(apps, schema_editor):
    """Reverse migration: split grouped settings and convert JSON back to strings"""
    CoreSettings = apps.get_model("core", "CoreSettings")

    # Helper to create individual setting
    def create_setting(key, name, value):
        # Convert value back to string representation for CharField
        if isinstance(value, str):
            str_value = value
        elif isinstance(value, bool):
            str_value = "true" if value else "false"
        elif isinstance(value, (int, float)):
            str_value = str(value)
        elif isinstance(value, (dict, list)):
            str_value = json.dumps(value)
        elif value is None:
            str_value = ""
        else:
            str_value = str(value)

        CoreSettings.objects.update_or_create(
            key=key,
            defaults={"name": name, "value": str_value}
        )

    # Split stream_settings
    try:
        stream = CoreSettings.objects.get(key="stream_settings")
        if isinstance(stream.value, dict):
            create_setting("default_user_agent", "Default User Agent", stream.value.get("default_user_agent"))
            create_setting("default_stream_profile", "Default Stream Profile", stream.value.get("default_stream_profile"))
            create_setting("stream_hash_key", "Stream Hash Key", stream.value.get("m3u_hash_key", ""))
            create_setting("preferred_region", "Preferred Region", stream.value.get("preferred_region"))
            create_setting("auto_import_mapped_files", "Auto Import Mapped Files", stream.value.get("auto_import_mapped_files"))
        stream.delete()
    except CoreSettings.DoesNotExist:
        pass

    # Split dvr_settings
    try:
        dvr = CoreSettings.objects.get(key="dvr_settings")
        if isinstance(dvr.value, dict):
            create_setting("dvr_tv_template", "DVR TV Template", dvr.value.get("tv_template", "TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"))
            create_setting("dvr_movie_template", "DVR Movie Template", dvr.value.get("movie_template", "Movies/{title} ({year}).mkv"))
            create_setting("dvr_tv_fallback_dir", "DVR TV Fallback Dir", dvr.value.get("tv_fallback_dir", "TV_Shows"))
            create_setting("dvr_tv_fallback_template", "DVR TV Fallback Template", dvr.value.get("tv_fallback_template", "TV_Shows/{show}/{start}.mkv"))
            create_setting("dvr_movie_fallback_template", "DVR Movie Fallback Template", dvr.value.get("movie_fallback_template", "Movies/{start}.mkv"))
            create_setting("dvr_comskip_enabled", "DVR Comskip Enabled", dvr.value.get("comskip_enabled", False))
            create_setting("dvr_comskip_custom_path", "DVR Comskip Custom Path", dvr.value.get("comskip_custom_path", ""))
            create_setting("dvr_pre_offset_minutes", "DVR Pre Offset Minutes", dvr.value.get("pre_offset_minutes", 0))
            create_setting("dvr_post_offset_minutes", "DVR Post Offset Minutes", dvr.value.get("post_offset_minutes", 0))
            create_setting("dvr_series_rules", "DVR Series Rules", dvr.value.get("series_rules", []))
        dvr.delete()
    except CoreSettings.DoesNotExist:
        pass

    # Split backup_settings
    try:
        backup = CoreSettings.objects.get(key="backup_settings")
        if isinstance(backup.value, dict):
            create_setting("backup_schedule_enabled", "Backup Schedule Enabled", backup.value.get("schedule_enabled", False))
            create_setting("backup_schedule_frequency", "Backup Schedule Frequency", backup.value.get("schedule_frequency", "weekly"))
            create_setting("backup_schedule_time", "Backup Schedule Time", backup.value.get("schedule_time", "02:00"))
            create_setting("backup_schedule_day_of_week", "Backup Schedule Day of Week", backup.value.get("schedule_day_of_week", 0))
            create_setting("backup_retention_count", "Backup Retention Count", backup.value.get("retention_count", 7))
            create_setting("backup_schedule_cron_expression", "Backup Schedule Cron Expression", backup.value.get("schedule_cron_expression", ""))
        backup.delete()
    except CoreSettings.DoesNotExist:
        pass

    # Split system_settings
    try:
        system = CoreSettings.objects.get(key="system_settings")
        if isinstance(system.value, dict):
            create_setting("system_time_zone", "System Time Zone", system.value.get("time_zone", "UTC"))
            create_setting("max_system_events", "Max System Events", system.value.get("max_system_events", 100))
        system.delete()
    except CoreSettings.DoesNotExist:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_add_vlc_stream_profile'),
    ]

    operations = [
        # First, convert all data to valid JSON strings while column is still CharField
        migrations.RunPython(convert_string_to_json, migrations.RunPython.noop),
        # Then change the field type to JSONField
        migrations.AlterField(
            model_name='coresettings',
            name='value',
            field=models.JSONField(blank=True, default=dict),
        ),
        # Finally, consolidate individual settings into grouped JSON objects
        migrations.RunPython(consolidate_settings, reverse_migration),
    ]
