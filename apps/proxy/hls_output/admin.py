"""
HLS Output Admin Interface
"""

from django.contrib import admin
from .models import HLSOutputProfile, HLSStream, HLSSegment


@admin.register(HLSOutputProfile)
class HLSOutputProfileAdmin(admin.ModelAdmin):
    """Admin interface for HLS Output Profiles"""
    
    list_display = [
        'name',
        'segment_duration',
        'max_playlist_segments',
        'enable_abr',
        'enable_ll_hls',
        'dvr_window_seconds',
        'auto_cleanup',
        'created_at'
    ]
    
    list_filter = [
        'enable_abr',
        'enable_ll_hls',
        'auto_cleanup',
        'use_memory_storage'
    ]
    
    search_fields = ['name', 'description']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description')
        }),
        ('Segment Settings', {
            'fields': (
                'segment_duration',
                'max_playlist_segments',
                'segment_format',
                'playlist_type'
            )
        }),
        ('DVR Settings', {
            'fields': (
                'dvr_window_seconds',
            )
        }),
        ('Quality & Bitrate', {
            'fields': (
                'enable_abr',
                'qualities'
            )
        }),
        ('Low-Latency HLS', {
            'fields': (
                'enable_ll_hls',
                'partial_segment_duration'
            )
        }),
        ('Storage Settings', {
            'fields': (
                'storage_path',
                'use_memory_storage'
            )
        }),
        ('Cleanup Settings', {
            'fields': (
                'auto_cleanup',
                'cleanup_interval_seconds'
            )
        }),
        ('Caching Settings', {
            'fields': (
                'playlist_cache_ttl',
                'segment_cache_ttl'
            )
        }),
        ('CDN Settings (Optional)', {
            'fields': (
                'enable_cdn',
                'cdn_base_url'
            )
        }),
    )


@admin.register(HLSStream)
class HLSStreamAdmin(admin.ModelAdmin):
    """Admin interface for HLS Streams"""
    
    list_display = [
        'stream_id',
        'channel',
        'profile',
        'status',
        'viewer_count',
        'current_sequence',
        'total_segments_generated',
        'start_time'
    ]
    
    list_filter = ['status', 'profile']
    
    search_fields = ['stream_id', 'channel__name']
    
    readonly_fields = [
        'stream_id',
        'ffmpeg_pid',
        'ffmpeg_command',
        'current_sequence',
        'total_segments_generated',
        'viewer_count',
        'total_bytes_generated',
        'start_time',
        'last_segment_time',
        'restart_count',
        'error_message'
    ]
    
    fieldsets = (
        ('Stream Information', {
            'fields': (
                'stream_id',
                'channel',
                'profile',
                'status'
            )
        }),
        ('FFmpeg Process', {
            'fields': (
                'ffmpeg_pid',
                'ffmpeg_command'
            )
        }),
        ('Statistics', {
            'fields': (
                'current_sequence',
                'total_segments_generated',
                'viewer_count',
                'total_bytes_generated',
                'start_time',
                'last_segment_time',
                'restart_count'
            )
        }),
        ('DVR Window', {
            'fields': (
                'dvr_start_sequence',
                'dvr_end_sequence'
            )
        }),
        ('Error Information', {
            'fields': (
                'error_message',
            )
        }),
    )


@admin.register(HLSSegment)
class HLSSegmentAdmin(admin.ModelAdmin):
    """Admin interface for HLS Segments"""
    
    list_display = [
        'stream',
        'sequence_number',
        'quality_level',
        'filename',
        'file_size',
        'duration',
        'created_at',
        'marked_for_deletion'
    ]
    
    list_filter = [
        'quality_level',
        'marked_for_deletion',
        'stream__status'
    ]
    
    search_fields = ['stream__stream_id', 'filename']
    
    readonly_fields = [
        'stream',
        'sequence_number',
        'quality_level',
        'filename',
        'file_path',
        'file_size',
        'duration',
        'program_date_time',
        'created_at',
        'deleted_at'
    ]

