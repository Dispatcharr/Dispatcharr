import json
import threading
import logging
import time
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from apps.proxy.config import TSConfig as Config  # Change this line
from .server import ProxyServer

logger = logging.getLogger(__name__)
proxy_server = ProxyServer()

@csrf_exempt
@require_http_methods(["POST"])
def initialize_stream(request, channel_id):
    """Initialize a new stream channel"""
    try:
        data = json.loads(request.body)
        url = data.get('url')
        if not url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
        
        # Start the channel
        proxy_server.initialize_channel(url, channel_id)
        
        # Wait for connection to be established
        manager = proxy_server.stream_managers[channel_id]
        wait_start = time.time()
        while not manager.connected:
            if time.time() - wait_start > Config.CONNECTION_TIMEOUT:
                proxy_server.stop_channel(channel_id)
                return JsonResponse({
                    'error': 'Connection timeout'
                }, status=504)
            if not manager.should_retry():
                proxy_server.stop_channel(channel_id)
                return JsonResponse({
                    'error': 'Failed to connect'
                }, status=502)
            time.sleep(0.1)
            
        return JsonResponse({
            'message': 'Stream initialized and connected',
            'channel': channel_id,
            'url': url
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to initialize stream: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def stream_ts(request, channel_id):
    """Handle TS stream requests"""
    if channel_id not in proxy_server.stream_managers:
        return JsonResponse({'error': 'Channel not found'}, status=404)
        
    def generate():
        client_id = threading.get_ident()
        try:
            buffer = proxy_server.stream_buffers[channel_id]
            client_manager = proxy_server.client_managers[channel_id]
            
            client_manager.add_client(client_id)
            last_index = buffer.index
            
            while True:
                with buffer.lock:
                    if buffer.index > last_index:
                        chunks_behind = buffer.index - last_index
                        start_pos = max(0, len(buffer.buffer) - chunks_behind)
                        
                        for i in range(start_pos, len(buffer.buffer)):
                            yield buffer.buffer[i]
                        last_index = buffer.index
                
                threading.Event().wait(0.1)  # Short sleep between checks
                
        except Exception as e:
            logger.error(f"Streaming error for channel {channel_id}: {e}")
        finally:
            try:
                if channel_id in proxy_server.client_managers:
                    remaining = proxy_server.client_managers[channel_id].remove_client(client_id)
                    if remaining == 0:
                        logger.info(f"No clients remaining, stopping channel {channel_id}")
                        proxy_server.stop_channel(channel_id)
            except Exception as e:
                logger.error(f"Error during client cleanup: {e}")

    return StreamingHttpResponse(
        generate(),
        content_type='video/MP2T'
    )

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