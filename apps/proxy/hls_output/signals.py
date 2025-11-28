"""
HLS Output Signals

Signal handlers for HLS Output events.
"""

import logging
from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import HLSStream
from .segment_manager import SegmentManager

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=HLSStream)
def cleanup_stream_on_delete(sender, instance, **kwargs):
    """Cleanup segments when stream is deleted"""
    try:
        logger.info(f"Cleaning up segments for deleted stream {instance.stream_id}")
        segment_mgr = SegmentManager(instance, instance.profile)
        segment_mgr.purge_all_segments()
    except Exception as e:
        logger.error(f"Error cleaning up stream on delete: {e}")

