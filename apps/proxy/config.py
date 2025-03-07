"""Shared configuration between proxy types"""

class BaseConfig:
    DEFAULT_USER_AGENT = 'VLC/3.0.20 LibVLC/3.0.20'
    CHUNK_SIZE = 8192
    CLIENT_POLL_INTERVAL = 0.1
    MAX_RETRIES = 3

class HLSConfig(BaseConfig):
    MIN_SEGMENTS = 12
    MAX_SEGMENTS = 16
    WINDOW_SIZE = 12
    INITIAL_SEGMENTS = 3
    INITIAL_CONNECTION_WINDOW = 10
    CLIENT_TIMEOUT_FACTOR = 1.5
    CLIENT_CLEANUP_INTERVAL = 10
    FIRST_SEGMENT_TIMEOUT = 5.0
    INITIAL_BUFFER_SECONDS = 25.0
    MAX_INITIAL_SEGMENTS = 10
    BUFFER_READY_TIMEOUT = 30.0

class TSConfig(BaseConfig):
    BUFFER_SIZE = 1000
    RECONNECT_DELAY = 5
    CLIENT_TIMEOUT = 15  # Seconds before stopping idle channel
    CONNECTION_TIMEOUT = 10  # Seconds to wait for initial connection