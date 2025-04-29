import logging
import time
import re
from .server import ProxyServer
from .redis_keys import RedisKeys
from .constants import TS_PACKET_SIZE, ChannelMetadataField
from redis.exceptions import ConnectionError, TimeoutError
from .utils import get_logger
from django.db import DatabaseError  # Add import for error handling

logger = get_logger()

class ChannelStatus:

    @staticmethod
    def _calculate_bitrate(total_bytes, duration):
        """Calculate bitrate in Kbps based on total bytes and duration in seconds"""
        if duration <= 0:
            return 0

        # Convert bytes to bits (x8) and divide by duration to get bits per second
        # Then divide by 1000 to get Kbps
        return (total_bytes * 8) / duration / 1000

    def get_detailed_channel_info(channel_id):
        proxy_server = ProxyServer.get_instance()

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
            'state': metadata.get(ChannelMetadataField.STATE.encode('utf-8'), b'unknown').decode('utf-8'),
            'url': metadata.get(ChannelMetadataField.URL.encode('utf-8'), b'').decode('utf-8'),
            'stream_profile': metadata.get(ChannelMetadataField.STREAM_PROFILE.encode('utf-8'), b'').decode('utf-8'),
            'started_at': metadata.get(ChannelMetadataField.INIT_TIME.encode('utf-8'), b'0').decode('utf-8'),
            'owner': metadata.get(ChannelMetadataField.OWNER.encode('utf-8'), b'unknown').decode('utf-8'),
            'buffer_index': int(buffer_index_value.decode('utf-8')) if buffer_index_value else 0,
        }

        # Add stream ID and name information
        stream_id_bytes = metadata.get(ChannelMetadataField.STREAM_ID.encode('utf-8'))
        if stream_id_bytes:
            try:
                stream_id = int(stream_id_bytes.decode('utf-8'))
                info['stream_id'] = stream_id

                # Look up stream name from database
                try:
                    from apps.channels.models import Stream
                    stream = Stream.objects.filter(id=stream_id).first()
                    if stream:
                        info['stream_name'] = stream.name
                except (ImportError, DatabaseError) as e:
                    logger.warning(f"Failed to get stream name for ID {stream_id}: {e}")
            except ValueError:
                logger.warning(f"Invalid stream_id format in Redis: {stream_id_bytes}")

        # Add M3U profile information
        m3u_profile_id_bytes = metadata.get(ChannelMetadataField.M3U_PROFILE.encode('utf-8'))
        if m3u_profile_id_bytes:
            try:
                m3u_profile_id = int(m3u_profile_id_bytes.decode('utf-8'))
                info['m3u_profile_id'] = m3u_profile_id

                # Look up M3U profile name from database
                try:
                    from apps.m3u.models import M3UAccountProfile
                    m3u_profile = M3UAccountProfile.objects.filter(id=m3u_profile_id).first()
                    if m3u_profile:
                        info['m3u_profile_name'] = m3u_profile.name
                except (ImportError, DatabaseError) as e:
                    logger.warning(f"Failed to get M3U profile name for ID {m3u_profile_id}: {e}")
            except ValueError:
                logger.warning(f"Invalid m3u_profile_id format in Redis: {m3u_profile_id_bytes}")

        # Add timing information
        state_changed_field = ChannelMetadataField.STATE_CHANGED_AT.encode('utf-8')
        if state_changed_field in metadata:
            state_changed_at = float(metadata[state_changed_field].decode('utf-8'))
            info['state_changed_at'] = state_changed_at
            info['state_duration'] = time.time() - state_changed_at

        init_time_field = ChannelMetadataField.INIT_TIME.encode('utf-8')
        if init_time_field in metadata:
            created_at = float(metadata[init_time_field].decode('utf-8'))
            info['started_at'] = created_at
            info['uptime'] = time.time() - created_at

        # Add data throughput information
        total_bytes_field = ChannelMetadataField.TOTAL_BYTES.encode('utf-8')
        if total_bytes_field in metadata:
            total_bytes = int(metadata[total_bytes_field].decode('utf-8'))
            info['total_bytes'] = total_bytes

            # Format total bytes in human-readable form
            if total_bytes < 1024:
                info['total_data'] = f"{total_bytes} B"
            elif total_bytes < 1024 * 1024:
                info['total_data'] = f"{total_bytes / 1024:.2f} KB"
            elif total_bytes < 1024 * 1024 * 1024:
                info['total_data'] = f"{total_bytes / (1024 * 1024):.2f} MB"
            else:
                info['total_data'] = f"{total_bytes / (1024 * 1024 * 1024):.2f} GB"

            # Calculate average bitrate if we have uptime
            if 'uptime' in info and info['uptime'] > 0:
                avg_bitrate = ChannelStatus._calculate_bitrate(total_bytes, info['uptime'])
                info['avg_bitrate_kbps'] = avg_bitrate

                # Format in Mbps if over 1000 Kbps
                if avg_bitrate > 1000:
                    info['avg_bitrate'] = f"{avg_bitrate / 1000:.2f} Mbps"
                else:
                    info['avg_bitrate'] = f"{avg_bitrate:.2f} Kbps"

        # Get client information
        client_set_key = RedisKeys.clients(channel_id)
        client_ids = proxy_server.redis_client.smembers(client_set_key)
        clients = []

        for client_id in client_ids:
            client_id_str = client_id.decode('utf-8')
            client_key = RedisKeys.client_metadata(channel_id, client_id_str)
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

                # Add transfer rate statistics
                if b'bytes_sent' in client_data:
                    client_info['bytes_sent'] = int(client_data[b'bytes_sent'].decode('utf-8'))

                # Add average transfer rate
                if b'avg_rate_KBps' in client_data:
                    client_info['avg_rate_KBps'] = float(client_data[b'avg_rate_KBps'].decode('utf-8'))
                elif b'transfer_rate_KBps' in client_data:  # For backward compatibility
                    client_info['avg_rate_KBps'] = float(client_data[b'transfer_rate_KBps'].decode('utf-8'))

                # Add current transfer rate
                if b'current_rate_KBps' in client_data:
                    client_info['current_rate_KBps'] = float(client_data[b'current_rate_KBps'].decode('utf-8'))

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
        proxy_server = ProxyServer.get_instance()

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
        proxy_server = ProxyServer.get_instance()

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
            created_at = float(metadata.get(ChannelMetadataField.INIT_TIME.encode('utf-8'), b'0').decode('utf-8'))
            uptime = time.time() - created_at if created_at > 0 else 0

            # Simplified info
            info = {
                'channel_id': channel_id,
                'state': metadata.get(ChannelMetadataField.STATE.encode('utf-8'), b'unknown').decode('utf-8'),
                'url': metadata.get(ChannelMetadataField.URL.encode('utf-8'), b'').decode('utf-8'),
                'stream_profile': metadata.get(ChannelMetadataField.STREAM_PROFILE.encode('utf-8'), b'').decode('utf-8'),
                'owner': metadata.get(ChannelMetadataField.OWNER.encode('utf-8'), b'unknown').decode('utf-8'),
                'buffer_index': int(buffer_index_value.decode('utf-8')) if buffer_index_value else 0,
                'client_count': client_count,
                'uptime': uptime
            }

            # Add stream ID and name information
            stream_id_bytes = metadata.get(ChannelMetadataField.STREAM_ID.encode('utf-8'))
            if stream_id_bytes:
                try:
                    stream_id = int(stream_id_bytes.decode('utf-8'))
                    info['stream_id'] = stream_id

                    # Look up stream name from database
                    try:
                        from apps.channels.models import Stream
                        stream = Stream.objects.filter(id=stream_id).first()
                        if stream:
                            info['stream_name'] = stream.name
                    except (ImportError, DatabaseError) as e:
                        logger.warning(f"Failed to get stream name for ID {stream_id}: {e}")
                except ValueError:
                    logger.warning(f"Invalid stream_id format in Redis: {stream_id_bytes}")

            # Add data throughput information to basic info
            total_bytes_bytes = proxy_server.redis_client.hget(metadata_key, ChannelMetadataField.TOTAL_BYTES.encode('utf-8'))
            if total_bytes_bytes:
                total_bytes = int(total_bytes_bytes.decode('utf-8'))
                info['total_bytes'] = total_bytes

                # Calculate and add bitrate
                if uptime > 0:
                    avg_bitrate = ChannelStatus._calculate_bitrate(total_bytes, uptime)
                    info['avg_bitrate_kbps'] = avg_bitrate

                    # Format for display
                    if avg_bitrate > 1000:
                        info['avg_bitrate'] = f"{avg_bitrate / 1000:.2f} Mbps"
                    else:
                        info['avg_bitrate'] = f"{avg_bitrate:.2f} Kbps"

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
                    client_key = RedisKeys.client_metadata(channel_id, client_id_str)

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

            # Add M3U profile information
            m3u_profile_id_bytes = metadata.get(ChannelMetadataField.M3U_PROFILE.encode('utf-8'))
            if m3u_profile_id_bytes:
                try:
                    m3u_profile_id = int(m3u_profile_id_bytes.decode('utf-8'))
                    info['m3u_profile_id'] = m3u_profile_id

                    # Look up M3U profile name from database
                    try:
                        from apps.m3u.models import M3UAccountProfile
                        m3u_profile = M3UAccountProfile.objects.filter(id=m3u_profile_id).first()
                        if m3u_profile:
                            info['m3u_profile_name'] = m3u_profile.name
                    except (ImportError, DatabaseError) as e:
                        logger.warning(f"Failed to get M3U profile name for ID {m3u_profile_id}: {e}")
                except ValueError:
                    logger.warning(f"Invalid m3u_profile_id format in Redis: {m3u_profile_id_bytes}")

            return info
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
            return None
