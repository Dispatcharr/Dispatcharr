class HLSRedisKeys:
    @staticmethod
    def channel_metadata(channel_uuid):
        return f"hls:channel:{channel_uuid}:metadata"

    @staticmethod
    def owner(channel_uuid):
        return f"hls:channel:{channel_uuid}:owner"

    @staticmethod
    def ffmpeg_stats(channel_uuid):
        return f"hls:channel:{channel_uuid}:ffmpeg_stats"

    @staticmethod
    def worker_heartbeat(worker_id):
        return f"hls:worker:{worker_id}:heartbeat"
