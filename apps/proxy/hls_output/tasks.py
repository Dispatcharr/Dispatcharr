"""
HLS Output Celery Tasks

Periodic tasks for cleanup, monitoring, and maintenance.
"""

import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import HLSStream, HLSSegment
from .segment_manager import SegmentManager
from .stream_manager import HLSStreamManager
from .redis_keys import HLSRedisKeys
from core.utils import RedisClient

logger = logging.getLogger(__name__)


@shared_task(name='hls_output.cleanup_old_segments')
def cleanup_old_segments():
    """
    Periodic task to cleanup old segments outside DVR window
    Run every 5 minutes
    """
    try:
        active_streams = HLSStream.objects.filter(status__in=['running', 'starting'])
        
        total_deleted = 0
        for stream in active_streams:
            try:
                segment_mgr = SegmentManager(stream, stream.profile)
                deleted = segment_mgr.cleanup_old_segments()
                total_deleted += deleted
            except Exception as e:
                logger.error(f"Error cleaning up segments for stream {stream.stream_id}: {e}")
        
        if total_deleted > 0:
            logger.info(f"Cleaned up {total_deleted} old segments across {active_streams.count()} streams")
        
        return {
            'streams_processed': active_streams.count(),
            'segments_deleted': total_deleted
        }
        
    except Exception as e:
        logger.error(f"Error in cleanup_old_segments task: {e}")
        return {'error': str(e)}


@shared_task(name='hls_output.cleanup_stopped_streams')
def cleanup_stopped_streams():
    """
    Cleanup segments from stopped streams after retention period
    Run every hour
    """
    try:
        # Find stopped streams older than 1 hour
        cutoff_time = timezone.now() - timedelta(hours=1)
        
        stopped_streams = HLSStream.objects.filter(
            status='stopped',
            updated_at__lt=cutoff_time
        )
        
        total_deleted = 0
        streams_cleaned = 0
        
        for stream in stopped_streams:
            try:
                segment_mgr = SegmentManager(stream, stream.profile)
                deleted = segment_mgr.purge_all_segments()
                total_deleted += deleted
                streams_cleaned += 1
                
                # Mark stream as cleaned
                stream.status = 'cleaned'
                stream.save(update_fields=['status'])
                
            except Exception as e:
                logger.error(f"Error purging stream {stream.stream_id}: {e}")
        
        if streams_cleaned > 0:
            logger.info(f"Purged {total_deleted} segments from {streams_cleaned} stopped streams")
        
        return {
            'streams_cleaned': streams_cleaned,
            'segments_deleted': total_deleted
        }
        
    except Exception as e:
        logger.error(f"Error in cleanup_stopped_streams task: {e}")
        return {'error': str(e)}


@shared_task(name='hls_output.monitor_streams')
def monitor_streams():
    """
    Monitor active streams and restart if needed
    Run every 2 minutes
    """
    try:
        active_streams = HLSStream.objects.filter(status__in=['running', 'starting'])
        
        restarted_count = 0
        error_count = 0
        
        for stream in active_streams:
            try:
                # Check if stream is stale (no segments in last 30 seconds)
                if stream.last_segment_time:
                    time_since_last_segment = (timezone.now() - stream.last_segment_time).total_seconds()
                    
                    if time_since_last_segment > 30:
                        logger.warning(
                            f"Stream {stream.stream_id} is stale "
                            f"(last segment {time_since_last_segment:.0f}s ago)"
                        )
                        
                        # Check if auto-restart is enabled
                        if stream.profile.enable_auto_restart:
                            stream_id_str = str(stream.stream_id)
                            if stream_id_str in HLSStreamManager._instances:
                                manager = HLSStreamManager._instances[stream_id_str]
                                manager.restart()
                                restarted_count += 1
                                logger.info(f"Auto-restarted stream {stream.stream_id}")
                        else:
                            # Mark as error
                            stream.status = 'error'
                            stream.error_message = 'Stream stale - no segments generated'
                            stream.save(update_fields=['status', 'error_message'])
                            error_count += 1
                
            except Exception as e:
                logger.error(f"Error monitoring stream {stream.stream_id}: {e}")
        
        return {
            'streams_monitored': active_streams.count(),
            'streams_restarted': restarted_count,
            'streams_errored': error_count
        }
        
    except Exception as e:
        logger.error(f"Error in monitor_streams task: {e}")
        return {'error': str(e)}


@shared_task(name='hls_output.update_viewer_counts')
def update_viewer_counts():
    """
    Update viewer counts from Redis sessions
    Run every 30 seconds
    """
    try:
        redis_client = RedisClient.get_instance()
        active_streams = HLSStream.objects.filter(status__in=['running', 'starting'])
        
        for stream in active_streams:
            try:
                stream_id_str = str(stream.stream_id)
                
                # Count active viewer sessions (not expired)
                pattern = f"hls:viewer:*:stream:{stream_id_str}"
                viewer_count = 0
                
                for key in redis_client.scan_iter(match=pattern):
                    if redis_client.exists(key):
                        viewer_count += 1
                
                # Update stream record
                if stream.viewer_count != viewer_count:
                    stream.viewer_count = viewer_count
                    stream.save(update_fields=['viewer_count'])
                
            except Exception as e:
                logger.error(f"Error updating viewer count for stream {stream.stream_id}: {e}")
        
        return {
            'streams_updated': active_streams.count()
        }
        
    except Exception as e:
        logger.error(f"Error in update_viewer_counts task: {e}")
        return {'error': str(e)}
