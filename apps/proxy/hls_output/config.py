"""
HLS Output Configuration Constants
"""


class HLSConfig:
    """Configuration constants for HLS Output system"""
    
    # Segment settings
    DEFAULT_SEGMENT_DURATION = 4  # seconds
    MIN_SEGMENT_DURATION = 2
    MAX_SEGMENT_DURATION = 10
    
    # Playlist settings
    DEFAULT_PLAYLIST_SIZE = 10  # number of segments
    MIN_PLAYLIST_SIZE = 3
    MAX_PLAYLIST_SIZE = 20
    
    # DVR settings
    DEFAULT_DVR_WINDOW = 7200  # 2 hours in seconds
    MAX_DVR_WINDOW = 86400  # 24 hours
    
    # Storage settings
    DEFAULT_STORAGE_PATH = '/var/www/hls'
    MEMORY_STORAGE_PATH = '/dev/shm/hls'
    
    # Caching settings
    PLAYLIST_CACHE_TTL = 2  # seconds
    SEGMENT_CACHE_TTL = 86400  # 24 hours
    
    # Cleanup settings
    DEFAULT_CLEANUP_INTERVAL = 60  # seconds
    
    # Low-latency settings
    DEFAULT_PARTIAL_SEGMENT_DURATION = 0.33  # seconds
    
    # FFmpeg settings
    FFMPEG_PRESET = 'veryfast'
    FFMPEG_TUNE = 'zerolatency'
    
    # Video codec settings
    VIDEO_CODEC = 'libx264'
    AUDIO_CODEC = 'aac'
    
    # 4K UHD Quality Profiles
    QUALITY_PROFILES = {
        '2160p': {
            'name': '2160p',
            'resolution': '3840x2160',
            'video_bitrate': '16000k',
            'audio_bitrate': '192k',
            'description': '4K UHD',
            'max_framerate': 60
        },
        '1440p': {
            'name': '1440p',
            'resolution': '2560x1440',
            'video_bitrate': '10000k',
            'audio_bitrate': '192k',
            'description': '2K QHD',
            'max_framerate': 60
        },
        '1080p': {
            'name': '1080p',
            'resolution': '1920x1080',
            'video_bitrate': '5000k',
            'audio_bitrate': '128k',
            'description': 'Full HD',
            'max_framerate': 60
        },
        '720p': {
            'name': '720p',
            'resolution': '1280x720',
            'video_bitrate': '2800k',
            'audio_bitrate': '128k',
            'description': 'HD',
            'max_framerate': 30
        },
        '480p': {
            'name': '480p',
            'resolution': '854x480',
            'video_bitrate': '1400k',
            'audio_bitrate': '96k',
            'description': 'SD',
            'max_framerate': 30
        },
        '360p': {
            'name': '360p',
            'resolution': '640x360',
            'video_bitrate': '800k',
            'audio_bitrate': '96k',
            'description': 'Low',
            'max_framerate': 30
        },
    }
    
    # Bitrate multipliers for buffer sizing
    BITRATE_BUFFER_MULTIPLIER = 1.07  # 7% overhead
    BITRATE_BUFSIZE_MULTIPLIER = 1.5  # 50% buffer

