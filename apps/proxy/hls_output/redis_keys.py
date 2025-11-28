"""
Redis Key Patterns for HLS Output System
"""


class HLSRedisKeys:
    """Redis key patterns for HLS Output system"""
    
    # Stream metadata
    STREAM_METADATA = "hls:stream:{stream_id}:metadata"
    STREAM_STATUS = "hls:stream:{stream_id}:status"
    STREAM_STATS = "hls:stream:{stream_id}:stats"
    
    # Segment tracking
    SEGMENT_INFO = "hls:stream:{stream_id}:segment:{quality}:{sequence}"
    SEGMENT_INDEX = "hls:stream:{stream_id}:segments:{quality}"  # Sorted set
    
    # DVR window
    DVR_WINDOW = "hls:stream:{stream_id}:dvr:window"
    DVR_SEQUENCES = "hls:stream:{stream_id}:dvr:sequences"  # Sorted set by timestamp
    
    # Playlist cache
    MASTER_PLAYLIST = "hls:stream:{stream_id}:playlist:master"
    MEDIA_PLAYLIST = "hls:stream:{stream_id}:playlist:{quality}"
    
    # Viewer tracking
    VIEWER_COUNT = "hls:stream:{stream_id}:viewers"
    VIEWER_SESSION = "hls:viewer:{session_id}:stream:{stream_id}"
    
    # Cleanup tracking
    CLEANUP_LOCK = "hls:stream:{stream_id}:cleanup:lock"
    CLEANUP_LAST_RUN = "hls:stream:{stream_id}:cleanup:last_run"
    
    # Performance metrics
    METRICS_ENCODING = "hls:metrics:encoding:{stream_id}"
    METRICS_DELIVERY = "hls:metrics:delivery:{stream_id}"
    
    @staticmethod
    def get_stream_metadata_key(stream_id: str) -> str:
        return HLSRedisKeys.STREAM_METADATA.format(stream_id=stream_id)
    
    @staticmethod
    def get_segment_info_key(stream_id: str, quality: str, sequence: int) -> str:
        return HLSRedisKeys.SEGMENT_INFO.format(
            stream_id=stream_id,
            quality=quality,
            sequence=sequence
        )
    
    @staticmethod
    def get_segment_index_key(stream_id: str, quality: str) -> str:
        return HLSRedisKeys.SEGMENT_INDEX.format(
            stream_id=stream_id,
            quality=quality
        )
    
    @staticmethod
    def get_dvr_sequences_key(stream_id: str) -> str:
        return HLSRedisKeys.DVR_SEQUENCES.format(stream_id=stream_id)
    
    @staticmethod
    def get_master_playlist_key(stream_id: str) -> str:
        return HLSRedisKeys.MASTER_PLAYLIST.format(stream_id=stream_id)
    
    @staticmethod
    def get_media_playlist_key(stream_id: str, quality: str) -> str:
        return HLSRedisKeys.MEDIA_PLAYLIST.format(stream_id=stream_id, quality=quality)
    
    @staticmethod
    def get_viewer_session_key(session_id: str, stream_id: str) -> str:
        return HLSRedisKeys.VIEWER_SESSION.format(session_id=session_id, stream_id=stream_id)
    
    @staticmethod
    def get_viewer_count_key(stream_id: str) -> str:
        return HLSRedisKeys.VIEWER_COUNT.format(stream_id=stream_id)

