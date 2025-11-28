"""
HLS Playlist Generator

Generates HLS master and media playlists.
"""

import logging
from datetime import timedelta
from django.utils import timezone
from .models import HLSSegment

logger = logging.getLogger(__name__)


class PlaylistGenerator:
    """Generates HLS master and media playlists"""
    
    def __init__(self, stream, profile):
        self.stream = stream
        self.profile = profile
    
    def generate_master_playlist(self) -> str:
        """Generate master playlist (multivariant)"""
        lines = ['#EXTM3U', '#EXT-X-VERSION:7']
        
        if not self.profile.qualities:
            # Single quality - no master playlist needed
            return self.generate_media_playlist('default')
        
        for quality in self.profile.qualities:
            resolution = quality['resolution']
            video_bitrate = int(quality['video_bitrate'].rstrip('k')) * 1000
            audio_bitrate = int(quality['audio_bitrate'].rstrip('k')) * 1000
            total_bitrate = video_bitrate + audio_bitrate
            quality_name = quality['name']
            
            lines.append(
                f'#EXT-X-STREAM-INF:BANDWIDTH={total_bitrate},'
                f'RESOLUTION={resolution},'
                f'CODECS="avc1.640028,mp4a.40.2"'
            )
            lines.append(f'{quality_name}/playlist.m3u8')
        
        return '\n'.join(lines) + '\n'
    
    def generate_media_playlist(self, quality_level: str, start_seq: int = None, end_seq: int = None) -> str:
        """Generate media playlist for specific quality"""
        
        # Get segments from database
        segments = self._get_segments(quality_level, start_seq, end_seq)
        
        if not segments:
            # Return minimal playlist
            lines = [
                '#EXTM3U',
                f'#EXT-X-VERSION:7',
                f'#EXT-X-TARGETDURATION:{self.profile.segment_duration}',
                f'#EXT-X-MEDIA-SEQUENCE:0',
            ]
            return '\n'.join(lines) + '\n'
        
        lines = [
            '#EXTM3U',
            f'#EXT-X-VERSION:7',
            f'#EXT-X-TARGETDURATION:{self.profile.segment_duration}',
            f'#EXT-X-MEDIA-SEQUENCE:{segments[0].sequence_number}',
        ]
        
        if self.profile.playlist_type == 'event':
            # DVR-enabled playlist
            pass  # Don't add EXT-X-ENDLIST until stream ends
        elif self.profile.playlist_type == 'vod':
            lines.append('#EXT-X-PLAYLIST-TYPE:VOD')
        
        # Add init segment for fMP4
        if self.profile.segment_format == 'fmp4':
            lines.append(f'#EXT-X-MAP:URI="init.mp4"')
        
        # Add segments
        for segment in segments:
            lines.append(f'#EXT-X-PROGRAM-DATE-TIME:{segment.program_date_time.isoformat()}Z')
            lines.append(f'#EXTINF:{segment.duration:.3f},')
            lines.append(segment.filename)
        
        # Add endlist if stream is stopped or VOD
        if self.profile.playlist_type == 'vod' or self.stream.status == 'stopped':
            lines.append('#EXT-X-ENDLIST')
        
        return '\n'.join(lines) + '\n'
    
    def _get_segments(self, quality_level: str, start_seq: int = None, end_seq: int = None):
        """Get segments from DVR window"""
        
        query = HLSSegment.objects.filter(
            stream=self.stream,
            quality_level=quality_level,
            marked_for_deletion=False
        )
        
        if start_seq is not None:
            query = query.filter(sequence_number__gte=start_seq)
        if end_seq is not None:
            query = query.filter(sequence_number__lte=end_seq)
        
        # Apply DVR window
        if self.profile.dvr_window_seconds > 0 and self.profile.playlist_type == 'event':
            dvr_cutoff = timezone.now() - timedelta(seconds=self.profile.dvr_window_seconds)
            query = query.filter(created_at__gte=dvr_cutoff)
        
        # Limit to max playlist segments for live
        if self.profile.playlist_type == 'live':
            query = query.order_by('-sequence_number')[:self.profile.max_playlist_segments]
            # Reverse to get chronological order
            segments = list(reversed(list(query)))
        else:
            segments = list(query.order_by('sequence_number'))
        
        return segments
    
    def get_segment_count(self, quality_level: str) -> int:
        """Get total segment count for quality level"""
        return HLSSegment.objects.filter(
            stream=self.stream,
            quality_level=quality_level,
            marked_for_deletion=False
        ).count()
    
    def get_dvr_window_duration(self, quality_level: str) -> float:
        """Get actual DVR window duration in seconds"""
        segments = self._get_segments(quality_level)
        
        if not segments:
            return 0.0
        
        total_duration = sum(seg.duration for seg in segments)
        return total_duration

