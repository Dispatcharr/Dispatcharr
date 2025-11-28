"""
HLS Segment Manager

Manages HLS segment storage and cleanup.
"""

import os
import logging
import json
from datetime import timedelta
from django.utils import timezone
from core.utils import RedisClient
from .models import HLSSegment
from .redis_keys import HLSRedisKeys
from .config import HLSConfig

logger = logging.getLogger(__name__)


class SegmentManager:
    """Manages HLS segment storage and cleanup"""
    
    def __init__(self, stream, profile):
        self.stream = stream
        self.profile = profile
        self.redis_client = RedisClient.get_instance()
    
    def get_storage_path(self, quality_level: str = None) -> str:
        """Get storage path for segments"""
        if self.profile.use_memory_storage:
            base_path = HLSConfig.MEMORY_STORAGE_PATH
        else:
            base_path = self.profile.storage_path
        
        path = os.path.join(base_path, str(self.stream.stream_id))
        
        if quality_level:
            path = os.path.join(path, quality_level)
        
        os.makedirs(path, exist_ok=True)
        return path
    
    def register_segment(self, sequence: int, quality: str, filename: str, duration: float):
        """Register new segment in database and Redis"""
        
        file_path = os.path.join(self.get_storage_path(quality), filename)
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        
        # Create segment record
        segment = HLSSegment.objects.create(
            stream=self.stream,
            sequence_number=sequence,
            quality_level=quality,
            filename=filename,
            file_path=file_path,
            file_size=file_size,
            duration=duration,
            program_date_time=timezone.now()
        )
        
        # Store in Redis for fast access
        redis_key = HLSRedisKeys.get_segment_info_key(
            str(self.stream.stream_id),
            quality,
            sequence
        )
        
        self.redis_client.setex(
            redis_key,
            self.profile.segment_cache_ttl,
            json.dumps({
                'filename': filename,
                'duration': duration,
                'size': file_size,
                'timestamp': segment.program_date_time.isoformat()
            })
        )
        
        # Add to segment index (sorted set)
        index_key = HLSRedisKeys.get_segment_index_key(
            str(self.stream.stream_id),
            quality
        )
        self.redis_client.zadd(index_key, {filename: sequence})
        
        # Add to DVR window (sorted set by timestamp)
        dvr_key = HLSRedisKeys.get_dvr_sequences_key(str(self.stream.stream_id))
        self.redis_client.zadd(dvr_key, {str(sequence): segment.program_date_time.timestamp()})
        
        # Update stream metadata
        self.stream.current_sequence = sequence
        self.stream.total_segments_generated += 1
        self.stream.last_segment_time = timezone.now()
        self.stream.total_bytes_generated += file_size
        self.stream.save(update_fields=[
            'current_sequence',
            'total_segments_generated',
            'last_segment_time',
            'total_bytes_generated'
        ])
        
        logger.debug(
            f"Registered segment {sequence} for quality {quality} "
            f"(size: {file_size} bytes, duration: {duration:.3f}s)"
        )
        
        return segment
    
    def cleanup_old_segments(self) -> int:
        """Delete segments outside DVR window"""
        
        if not self.profile.auto_cleanup:
            return 0
        
        deleted_count = 0
        
        # Calculate DVR window cutoff
        if self.profile.dvr_window_seconds > 0:
            cutoff_time = timezone.now() - timedelta(seconds=self.profile.dvr_window_seconds)
            
            # Mark segments for deletion
            query = HLSSegment.objects.filter(
                stream=self.stream,
                marked_for_deletion=False,
                created_at__lt=cutoff_time
            )
        else:
            # Keep only max_playlist_segments
            cutoff_sequence = self.stream.current_sequence - self.profile.max_playlist_segments
            
            query = HLSSegment.objects.filter(
                stream=self.stream,
                marked_for_deletion=False,
                sequence_number__lt=cutoff_sequence
            )
        
        segments_to_delete = list(query)
        
        for segment in segments_to_delete:
            # Delete file
            if os.path.exists(segment.file_path):
                try:
                    os.remove(segment.file_path)
                    deleted_count += 1
                except OSError as e:
                    logger.error(f"Failed to delete segment {segment.file_path}: {e}")
            
            # Mark as deleted
            segment.marked_for_deletion = True
            segment.deleted_at = timezone.now()
            segment.save(update_fields=['marked_for_deletion', 'deleted_at'])

            # Remove from Redis
            redis_key = HLSRedisKeys.get_segment_info_key(
                str(self.stream.stream_id),
                segment.quality_level,
                segment.sequence_number
            )
            self.redis_client.delete(redis_key)

            # Remove from index
            index_key = HLSRedisKeys.get_segment_index_key(
                str(self.stream.stream_id),
                segment.quality_level
            )
            self.redis_client.zrem(index_key, segment.filename)

        # Clean up DVR window in Redis
        if self.profile.dvr_window_seconds > 0:
            dvr_key = HLSRedisKeys.get_dvr_sequences_key(str(self.stream.stream_id))
            cutoff_timestamp = cutoff_time.timestamp()
            self.redis_client.zremrangebyscore(dvr_key, '-inf', cutoff_timestamp)

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old segments for stream {self.stream.stream_id}")

        return deleted_count

    def purge_all_segments(self):
        """Delete all segments for this stream"""

        segments = HLSSegment.objects.filter(stream=self.stream)
        deleted_count = 0

        for segment in segments:
            if os.path.exists(segment.file_path):
                try:
                    os.remove(segment.file_path)
                    deleted_count += 1
                except OSError as e:
                    logger.error(f"Failed to delete segment {segment.file_path}: {e}")

        # Delete all segment records
        segments.delete()

        # Delete stream directory
        stream_dir = os.path.join(
            self.profile.storage_path,
            str(self.stream.stream_id)
        )

        if os.path.exists(stream_dir):
            try:
                import shutil
                shutil.rmtree(stream_dir)
            except OSError as e:
                logger.error(f"Failed to delete stream directory {stream_dir}: {e}")

        # Clean up Redis keys
        pattern = f"hls:stream:{self.stream.stream_id}:*"
        for key in self.redis_client.scan_iter(match=pattern):
            self.redis_client.delete(key)

        logger.info(f"Purged all segments for stream {self.stream.stream_id} ({deleted_count} files deleted)")

        return deleted_count

