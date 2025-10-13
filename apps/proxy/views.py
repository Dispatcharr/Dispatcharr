import logging

from django.apps import apps
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.media_library.views import stream_media_file

logger = logging.getLogger(__name__)

class ProxyViewSet(viewsets.ViewSet):
    """ViewSet for managing proxy servers"""

    @action(detail=False, methods=['post'])
    def start(self, request):
        """Start a proxy server for a channel"""
        try:
            proxy_type = request.data.get('type', 'hls')
            channel_id = request.data.get('channel', 'default')
            url = request.data.get('url')

            if not url:
                return Response(
                    {'error': 'URL is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            proxy_app = apps.get_app_config('proxy')
            proxy_server = getattr(proxy_app, f'{proxy_type}_proxy')
            proxy_server.initialize_channel(url, channel_id)

            return Response({
                'message': f'{proxy_type.upper()} proxy started',
                'channel': channel_id,
                'url': url
            })

        except Exception as e:
            logger.error(f"Error starting proxy: {e}")
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


    @action(detail=False, methods=['post'])
    def stop(self, request):
        """Stop a proxy server for a channel"""
        try:
            proxy_type = request.data.get('type', 'hls')
            channel_id = request.data.get('channel', 'default')

            proxy_app = apps.get_app_config('proxy')
            proxy_server = getattr(proxy_app, f'{proxy_type}_proxy')
            proxy_server.stop_channel(channel_id)

            return Response({
                'message': f'{proxy_type.upper()} proxy stopped',
                'channel': channel_id
            })

        except Exception as e:
            logger.error(f"Error stopping proxy: {e}")
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


def library_stream(request, token: str) -> HttpResponse:
    """
    Shallow proxy around the media library stream endpoint so playback traffic
    is routed through the proxy layer (for stats, connection tracking, etc.).
    """
    return stream_media_file(request, token)
