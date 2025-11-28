"""
HLS Stream Manager

Manages HLS stream lifecycle.
"""

import logging
import gevent
from .models import HLSStream
from .encoder import HLSEncoder
from .playlist_generator import PlaylistGenerator
from .segment_manager import SegmentManager

logger = logging.getLogger(__name__)


class HLSStreamManager:
    """Manages HLS stream lifecycle"""
    
    _instances = {}  # stream_id -> HLSStreamManager
    
    def __init__(self, stream: HLSStream):
        self.stream = stream
        self.profile = stream.profile
        self.encoder = HLSEncoder(stream, self.profile)
        self.playlist_gen = PlaylistGenerator(stream, self.profile)
        self.segment_mgr = SegmentManager(stream, self.profile)
        self.cleanup_greenlet = None
    
    @classmethod
    def get_or_create(cls, channel_id: int) -> 'HLSStreamManager':
        """Get existing or create new stream manager"""
        
        from apps.channels.models import Channel
        
        channel = Channel.objects.get(id=channel_id)
        
        if not channel.hls_output_enabled or not channel.hls_output_profile:
            raise ValueError("HLS output not enabled for this channel")
        
        # Check for existing active stream
        existing_stream = HLSStream.objects.filter(
            channel=channel,
            status__in=['starting', 'running']
        ).first()
        
        if existing_stream:
            stream_id_str = str(existing_stream.stream_id)
            if stream_id_str in cls._instances:
                return cls._instances[stream_id_str]
            else:
                manager = cls(existing_stream)
                cls._instances[stream_id_str] = manager
                return manager
        
        # Create new stream
        stream = HLSStream.objects.create(
            channel=channel,
            profile=channel.hls_output_profile,
            status='starting'
        )
        
        manager = cls(stream)
        cls._instances[str(stream.stream_id)] = manager
        return manager
    
    @classmethod
    def get_by_stream_id(cls, stream_id: str) -> 'HLSStreamManager':
        """Get stream manager by stream ID"""
        if stream_id in cls._instances:
            return cls._instances[stream_id]
        
        # Try to load from database
        try:
            stream = HLSStream.objects.get(stream_id=stream_id, status__in=['starting', 'running'])
            manager = cls(stream)
            cls._instances[stream_id] = manager
            return manager
        except HLSStream.DoesNotExist:
            raise ValueError(f"Stream {stream_id} not found or not active")
    
    def start(self, input_url: str):
        """Start HLS encoding"""
        
        try:
            logger.info(f"Starting HLS stream {self.stream.stream_id} for channel {self.stream.channel.name}")
            
            # Start FFmpeg encoder
            self.encoder.start(input_url)
            
            # Start cleanup task
            if self.profile.auto_cleanup:
                self.cleanup_greenlet = gevent.spawn(self._cleanup_loop)
            
            logger.info(f"HLS stream {self.stream.stream_id} started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start HLS stream: {e}")
            self.stream.status = 'error'
            self.stream.error_message = str(e)
            self.stream.save()
            raise
    
    def stop(self):
        """Stop HLS encoding"""
        
        try:
            logger.info(f"Stopping HLS stream {self.stream.stream_id}")
            
            # Stop encoder
            self.encoder.stop()
            
            # Stop cleanup
            if self.cleanup_greenlet:
                self.cleanup_greenlet.kill()
            
            # Remove from instances
            stream_id_str = str(self.stream.stream_id)
            if stream_id_str in self._instances:
                del self._instances[stream_id_str]
            
            logger.info(f"HLS stream {self.stream.stream_id} stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping HLS stream: {e}")
    
    def restart(self):
        """Restart HLS encoding"""
        
        logger.info(f"Restarting HLS stream {self.stream.stream_id}")
        
        # Get input URL before stopping
        input_url = self.stream.channel.get_stream_url()
        
        # Stop current encoding
        self.stop()
        
        # Wait briefly
        gevent.sleep(2)
        
        # Start new encoding
        self.start(input_url)
        
        # Increment restart count
        self.stream.restart_count += 1
        self.stream.save(update_fields=['restart_count'])

    def _cleanup_loop(self):
        """Periodic cleanup of old segments"""
        while True:
            try:
                self.segment_mgr.cleanup_old_segments()
                gevent.sleep(self.profile.cleanup_interval_seconds)
            except Exception as e:
                logger.error(f"Cleanup error for stream {self.stream.stream_id}: {e}")
                gevent.sleep(60)  # Wait longer on error

