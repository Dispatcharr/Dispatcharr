"""
Defines Redis key patterns used throughout the TS proxy service.
Centralizing these key patterns makes it easier to maintain and change them if needed.
"""

class RedisKeys:
    @staticmethod
    def channel_metadata(channel_id):
        """Key for channel metadata hash"""
        return f"live:channel:{channel_id}:metadata"

    @staticmethod
    def buffer_index(channel_id):
        """Key for tracking input buffer index"""
        return f"live:channel:{channel_id}:input:buffer:index"

    @staticmethod
    def buffer_chunk(channel_id, chunk_index):
        """Key for specific input buffer chunk"""
        return f"live:channel:{channel_id}:input:buffer:chunk:{chunk_index}"

    @staticmethod
    def buffer_chunk_prefix(channel_id):
        """Prefix for input buffer chunks"""
        return f"live:channel:{channel_id}:input:buffer:chunk:"

    @staticmethod
    def channel_stopping(channel_id):
        """Key indicating channel is stopping"""
        return f"live:channel:{channel_id}:stopping"

    @staticmethod
    def client_stop(channel_id, client_id):
        """Key requesting client stop"""
        return f"live:channel:{channel_id}:client:{client_id}:stop"

    @staticmethod
    def events_channel(channel_id):
        """PubSub channel for events"""
        return f"live:events:{channel_id}"

    @staticmethod
    def switch_request(channel_id):
        """Key for stream switch request"""
        return f"live:channel:{channel_id}:switch_request"

    @staticmethod
    def channel_owner(channel_id):
        """Key for storing channel owner worker ID"""
        return f"live:channel:{channel_id}:owner"

    @staticmethod
    def clients(channel_id):
        """Key for set of client IDs"""
        return f"live:channel:{channel_id}:clients"

    @staticmethod
    def last_client_disconnect(channel_id):
        """Key for last client disconnect timestamp"""
        return f"live:channel:{channel_id}:last_client_disconnect_time"

    @staticmethod
    def connection_attempt(channel_id):
        """Key for connection attempt timestamp"""
        return f"live:channel:{channel_id}:connection_attempt_time"

    @staticmethod
    def last_data(channel_id):
        """Key for last data timestamp"""
        return f"live:channel:{channel_id}:last_data"

    @staticmethod
    def switch_status(channel_id):
        """Key for stream switch status"""
        return f"live:channel:{channel_id}:switch_status"

    @staticmethod
    def worker_heartbeat(worker_id):
        """Key for worker heartbeat"""
        return f"live:worker:{worker_id}:heartbeat"

    @staticmethod
    def chunk_timestamps(channel_id):
        """Sorted set mapping chunk receive-timestamps (score) to chunk indices (member).
        Used for time-based client positioning."""
        return f"live:channel:{channel_id}:input:buffer:chunk_timestamps"

    @staticmethod
    def transcode_active(channel_id):
        """Key indicating active transcode process"""
        return f"live:channel:{channel_id}:transcode_active"

    @staticmethod
    def client_metadata(channel_id, client_id):
        """Key for client metadata hash"""
        return f"live:channel:{channel_id}:clients:{client_id}"

    # Output format buffer keys - parameterized by format name (e.g. 'fmp4').
    # Adding a new output format only requires a new manager; the key structure
    # is shared so no new key methods are needed.
    @staticmethod
    def output_buffer_index(channel_id, fmt):
        return f"live:channel:{channel_id}:output:{fmt}:buffer:index"

    @staticmethod
    def output_buffer_chunk(channel_id, fmt, chunk_index):
        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk:{chunk_index}"

    @staticmethod
    def output_buffer_chunk_prefix(channel_id, fmt):
        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk:"

    @staticmethod
    def output_init(channel_id, fmt):
        """Binary init segment for formats that require one (e.g. fMP4 ftyp+moov)."""
        return f"live:channel:{channel_id}:output:{fmt}:init"

    @staticmethod
    def output_state(channel_id, fmt):
        """Remux/transcode manager state for this output format."""
        return f"live:channel:{channel_id}:output:{fmt}:state"

    @staticmethod
    def output_owner(channel_id, fmt):
        """Worker ID owning the output format manager."""
        return f"live:channel:{channel_id}:output:{fmt}:owner"

    @staticmethod
    def output_playlist(channel_id, fmt):
        """Rolling HLS playlist descriptor (JSON window of segment seq/duration)."""
        return f"live:channel:{channel_id}:output:{fmt}:playlist"

    @staticmethod
    def output_chunk_timestamps(channel_id, fmt):
        """Sorted set mapping fragment receive-timestamps to fragment indices."""
        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk_timestamps"

