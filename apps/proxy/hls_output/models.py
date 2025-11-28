"""
HLS Output Models

Database models for HLS streaming output system.
"""

from django.db import models
from django.utils import timezone
import uuid


class HLSOutputProfile(models.Model):
    """HLS Output configuration profile"""
    
    # Basic Info
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    
    # Segment Settings
    segment_duration = models.IntegerField(
        default=4,
        help_text="Target segment duration in seconds (2-10)"
    )
    segment_format = models.CharField(
        max_length=10,
        choices=[('fmp4', 'Fragmented MP4'), ('mpegts', 'MPEG-TS')],
        default='fmp4'
    )
    playlist_type = models.CharField(
        max_length=10,
        choices=[('live', 'Live'), ('event', 'Event/DVR'), ('vod', 'VOD')],
        default='event'
    )
    
    # DVR Settings
    dvr_window_seconds = models.IntegerField(
        default=7200,  # 2 hours
        help_text="DVR window duration in seconds (0-86400)"
    )
    max_playlist_segments = models.IntegerField(
        default=10,
        help_text="Number of segments in live playlist"
    )
    
    # Quality/Bitrate Settings
    enable_abr = models.BooleanField(
        default=True,
        help_text="Enable Adaptive Bitrate Streaming"
    )
    qualities = models.JSONField(
        default=list,
        help_text="List of quality profiles: [{name, resolution, video_bitrate, audio_bitrate}]"
    )
    
    # Low-Latency Settings
    enable_ll_hls = models.BooleanField(
        default=False,
        help_text="Enable Low-Latency HLS"
    )
    partial_segment_duration = models.FloatField(
        default=0.33,
        help_text="Partial segment duration for LL-HLS (seconds)"
    )
    
    # Storage Settings
    storage_path = models.CharField(
        max_length=512,
        default='/var/www/hls',
        help_text="Base path for HLS segment storage"
    )
    use_memory_storage = models.BooleanField(
        default=False,
        help_text="Use /dev/shm for hot segments"
    )
    
    # Cleanup Settings
    auto_cleanup = models.BooleanField(
        default=True,
        help_text="Automatically delete old segments"
    )
    cleanup_interval_seconds = models.IntegerField(
        default=60,
        help_text="Cleanup interval in seconds"
    )
    
    # Caching Settings
    enable_nginx_cache = models.BooleanField(
        default=True,
        help_text="Enable Nginx caching for HLS delivery"
    )
    playlist_cache_ttl = models.IntegerField(
        default=2,
        help_text="Playlist cache TTL in seconds"
    )
    segment_cache_ttl = models.IntegerField(
        default=86400,
        help_text="Segment cache TTL in seconds"
    )
    
    # CDN Settings (Optional)
    enable_cdn = models.BooleanField(
        default=False,
        help_text="Enable CDN integration (optional)"
    )
    cdn_base_url = models.URLField(
        blank=True,
        help_text="CDN base URL (e.g., https://cdn.example.com)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'hls_output_profiles'
        verbose_name = 'HLS Output Profile'
        verbose_name_plural = 'HLS Output Profiles'
    
    def __str__(self):
        return self.name
    
    @staticmethod
    def get_default_qualities():
        """Get default quality ladder including 4K UHD"""
        return [
            {
                'name': '2160p',
                'resolution': '3840x2160',
                'video_bitrate': '16000k',
                'audio_bitrate': '192k',
                'description': '4K UHD'
            },
            {
                'name': '1440p',
                'resolution': '2560x1440',
                'video_bitrate': '10000k',
                'audio_bitrate': '192k',
                'description': '2K QHD'
            },
            {
                'name': '1080p',
                'resolution': '1920x1080',
                'video_bitrate': '5000k',
                'audio_bitrate': '128k',
                'description': 'Full HD'
            },
            {
                'name': '720p',
                'resolution': '1280x720',
                'video_bitrate': '2800k',
                'audio_bitrate': '128k',
                'description': 'HD'
            },
            {
                'name': '480p',
                'resolution': '854x480',
                'video_bitrate': '1400k',
                'audio_bitrate': '96k',
                'description': 'SD'
            },
            {
                'name': '360p',
                'resolution': '640x360',
                'video_bitrate': '800k',
                'audio_bitrate': '96k',
                'description': 'Low'
            },
        ]


class HLSStream(models.Model):
    """Active HLS stream instance"""

    # Relationships
    channel = models.ForeignKey(
        'core.Channel',
        on_delete=models.CASCADE,
        related_name='hls_streams'
    )
    profile = models.ForeignKey(
        HLSOutputProfile,
        on_delete=models.PROTECT,
        related_name='streams'
    )

    # Stream Info
    stream_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(
        max_length=20,
        choices=[
            ('starting', 'Starting'),
            ('running', 'Running'),
            ('stopping', 'Stopping'),
            ('stopped', 'Stopped'),
            ('error', 'Error')
        ],
        default='starting'
    )

    # FFmpeg Process
    ffmpeg_pid = models.IntegerField(null=True, blank=True)
    ffmpeg_command = models.TextField(blank=True)

    # Segment Tracking
    current_sequence = models.BigIntegerField(default=0)
    total_segments_generated = models.BigIntegerField(default=0)

    # DVR Window
    dvr_start_sequence = models.BigIntegerField(default=0)
    dvr_end_sequence = models.BigIntegerField(default=0)

    # Statistics
    start_time = models.DateTimeField(auto_now_add=True)
    last_segment_time = models.DateTimeField(null=True, blank=True)
    viewer_count = models.IntegerField(default=0)
    total_bytes_generated = models.BigIntegerField(default=0)

    # Error Tracking
    error_message = models.TextField(blank=True)
    restart_count = models.IntegerField(default=0)

    class Meta:
        db_table = 'hls_streams'
        verbose_name = 'HLS Stream'
        verbose_name_plural = 'HLS Streams'
        indexes = [
            models.Index(fields=['stream_id']),
            models.Index(fields=['channel', 'status']),
        ]

    def __str__(self):
        return f"HLS Stream {self.stream_id} - {self.channel.name}"


class HLSSegment(models.Model):
    """Individual HLS segment metadata"""

    # Relationships
    stream = models.ForeignKey(
        HLSStream,
        on_delete=models.CASCADE,
        related_name='segments'
    )

    # Segment Info
    sequence_number = models.BigIntegerField()
    quality_level = models.CharField(max_length=20)  # e.g., "2160p", "1080p", "720p"

    # File Info
    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512)
    file_size = models.BigIntegerField(default=0)
    duration = models.FloatField()  # Actual duration in seconds

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    program_date_time = models.DateTimeField()  # For time-shifting

    # Cleanup
    marked_for_deletion = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'hls_segments'
        verbose_name = 'HLS Segment'
        verbose_name_plural = 'HLS Segments'
        unique_together = [['stream', 'sequence_number', 'quality_level']]
        indexes = [
            models.Index(fields=['stream', 'sequence_number']),
            models.Index(fields=['created_at']),
            models.Index(fields=['marked_for_deletion']),
        ]

    def __str__(self):
        return f"Segment {self.sequence_number} - {self.quality_level}"

