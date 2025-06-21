import json # Added missing import
from django.conf import settings as django_settings
from core.models import CoreSettings as SystemCoreSettings # Renamed to avoid conflict
import logging

logger = logging.getLogger(__name__)

DEFAULT_HLS_SETTINGS = {
    "hls_segment_path": "/tmp/dispatcharr_hls/", # Default if not in DB
    "hls_default_segment_time": "4",
    "hls_default_list_size": "5",
    "hls_default_flags": "delete_segments+round_durations",
    "hls_extra_ffmpeg_options": "",
    "hls_ffmpeg_stall_speed_threshold": "0.5", # Speed below which is considered stalling (e.g., 0.5x)
    "hls_ffmpeg_stall_duration_threshold": "60", # Seconds of low speed before considered stalled
    "hls_ffmpeg_stats_max_age": "120", # Seconds. If stats older than this, process considered unresponsive
    "hls_abr_renditions": "[]", # Default to empty list (non-ABR). JSON string.
}

class HLSConfig:
    def __init__(self):
        self._load_settings()

    def _load_settings(self):
        # Load from Django settings first (if defined there for some reason)
        self.hls_segment_path = getattr(django_settings, "HLS_SEGMENT_PATH", None)
        self.hls_default_segment_time = getattr(django_settings, "HLS_DEFAULT_SEGMENT_TIME", None)
        self.hls_default_list_size = getattr(django_settings, "HLS_DEFAULT_LIST_SIZE", None)
        self.hls_default_flags = getattr(django_settings, "HLS_DEFAULT_FLAGS", None)
        self.hls_extra_ffmpeg_options = getattr(django_settings, "HLS_EXTRA_FFMPEG_OPTIONS", None)
        self.hls_ffmpeg_stall_speed_threshold = getattr(django_settings, "HLS_FFMPEG_STALL_SPEED_THRESHOLD", None)
        self.hls_ffmpeg_stall_duration_threshold = getattr(django_settings, "HLS_FFMPEG_STALL_DURATION_THRESHOLD", None)
        self.hls_ffmpeg_stats_max_age = getattr(django_settings, "HLS_FFMPEG_STATS_MAX_AGE", None)
        self.hls_abr_renditions_str = getattr(django_settings, "HLS_ABR_RENDITIONS", None) # Store the string form
        self.hls_abr_renditions = [] # Parsed list


        # Override with values from CoreSettings in the database if they exist
        try:
            # Helper to load a setting or use default
            def load_setting(attr_name, core_setting_key, default_value, is_json=False):
                current_value_attr = f"{attr_name}_str" if is_json else attr_name
                current_value = getattr(self, current_value_attr, None)

                if current_value is None: # Only fetch from DB if not already set by Django settings
                    try:
                        setting_obj = SystemCoreSettings.objects.get(key=core_setting_key)
                        db_value = setting_obj.value
                        logger.debug(f"Fetched {core_setting_key} from DB: {db_value}")
                    except SystemCoreSettings.DoesNotExist:
                        db_value = default_value
                        logger.debug(f"{core_setting_key} not found in DB, using default: {db_value}")
                    except Exception as e_db:
                        logger.error(f"Error fetching {core_setting_key} from DB, using default: {default_value}. Error: {e_db}")
                        db_value = default_value

                    if is_json:
                        setattr(self, current_value_attr, db_value) # Store the string form (which might be default_value if not found)
                        try:
                            # Ensure db_value is not None before json.loads attempt
                            setattr(self, attr_name, json.loads(db_value if db_value is not None else "[]"))
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse JSON for {core_setting_key} (value: {db_value}), using empty list as fallback.")
                            setattr(self, attr_name, [])
                    else:
                        setattr(self, attr_name, db_value)
                elif is_json: # If set by Django settings (already a string), parse it
                     try:
                        # Ensure current_value is not None before json.loads attempt
                        setattr(self, attr_name, json.loads(current_value if current_value is not None else "[]"))
                     except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON from Django setting for {core_setting_key} (value: {current_value}), using empty list.")
                        setattr(self, attr_name, [])


                # Ensure type consistency for numeric-like settings if they are strings (and not JSON source)
                if not is_json and isinstance(getattr(self, attr_name), str) and default_value is not None and not isinstance(default_value, str) :
                    try:
                        if isinstance(default_value, float):
                             setattr(self, attr_name, float(getattr(self, attr_name)))
                        elif isinstance(default_value, int):
                             setattr(self, attr_name, int(getattr(self, attr_name)))
                    except ValueError:
                        logger.warning(f"Could not convert HLS setting {core_setting_key} to numeric type, using default: {default_value}")
                        setattr(self, attr_name, default_value)


            load_setting("hls_segment_path", "hls_segment_path", DEFAULT_HLS_SETTINGS["hls_segment_path"])
            load_setting("hls_default_segment_time", "hls_default_segment_time", DEFAULT_HLS_SETTINGS["hls_default_segment_time"])
            load_setting("hls_default_list_size", "hls_default_list_size", DEFAULT_HLS_SETTINGS["hls_default_list_size"])
            load_setting("hls_default_flags", "hls_default_flags", DEFAULT_HLS_SETTINGS["hls_default_flags"])
            load_setting("hls_extra_ffmpeg_options", "hls_extra_ffmpeg_options", DEFAULT_HLS_SETTINGS["hls_extra_ffmpeg_options"])
            load_setting("hls_ffmpeg_stall_speed_threshold", "hls_ffmpeg_stall_speed_threshold", float(DEFAULT_HLS_SETTINGS["hls_ffmpeg_stall_speed_threshold"]))
            load_setting("hls_ffmpeg_stall_duration_threshold", "hls_ffmpeg_stall_duration_threshold", int(DEFAULT_HLS_SETTINGS["hls_ffmpeg_stall_duration_threshold"]))
            load_setting("hls_ffmpeg_stats_max_age", "hls_ffmpeg_stats_max_age", int(DEFAULT_HLS_SETTINGS["hls_ffmpeg_stats_max_age"]))
            load_setting("hls_abr_renditions", "hls_abr_renditions", DEFAULT_HLS_SETTINGS["hls_abr_renditions"], is_json=True)


        except Exception as e:
            logger.error(f"Error loading HLS CoreSettings, using defaults: {e}", exc_info=True)
            # Ensure defaults are set if DB query fails or type conversion issues persist for new settings
            self.hls_segment_path = self.hls_segment_path or DEFAULT_HLS_SETTINGS["hls_segment_path"]
            # ... (ensure other existing defaults are set here too) ...
            self.hls_ffmpeg_stall_speed_threshold = self.hls_ffmpeg_stall_speed_threshold or float(DEFAULT_HLS_SETTINGS["hls_ffmpeg_stall_speed_threshold"])
            self.hls_ffmpeg_stall_duration_threshold = self.hls_ffmpeg_stall_duration_threshold or int(DEFAULT_HLS_SETTINGS["hls_ffmpeg_stall_duration_threshold"])
            self.hls_ffmpeg_stats_max_age = self.hls_ffmpeg_stats_max_age or int(DEFAULT_HLS_SETTINGS["hls_ffmpeg_stats_max_age"])
            if not hasattr(self, 'hls_abr_renditions') or not self.hls_abr_renditions: # Check if it wasn't set or parsing failed
                try:
                    self.hls_abr_renditions = json.loads(DEFAULT_HLS_SETTINGS["hls_abr_renditions"])
                except json.JSONDecodeError:
                    self.hls_abr_renditions = []

        logger.info(f"HLS Config Loaded: Segment Path='{self.hls_segment_path}', ABR Renditions: {len(self.hls_abr_renditions)} found.")

# Singleton instance
hls_config = HLSConfig()

# Helper function to get a specific HLS setting
def get_hls_setting(key_name):
    if hasattr(hls_config, key_name):
        return getattr(hls_config, key_name)
    logger.warning(f"HLS setting '{key_name}' not found in HLSConfig.")
    return DEFAULT_HLS_SETTINGS.get(key_name) # Fallback to hardcoded defaults if not even in HLSConfig

# Example usage:
# from .config import get_hls_setting
# segment_path = get_hls_setting("hls_segment_path")
