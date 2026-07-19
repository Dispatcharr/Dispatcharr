from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.apps import apps
import logging

logger = logging.getLogger(__name__)

@receiver(pre_delete)
def cleanup_proxy_servers(sender, **kwargs):
    """Clean up proxy servers when Django shuts down"""
    try:
        proxy_app = apps.get_app_config('proxy')
        hls_proxy = getattr(proxy_app, 'hls_proxy', None)
        if hls_proxy is not None:
            for channel_id in list(hls_proxy.stream_managers.keys()):
                hls_proxy.stop_channel(channel_id)
        live_proxy = getattr(proxy_app, 'live_proxy', None)
        if live_proxy is not None:
            for channel_id in list(live_proxy.stream_managers.keys()):
                live_proxy.stop_channel(channel_id)
        logger.info("Proxy servers cleaned up successfully")
    except Exception as e:
        logger.error(f"Error during proxy server cleanup: {e}")
