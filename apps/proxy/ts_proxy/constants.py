"""
Constants used throughout the TS Proxy application.
Centralizing constants makes it easier to maintain and modify them.
"""

# Redis related constants
REDIS_KEY_PREFIX = "ts_proxy"
REDIS_TTL_DEFAULT = 3600  # 1 hour
REDIS_TTL_SHORT = 60      # 1 minute
REDIS_TTL_MEDIUM = 300    # 5 minutes

# Channel states
class ChannelState:
    INITIALIZING = "initializing"
    CONNECTING = "connecting"
    WAITING_FOR_CLIENTS = "waiting_for_clients"
    ACTIVE = "active"
    ERROR = "error"
    STOPPING = "stopping"
    STOPPED = "stopped"
    BUFFERING = "buffering"

# Event types
class EventType:
    STREAM_SWITCH = "stream_switch"
    STREAM_SWITCHED = "stream_switched"
    CHANNEL_STOP = "channel_stop"
    CHANNEL_STOPPED = "channel_stopped"
    CLIENT_CONNECTED = "client_connected"
    CLIENT_DISCONNECTED = "client_disconnected"
    CLIENT_STOP = "client_stop"

# Stream types
class StreamType:
    HLS = "hls"
    RTSP = "rtsp"
    UDP = "udp"
    TS = "ts"
    UNKNOWN = "unknown"

# Channel metadata field names stored in Redis
class ChannelMetadataField:
    # Basic fields
    URL = "url"
    USER_AGENT = "user_agent"
    STATE = "state"
    OWNER = "owner"
    STREAM_ID = "stream_id"

    # Profile fields
    STREAM_PROFILE = "stream_profile"
    M3U_PROFILE = "m3u_profile"

    # Status and error fields
    ERROR_MESSAGE = "error_message"
    ERROR_TIME = "error_time"
    STATE_CHANGED_AT = "state_changed_at"
    INIT_TIME = "init_time"
    CONNECTION_READY_TIME = "connection_ready_time"

    # Buffer and data tracking
    BUFFER_CHUNKS = "buffer_chunks"
    TOTAL_BYTES = "total_bytes"

    # Stream switching
    STREAM_SWITCH_TIME = "stream_switch_time"
    STREAM_SWITCH_REASON = "stream_switch_reason"

    # FFmpeg performance metrics
    FFMPEG_SPEED = "ffmpeg_speed"
    FFMPEG_FPS = "ffmpeg_fps"
    ACTUAL_FPS = "actual_fps"
    FFMPEG_OUTPUT_BITRATE = "ffmpeg_output_bitrate"
    FFMPEG_STATS_UPDATED = "ffmpeg_stats_updated"

    # Video stream info
    VIDEO_CODEC = "video_codec"
    RESOLUTION = "resolution"
    WIDTH = "width"
    HEIGHT = "height"
    SOURCE_FPS = "source_fps"
    PIXEL_FORMAT = "pixel_format"
    VIDEO_BITRATE = "video_bitrate"

    # Audio stream info
    AUDIO_CODEC = "audio_codec"
    SAMPLE_RATE = "sample_rate"
    AUDIO_CHANNELS = "audio_channels"
    AUDIO_BITRATE = "audio_bitrate"

    # Stream format info
    STREAM_TYPE = "stream_type"
    # Stream info timestamp
    STREAM_INFO_UPDATED = "stream_info_updated"

    # Client metadata fields
    CONNECTED_AT = "connected_at"
    LAST_ACTIVE = "last_active"
    BYTES_SENT = "bytes_sent"
    AVG_RATE_KBPS = "avg_rate_KBps"
    CURRENT_RATE_KBPS = "current_rate_KBps"
    IP_ADDRESS = "ip_address"
    WORKER_ID = "worker_id"
    CHUNKS_SENT = "chunks_sent"
    STATS_UPDATED_AT = "stats_updated_at"

# TS packet constants
TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47
NULL_PID_HIGH = 0x1F
NULL_PID_LOW = 0xFF
