"""
fMP4 Stream Generator

Yields the fMP4 init segment followed by fMP4 buffer chunks to a single client.
Mirrors StreamGenerator's structure: same resource checks, same cleanup path,
same client registration in the main ClientManager so that the existing
zero-clients → stop_channel shutdown chain works for all client types.
"""

import time
import gevent
from apps.channels.models import Channel, Stream
from core.utils import log_system_event
from ...server import ProxyServer
from ...redis_keys import RedisKeys
from ...constants import ChannelMetadataField
from .buffer import FMP4StreamBuffer
from .manager import FMP4_STATE_ACTIVE, INIT_SEGMENT_TIMEOUT
from ...config_helper import ConfigHelper
from ...utils import get_logger

logger = get_logger()


def create_fmp4_stream_generator(channel_id, client_id, client_ip, client_user_agent,
                                  channel_initializing=False, user=None, fmt='fmp4'):
    gen = FMP4StreamGenerator(channel_id, client_id, client_ip, client_user_agent,
                               channel_initializing, user, fmt=fmt)
    return gen.generate


class FMP4StreamGenerator:

    def __init__(self, channel_id, client_id, client_ip, client_user_agent,
                 channel_initializing=False, user=None, fmt='fmp4'):
        self.channel_id = channel_id
        self.client_id = client_id
        self.client_ip = client_ip
        self.client_user_agent = client_user_agent
        self.channel_initializing = channel_initializing
        self.user = user
        self.fmt = fmt

        try:
            _name = Channel.objects.filter(uuid=channel_id).values_list('name', flat=True).first()
            self.channel_name = _name if _name else str(channel_id)
        except Exception:
            self.channel_name = str(channel_id)

        self.stream_start_time = time.time()
        self.bytes_sent = 0
        self.chunks_sent = 0
        self.local_index = 0
        self.last_yield_time = time.time()
        self.consecutive_empty = 0

        self._last_resource_check_time = 0.0
        self._resource_check_interval = 1.0

        self.proxy_server = None
        self.fmp4_buffer = None

    # ------------------------------------------------------------------
    # Main generator
    # ------------------------------------------------------------------

    def generate(self):
        self.stream_start_time = time.time()

        try:
            logger.info(f"[{self.client_id}] fMP4 stream generator started")

            # Wait for the main TS channel to be ready (reuses existing init wait logic)
            if self.channel_initializing:
                if not self._wait_for_channel_ready():
                    return

            # Wait for fMP4 remux to be ready and init segment available
            if not self._wait_for_fmp4_ready():
                return

            # Set up local references
            if not self._setup_streaming():
                return

            try:
                log_system_event(
                    'client_connect',
                    channel_id=self.channel_id,
                    channel_name=self.channel_name,
                    client_ip=self.client_ip,
                    client_id=self.client_id,
                    user_agent=self.client_user_agent[:100] if self.client_user_agent else None,
                    username=self.user.username if self.user else None,
                )
            except Exception:
                pass

            # Yield init segment first - every new client needs it
            init_segment = self._fetch_init_segment()
            if not init_segment:
                logger.error(f"[{self.client_id}] fMP4 init segment disappeared, aborting")
                return
            yield init_segment
            self.bytes_sent += len(init_segment)

            # Main data loop
            for chunk in self._stream_data_generator():
                yield chunk

        except Exception as e:
            logger.error(f"[{self.client_id}] fMP4 stream error: {e}", exc_info=True)
        finally:
            self._cleanup()

    # ------------------------------------------------------------------
    # Wait helpers
    # ------------------------------------------------------------------

    def _wait_for_channel_ready(self) -> bool:
        """Wait for the main TS channel to reach active/waiting_for_clients state."""
        proxy_server = ProxyServer.get_instance()
        deadline = time.time() + ConfigHelper.client_wait_timeout()

        while time.time() < deadline:
            if proxy_server.redis_client:
                meta = proxy_server.redis_client.hgetall(
                    RedisKeys.channel_metadata(self.channel_id)
                )
                state = meta.get('state', '')
                if state in ('waiting_for_clients', 'active'):
                    return True
                if state in ('error', 'stopped', 'stopping'):
                    logger.error(f"[{self.client_id}] Channel in {state} state during fMP4 init wait")
                    return False
                # Check stop key
                if proxy_server.redis_client.exists(RedisKeys.channel_stopping(self.channel_id)):
                    return False
            gevent.sleep(0.1)

        logger.warning(f"[{self.client_id}] Timed out waiting for TS channel to become ready")
        return False

    def _wait_for_fmp4_ready(self) -> bool:
        """Wait for FMP4RemuxManager to store the init segment in Redis."""
        proxy_server = ProxyServer.get_instance()
        if not proxy_server.redis_client:
            return False

        init_key = RedisKeys.output_init(self.channel_id, self.fmt)
        deadline = time.time() + INIT_SEGMENT_TIMEOUT

        while time.time() < deadline:
            if proxy_server.redis_client.exists(init_key):
                logger.info(f"[{self.client_id}] fMP4 init segment ready")
                return True

            # Bail out if channel is stopping
            if proxy_server.redis_client.exists(RedisKeys.channel_stopping(self.channel_id)):
                logger.info(f"[{self.client_id}] Channel stopping while waiting for fMP4 init")
                return False

            gevent.sleep(0.1)

        logger.error(
            f"[{self.client_id}] Timed out waiting for fMP4 init segment "
            f"({INIT_SEGMENT_TIMEOUT}s)"
        )
        return False

    # ------------------------------------------------------------------
    # Setup and streaming
    # ------------------------------------------------------------------

    def _setup_streaming(self) -> bool:
        proxy_server = ProxyServer.get_instance()
        self.proxy_server = proxy_server

        # Build a local FMP4StreamBuffer reader (shares Redis keyspace, no local state)
        from core.utils import RedisClient
        self.fmp4_buffer = FMP4StreamBuffer(
            self.channel_id, redis_client=RedisClient.get_buffer(), fmt=self.fmt
        )

        # Determine start position
        if self.channel_initializing:
            # First client on a new channel - start from the very beginning
            self.local_index = 0
            logger.info(f"[{self.client_id}] fMP4 channel initializer: starting at index 0")
        else:
            # Joining an existing stream - use time-based positioning (same as TS clients)
            behind_seconds = ConfigHelper.new_client_behind_seconds()
            # Read live head fresh from Redis (self.fmp4_buffer.index is stale from __init__)
            try:
                raw = RedisClient.get_buffer().get(self.fmp4_buffer.buffer_index_key)
                current = int(raw) if raw else 0
            except Exception:
                current = self.fmp4_buffer.index
            if behind_seconds > 0:
                time_index = self.fmp4_buffer.find_chunk_index_by_time(behind_seconds)
                if time_index is not None:
                    self.local_index = max(0, time_index)
                    logger.info(
                        f"[{self.client_id}] fMP4 time-based start: "
                        f"{behind_seconds}s behind -> index {self.local_index} "
                        f"(buffer head at {current})"
                    )
                else:
                    # Not enough buffer - start at oldest available fragment
                    self.local_index = 0
                    logger.info(
                        f"[{self.client_id}] fMP4 buffer shorter than {behind_seconds}s, "
                        f"starting at oldest available fragment "
                        f"(buffer head at {current})"
                    )
            else:
                self.local_index = max(0, current - 1)
                logger.info(
                    f"[{self.client_id}] fMP4 live start (behind_seconds=0), "
                    f"index {self.local_index} (buffer head at {current})"
                )

        logger.info(
            f"[{self.client_id}] fMP4 streaming setup complete, "
            f"starting at index {self.local_index}"
        )
        return True

    def _fetch_init_segment(self) -> bytes:
        from core.utils import RedisClient
        redis_buf = RedisClient.get_buffer()
        if not redis_buf:
            return b''
        data = redis_buf.get(RedisKeys.output_init(self.channel_id, self.fmt))
        return data if data else b''

    def _stream_data_generator(self):
        proxy_server = self.proxy_server or ProxyServer.get_instance()
        stats_write_interval = 1.0
        last_stats_write = 0.0

        while True:
            if not self._check_resources():
                break

            chunks, new_index = self.fmp4_buffer.get_chunks(start_index=self.local_index)

            if chunks:
                self.consecutive_empty = 0
                for chunk in chunks:
                    yield chunk
                    self.bytes_sent += len(chunk)
                    self.chunks_sent += 1
                self.local_index = new_index
                self.last_yield_time = time.time()

                # Update last_active in Redis so ghost detection doesn't fire
                now = time.time()
                if proxy_server.redis_client and now - last_stats_write >= stats_write_interval:
                    last_stats_write = now
                    try:
                        client_key = RedisKeys.client_metadata(self.channel_id, self.client_id)
                        proxy_server.redis_client.hset(client_key, "last_active", str(now))
                    except Exception:
                        pass
            else:
                self.consecutive_empty += 1
                gevent.sleep(0.05)

                if self._is_timeout():
                    break

    # ------------------------------------------------------------------
    # Resource / timeout checks  (mirrors StreamGenerator pattern)
    # ------------------------------------------------------------------

    def _check_resources(self) -> bool:
        proxy_server = self.proxy_server or ProxyServer.get_instance()

        if self.channel_id not in proxy_server.stream_buffers:
            logger.info(f"[{self.client_id}] TS buffer gone, terminating fMP4 stream")
            return False

        if self.channel_id not in proxy_server.client_managers:
            logger.info(f"[{self.client_id}] Client manager gone, terminating fMP4 stream")
            return False

        client_manager = proxy_server.client_managers[self.channel_id]
        if self.client_id not in client_manager.clients:
            logger.info(f"[{self.client_id}] Client no longer in client manager")
            return False

        if not proxy_server.redis_client:
            return True

        now = time.time()
        if now - self._last_resource_check_time < self._resource_check_interval:
            return True
        self._last_resource_check_time = now

        if proxy_server.redis_client.exists(RedisKeys.channel_stopping(self.channel_id)):
            logger.info(f"[{self.client_id}] Channel stop signal, terminating fMP4 stream")
            return False

        meta = proxy_server.redis_client.hgetall(RedisKeys.channel_metadata(self.channel_id))
        if meta and meta.get('state') in ('error', 'stopped', 'stopping'):
            logger.info(
                f"[{self.client_id}] Channel in {meta.get('state')} state, "
                f"terminating fMP4 stream"
            )
            return False

        if proxy_server.redis_client.exists(RedisKeys.client_stop(self.channel_id, self.client_id)):
            logger.info(f"[{self.client_id}] Client stop signal")
            return False

        return True

    def _is_timeout(self) -> bool:
        timeout = ConfigHelper.stream_timeout() + ConfigHelper.failover_grace_period()
        if time.time() - self.last_yield_time > timeout:
            logger.warning(
                f"[{self.client_id}] fMP4 no data for {timeout}s, disconnecting"
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Cleanup - mirrors StreamGenerator._cleanup() exactly so shutdown
    # chain fires identically for fMP4 clients
    # ------------------------------------------------------------------

    def _cleanup(self):
        elapsed = time.time() - self.stream_start_time
        proxy_server = ProxyServer.get_instance()

        # Release stream allocation if last client (mirrors StreamGenerator)
        if proxy_server.redis_client:
            try:
                meta_key = RedisKeys.channel_metadata(self.channel_id)
                stream_id_bytes = proxy_server.redis_client.hget(
                    meta_key, ChannelMetadataField.STREAM_ID
                )
                if stream_id_bytes:
                    if self.channel_id in proxy_server.client_managers:
                        client_count = proxy_server.client_managers[
                            self.channel_id
                        ].get_total_client_count()
                        if client_count <= 1 and proxy_server.am_i_owner(self.channel_id):
                            try:
                                try:
                                    obj = Channel.objects.get(uuid=self.channel_id)
                                except (Channel.DoesNotExist, Exception):
                                    obj = Stream.objects.get(stream_hash=self.channel_id)
                                obj.release_stream()
                            except Exception as e:
                                logger.error(
                                    f"[{self.client_id}] Error releasing stream: {e}"
                                )
            except Exception as e:
                logger.error(f"[{self.client_id}] Error in stream release check: {e}")

        # Remove from MAIN ClientManager - this is what triggers handle_client_disconnect
        # and the zero-clients → stop_channel path, same as TS clients.
        local_clients = 0
        total_clients = 0
        if self.channel_id in proxy_server.client_managers:
            client_manager = proxy_server.client_managers[self.channel_id]
            local_clients = client_manager.remove_client(self.client_id)
            total_clients = client_manager.get_total_client_count()

        logger.info(
            f"[{self.client_id}] fMP4 client disconnected after {elapsed:.2f}s "
            f"({self.bytes_sent / 1024:.1f} KB sent, "
            f"local: {local_clients}, total: {total_clients})"
        )
