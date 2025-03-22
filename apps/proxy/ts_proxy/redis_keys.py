"""
Defines Redis key patterns used throughout the TS proxy service.
Centralizing these key patterns makes it easier to maintain and change them if needed.
"""

class RedisKeys:
    @staticmethod
    def channel_metadata(channel_id):
        """Key for channel metadata hash"""
        return f"ts_proxy:channel:{channel_id}:metadata"

    @staticmethod
    def buffer_index(channel_id):
        """Key for tracking buffer index"""
        return f"ts_proxy:channel:{channel_id}:buffer:index"

    @staticmethod
    def buffer_chunk(channel_id, chunk_index):
        """Key for specific buffer chunk"""
        return f"ts_proxy:channel:{channel_id}:buffer:chunk:{chunk_index}"

    @staticmethod
    def buffer_chunk_prefix(channel_id):
        """Prefix for buffer chunks"""
        return f"ts_proxy:channel:{channel_id}:buffer:chunk:"

    @staticmethod
    def channel_stopping(channel_id):
        """Key indicating channel is stopping"""
        return f"ts_proxy:channel:{channel_id}:stopping"

    @staticmethod
    def client_stop(channel_id, client_id):
        """Key requesting client stop"""
        return f"ts_proxy:channel:{channel_id}:client:{client_id}:stop"

    @staticmethod
    def events_channel(channel_id):
        """PubSub channel for events"""
        return f"ts_proxy:events:{channel_id}"

    @staticmethod
    def switch_request(channel_id):
        """Key for stream switch request"""
        return f"ts_proxy:channel:{channel_id}:switch_request"

    @staticmethod
    def channel_owner(channel_id):
        """Key for storing channel owner worker ID"""
        return f"ts_proxy:channel:{channel_id}:owner"

    @staticmethod
    def clients(channel_id):
        """Key for set of client IDs"""
        return f"ts_proxy:channel:{channel_id}:clients"

    @staticmethod
    def last_client_disconnect(channel_id):
        """Key for last client disconnect timestamp"""
        return f"ts_proxy:channel:{channel_id}:last_client_disconnect_time"

    @staticmethod
    def connection_attempt(channel_id):
        """Key for connection attempt timestamp"""
        return f"ts_proxy:channel:{channel_id}:connection_attempt_time"

    @staticmethod
    def last_data(channel_id):
        """Key for last data timestamp"""
        return f"ts_proxy:channel:{channel_id}:last_data"

    @staticmethod
    def switch_status(channel_id):
        """Key for stream switch status"""
        return f"ts_proxy:channel:{channel_id}:switch_status"

    @staticmethod
    def worker_heartbeat(worker_id):
        """Key for worker heartbeat"""
        return f"ts_proxy:worker:{worker_id}:heartbeat"

    @staticmethod
    def transcode_active(channel_id):
        """Key indicating active transcode process"""
        return f"ts_proxy:channel:{channel_id}:transcode_active"

    @staticmethod
    def client_metadata(channel_id, client_id):
        """Key for client metadata hash"""
        return f"ts_proxy:channel:{channel_id}:clients:{client_id}"
