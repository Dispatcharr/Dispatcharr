import logging
import time
import re
from . import proxy_server
from .redis_keys import RedisKeys
from .constants import TS_PACKET_SIZE
from redis.exceptions import ConnectionError, TimeoutError
from .utils import get_logger

logger = get_logger()

class ChannelStatus:

    def get_detailed_channel_info(channel_id):
        # Get channel metadata
        metadata_key = RedisKeys.channel_metadata(channel_id)
        metadata = proxy_server.redis_client.hgetall(metadata_key)

        if not metadata:
            return None

        # Basic channel info
        buffer_index_key = RedisKeys.buffer_index(channel_id)
        buffer_index_value = proxy_server.redis_client.get(buffer_index_key)

        info = {
            'channel_id': channel_id,
            'state': metadata.get(b'state', b'unknown').decode('utf-8'),
            'url': metadata.get(b'url', b'').decode('utf-8'),
            'profile': metadata.get(b'profile', b'unknown').decode('utf-8'),
            'started_at': metadata.get(b'init_time', b'0').decode('utf-8'),
            'owner': metadata.get(b'owner', b'unknown').decode('utf-8'),
            'buffer_index': int(buffer_index_value.decode('utf-8')) if buffer_index_value else 0,
        }

        # Add timing information
        if b'state_changed_at' in metadata:
            state_changed_at = float(metadata[b'state_changed_at'].decode('utf-8'))
            info['state_changed_at'] = state_changed_at
            info['state_duration'] = time.time() - state_changed_at

        if b'init_time' in metadata:
            created_at = float(metadata[b'init_time'].decode('utf-8'))
            info['started_at'] = created_at
            info['uptime'] = time.time() - created_at

        # Get client information
        client_set_key = RedisKeys.clients(channel_id)
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
                    chunk_key = RedisKeys.buffer_chunk(channel_id, i)

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
                    total_ts_packets = total_data // TS_PACKET_SIZE
                    buffer_stats['estimated_ts_packets'] = total_ts_packets
                    buffer_stats['is_ts_aligned'] = all(size % TS_PACKET_SIZE == 0 for size in chunk_sizes)
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
        chunk_ttl_key = RedisKeys.buffer_chunk(channel_id, info['buffer_index'])
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

    @staticmethod
    def _execute_redis_command(command_func):
        """Execute Redis command with error handling"""
        if not proxy_server.redis_client:
            return None

        try:
            return command_func()
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis connection error in ChannelStatus: {e}")
            return None
        except Exception as e:
            logger.error(f"Redis command error in ChannelStatus: {e}")
            return None

    @staticmethod
    def get_basic_channel_info(channel_id):
        """Get basic channel information with Redis error handling"""
        try:
            # Use _execute_redis_command for Redis operations
            metadata_key = RedisKeys.channel_metadata(channel_id)
            metadata = ChannelStatus._execute_redis_command(
                lambda: proxy_server.redis_client.hgetall(metadata_key)
            )

            if not metadata:
                return None

            # Basic channel info only - omit diagnostics and details
            buffer_index_key = RedisKeys.buffer_index(channel_id)
            buffer_index_value = proxy_server.redis_client.get(buffer_index_key)

            # Count clients (using efficient count method)
            client_set_key = RedisKeys.clients(channel_id)
            client_count = proxy_server.redis_client.scard(client_set_key) or 0

            # Calculate uptime
            created_at = float(metadata.get(b'init_time', b'0').decode('utf-8'))
            uptime = time.time() - created_at if created_at > 0 else 0

            # Simplified info
            info = {
                'channel_id': channel_id,
                'state': metadata.get(b'state', b'unknown').decode('utf-8'),
                'url': metadata.get(b'url', b'').decode('utf-8'),
                'profile': metadata.get(b'profile', b'unknown').decode('utf-8'),
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
                        'user_agent': proxy_server.redis_client.hget(client_key, 'user_agent'),
                        'ip_address': proxy_server.redis_client.hget(client_key, 'ip_address').decode('utf-8'),
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
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
            return None
