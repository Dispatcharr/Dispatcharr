import json
import threading
import time
import random
import sys
import os
import re
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET
from apps.proxy.config import TSConfig as Config
from .server import ProxyServer
from apps.proxy.ts_proxy.server import logging as server_logging

# Configure logging properly to ensure visibility
logger = server_logging

# Initialize proxy server
proxy_server = ProxyServer()

@csrf_exempt
@require_http_methods(["POST"])
def initialize_stream(request, channel_id):
    """Initialize a new stream channel with initialization-based ownership"""
    try:
        data = json.loads(request.body)
        url = data.get('url')
        if not url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
        
        # Get optional user_agent from request
        user_agent = data.get('user_agent')
        
        # Try to acquire ownership and create connection
        success = proxy_server.initialize_channel(url, channel_id, user_agent)
        if not success:
            return JsonResponse({'error': 'Failed to initialize channel'}, status=500)
        
        # If we're the owner, wait for connection
        if proxy_server.am_i_owner(channel_id):
            # Wait for connection to be established
            manager = proxy_server.stream_managers.get(channel_id)
            if manager:
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
        
        # Return success response with owner status
        return JsonResponse({
            'message': 'Stream initialized and connected',
            'channel': channel_id,
            'url': url,
            'owner': proxy_server.am_i_owner(channel_id)
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to initialize stream: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@require_GET
def stream_ts(request, channel_id):
    """Stream TS data to client with single client registration"""
    try:
        # Generate a unique client ID
        client_id = f"client_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        logger.info(f"[{client_id}] Requested stream for channel {channel_id}")
        
        # Extract user agent only once
        user_agent = None
        for header in ['HTTP_USER_AGENT', 'User-Agent', 'user-agent']:
            if header in request.META:
                user_agent = request.META[header]
                logger.debug(f"[{client_id}] Found user agent in header: {header}")
                break
                
        # Check if channel exists or initialize it
        if not proxy_server.check_if_channel_exists(channel_id):
            logger.error(f"[{client_id}] Channel {channel_id} not found")
            return JsonResponse({'error': 'Channel not found'}, status=404)
        
        # Wait for channel to become ready if it's initializing
        if proxy_server.redis_client:
            wait_start = time.time()
            max_wait = getattr(Config, 'CLIENT_WAIT_TIMEOUT', 30)  # Maximum wait time in seconds
            
            # Check channel state
            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
            waiting = True
            
            while waiting and time.time() - wait_start < max_wait:
                metadata = proxy_server.redis_client.hgetall(metadata_key)
                if not metadata or b'state' not in metadata:
                    logger.warning(f"[{client_id}] Channel {channel_id} metadata missing")
                    break
                    
                state = metadata[b'state'].decode('utf-8')
                
                # If channel is ready for clients, continue
                if state in ['waiting_for_clients', 'active']:
                    logger.info(f"[{client_id}] Channel {channel_id} ready (state={state}), proceeding with connection")
                    waiting = False
                elif state in ['initializing', 'connecting']:
                    # Channel is still initializing or connecting, wait a bit longer
                    elapsed = time.time() - wait_start
                    logger.info(f"[{client_id}] Waiting for channel {channel_id} to become ready ({elapsed:.1f}s), current state: {state}")
                    time.sleep(0.5)  # Wait 500ms before checking again
                else:
                    # Unknown or error state
                    logger.warning(f"[{client_id}] Channel {channel_id} in unexpected state: {state}")
                    break
            
            # Check if we timed out waiting
            if waiting and time.time() - wait_start >= max_wait:
                logger.warning(f"[{client_id}] Timeout waiting for channel {channel_id} to become ready")
                return JsonResponse({'error': 'Timeout waiting for channel to initialize'}, status=503)

        # CRITICAL FIX: Ensure local resources are properly initialized before streaming
        if channel_id not in proxy_server.stream_buffers or channel_id not in proxy_server.client_managers:
            logger.warning(f"[{client_id}] Channel {channel_id} exists in Redis but not initialized in this worker - initializing now")
            
            # Get URL from Redis metadata
            url = None
            if proxy_server.redis_client:
                metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
                url_bytes = proxy_server.redis_client.hget(metadata_key, "url")
                if url_bytes:
                    url = url_bytes.decode('utf-8')
            
            # Initialize local resources - pass the user_agent we extracted earlier
            success = proxy_server.initialize_channel(url, channel_id, user_agent)
            if not success:
                logger.error(f"[{client_id}] Failed to initialize channel {channel_id} locally")
                return JsonResponse({'error': 'Failed to initialize channel locally'}, status=500)
                
            logger.info(f"[{client_id}] Successfully initialized channel {channel_id} locally")
        
        # Get stream buffer and client manager
        buffer = proxy_server.stream_buffers[channel_id]
        client_manager = proxy_server.client_managers[channel_id]
        client_manager.add_client(client_id, user_agent)
        logger.info(f"[{client_id}] Client registered with channel {channel_id}")
        
        # Start stream response
        def generate():            
            stream_start_time = time.time()
            bytes_sent = 0
            chunks_sent = 0
            
            try:
                # ENHANCED USER AGENT DETECTION - check multiple possible headers
                user_agent = None
                
                # Try multiple possible header formats
                ua_headers = ['HTTP_USER_AGENT', 'User-Agent', 'user-agent', 'User_Agent']
                
                for header in ua_headers:
                    if header in request.META:
                        user_agent = request.META[header]
                        logger.debug(f"Found user agent in header: {header}")
                        break
                        
                # Try request.headers dictionary (Django 2.2+)
                if not user_agent and hasattr(request, 'headers'):
                    for header in ['User-Agent', 'user-agent']:
                        if header in request.headers:
                            user_agent = request.headers[header]
                            logger.debug(f"Found user agent in request.headers: {header}")
                            break
                
                # Final fallback - check if in any header with case-insensitive matching
                if not user_agent:
                    for key, value in request.META.items():
                        if key.upper().replace('_', '-') == 'USER-AGENT':
                            user_agent = value
                            logger.debug(f"Found user agent in alternate header: {key}")
                            break
                
                # Log headers for debugging user agent issues
                if not user_agent:
                    # Log all headers to help troubleshoot
                    headers = {k: v for k, v in request.META.items() if k.startswith('HTTP_')}
                    logger.debug(f"No user agent found in request. Available headers: {headers}")
                    user_agent = "Unknown-Client"  # Default value instead of None
                
                logger.info(f"[{client_id}] New client connected to channel {channel_id} with user agent: {user_agent}")
                
                # Add client to manager with user agent
                client_manager = proxy_server.client_managers[channel_id]
                client_count = client_manager.add_client(client_id, user_agent)
                
                # If this is the first client, try to acquire ownership
                if client_count == 1 and not proxy_server.am_i_owner(channel_id):
                    if proxy_server.try_acquire_ownership(channel_id):
                        logger.info(f"[{client_id}] First client, acquiring channel ownership")
                        
                        # Get channel metadata from Redis
                        if proxy_server.redis_client:
                            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
                            url_bytes = proxy_server.redis_client.hget(metadata_key, "url")
                            ua_bytes = proxy_server.redis_client.hget(metadata_key, "user_agent")
                            
                            url = url_bytes.decode('utf-8') if url_bytes else None
                            user_agent = ua_bytes.decode('utf-8') if ua_bytes else None
                            
                            if url:
                                # Create and start stream connection
                                from .server import StreamManager  # Import here to avoid circular import
                                
                                logger.info(f"[{client_id}] Creating stream connection for URL: {url}")
                                buffer = proxy_server.stream_buffers[channel_id]
                                
                                stream_manager = StreamManager(url, buffer, user_agent=user_agent)
                                proxy_server.stream_managers[channel_id] = stream_manager
                                
                                thread = threading.Thread(target=stream_manager.run, daemon=True)
                                thread.name = f"stream-{channel_id}"
                                thread.start()
                                
                                # Wait briefly for connection
                                wait_start = time.time()
                                while not stream_manager.connected:
                                    if time.time() - wait_start > Config.CONNECTION_TIMEOUT:
                                        break
                                    time.sleep(0.1)
                
                # Get buffer - stream manager may not exist in this worker
                buffer = proxy_server.stream_buffers.get(channel_id)
                stream_manager = proxy_server.stream_managers.get(channel_id)
                
                if not buffer:
                    logger.error(f"[{client_id}] No buffer found for channel {channel_id}")
                    return
                
                # Client state tracking - use config for initial position
                initial_behind = getattr(Config, 'INITIAL_BEHIND_CHUNKS', 10)
                current_buffer_index = buffer.index
                local_index = max(0, current_buffer_index - initial_behind)
                logger.debug(f"[{client_id}] Buffer at {current_buffer_index}, starting {initial_behind} chunks behind at index {local_index}")

                initial_position = local_index
                last_yield_time = time.time()
                empty_reads = 0
                bytes_sent = 0
                chunks_sent = 0
                stream_start_time = time.time()
                consecutive_empty = 0  # Track consecutive empty reads
                
                # Timing parameters from config
                ts_packet_size = 188
                target_bitrate = Config.TARGET_BITRATE 
                packets_per_second = target_bitrate / (8 * ts_packet_size)
                
                logger.info(f"[{client_id}] Starting stream at index {local_index} (buffer at {buffer.index})")
                
                # Check if we're the owner worker
                is_owner_worker = proxy_server.am_i_owner(channel_id) if hasattr(proxy_server, 'am_i_owner') else True
                
                # Main streaming loop
                while True:
                    # Get chunks at client's position using improved strategy
                    chunks, next_index = get_client_data(buffer, local_index)
                    
                    if chunks:
                        empty_reads = 0
                        consecutive_empty = 0
                        
                        # Process and send chunks
                        total_size = sum(len(c) for c in chunks)
                        logger.debug(f"[{client_id}] Retrieved {len(chunks)} chunks ({total_size} bytes) from index {local_index+1} to {next_index}")
                        
                        # CRITICAL FIX: Actually send the chunks to the client
                        for chunk in chunks:
                            try:
                                # This is the crucial line that was likely missing
                                yield chunk
                                bytes_sent += len(chunk)
                                chunks_sent += 1
                                
                                # Log every 100 chunks for visibility
                                if chunks_sent % 100 == 0:
                                    elapsed = time.time() - stream_start_time
                                    rate = bytes_sent / elapsed / 1024 if elapsed > 0 else 0
                                    logger.info(f"[{client_id}] Stats: {chunks_sent} chunks, {bytes_sent/1024:.1f}KB, {rate:.1f}KB/s")
                            except Exception as e:
                                logger.error(f"[{client_id}] Error sending chunk to client: {e}")
                                raise  # Re-raise to exit the generator
                        
                        # Update index after successfully sending all chunks
                        local_index = next_index
                        last_yield_time = time.time()
                    else:
                        # No chunks available
                        empty_reads += 1
                        consecutive_empty += 1
                        
                        # Check if we're caught up to buffer head
                        at_buffer_head = local_index >= buffer.index
                        
                        # If we're at buffer head and no data is coming, send keepalive
                        # Only check stream manager health if it exists
                        stream_healthy = stream_manager.healthy if stream_manager else True
                        
                        if at_buffer_head and not stream_healthy and consecutive_empty >= 5:
                            # Create a null TS packet as keepalive (188 bytes filled with padding)
                            # This prevents VLC from hitting EOF
                            keepalive_packet = bytearray(188)
                            keepalive_packet[0] = 0x47  # Sync byte
                            keepalive_packet[1] = 0x1F  # PID high bits (null packet)
                            keepalive_packet[2] = 0xFF  # PID low bits (null packet)
                            
                            logger.debug(f"[{client_id}] Sending keepalive packet while waiting at buffer head")
                            yield bytes(keepalive_packet)
                            bytes_sent += len(keepalive_packet)
                            last_yield_time = time.time()
                            consecutive_empty = 0  # Reset consecutive counter but keep total empty_reads
                            time.sleep(Config.KEEPALIVE_INTERVAL)
                        else:
                            # Standard wait
                            sleep_time = min(0.1 * consecutive_empty, 1.0)  # Progressive backoff up to 1s
                            time.sleep(sleep_time)
                            
                        # Log empty reads periodically
                        if empty_reads % 50 == 0:
                            stream_status = "healthy" if (stream_manager and stream_manager.healthy) else "unknown"
                            logger.debug(f"[{client_id}] Waiting for chunks beyond {local_index} (buffer at {buffer.index}, stream: {stream_status})")
                        
                        # CRITICAL FIX: Check for client disconnect during wait periods
                        # Django/WSGI might not immediately detect disconnections, but we can check periodically
                        if consecutive_empty > 10:  # After some number of empty reads
                            if hasattr(request, 'META') and request.META.get('wsgi.input'):
                                try:
                                    # Try to check if the connection is still alive
                                    available = request.META['wsgi.input'].read(0)
                                    if available is None:  # Connection closed
                                        logger.info(f"[{client_id}] Detected client disconnect during wait")
                                        break
                                except Exception:
                                    # Error reading from connection, likely closed
                                    logger.info(f"[{client_id}] Connection error, client likely disconnected")
                                    break
                        
                        # Disconnect after long inactivity
                        # For non-owner workers, we're more lenient with timeout
                        if time.time() - last_yield_time > Config.STREAM_TIMEOUT:
                            if stream_manager and not stream_manager.healthy:
                                logger.warning(f"[{client_id}] No data for {Config.STREAM_TIMEOUT}s and stream unhealthy, disconnecting")
                                break
                            elif not is_owner_worker and consecutive_empty > 100:
                                # Non-owner worker without data for too long
                                logger.warning(f"[{client_id}] Non-owner worker with no data for {Config.STREAM_TIMEOUT}s, disconnecting")
                                break
                        
                        # ADD THIS: Check if worker has more recent chunks but still stuck
                        # This can indicate the client is disconnected but we're not detecting it
                        if consecutive_empty > 100 and buffer.index > local_index + 50:
                            logger.warning(f"[{client_id}] Possible ghost client: buffer has advanced {buffer.index - local_index} chunks ahead but client stuck at {local_index}")
                            break
                        
            except Exception as e:
                logger.error(f"[{client_id}] Stream error: {e}", exc_info=True)
            finally:
                # Client cleanup
                elapsed = time.time() - stream_start_time
                local_clients = 0
                
                if channel_id in proxy_server.client_managers:
                    local_clients = proxy_server.client_managers[channel_id].remove_client(client_id)
                    total_clients = proxy_server.client_managers[channel_id].get_total_client_count()
                    logger.info(f"[{client_id}] Disconnected after {elapsed:.2f}s, {bytes_sent/1024:.1f}KB in {chunks_sent} chunks (local: {local_clients}, total: {total_clients})")
                    
                    # If no clients left and we're the owner, schedule shutdown using the config value
                    if local_clients == 0 and proxy_server.am_i_owner(channel_id):
                        logger.info(f"No local clients left for channel {channel_id}, scheduling shutdown")
                        def delayed_shutdown():
                            # Use the config setting instead of hardcoded value
                            shutdown_delay = getattr(Config, 'CHANNEL_SHUTDOWN_DELAY', 5)
                            logger.info(f"Waiting {shutdown_delay}s before checking if channel should be stopped")
                            time.sleep(shutdown_delay)
                            
                            # After delay, check global client count
                            if channel_id in proxy_server.client_managers:
                                total = proxy_server.client_managers[channel_id].get_total_client_count()
                                if total == 0:
                                    logger.info(f"Shutting down channel {channel_id} as no clients connected")
                                    proxy_server.stop_channel(channel_id)
                                else:
                                    logger.info(f"Not shutting down channel {channel_id}, {total} clients still connected")
                        
                        shutdown_thread = threading.Thread(target=delayed_shutdown)
                        shutdown_thread.daemon = True
                        shutdown_thread.start()
                
        response = StreamingHttpResponse(
            streaming_content=generate(),
            content_type='video/mp2t'
        )
        return response
        
    except Exception as e:
        logger.error(f"Error in stream_ts: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def change_stream(request, channel_id):
    """Change stream URL for existing channel with enhanced diagnostics"""
    try:
        data = json.loads(request.body)
        new_url = data.get('url')
        user_agent = data.get('user_agent')
        
        if not new_url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
        
        logger.info(f"Attempting to change stream URL for channel {channel_id} to {new_url}")
        
        # Enhanced channel detection
        in_local_managers = channel_id in proxy_server.stream_managers
        in_local_buffers = channel_id in proxy_server.stream_buffers
        
        # First check Redis directly before using our wrapper method
        redis_keys = None
        if proxy_server.redis_client:
            try:
                redis_keys = proxy_server.redis_client.keys(f"ts_proxy:*:{channel_id}*")
                redis_keys = [k.decode('utf-8') for k in redis_keys] if redis_keys else []
            except Exception as e:
                logger.error(f"Error checking Redis keys: {e}")
        
        # Now use our standard check
        channel_exists = proxy_server.check_if_channel_exists(channel_id)
        
        # Log detailed diagnostics
        logger.info(f"Channel {channel_id} diagnostics: "
                   f"in_local_managers={in_local_managers}, "
                   f"in_local_buffers={in_local_buffers}, "
                   f"redis_keys_count={len(redis_keys) if redis_keys else 0}, "
                   f"channel_exists={channel_exists}")
        
        if not channel_exists:
            # If channel doesn't exist but we found Redis keys, force initialize it
            if redis_keys:
                logger.warning(f"Channel {channel_id} not detected by check_if_channel_exists but Redis keys exist. Forcing initialization.")
                proxy_server.initialize_channel(new_url, channel_id, user_agent)
            else:
                logger.error(f"Channel {channel_id} not found in any worker or Redis")
                return JsonResponse({
                    'error': 'Channel not found',
                    'diagnostics': {
                        'in_local_managers': in_local_managers,
                        'in_local_buffers': in_local_buffers,
                        'redis_keys': redis_keys,
                    }
                }, status=404)
        
        # Update metadata in Redis regardless of ownership - this ensures URL is updated
        # even if the owner worker is handling another request
        if proxy_server.redis_client:
            try:
                metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
                
                # First check if the key exists and what type it is
                key_type = proxy_server.redis_client.type(metadata_key).decode('utf-8')
                logger.debug(f"Redis key {metadata_key} is of type: {key_type}")
                
                # Use the appropriate method based on the key type
                if key_type == 'hash':
                    proxy_server.redis_client.hset(metadata_key, "url", new_url)
                    if user_agent:
                        proxy_server.redis_client.hset(metadata_key, "user_agent", user_agent)
                elif key_type == 'none':  # Key doesn't exist yet
                    # Create new hash with all required fields
                    metadata = {"url": new_url}
                    if user_agent:
                        metadata["user_agent"] = user_agent
                    proxy_server.redis_client.hset(metadata_key, mapping=metadata)
                else:
                    # If key exists with wrong type, delete it and recreate
                    proxy_server.redis_client.delete(metadata_key)
                    metadata = {"url": new_url}
                    if user_agent:
                        metadata["user_agent"] = user_agent
                    proxy_server.redis_client.hset(metadata_key, mapping=metadata)
                    
                # Set switch request flag to ensure all workers see it
                switch_key = f"ts_proxy:channel:{channel_id}:switch_request"
                proxy_server.redis_client.setex(switch_key, 30, new_url)  # 30 second TTL
                
                logger.info(f"Updated metadata for channel {channel_id} in Redis")
            except Exception as e:
                logger.error(f"Error updating Redis metadata: {e}", exc_info=True)
                
        # If we're the owner, update directly
        if proxy_server.am_i_owner(channel_id) and channel_id in proxy_server.stream_managers:
            logger.info(f"This worker is the owner, changing stream URL for channel {channel_id}")
            manager = proxy_server.stream_managers[channel_id]
            old_url = manager.url
            
            # Update the stream
            result = manager.update_url(new_url)
            logger.info(f"Stream URL changed from {old_url} to {new_url}, result: {result}")
            return JsonResponse({
                'message': 'Stream URL updated',
                'channel': channel_id,
                'url': new_url,
                'owner': True,
                'worker_id': proxy_server.worker_id
            })
        
        # If we're not the owner, publish an event for the owner to pick up
        else:
            logger.info(f"This worker is not the owner, requesting URL change via Redis PubSub")
            # Publish switch request event
            switch_request = {
                "event": "stream_switch",
                "channel_id": channel_id,
                "url": new_url,
                "user_agent": user_agent,
                "requester": proxy_server.worker_id,
                "timestamp": time.time()
            }
            
            proxy_server.redis_client.publish(
                f"ts_proxy:events:{channel_id}", 
                json.dumps(switch_request)
            )
            
            return JsonResponse({
                'message': 'Stream URL change requested',
                'channel': channel_id,
                'url': new_url,
                'owner': False,
                'worker_id': proxy_server.worker_id
            })
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to change stream: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@require_GET
def channel_status(request, channel_id=None):
    """
    Returns status information about channels with detail level based on request:
    - /status/ returns basic summary of all channels
    - /status/{channel_id} returns detailed info about specific channel
    """
    try:
        # Check if Redis is available
        if not proxy_server.redis_client:
            return JsonResponse({'error': 'Redis connection not available'}, status=500)
            
        # Function for detailed channel info (used when channel_id is provided)
        def get_detailed_channel_info(channel_id):
            # Get channel metadata
            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
            metadata = proxy_server.redis_client.hgetall(metadata_key)
            
            if not metadata:
                return None
                
            # Get detailed info - existing implementation
            # Get channel metadata
            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
            metadata = proxy_server.redis_client.hgetall(metadata_key)
            
            if not metadata:
                return None
                
            # Basic channel info
            buffer_index_value = proxy_server.redis_client.get(f"ts_proxy:channel:{channel_id}:buffer:index")
            
            info = {
                'channel_id': channel_id,
                'state': metadata.get(b'state', b'unknown').decode('utf-8'),
                'url': metadata.get(b'url', b'').decode('utf-8'),
                'created_at': metadata.get(b'created_at', b'0').decode('utf-8'),
                'owner': metadata.get(b'owner', b'unknown').decode('utf-8'),
                
                # Properly decode the buffer index value
                'buffer_index': int(buffer_index_value.decode('utf-8')) if buffer_index_value else 0,
            }
            
            # Add timing information
            if b'state_changed_at' in metadata:
                state_changed_at = float(metadata[b'state_changed_at'].decode('utf-8'))
                info['state_changed_at'] = state_changed_at
                info['state_duration'] = time.time() - state_changed_at
                
            if b'created_at' in metadata:
                created_at = float(metadata[b'created_at'].decode('utf-8'))
                info['created_at'] = created_at
                info['uptime'] = time.time() - created_at
                
            # Get client information
            client_set_key = f"ts_proxy:channel:{channel_id}:clients"
            client_ids = proxy_server.redis_client.smembers(client_set_key)
            clients = []
            
            for client_id in client_ids:
                client_id_str = client_id.decode('utf-8')
                client_key = f"ts_proxy:channel:{channel_id}:clients:{client_id_str}"
                client_data = proxy_server.redis_client.hgetall(client_key)
                
                if client_data:
                    client_info = {
                        'client_id': client_id_str,
                        'user_agent': client_data.get(b'user_agent', b'unknown').decode('utf-8'),
                        'worker_id': client_data.get(b'worker_id', b'unknown').decode('utf-8'),
                    }
                    
                    if b'connected_at' in client_data:
                        connected_at = float(client_data[b'connected_at'].decode('utf-8'))
                        client_info['connected_at'] = connected_at
                        client_info['connection_duration'] = time.time() - connected_at
                        
                    if b'last_active' in client_data:
                        last_active = float(client_data[b'last_active'].decode('utf-8'))
                        client_info['last_active'] = last_active
                        client_info['last_active_ago'] = time.time() - last_active
                        
                    clients.append(client_info)
            
            info['clients'] = clients
            info['client_count'] = len(clients)
            
            # Get buffer health with improved diagnostics
            buffer_stats = {
                'chunks': info['buffer_index'],
                'diagnostics': {}
            }

            # Sample a few recent chunks to check sizes with better error handling
            if info['buffer_index'] > 0:
                try:
                    sample_chunks = min(5, info['buffer_index'])
                    chunk_sizes = []
                    chunk_keys_found = []
                    chunk_keys_missing = []
                    
                    # Check if the keys exist before getting
                    for i in range(info['buffer_index']-sample_chunks+1, info['buffer_index']+1):
                        chunk_key = f"ts_proxy:channel:{channel_id}:buffer:chunk:{i}"
                        
                        # Check if key exists first
                        if proxy_server.redis_client.exists(chunk_key):
                            chunk_data = proxy_server.redis_client.get(chunk_key)
                            if chunk_data:
                                chunk_size = len(chunk_data)
                                chunk_sizes.append(chunk_size)
                                chunk_keys_found.append(i)
                                
                                # Check for TS alignment (packets are 188 bytes)
                                ts_packets = chunk_size // 188
                                ts_aligned = chunk_size % 188 == 0
                                
                                # Add for first chunk only to avoid too much data
                                if len(chunk_keys_found) == 1:
                                    buffer_stats['diagnostics']['first_chunk'] = {
                                        'index': i,
                                        'size': chunk_size,
                                        'ts_packets': ts_packets,
                                        'aligned': ts_aligned,
                                        'first_byte': chunk_data[0] if chunk_size > 0 else None
                                    }
                        else:
                            chunk_keys_missing.append(i)
                            
                    # Add detailed diagnostics        
                    if chunk_sizes:
                        buffer_stats['avg_chunk_size'] = sum(chunk_sizes) / len(chunk_sizes)
                        buffer_stats['recent_chunk_sizes'] = chunk_sizes 
                        buffer_stats['keys_found'] = chunk_keys_found
                        buffer_stats['keys_missing'] = chunk_keys_missing
                        
                        # Calculate data rate
                        total_data = sum(chunk_sizes)
                        buffer_stats['total_sample_bytes'] = total_data
                        
                        # Add TS packet analysis
                        total_ts_packets = total_data // 188
                        buffer_stats['estimated_ts_packets'] = total_ts_packets
                        buffer_stats['is_ts_aligned'] = all(size % 188 == 0 for size in chunk_sizes)
                    else:
                        # If no chunks found, scan for keys to help debug
                        all_buffer_keys = []
                        cursor = 0

                        buffer_key_pattern = f"ts_proxy:channel:{channel_id}:buffer:chunk:*"
                        
                        while True:
                            cursor, keys = proxy_server.redis_client.scan(cursor, match=buffer_key_pattern, count=100)
                            if keys:
                                all_buffer_keys.extend([k.decode('utf-8') for k in keys])
                            if cursor == 0 or len(all_buffer_keys) >= 20:  # Limit to 20 keys
                                break
                                
                        buffer_stats['diagnostics']['all_buffer_keys'] = all_buffer_keys[:20]  # First 20 keys
                        buffer_stats['diagnostics']['total_buffer_keys'] = len(all_buffer_keys)
                        
                except Exception as e:
                    # Capture any errors for diagnostics
                    buffer_stats['error'] = str(e)
                    buffer_stats['diagnostics']['exception'] = str(e)
                    
            # Add TTL information to see if chunks are expiring
            chunk_ttl_key = f"ts_proxy:channel:{channel_id}:buffer:chunk:{info['buffer_index']}" 
            chunk_ttl = proxy_server.redis_client.ttl(chunk_ttl_key)
            buffer_stats['latest_chunk_ttl'] = chunk_ttl

            info['buffer_stats'] = buffer_stats
                
            # Get local worker info if available
            if channel_id in proxy_server.stream_managers:
                manager = proxy_server.stream_managers[channel_id]
                info['local_manager'] = {
                    'healthy': manager.healthy,
                    'connected': manager.connected,
                    'last_data_time': manager.last_data_time,
                    'last_data_age': time.time() - manager.last_data_time
                }
                
            return info
        
        # Function for basic channel info (used for all channels summary)
        def get_basic_channel_info(channel_id):
            # Get channel metadata
            metadata_key = f"ts_proxy:channel:{channel_id}:metadata"
            metadata = proxy_server.redis_client.hgetall(metadata_key)
            
            if not metadata:
                return None
                
            # Basic channel info only - omit diagnostics and details
            buffer_index_value = proxy_server.redis_client.get(f"ts_proxy:channel:{channel_id}:buffer:index")
            
            # Count clients (using efficient count method)
            client_set_key = f"ts_proxy:channel:{channel_id}:clients"
            client_count = proxy_server.redis_client.scard(client_set_key) or 0
            
            # Calculate uptime
            created_at = float(metadata.get(b'init_time', b'0').decode('utf-8'))
            uptime = time.time() - created_at if created_at > 0 else 0
            
            # Simplified info
            info = {
                'channel_id': channel_id,
                'state': metadata.get(b'state', b'unknown').decode('utf-8'),
                'url': metadata.get(b'url', b'').decode('utf-8'),
                'owner': metadata.get(b'owner', b'unknown').decode('utf-8'),
                'buffer_index': int(buffer_index_value.decode('utf-8')) if buffer_index_value else 0,
                'client_count': client_count,
                'uptime': uptime
            }
            
            # Quick health check if available locally
            if channel_id in proxy_server.stream_managers:
                manager = proxy_server.stream_managers[channel_id]
                info['healthy'] = manager.healthy

            # Get concise client information
            clients = []
            client_set_key = f"ts_proxy:channel:{channel_id}:clients"
            client_ids = proxy_server.redis_client.smembers(client_set_key)

            # Process only if we have clients and keep it limited
            if client_ids:
                # Get up to 10 clients for the basic view
                for client_id in list(client_ids)[:10]:
                    client_id_str = client_id.decode('utf-8')
                    client_key = f"ts_proxy:channel:{channel_id}:clients:{client_id_str}"
                    
                    # Efficient way - just retrieve the essentials
                    client_info = {
                        'client_id': client_id_str,
                        'user_agent': proxy_server.redis_client.hget(client_key, 'user_agent')
                    }
                    
                    if client_info['user_agent']:
                        client_info['user_agent'] = client_info['user_agent'].decode('utf-8')
                    else:
                        client_info['user_agent'] = 'unknown'
                        
                    # Just get connected_at for client age
                    connected_at_bytes = proxy_server.redis_client.hget(client_key, 'connected_at')
                    if connected_at_bytes:
                        connected_at = float(connected_at_bytes.decode('utf-8'))
                        client_info['connected_since'] = time.time() - connected_at
                        
                    clients.append(client_info)

            # Add clients to info
            info['clients'] = clients
            
            return info
            
        # Handle single channel or all channels
        if channel_id:
            # Detailed info for specific channel
            channel_info = get_detailed_channel_info(channel_id)
            if channel_info:
                return JsonResponse(channel_info)
            else:
                return JsonResponse({'error': f'Channel {channel_id} not found'}, status=404)
        else:
            # Basic info for all channels
            channel_pattern = "ts_proxy:channel:*:metadata"
            all_channels = []
            
            # Extract channel IDs from keys
            cursor = 0
            while True:
                cursor, keys = proxy_server.redis_client.scan(cursor, match=channel_pattern)
                for key in keys:
                    channel_id_match = re.search(r"ts_proxy:channel:(.*):metadata", key.decode('utf-8'))
                    if channel_id_match:
                        ch_id = channel_id_match.group(1)
                        channel_info = get_basic_channel_info(ch_id)
                        if channel_info:
                            all_channels.append(channel_info)
                
                if cursor == 0:
                    break
            
            return JsonResponse({'channels': all_channels, 'count': len(all_channels)})
            
    except Exception as e:
        logger.error(f"Error in channel_status: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

def get_client_data(buffer, local_index):
    """Get optimal amount of data for client"""
    # Define limits
    MIN_CHUNKS = 3                      # Minimum chunks to read for efficiency
    MAX_CHUNKS = 20                     # Safety limit to prevent memory spikes
    TARGET_SIZE = 1024 * 1024           # Target ~1MB per response (typical media buffer)
    MAX_SIZE = 2 * 1024 * 1024          # Hard cap at 2MB
    
    # Calculate how far behind we are
    chunks_behind = buffer.index - local_index
    
    # Determine optimal chunk count
    if chunks_behind <= MIN_CHUNKS:
        # Not much data, retrieve what's available
        chunk_count = max(1, chunks_behind)
    elif chunks_behind <= MAX_CHUNKS:
        # Reasonable amount behind, catch up completely
        chunk_count = chunks_behind
    else:
        # Way behind, retrieve MAX_CHUNKS to avoid memory pressure
        chunk_count = MAX_CHUNKS
    
    # Retrieve chunks
    chunks = buffer.get_chunks_exact(local_index, chunk_count)
    
    # Check total size
    total_size = sum(len(c) for c in chunks)
    
    # If we're under target and have more chunks available, get more
    if total_size < TARGET_SIZE and chunks_behind > chunk_count:
        # Calculate how many more chunks we can get
        additional = min(MAX_CHUNKS - chunk_count, chunks_behind - chunk_count)
        more_chunks = buffer.get_chunks_exact(local_index + chunk_count, additional)
        
        # Check if adding more would exceed MAX_SIZE
        additional_size = sum(len(c) for c in more_chunks)
        if total_size + additional_size <= MAX_SIZE:
            chunks.extend(more_chunks)
            chunk_count += additional
    
    return chunks, local_index + chunk_count