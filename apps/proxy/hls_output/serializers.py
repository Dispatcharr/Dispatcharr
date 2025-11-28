"""
HLS Output Serializers
"""

from rest_framework import serializers
from .models import HLSStream, HLSOutputProfile, HLSSegment


class HLSOutputProfileSerializer(serializers.ModelSerializer):
    """Serializer for HLS Output Profile"""
    
    class Meta:
        model = HLSOutputProfile
        fields = '__all__'
    
    def validate_qualities(self, value):
        """Validate quality profiles structure"""
        if not isinstance(value, list):
            raise serializers.ValidationError("Qualities must be a list")
        
        for quality in value:
            required_fields = ['name', 'resolution', 'video_bitrate', 'audio_bitrate']
            for field in required_fields:
                if field not in quality:
                    raise serializers.ValidationError(
                        f"Quality profile missing required field: {field}"
                    )
        
        return value
    
    def validate_segment_duration(self, value):
        """Validate segment duration"""
        if value < 2 or value > 10:
            raise serializers.ValidationError("Segment duration must be between 2 and 10 seconds")
        return value
    
    def validate_dvr_window_seconds(self, value):
        """Validate DVR window"""
        if value < 0 or value > 86400:
            raise serializers.ValidationError("DVR window must be between 0 and 86400 seconds (24 hours)")
        return value


class HLSSegmentSerializer(serializers.ModelSerializer):
    """Serializer for HLS Segment"""
    
    class Meta:
        model = HLSSegment
        fields = [
            'sequence_number',
            'quality_level',
            'filename',
            'file_size',
            'duration',
            'created_at',
            'program_date_time'
        ]


class HLSStreamSerializer(serializers.ModelSerializer):
    """Serializer for HLS Stream"""
    
    profile_name = serializers.CharField(source='profile.name', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    channel_number = serializers.FloatField(source='channel.channel_number', read_only=True)
    uptime_seconds = serializers.SerializerMethodField()
    average_bitrate = serializers.SerializerMethodField()
    
    class Meta:
        model = HLSStream
        fields = [
            'stream_id',
            'channel',
            'channel_name',
            'channel_number',
            'profile',
            'profile_name',
            'status',
            'current_sequence',
            'total_segments_generated',
            'viewer_count',
            'total_bytes_generated',
            'start_time',
            'last_segment_time',
            'uptime_seconds',
            'average_bitrate',
            'restart_count',
            'error_message',
            'dvr_start_sequence',
            'dvr_end_sequence'
        ]
    
    def get_uptime_seconds(self, obj):
        """Calculate uptime in seconds"""
        if obj.start_time:
            from django.utils import timezone
            return (timezone.now() - obj.start_time).total_seconds()
        return 0
    
    def get_average_bitrate(self, obj):
        """Calculate average bitrate in bps"""
        uptime = self.get_uptime_seconds(obj)
        if uptime > 0:
            return (obj.total_bytes_generated * 8) / uptime
        return 0


class HLSStreamListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for stream list"""
    
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    profile_name = serializers.CharField(source='profile.name', read_only=True)
    
    class Meta:
        model = HLSStream
        fields = [
            'stream_id',
            'channel_name',
            'profile_name',
            'status',
            'viewer_count',
            'start_time'
        ]

