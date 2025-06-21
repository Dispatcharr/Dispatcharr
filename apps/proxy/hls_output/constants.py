class HLSChannelState:
    IDLE = "idle"
    STARTING_FFMPEG = "starting_ffmpeg"
    GENERATING_HLS = "generating_hls"  # FFmpeg is running
    ACTIVE = "active"  # Manifest ready, segments available
    STOPPING_FFMPEG = "stopping_ffmpeg"
    STOPPED = "stopped"
    ERROR = "error"
