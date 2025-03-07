import json
import threading
import logging
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .server import ProxyServer, Config

logger = logging.getLogger(__name__)
proxy_server = ProxyServer()

@csrf_exempt
@require_http_methods(["GET"])
def stream_endpoint(request, channel_id):
    """Handle HLS manifest requests"""
    if channel_id not in proxy_server.stream_managers:
        return JsonResponse({'error': 'Channel not found'}, status=404)
    
    response = proxy_server.stream_endpoint(channel_id)
    return StreamingHttpResponse(
        response[0],
        content_type='application/vnd.apple.mpegurl',
        status=response[1]
    )

@csrf_exempt
@require_http_methods(["GET"])
def get_segment(request, segment_name):
    """Serve MPEG-TS segments"""
    try:
        segment_num = int(segment_name.split('.')[0])
        buffer = proxy_server.stream_buffers.get(segment_num)
        
        if not buffer:
            return JsonResponse({'error': 'Segment not found'}, status=404)
            
        return StreamingHttpResponse(
            buffer,
            content_type='video/MP2T'
        )
    except ValueError:
        return JsonResponse({'error': 'Invalid segment name'}, status=400)
    except Exception as e:
        logger.error(f"Error serving segment: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def change_stream(request, channel_id):
    """Change stream URL for existing channel"""
    try:
        if channel_id not in proxy_server.stream_managers:
            return JsonResponse({'error': 'Channel not found'}, status=404)
            
        data = json.loads(request.body)
        new_url = data.get('url')
        if not new_url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
            
        manager = proxy_server.stream_managers[channel_id]
        if manager.update_url(new_url):
            return JsonResponse({
                'message': 'Stream URL updated',
                'channel': channel_id,
                'url': new_url
            })
            
        return JsonResponse({
            'message': 'URL unchanged',
            'channel': channel_id,
            'url': new_url
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to change stream: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def initialize_stream(request, channel_id):
    """Initialize a new HLS stream channel"""
    try:
        data = json.loads(request.body)
        url = data.get('url')
        if not url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
            
        proxy_server.initialize_channel(url, channel_id)
        return JsonResponse({
            'message': 'Stream initialized',
            'channel': channel_id,
            'url': url
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to initialize stream: {e}")
        return JsonResponse({'error': str(e)}, status=500)