"""Stream connection management for TS proxy"""

import threading
import logging
import time
import socket
import requests
import subprocess
import gevent
import re
from typing import Optional, List
from django.db import connection
from django.shortcuts import get_object_or_404
from urllib3.exceptions import ReadTimeoutError
from apps.proxy.config import TSConfig as Config
from apps.channels.models import Channel, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from core.models import UserAgent, CoreSettings
from core.utils import log_system_event
from .stream_buffer import StreamBuffer
from .utils import detect_stream_type, get_logger
from .redis_keys import RedisKeys
from .constants import ChannelState, EventType, StreamType, ChannelMetadataField, TS_PACKET_SIZE
from .config_helper import ConfigHelper
from .url_utils import get_alternate_streams, get_stream_info_for_switch, get_stream_object

logger = get_logger()

class StreamManager:
    """Manages a connection to a TS stream without using raw sockets"""

    def __init__(self, channel_id, url, buffer, user_agent=None, transcode=False, stream_id=None, worker_id=None):
        # Basic properties
        self.channel_id = channel_id
        self.url = url
        self.buffer = buffer
        self.running = True
        self.connected = False
        self.retry_count = 0
        self.max_retries = ConfigHelper.max_retries()
        self.current_response = None
        self.current_session = None
        self.url_switching = False
        self.url_switch_start_time = 0
        self.url_switch_timeout = ConfigHelper.url_switch_timeout()
        self.buffering = False
        self.buffering_timeout = ConfigHelper.buffering_timeout()
        self.buffering_speed = ConfigHelper.buffering_speed()
        self.buffering_start_time = None
        # Store worker_id for ownership checks
        self.worker_id = worker_id

        # Sockets used for transcode jobs
        self.socket = None
        self.transcode = transcode
        self.transcode_process = None

        # User agent for connection
        self.user_agent = user_agent or Config.DEFAULT_USER_AGENT

        # Stream health monitoring
        self.last_data_time = time.time()
        self.healthy = True
        self.health_check_interval = ConfigHelper.get('HEALTH_CHECK_INTERVAL', 5)
        self.chunk_size = ConfigHelper.chunk_size()

        # Add to your __init__ method
        self._buffer_check_timers = []
        self.stopping = False

        # Add tracking for tried streams and current stream
        self.current_stream_id = stream_id
        self.tried_stream_ids = set()

        # IMPROVED LOGGING: Better handle and track stream ID
        if stream_id:
            self.tried_stream_ids.add(stream_id)
            logger.info(f"Initialized stream manager for channel {buffer.channel_id} with stream ID {stream_id}")
        else:
            # Try to get stream ID from Redis metadata if available
            if hasattr(buffer, 'redis_client') and buffer.redis_client:
                try:
                    metadata_key = RedisKeys.channel_metadata(channel_id)

                    # Log all metadata for debugging purposes
                    metadata = buffer.redis_client.hgetall(metadata_key)
                    if metadata:
                        logger.debug(f"Redis metadata for channel {channel_id}: {metadata}")

                    # Try to get stream_id specifically
                    stream_id_bytes = buffer.redis_client.hget(metadata_key, "stream_id")
                    if stream_id_bytes:
                        self.current_stream_id = int(stream_id_bytes.decode('utf-8'))
                        self.tried_stream_ids.add(self.current_stream_id)
                        logger.info(f"Loaded stream ID {self.current_stream_id} from Redis for channel {buffer.channel_id}")
                    else:
                        logger.warning(f"No stream_id found in Redis for channel {channel_id}. "
                                     f"Stream switching will rely on URL comparison to avoid selecting the same stream.")
                except Exception as e:
                    logger.warning(f"Error loading stream ID from Redis: {e}")
            else:
                logger.warning(f"Unable to get stream ID for channel {channel_id}. "
                             f"Stream switching will rely on URL comparison to avoid selecting the same stream.")

        logger.info(f"Initialized stream manager for channel {buffer.channel_id}")

        # Add this flag for tracking transcoding process status
        self.transcode_process_active = False

        # Add tracking for data throughput
        self.bytes_processed = 0
        self.last_bytes_update = time.time()
        self.bytes_update_interval = 5  # Update Redis every 5 seconds

        # Add stderr reader thread property
        self.stderr_reader_thread = None
        self.ffmpeg_input_phase = True  # Track if we're still reading input info

        # Add HTTP reader thread property
        self.http_reader = None

    def _create_session(self):
        """Create and configure requests session with optimal settings"""
        session = requests.Session()

        # Configure session headers
        session.headers.update({
            'User-Agent': self.user_agent,
            'Connection': 'keep-alive'
        })

        # Set up connection pooling for better performance
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,     # Single connection for this stream
            pool_maxsize=1,         # Max size of connection pool
            max_retries=3,          # Auto-retry for failed requests
            pool_block=False        # Don't block when pool is full
        )

        # Apply adapter to both HTTP and HTTPS
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        return session

    def _wait_for_existing_processes_to_close(self, timeout=5.0):
        """Wait for existing processes/connections to fully close before establishing new ones"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check if transcode process is still running
            if self.transcode_process and self.transcode_process.poll() is None:
                logger.debug(f"Waiting for existing transcode process to terminate for channel {self.channel_id}")
                gevent.sleep(0.1)
                continue

            # Check if HTTP connections are still active
            if self.current_response or self.current_session:
                logger.debug(f"Waiting for existing HTTP connections to close for channel {self.channel_id}")
                gevent.sleep(0.1)
                continue

            # Check if socket is still active
            if self.socket:
                logger.debug(f"Waiting for existing socket to close for channel {self.channel_id}")
                gevent.sleep(0.1)
                continue

            # All processes/connections are closed
            logger.debug(f"All existing processes closed for channel {self.channel_id}")
            return True

        # Timeout reached
        logger.warning(f"Timeout waiting for existing processes to close for channel {self.channel_id} after {timeout}s")
        return False

    def run(self):
        """Main execution loop using HTTP streaming with improved connection handling and stream switching"""
        # Add a stop flag to the class properties
        self.stop_requested = False
        # Add tracking for stream switching attempts
        stream_switch_attempts = 0
        # Get max stream switches from config using the helper method
        max_stream_switches = ConfigHelper.max_stream_switches()  # Prevent infinite switching loops

        try:


            # Start health monitor thread
            health_thread = threading.Thread(target=self._monitor_health, daemon=True)
            health_thread.start()

            logger.info(f"Starting stream for URL: {self.url} for channel {self.channel_id}")

            # Main stream switching loop - we'll try different streams if needed
            while self.running and stream_switch_attempts <= max_stream_switches:
                # Check for stuck switching state
                if self.url_switching and time.time() - self.url_switch_start_time > self.url_switch_timeout:
                    logger.warning(f"URL switching state appears stuck for channel {self.channel_id} "
                                 f"({time.time() - self.url_switch_start_time:.1f}s > {self.url_switch_timeout}s timeout). "
                                 f"Resetting switching state.")
                    self._reset_url_switching_state()

                # NEW: Check for health monitor recovery requests
                if hasattr(self, 'needs_reconnect') and self.needs_reconnect and not self.url_switching:
                    logger.info(f"Health monitor requested reconnect for channel {self.channel_id}")
                    self.needs_reconnect = False

                    # Attempt reconnect without changing streams
                    if self._attempt_reconnect():
                        logger.info(f"Health-requested reconnect successful for channel {self.channel_id}")
                        continue  # Go back to main loop
                    else:
                        logger.warning(f"Health-requested reconnect failed, will try stream switch for channel {self.channel_id}")
                        self.needs_stream_switch = True

                if hasattr(self, 'needs_stream_switch') and self.needs_stream_switch and not self.url_switching:
                    logger.info(f"Health monitor requested stream switch for channel {self.channel_id}")
                    self.needs_stream_switch = False

                    if self._try_next_stream():
                        logger.info(f"Health-requested stream switch successful for channel {self.channel_id}")
                        stream_switch_attempts += 1
                        self.retry_count = 0  # Reset retries for new stream
                        continue  # Go back to main loop with new stream
                    else:
                        logger.error(f"Health-requested stream switch failed for channel {self.channel_id}")
                        # Continue with normal flow

                # Check stream type before connecting
                self.stream_type = detect_stream_type(self.url)
                if self.transcode == False and self.stream_type in (StreamType.HLS, StreamType.RTSP, StreamType.UDP):
                    stream_type_name = "HLS" if self.stream_type == StreamType.HLS else ("RTSP/RTP" if self.stream_type == StreamType.RTSP else "UDP")
                    logger.info(f"Detected {stream_type_name} stream: {self.url} for channel {self.channel_id}")
                    logger.info(f"{stream_type_name} streams require FFmpeg for channel {self.channel_id}")
                    # Enable transcoding for HLS, RTSP/RTP, and UDP streams
                    self.transcode = True
                    # We'll override the stream profile selection with ffmpeg in the transcoding section
                    self.force_ffmpeg = True
                # Reset connection retry count for this specific URL
                self.retry_count = 0
                url_failed = False
                if self.url_switching:
                    logger.debug(f"Skipping connection attempt during URL switch for channel {self.channel_id}")
                    gevent.sleep(0.1)  # REPLACE time.sleep(0.1)
                    continue
                # Connection retry loop for current URL
                while self.running and self.retry_count < self.max_retries and not url_failed and not self.needs_stream_switch:

                    logger.info(f"Connection attempt {self.retry_count + 1}/{self.max_retries} for URL: {self.url} for channel {self.channel_id}")

                    # Handle connection based on whether we transcode or not
                    connection_result = False
                    try:
                        if self.transcode:
                            connection_result = self._establish_transcode_connection()
                        else:
                            connection_result = self._establish_http_connection()

                        if connection_result:
                            # Store connection start time to measure success duration
                            connection_start_time = time.time()

                            # Log reconnection event if this is a retry (not first attempt)
                            if self.retry_count > 0:
                                try:
                                    channel_obj = Channel.objects.get(uuid=self.channel_id)
                                    log_system_event(
                                        'channel_reconnect',
                                        channel_id=self.channel_id,
                                        channel_name=channel_obj.name,
                                        attempt=self.retry_count + 1,
                                        max_attempts=self.max_retries
                                    )
                                except Exception as e:
                                    logger.error(f"Could not log reconnection event: {e}")

                            # Successfully connected - read stream data until disconnect/error
                            self._process_stream_data()
                            # If we get here, the connection was closed/failed

                            # Reset stream switch attempts if the connection lasted longer than threshold
                            # This indicates we had a stable connection for a while before failing
                            connection_duration = time.time() - connection_start_time
                            stable_connection_threshold = 30  # 30 seconds threshold

                            if self.needs_stream_switch:
                                logger.info(f"Stream needs to switch after {connection_duration:.1f} seconds for channel: {self.channel_id}")
                                break  # Exit to switch streams
                            if connection_duration > stable_connection_threshold:
                                logger.info(f"Stream was stable for {connection_duration:.1f} seconds, resetting switch attempts counter for channel: {self.channel_id}")
                                stream_switch_attempts = 0

                        # Connection failed or ended - decide what to do next
                        if self.stop_requested or not self.running:
                            # Normal shutdown requested
                            return

                        # Connection failed, increment retry count
                        self.retry_count += 1
                        self.connected = False

                        # If we've reached max retries, mark this URL as failed
                        if self.retry_count >= self.max_retries:
                            url_failed = True
                            logger.warning(f"Maximum retry attempts ({self.max_retries}) reached for URL: {self.url} for channel: {self.channel_id}")

                            # Log connection error event
                            try:
                                channel_obj = Channel.objects.get(uuid=self.channel_id)
                                log_system_event(
                                    'channel_error',
                                    channel_id=self.channel_id,
                                    channel_name=channel_obj.name,
                                    error_type='connection_failed',
                                    url=self.url[:100] if self.url else None,
                                    attempts=self.max_retries
                                )
                            except Exception as e:
                                logger.error(f"Could not log connection error event: {e}")
                        else:
                            # Wait with exponential backoff before retrying
                            timeout = min(.25 * self.retry_count, 3)  # Cap at 3 seconds
                            logger.info(f"Reconnecting in {timeout} seconds... (attempt {self.retry_count}/{self.max_retries}) for channel: {self.channel_id}")
                            gevent.sleep(timeout)  # REPLACE time.sleep(timeout)

                    except Exception as e:
                        logger.error(f"Connection error on channel: {self.channel_id}: {e}", exc_info=True)
                        self.retry_count += 1
                        self.connected = False

                        if self.retry_count >= self.max_retries:
                            url_failed = True

                            # Log connection error event with exception details
                            try:
                                channel_obj = Channel.objects.get(uuid=self.channel_id)
                                log_system_event(
                                    'channel_error',
                                    channel_id=self.channel_id,
                                    channel_name=channel_obj.name,
                                    error_type='connection_exception',
                                    error_message=str(e)[:200],
                                    url=self.url[:100] if self.url else None,
                                    attempts=self.max_retries
                                )
                            except Exception as log_error:
                                logger.error(f"Could not log connection error event: {log_error}")
                        else:
                            # Wait with exponential backoff before retrying
                            timeout = min(.25 * self.retry_count, 3)  # Cap at 3 seconds
                            logger.info(f"Reconnecting in {timeout} seconds after error... (attempt {self.retry_count}/{self.max_retries}) for channel: {self.channel_id}")
                            gevent.sleep(timeout)  # REPLACE time.sleep(timeout)

                # If URL failed and we're still running, try switching to another stream
                if url_failed and self.running:
                    logger.info(f"URL {self.url} failed after {self.retry_count} attempts, trying next stream for channel: {self.channel_id}")

                    # Try to switch to next stream
                    switch_result = self._try_next_stream()
                    if switch_result:
                        # Successfully switched to a new stream, continue with the new URL
                        stream_switch_attempts += 1
                        logger.info(f"Successfully switched to new URL: {self.url} (switch attempt {stream_switch_attempts}/{max_stream_switches}) for channel: {self.channel_id}")
                        # Reset retry count for the new stream - important for the loop to work correctly
                        self.retry_count = 0
                        # Continue outer loop with new URL - DON'T add a break statement here
                    else:
                        # No more streams to try
                        logger.error(f"Failed to find alternative streams after {stream_switch_attempts} attempts for channel: {self.channel_id}")
                        break
                elif not self.running:
                    # Normal shutdown was requested
                    break

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
        finally:
            # Enhanced cleanup in the finally block
            self.connected = False

            # Explicitly cancel all timers
            for timer in list(self._buffer_check_timers):
                try:
                    if timer and timer.is_alive():
                        timer.cancel()
                except Exception:
                    pass

            self._buffer_check_timers.clear()

            # Make sure transcode process is terminated
            if self.transcode_process_active:
                logger.info(f"Ensuring transcode process is terminated in finally block for channel: {self.channel_id}")
                self._close_socket()

            # Close all connections
            self._close_all_connections()

            # Update channel state in Redis to prevent clients from waiting indefinitely
            if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                try:
                    metadata_key = RedisKeys.channel_metadata(self.channel_id)

                    # Check if we're the owner before updating state
                    owner_key = RedisKeys.channel_owner(self.channel_id)
                    current_owner = self.buffer.redis_client.get(owner_key)

                    # Use the worker_id that was passed in during initialization
                    if current_owner and self.worker_id and current_owner.decode('utf-8') == self.worker_id:
                        # Determine the appropriate error message based on retry failures
                        if self.tried_stream_ids and len(self.tried_stream_ids) > 0:
                            error_message = f"All {len(self.tried_stream_ids)} stream options failed"
                        else:
                            error_message = f"Connection failed after {self.max_retries} attempts"

                        # Update metadata to indicate error state
                        update_data = {
                            ChannelMetadataField.STATE: ChannelState.ERROR,
                            ChannelMetadataField.STATE_CHANGED_AT: str(time.time()),
                            ChannelMetadataField.ERROR_MESSAGE: error_message,
                            ChannelMetadataField.ERROR_TIME: str(time.time())
                        }
                        self.buffer.redis_client.hset(metadata_key, mapping=update_data)
                        logger.info(f"Updated channel {self.channel_id} state to ERROR in Redis after stream failure")

                        # Also set stopping key to ensure clients disconnect
                        stop_key = RedisKeys.channel_stopping(self.channel_id)
                        self.buffer.redis_client.setex(stop_key, 60, "true")
                except Exception as e:
                    logger.error(f"Failed to update channel state in Redis: {e} for channel {self.channel_id}", exc_info=True)

            # Close database connection for this thread
            try:
                connection.close()
            except Exception:
                pass

            logger.info(f"Stream manager stopped for channel {self.channel_id}")

    def _establish_transcode_connection(self):
        """Establish a connection using transcoding"""
        try:
            logger.debug(f"Building transcode command for channel {self.channel_id}")

            # Check if we already have a running transcode process
            if self.transcode_process and self.transcode_process.poll() is None:
                logger.info(f"Existing transcode process found for channel {self.channel_id}, closing before establishing new connection")
                self._close_socket()

                # Wait for the process to fully terminate
                if not self._wait_for_existing_processes_to_close():
                    logger.error(f"Failed to close existing transcode process for channel {self.channel_id}")
                    return False

            # Also check for any lingering HTTP connections
            if self.current_response or self.current_session:
                logger.debug(f"Closing existing HTTP connections before establishing transcode connection for channel {self.channel_id}")
                self._close_connection()

            channel = get_stream_object(self.channel_id)

            # Use FFmpeg specifically for HLS streams
            if hasattr(self, 'force_ffmpeg') and self.force_ffmpeg:
                from core.models import StreamProfile
                try:
                    stream_profile = StreamProfile.objects.get(name='ffmpeg', locked=True)
                    logger.info("Using FFmpeg stream profile for unsupported proxy content (HLS/RTSP/UDP)")
                except StreamProfile.DoesNotExist:
                    # Fall back to channel's profile if FFmpeg not found
                    stream_profile = channel.get_stream_profile()
                    logger.warning(f"FFmpeg profile not found, using channel default profile for channel: {self.channel_id}")
            else:
                stream_profile = channel.get_stream_profile()

            # Build and start transcode command
            self.transcode_cmd = stream_profile.build_command(self.url, self.user_agent)

            # For UDP streams, remove any user_agent parameters from the command
            if hasattr(self, 'stream_type') and self.stream_type == StreamType.UDP:
                # Filter out any arguments that contain the user_agent value or related headers
                self.transcode_cmd = [arg for arg in self.transcode_cmd if self.user_agent not in arg and 'user-agent' not in arg.lower() and 'user_agent' not in arg.lower()]
                logger.debug(f"Removed user_agent parameters from UDP stream command for channel: {self.channel_id}")

            logger.debug(f"Starting transcode process: {self.transcode_cmd} for channel: {self.channel_id}")

            # Modified to capture stderr instead of discarding it
            self.transcode_process = subprocess.Popen(
                self.transcode_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Capture stderr instead of discarding it
                bufsize=188 * 64            # Buffer optimized for TS packets
            )

            # Start a thread to read stderr
            self._start_stderr_reader()

            # Set flag that transcoding process is active
            self.transcode_process_active = True

            self.socket = self.transcode_process.stdout  # Read from std output
            self.connected = True

            # Set connection start time for stability tracking
            self.connection_start_time = time.time()

            # Set channel state to waiting for clients
            self._set_waiting_for_clients()

            return True
        except Exception as e:
            logger.error(f"Error establishing transcode connection for channel: {self.channel_id}: {e}", exc_info=True)
            self._close_socket()
            return False

    def _start_stderr_reader(self):
        """Start a thread to read stderr from the transcode process"""
        if self.transcode_process and self.transcode_process.stderr:
            self.stderr_reader_thread = threading.Thread(
                target=self._read_stderr,
                daemon=True  # Use daemon thread so it doesn't block program exit
            )
            self.stderr_reader_thread.start()
            logger.debug(f"Started stderr reader thread for channel {self.channel_id}")

    def _read_stderr(self):
        """Read and log ffmpeg stderr output with real-time stats parsing"""
        try:
            buffer = b""
            last_stats_line = b""

            # Read byte by byte for immediate detection
            while self.transcode_process and self.transcode_process.stderr:
                try:
                    # Read one byte at a time for immediate processing
                    byte = self.transcode_process.stderr.read(1)
                    if not byte:
                        break

                    buffer += byte

                    # Check for frame= at the start of buffer (new stats line)
                    if buffer == b"frame=":
                        # We detected the start of a stats line, read until we get a complete line
                        # or hit a carriage return (which overwrites the previous stats)
                        while True:
                            next_byte = self.transcode_process.stderr.read(1)
                            if not next_byte:
                                break

                            buffer += next_byte

                            # Break on carriage return (stats overwrite) or newline
                            if next_byte in (b'\r', b'\n'):
                                break

                            # Also break if we have enough data for a typical stats line
                            if len(buffer) > 200:  # Typical stats line length
                                break

                        # Process the stats line immediately
                        if buffer.strip():
                            try:
                                stats_text = buffer.decode('utf-8', errors='ignore').strip()
                                if stats_text and "frame=" in stats_text:
                                    self._parse_ffmpeg_stats(stats_text)
                                    self._log_stderr_content(stats_text)
                            except Exception as e:
                                logger.debug(f"Error parsing immediate stats line: {e}")

                        # Clear buffer after processing
                        buffer = b""
                        continue

                    # Handle regular line breaks for non-stats content
                    elif byte == b'\n':
                        if buffer.strip():
                            line_text = buffer.decode('utf-8', errors='ignore').strip()
                            if line_text and not line_text.startswith("frame="):
                                self._log_stderr_content(line_text)
                        buffer = b""

                    # Handle carriage returns (potential stats overwrite)
                    elif byte == b'\r':
                        # Check if this might be a stats line
                        if b"frame=" in buffer:
                            try:
                                stats_text = buffer.decode('utf-8', errors='ignore').strip()
                                if stats_text and "frame=" in stats_text:
                                    self._parse_ffmpeg_stats(stats_text)
                                    self._log_stderr_content(stats_text)
                            except Exception as e:
                                logger.debug(f"Error parsing stats on carriage return: {e}")
                        elif buffer.strip():
                            # Regular content with carriage return
                            line_text = buffer.decode('utf-8', errors='ignore').strip()
                            if line_text:
                                self._log_stderr_content(line_text)
                        buffer = b""

                    # Prevent buffer from growing too large for non-stats content
                    elif len(buffer) > 1024 and b"frame=" not in buffer:
                        # Process whatever we have if it's not a stats line
                        if buffer.strip():
                            line_text = buffer.decode('utf-8', errors='ignore').strip()
                            if line_text:
                                self._log_stderr_content(line_text)
                        buffer = b""

                except Exception as e:
                    logger.error(f"Error reading stderr byte: {e}")
                    break

            # Process any remaining buffer content
            if buffer.strip():
                try:
                    remaining_text = buffer.decode('utf-8', errors='ignore').strip()
                    if remaining_text:
                        if "frame=" in remaining_text:
                            self._parse_ffmpeg_stats(remaining_text)
                        self._log_stderr_content(remaining_text)
                except Exception as e:
                    logger.debug(f"Error processing remaining buffer: {e}")

        except Exception as e:
            # Catch any other exceptions in the thread to prevent crashes
            try:
                logger.error(f"Error in stderr reader thread for channel {self.channel_id}: {e}")
            except:
                pass

    def _log_stderr_content(self, content):
        """Log stderr content from FFmpeg with appropriate log levels"""
        try:
            content = content.strip()
            if not content:
                return

            # Convert to lowercase for easier matching
            content_lower = content.lower()
            # Check if we are still in the input phase
            if content_lower.startswith('input #') or 'decoder' in content_lower:
                self.ffmpeg_input_phase = True
            # Track FFmpeg phases - once we see output info, we're past input phase
            if content_lower.startswith('output #') or 'encoder' in content_lower:
                self.ffmpeg_input_phase = False

            # Parse VLC-specific output - look for TS demux type info for codec detection
            if 'ts demux debug' in content_lower and 'type=' in content_lower and ('video' in content_lower or 'audio' in content_lower):
                from .services.channel_service import ChannelService
                ChannelService.parse_and_store_stream_info(self.channel_id, content, "vlc", self.current_stream_id)
            
            # Parse streamlink-specific output
            if 'opening stream:' in content_lower or 'available streams:' in content_lower:
                from .services.channel_service import ChannelService
                ChannelService.parse_and_store_stream_info(self.channel_id, content, "streamlink", self.current_stream_id)

            # Only parse stream info if we're still in the input phase
            if ("stream #" in content_lower and
                ("video:" in content_lower or "audio:" in content_lower) and
                self.ffmpeg_input_phase):

                from .services.channel_service import ChannelService
                if "video:" in content_lower:
                    ChannelService.parse_and_store_stream_info(self.channel_id, content, "video", self.current_stream_id)
                elif "audio:" in content_lower:
                    ChannelService.parse_and_store_stream_info(self.channel_id, content, "audio", self.current_stream_id)

            # Determine log level based on content
            if any(keyword in content_lower for keyword in ['error', 'failed', 'cannot', 'invalid', 'corrupt']):
                logger.error(f"FFmpeg stderr for channel {self.channel_id}: {content}")
            elif any(keyword in content_lower for keyword in ['warning', 'deprecated', 'ignoring']):
                logger.warning(f"FFmpeg stderr for channel {self.channel_id}: {content}")
            elif content.startswith('frame=') or 'fps=' in content or 'speed=' in content:
                # Stats lines - log at trace level to avoid spam
                logger.trace(f"FFmpeg stats for channel {self.channel_id}: {content}")
            elif any(keyword in content_lower for keyword in ['input', 'output', 'stream', 'video', 'audio']):
                # Stream info - log at info level
                logger.info(f"FFmpeg info for channel {self.channel_id}: {content}")
                if content.startswith('Input #0'):
                    # If it's input 0, parse stream info
                    from .services.channel_service import ChannelService
                    ChannelService.parse_and_store_stream_info(self.channel_id, content, "input", self.current_stream_id)
            else:
                # Everything else at debug level
                logger.debug(f"FFmpeg stderr for channel {self.channel_id}: {content}")

        except Exception as e:
            logger.error(f"Error logging stderr content for channel {self.channel_id}: {e}")

    def _parse_ffmpeg_stats(self, stats_line):
        """Parse FFmpeg stats line and extract speed, fps, and bitrate"""
        try:
            # Example FFmpeg stats line:
            # frame= 1234 fps= 30 q=28.0 size=    2048kB time=00:00:41.33 bitrate= 406.1kbits/s speed=1.02x

            # Extract speed (e.g., "speed=1.02x")
            speed_match = re.search(r'speed=\s*([0-9.]+)x?', stats_line)
            ffmpeg_speed = float(speed_match.group(1)) if speed_match else None

            # Extract fps (e.g., "fps= 30")
            fps_match = re.search(r'fps=\s*([0-9.]+)', stats_line)
            ffmpeg_fps = float(fps_match.group(1)) if fps_match else None

            # Extract bitrate (e.g., "bitrate= 406.1kbits/s")
            bitrate_match = re.search(r'bitrate=\s*([0-9.]+(?:\.[0-9]+)?)\s*([kmg]?)bits/s', stats_line, re.IGNORECASE)
            ffmpeg_output_bitrate = None
            if bitrate_match:
                bitrate_value = float(bitrate_match.group(1))
                unit = bitrate_match.group(2).lower()
                # Convert to kbps
                if unit == 'm':
                    bitrate_value *= 1000
                elif unit == 'g':
                    bitrate_value *= 1000000
                # If no unit or 'k', it's already in kbps
                ffmpeg_output_bitrate = bitrate_value

            # Calculate actual FPS
            actual_fps = None
            if ffmpeg_fps is not None and ffmpeg_speed is not None and ffmpeg_speed > 0:
                actual_fps = ffmpeg_fps / ffmpeg_speed
            # Store in Redis if we have valid data
            if any(x is not None for x in [ffmpeg_speed, ffmpeg_fps, actual_fps, ffmpeg_output_bitrate]):
                self._update_ffmpeg_stats_in_redis(ffmpeg_speed, ffmpeg_fps, actual_fps, ffmpeg_output_bitrate)

                # Also save ffmpeg_output_bitrate to database if we have stream_id
                if ffmpeg_output_bitrate is not None and self.current_stream_id:
                    from .services.channel_service import ChannelService
                    ChannelService._update_stream_stats_in_db(
                        self.current_stream_id,
                        ffmpeg_output_bitrate=ffmpeg_output_bitrate
                    )

            # Fix the f-string formatting
            actual_fps_str = f"{actual_fps:.1f}" if actual_fps is not None else "N/A"
            ffmpeg_output_bitrate_str = f"{ffmpeg_output_bitrate:.1f}" if ffmpeg_output_bitrate is not None else "N/A"
            # Log the stats
            logger.debug(f"FFmpeg stats for channel {self.channel_id}: - Speed: {ffmpeg_speed}x, FFmpeg FPS: {ffmpeg_fps}, "
                        f"Actual FPS: {actual_fps_str}, "
                        f"Output Bitrate: {ffmpeg_output_bitrate_str} kbps")
            # If we have a valid speed, check for buffering
            if ffmpeg_speed is not None and ffmpeg_speed < self.buffering_speed:
                if self.buffering:
                    # Buffering is still ongoing, check for how long
                    if self.buffering_start_time is None:
                        self.buffering_start_time = time.time()
                    else:
                        buffering_duration = time.time() - self.buffering_start_time
                        if buffering_duration > self.buffering_timeout:
                            # Buffering timeout reached, log error and try next stream
                            logger.error(f"Buffering timeout reached for channel {self.channel_id} after {buffering_duration:.1f} seconds")
                            # Send next stream request
                            if self._try_next_stream():
                                logger.info(f"Switched to next stream for channel {self.channel_id} after buffering timeout")
                                # Reset buffering state
                                self.buffering = False
                                self.buffering_start_time = None

                                # Log failover event
                                try:
                                    channel_obj = Channel.objects.get(uuid=self.channel_id)
                                    log_system_event(
                                        'channel_failover',
                                        channel_id=self.channel_id,
                                        channel_name=channel_obj.name,
                                        reason='buffering_timeout',
                                        duration=buffering_duration
                                    )
                                except Exception as e:
                                    logger.error(f"Could not log failover event: {e}")
                            else:
                                logger.error(f"Failed to switch to next stream for channel {self.channel_id} after buffering timeout")
                else:
                    # Buffering just started, set the flag and start timer
                    self.buffering = True
                    self.buffering_start_time = time.time()
                    logger.warning(f"Buffering started for channel {self.channel_id} - speed: {ffmpeg_speed}x")

                    # Log system event for buffering
                    try:
                        channel_obj = Channel.objects.get(uuid=self.channel_id)
                        log_system_event(
                            'channel_buffering',
                            channel_id=self.channel_id,
                            channel_name=channel_obj.name,
                            speed=ffmpeg_speed
                        )
                    except Exception as e:
                        logger.error(f"Could not log buffering event: {e}")

                # Log buffering warning
                logger.debug(f"FFmpeg speed on channel {self.channel_id} is below {self.buffering_speed} ({ffmpeg_speed}x) - buffering detected")
                # Set channel state to buffering
                if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                    metadata_key = RedisKeys.channel_metadata(self.channel_id)
                    self.buffer.redis_client.hset(metadata_key, ChannelMetadataField.STATE, ChannelState.BUFFERING)
            elif ffmpeg_speed is not None and ffmpeg_speed >= self.buffering_speed:
                # Speed is good, check if we were buffering
                if self.buffering:
                    # Reset buffering state
                    logger.info(f"Buffering ended for channel {self.channel_id} - speed: {ffmpeg_speed}x")
                    self.buffering = False
                    self.buffering_start_time = None
                    # Set channel state to active if speed is good
                    if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                        metadata_key = RedisKeys.channel_metadata(self.channel_id)
                        self.buffer.redis_client.hset(metadata_key, ChannelMetadataField.STATE, ChannelState.ACTIVE)

        except Exception as e:
            logger.debug(f"Error parsing FFmpeg stats: {e}")

    def _update_ffmpeg_stats_in_redis(self, speed, fps, actual_fps, output_bitrate):
        """Update FFmpeg performance stats in Redis metadata"""
        try:
            if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                metadata_key = RedisKeys.channel_metadata(self.channel_id)
                update_data = {
                    ChannelMetadataField.FFMPEG_STATS_UPDATED: str(time.time())
                }

                if speed is not None:
                    update_data[ChannelMetadataField.FFMPEG_SPEED] = str(round(speed, 3))

                if fps is not None:
                    update_data[ChannelMetadataField.FFMPEG_FPS] = str(round(fps, 1))

                if actual_fps is not None:
                    update_data[ChannelMetadataField.ACTUAL_FPS] = str(round(actual_fps, 1))

                if output_bitrate is not None:
                    update_data[ChannelMetadataField.FFMPEG_OUTPUT_BITRATE] = str(round(output_bitrate, 1))

                self.buffer.redis_client.hset(metadata_key, mapping=update_data)

        except Exception as e:
            logger.error(f"Error updating FFmpeg stats in Redis: {e}")


    def _establish_http_connection(self):
        """Establish HTTP connection using thread-based reader (same as transcode path)"""
        try:
            logger.debug(f"Using HTTP streamer thread to connect to stream: {self.url}")

            # Check if we already have active HTTP connections
            if self.current_response or self.current_session:
                logger.info(f"Existing HTTP connection found for channel {self.channel_id}, closing before establishing new connection")
                self._close_connection()

                # Wait for connections to fully close
                if not self._wait_for_existing_processes_to_close():
                    logger.error(f"Failed to close existing HTTP connections for channel {self.channel_id}")
                    return False

            # Also check for any lingering transcode processes
            if self.transcode_process and self.transcode_process.poll() is None:
                logger.debug(f"Closing existing transcode process before establishing HTTP connection for channel {self.channel_id}")
                self._close_socket()

            # Use HTTPStreamReader to fetch stream and pipe to a readable file descriptor
            # This allows us to use the same fetch_chunk() path as transcode
            from .http_streamer import HTTPStreamReader

            # Create and start the HTTP stream reader
            self.http_reader = HTTPStreamReader(
                url=self.url,
                user_agent=self.user_agent,
                chunk_size=self.chunk_size
            )

            # Start the reader thread and get the read end of the pipe
            pipe_fd = self.http_reader.start()

            # Wrap the file descriptor in a file object (same as transcode stdout)
            import os
            self.socket = os.fdopen(pipe_fd, 'rb', buffering=0)
            self.connected = True
            self.healthy = True

            logger.info(f"Successfully started HTTP streamer thread for channel {self.channel_id}")

            # Store connection start time for stability tracking
            self.connection_start_time = time.time()

            # Set channel state to waiting for clients
            self._set_waiting_for_clients()

            return True

        except Exception as e:
            logger.error(f"Error establishing HTTP connection for channel {self.channel_id}: {e}", exc_info=True)
            self._close_socket()
            return False

    def _update_bytes_processed(self, chunk_size):
        """Update the total bytes processed in Redis metadata"""
        try:
            # Update local counter
            self.bytes_processed += chunk_size

            # Only update Redis periodically to reduce overhead
            now = time.time()
            if now - self.last_bytes_update >= self.bytes_update_interval:
                if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                    # Update channel metadata with total bytes
                    metadata_key = RedisKeys.channel_metadata(self.channel_id)

                    # Use hincrby to atomically increment the total_bytes field
                    self.buffer.redis_client.hincrby(metadata_key, ChannelMetadataField.TOTAL_BYTES, self.bytes_processed)

                    # Reset local counter after updating Redis
                    self.bytes_processed = 0
                    self.last_bytes_update = now

                    logger.debug(f"Updated {ChannelMetadataField.TOTAL_BYTES} in Redis for channel {self.channel_id}")
        except Exception as e:
            logger.error(f"Error updating bytes processed: {e}")

    def _process_stream_data(self):
        """Process stream data until disconnect or error - unified path for both transcode and HTTP"""
        try:
            # Both transcode and HTTP now use the same subprocess/socket approach
            # This gives us perfect control: check flags between chunks, timeout just returns False
            while self.running and self.connected and not self.stop_requested and not self.needs_stream_switch:
                if self.fetch_chunk():
                    self.last_data_time = time.time()
                else:
                    # fetch_chunk() returned False - could be timeout, no data, or error
                    if not self.running:
                        break
                    # Brief sleep before retry to avoid tight loop
                    gevent.sleep(0.1)
        except Exception as e:
            logger.error(f"Error processing stream data for channel {self.channel_id}: {e}", exc_info=True)

        # If we exit the loop, connection is closed or failed
        self.connected = False

    def _close_all_connections(self):
        """Close all connection resources"""
        if self.socket or self.transcode_process:
            try:
                self._close_socket()
            except Exception as e:
                logger.debug(f"Error closing socket for channel {self.channel_id}: {e}")

        if self.current_response:
            try:
                self.current_response.close()
            except Exception as e:
                logger.debug(f"Error closing response for channel {self.channel_id}: {e}")

        if self.current_session:
            try:
                self.current_session.close()
            except Exception as e:
                logger.debug(f"Error closing session for channel {self.channel_id}: {e}")

        # Clear references
        self.socket = None
        self.current_response = None
        self.current_session = None
        self.transcode_process = None

    def stop(self):
        """Stop the stream manager and cancel all timers"""
        logger.info(f"Stopping stream manager for channel {self.channel_id}")

        # Add at the beginning of your stop method
        self.stopping = True

        # Release stream resources if we're the owner
        if self.current_stream_id and hasattr(self, 'worker_id') and self.worker_id:
            if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                owner_key = RedisKeys.channel_owner(self.channel_id)
                current_owner = self.buffer.redis_client.get(owner_key)

        # Cancel all buffer check timers
        for timer in list(self._buffer_check_timers):
            try:
                if timer and timer.is_alive():
                    timer.cancel()
            except Exception as e:
                logger.error(f"Error canceling buffer check timer for channel {self.channel_id}: {e}")

        self._buffer_check_timers.clear()

        # Set the flag first
        self.stop_requested = True

        # Close any active response connection
        if hasattr(self, 'current_response') and self.current_response:  # CORRECT NAME
            try:
                self.current_response.close()  # CORRECT NAME
            except Exception:
                pass

        # Also close the session
        if hasattr(self, 'current_session') and self.current_session:
            try:
                self.current_session.close()
            except Exception:
                pass

        # Explicitly close socket/transcode resources
        self._close_socket()

        # Set running to false to ensure thread exits
        self.running = False

    def update_url(self, new_url, stream_id=None, m3u_profile_id=None):
        """Update stream URL and reconnect with proper cleanup for both HTTP and transcode sessions"""
        if new_url == self.url:
            logger.info(f"URL unchanged: {new_url}")
            return False

        logger.info(f"Switching stream URL from {self.url} to {new_url} for channel {self.channel_id}")

        # Import both models for proper resource management
        from apps.channels.models import Stream, Channel
        from django.db import connection

        # Update stream profile if we're switching streams
        if self.current_stream_id and stream_id and self.current_stream_id != stream_id:
            try:
                # Get the channel by UUID
                channel = Channel.objects.get(uuid=self.channel_id)

                # Get stream to find its profile
                #new_stream = Stream.objects.get(pk=stream_id)

                # Use the new method to update the profile and manage connection counts
                if m3u_profile_id:
                    success = channel.update_stream_profile(m3u_profile_id)
                    if success:
                        logger.debug(f"Updated m3u profile for channel {self.channel_id} to use profile from stream {stream_id}")
                    else:
                        logger.warning(f"Failed to update stream profile for channel {self.channel_id}")

            except Exception as e:
                logger.error(f"Error updating stream profile for channel {self.channel_id}: {e}")

            finally:
                # Always close database connection after profile update
                try:
                    connection.close()
                except Exception:
                    pass

        # CRITICAL: Set a flag to prevent immediate reconnection with old URL
        self.url_switching = True
        self.url_switch_start_time = time.time()

        try:
            # Check which type of connection we're using and close it properly
            if self.transcode or self.socket:
                logger.debug(f"Closing transcode process before URL change for channel {self.channel_id}")
                self._close_socket()
            else:
                logger.debug(f"Closing HTTP connection before URL change for channel {self.channel_id}")
                self._close_connection()

            # Update URL and reset connection state
            old_url = self.url
            self.url = new_url
            self.connected = False

            # Update stream ID if provided
            if stream_id:
                old_stream_id = self.current_stream_id
                self.current_stream_id = stream_id
                # Add stream ID to tried streams for proper tracking
                self.tried_stream_ids.add(stream_id)
                logger.info(f"Updated stream ID from {old_stream_id} to {stream_id} for channel {self.channel_id}")

            # Reset retry counter to allow immediate reconnect
            self.retry_count = 0

            # Also reset buffer position to prevent stale data after URL change
            if hasattr(self.buffer, 'reset_buffer_position'):
                try:
                    self.buffer.reset_buffer_position()
                    logger.debug("Reset buffer position for clean URL switch")
                except Exception as e:
                    logger.warning(f"Failed to reset buffer position: {e}")

            # Log stream switch event
            try:
                channel_obj = Channel.objects.get(uuid=self.channel_id)
                log_system_event(
                    'stream_switch',
                    channel_id=self.channel_id,
                    channel_name=channel_obj.name,
                    new_url=new_url[:100] if new_url else None,
                    stream_id=stream_id
                )
            except Exception as e:
                logger.error(f"Could not log stream switch event: {e}")

            return True
        except Exception as e:
            logger.error(f"Error during URL update for channel {self.channel_id}: {e}", exc_info=True)
            return False
        finally:
            # CRITICAL FIX: Always reset the URL switching flag when done, whether successful or not
            self.url_switching = False
            logger.info(f"Stream switch completed for channel {self.channel_id}")

    def should_retry(self) -> bool:
        """Check if connection retry is allowed"""
        return self.retry_count < self.max_retries

    def _monitor_health(self):
        """Monitor stream health and set flags for the main loop to handle recovery"""
        consecutive_unhealthy_checks = 0
        max_unhealthy_checks = 3

        # Add flags for the main loop to check
        self.needs_reconnect = False
        self.needs_stream_switch = False
        self.last_health_action_time = 0
        action_cooldown = 30  # Prevent rapid recovery attempts

        while self.running:
            try:
                now = time.time()
                inactivity_duration = now - self.last_data_time
                timeout_threshold = getattr(Config, 'CONNECTION_TIMEOUT', 10)

                if inactivity_duration > timeout_threshold and self.connected:
                    if self.healthy:
                        logger.warning(f"Stream unhealthy for channel {self.channel_id} - no data for {inactivity_duration:.1f}s")
                        self.healthy = False

                    consecutive_unhealthy_checks += 1

                    # Only set flags if enough time has passed since last action
                    if (consecutive_unhealthy_checks >= max_unhealthy_checks and
                        now - self.last_health_action_time > action_cooldown):

                        # Calculate stability to decide on action type
                        connection_start_time = getattr(self, 'connection_start_time', 0)
                        stable_time = self.last_data_time - connection_start_time if connection_start_time > 0 else 0

                        if stable_time >= 30:  # Stream was stable, try reconnect first
                            if not self.needs_reconnect:
                                logger.info(f"Setting reconnect flag for stable stream (stable for {stable_time:.1f}s) for channel {self.channel_id}")
                                self.needs_reconnect = True
                                self.last_health_action_time = now
                        else:
                            # Stream wasn't stable, suggest stream switch
                            if not self.needs_stream_switch:
                                logger.info(f"Setting stream switch flag for unstable stream (stable for {stable_time:.1f}s) for channel {self.channel_id}")
                                self.needs_stream_switch = True
                                self.last_health_action_time = now

                        consecutive_unhealthy_checks = 0 # Reset after setting flag

                elif self.connected and not self.healthy:
                    # Auto-recover health when data resumes
                    logger.info(f"Stream health restored for channel {self.channel_id} - data resumed after {inactivity_duration:.1f}s")
                    self.healthy = True
                    consecutive_unhealthy_checks = 0
                    # Clear recovery flags when healthy again
                    self.needs_reconnect = False
                    self.needs_stream_switch = False

                if self.healthy:
                    consecutive_unhealthy_checks = 0

            except Exception as e:
                logger.error(f"Error in health monitor: {e}")

            gevent.sleep(self.health_check_interval)  # REPLACE time.sleep(self.health_check_interval)

    def _attempt_reconnect(self):
        """Attempt to reconnect to the current stream"""
        try:
            logger.info(f"Attempting reconnect to current stream for channel {self.channel_id}")

            # Don't try to reconnect if we're already switching URLs
            if self.url_switching:
                logger.info(f"URL switching already in progress, skipping reconnect for channel {self.channel_id}")
                return False

            # Set a flag to prevent concurrent operations
            if hasattr(self, 'reconnecting') and self.reconnecting:
                logger.info(f"Reconnect already in progress, skipping for channel {self.channel_id}")
                return False

            self.reconnecting = True

            try:
                # Close existing connection and wait for it to fully terminate
                if self.transcode or self.socket:
                    logger.debug(f"Closing transcode process before reconnect for channel {self.channel_id}")
                    self._close_socket()
                else:
                    logger.debug(f"Closing HTTP connection before reconnect for channel {self.channel_id}")
                    self._close_connection()

                # Wait for all processes to fully close before attempting reconnect
                if not self._wait_for_existing_processes_to_close():
                    logger.warning(f"Some processes may still be running during reconnect for channel {self.channel_id}")

                self.connected = False

                # Attempt to establish a new connection using the same URL
                connection_result = False
                if self.transcode:
                    connection_result = self._establish_transcode_connection()
                else:
                    connection_result = self._establish_http_connection()

                if connection_result:
                    self.connection_start_time = time.time()
                    logger.info(f"Reconnect successful for channel {self.channel_id}")

                    # Log reconnection event
                    try:
                        channel_obj = Channel.objects.get(uuid=self.channel_id)
                        log_system_event(
                            'channel_reconnect',
                            channel_id=self.channel_id,
                            channel_name=channel_obj.name,
                            reason='health_monitor'
                        )
                    except Exception as e:
                        logger.error(f"Could not log reconnection event: {e}")

                    return True
                else:
                    logger.warning(f"Reconnect failed for channel {self.channel_id}")
                    return False

            finally:
                self.reconnecting = False

        except Exception as e:
            logger.error(f"Error in reconnect attempt for channel {self.channel_id}: {e}", exc_info=True)
            self.reconnecting = False
            return False

    def _attempt_health_recovery(self):
        """Attempt to recover stream health by switching to another stream"""
        try:
            logger.info(f"Attempting health recovery for channel {self.channel_id}")

            # Don't try to switch if we're already in the process of switching URLs
            if self.url_switching:
                logger.info(f"URL switching already in progress, skipping health recovery for channel {self.channel_id}")
                return

            # Try to switch to next stream
            switch_result = self._try_next_stream()
            if switch_result:
                logger.info(f"Health recovery successful - switched to new stream for channel {self.channel_id}")
                return True
            else:
                logger.warning(f"Health recovery failed - no alternative streams available for channel {self.channel_id}")
                return False

        except Exception as e:
            logger.error(f"Error in health recovery attempt for channel {self.channel_id}: {e}", exc_info=True)
            return False

    def _close_connection(self):
        """Close HTTP connection resources"""
        # Close response if it exists
        if hasattr(self, 'current_response') and self.current_response:
            try:
                self.current_response.close()
            except Exception as e:
                logger.debug(f"Error closing response for channel {self.channel_id}: {e}")
            self.current_response = None

        # Close session if it exists
        if hasattr(self, 'current_session') and self.current_session:
            try:
                self.current_session.close()
            except Exception as e:
                logger.debug(f"Error closing session for channel {self.channel_id}: {e}")
            self.current_session = None

    def _close_socket(self):
        """Close socket and transcode resources as needed"""
        # First try to use _close_connection for HTTP resources
        if self.current_response or self.current_session:
            self._close_connection()

        # Stop HTTP reader thread if it exists
        if hasattr(self, 'http_reader') and self.http_reader:
            try:
                logger.debug(f"Stopping HTTP reader thread for channel {self.channel_id}")
                self.http_reader.stop()
                self.http_reader = None
            except Exception as e:
                logger.debug(f"Error stopping HTTP reader for channel {self.channel_id}: {e}")

        # Otherwise handle socket and transcode resources
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.debug(f"Error closing socket for channel {self.channel_id}: {e}")
                pass

        # Enhanced transcode process cleanup with immediate termination
        if self.transcode_process:
            try:
                logger.debug(f"Killing transcode process for channel {self.channel_id}")
                self.transcode_process.kill()

                # Give it a very short time to die
                try:
                    self.transcode_process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    logger.error(f"Failed to kill transcode process even with force for channel {self.channel_id}")
            except Exception as e:
                logger.debug(f"Error terminating transcode process for channel {self.channel_id}: {e}")

                # Final attempt: try to kill directly
                try:
                    self.transcode_process.kill()
                except Exception as e:
                    logger.error(f"Final kill attempt failed for channel {self.channel_id}: {e}")

            # Explicitly close all subprocess pipes to prevent file descriptor leaks
            try:
                if self.transcode_process.stdin:
                    self.transcode_process.stdin.close()
                if self.transcode_process.stdout:
                    self.transcode_process.stdout.close()
                if self.transcode_process.stderr:
                    self.transcode_process.stderr.close()
                logger.debug(f"Closed all subprocess pipes for channel {self.channel_id}")
            except Exception as e:
                logger.debug(f"Error closing subprocess pipes for channel {self.channel_id}: {e}")

            # Join stderr reader thread to ensure it's fully terminated
            if hasattr(self, 'stderr_reader_thread') and self.stderr_reader_thread and self.stderr_reader_thread.is_alive():
                try:
                    logger.debug(f"Waiting for stderr reader thread to terminate for channel {self.channel_id}")
                    self.stderr_reader_thread.join(timeout=2.0)
                    if self.stderr_reader_thread.is_alive():
                        logger.warning(f"Stderr reader thread did not terminate within timeout for channel {self.channel_id}")
                except Exception as e:
                    logger.debug(f"Error joining stderr reader thread for channel {self.channel_id}: {e}")
                finally:
                    self.stderr_reader_thread = None

            self.transcode_process = None
            self.transcode_process_active = False  # Reset the flag

            # Clear transcode active key in Redis if available
            if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                try:
                    transcode_key = RedisKeys.transcode_active(self.channel_id)
                    self.buffer.redis_client.delete(transcode_key)
                    logger.debug(f"Cleared transcode active flag for channel {self.channel_id}")
                except Exception as e:
                    logger.debug(f"Error clearing transcode flag for channel {self.channel_id}: {e}")
        self.socket = None
        self.connected = False
        # Cancel any remaining buffer check timers
        for timer in list(self._buffer_check_timers):
            try:
                if timer and timer.is_alive():
                    timer.cancel()
                    logger.debug(f"Cancelled buffer check timer during socket close for channel {self.channel_id}")
            except Exception as e:
                logger.debug(f"Error canceling timer during socket close for channel {self.channel_id}: {e}")

        self._buffer_check_timers = []

    def fetch_chunk(self):
        """Fetch data from socket with timeout handling"""
        if not self.connected or not self.socket:
            return False

        try:
            # Set timeout for chunk reads
            chunk_timeout = ConfigHelper.chunk_timeout()  # Use centralized timeout configuration

            try:
                # Handle different socket types with timeout
                if hasattr(self.socket, 'recv'):
                    # Standard socket - set timeout
                    original_timeout = self.socket.gettimeout()
                    self.socket.settimeout(chunk_timeout)
                    chunk = self.socket.recv(Config.CHUNK_SIZE)
                    self.socket.settimeout(original_timeout)  # Restore original timeout
                else:
                    # SocketIO object (transcode process stdout) - use select for timeout
                    import select
                    ready, _, _ = select.select([self.socket], [], [], chunk_timeout)

                    if not ready:
                        # Timeout occurred
                        logger.debug(f"Chunk read timeout ({chunk_timeout}s) for channel {self.channel_id}")
                        return False

                    chunk = self.socket.read(Config.CHUNK_SIZE)

            except socket.timeout:
                # Socket timeout occurred
                logger.debug(f"Socket timeout ({chunk_timeout}s) for channel {self.channel_id}")
                return False

            if not chunk:
                # Connection closed by server
                logger.warning(f"Server closed connection for channel {self.channel_id}")
                self._close_socket()
                self.connected = False
                return False

            # Track chunk size before adding to buffer
            chunk_size = len(chunk)
            self._update_bytes_processed(chunk_size)

            # Add directly to buffer without TS-specific processing
            success = self.buffer.add_chunk(chunk)

            # Update last data timestamp in Redis if successful
            if success and hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                last_data_key = RedisKeys.last_data(self.buffer.channel_id)
                self.buffer.redis_client.set(last_data_key, str(time.time()), ex=60)

            return True

        except (socket.timeout, socket.error) as e:
            # Socket error
            logger.error(f"Socket error: {e}")
            self._close_socket()
            self.connected = False
            return False

        except Exception as e:
            logger.error(f"Error in fetch_chunk: {e}")
            return False

    def _set_waiting_for_clients(self):
        """Set channel state to waiting for clients AFTER buffer has enough chunks"""
        try:
            if hasattr(self.buffer, 'channel_id') and hasattr(self.buffer, 'redis_client'):
                channel_id = self.buffer.channel_id
                redis_client = self.buffer.redis_client

                if channel_id and redis_client:
                    current_time = str(time.time())
                    metadata_key = RedisKeys.channel_metadata(channel_id)

                    # Check current state first
                    current_state = None
                    try:
                        metadata = redis_client.hgetall(metadata_key)
                        state_field = ChannelMetadataField.STATE.encode('utf-8')
                        if metadata and state_field in metadata:
                            current_state = metadata[state_field].decode('utf-8')
                    except Exception as e:
                        logger.error(f"Error checking current state: {e}")

                    # Only update if not already past connecting
                    if not current_state or current_state in [ChannelState.INITIALIZING, ChannelState.CONNECTING]:
                        # NEW CODE: Check if buffer has enough chunks
                        # IMPORTANT: Read from Redis, not local buffer.index, because in multi-worker setup
                        # each worker has its own StreamBuffer instance with potentially stale local index
                        buffer_index_key = RedisKeys.buffer_index(channel_id)
                        current_buffer_index = 0
                        try:
                            redis_index = redis_client.get(buffer_index_key)
                            if redis_index:
                                current_buffer_index = int(redis_index)
                        except Exception as e:
                            logger.error(f"Error reading buffer index from Redis: {e}")

                        initial_chunks_needed = ConfigHelper.initial_behind_chunks()

                        if current_buffer_index < initial_chunks_needed:
                            # Not enough buffer yet - set to connecting state if not already
                            if current_state != ChannelState.CONNECTING:
                                update_data = {
                                    ChannelMetadataField.STATE: ChannelState.CONNECTING,
                                    ChannelMetadataField.STATE_CHANGED_AT: current_time
                                }
                                redis_client.hset(metadata_key, mapping=update_data)
                                logger.info(f"Channel {channel_id} connected but waiting for buffer to fill: {current_buffer_index}/{initial_chunks_needed} chunks")

                            # Schedule a retry to check buffer status again
                            timer = threading.Timer(0.5, self._check_buffer_and_set_state)
                            timer.daemon = True
                            timer.start()
                            return False

                        # We have enough buffer, proceed with state change
                        update_data = {
                            ChannelMetadataField.STATE: ChannelState.WAITING_FOR_CLIENTS,
                            ChannelMetadataField.CONNECTION_READY_TIME: current_time,
                            ChannelMetadataField.STATE_CHANGED_AT: current_time,
                            ChannelMetadataField.BUFFER_CHUNKS: str(current_buffer_index)
                        }
                        redis_client.hset(metadata_key, mapping=update_data)

                        # Get configured grace period or default
                        grace_period = ConfigHelper.channel_init_grace_period()
                        logger.info(f"STREAM MANAGER: Updated channel {channel_id} state: {current_state or 'None'} -> {ChannelState.WAITING_FOR_CLIENTS} with {current_buffer_index} buffer chunks")
                        logger.info(f"Started initial connection grace period ({grace_period}s) for channel {channel_id}")
                    else:
                        logger.debug(f"Not changing state: channel {channel_id} already in {current_state} state")
        except Exception as e:
            logger.error(f"Error setting waiting for clients state for channel {channel_id}: {e}")

    def _check_buffer_and_set_state(self):
        """Check buffer size and set state to waiting_for_clients when ready"""
        try:
            # Enhanced stop detection with short-circuit return
            if not self.running or getattr(self, 'stopping', False) or getattr(self, 'reconnecting', False):
                logger.debug(f"Buffer check aborted - channel {self.buffer.channel_id} is stopping or reconnecting")
                return False  # Return value to indicate check was aborted

            # Clean up completed timers
            self._buffer_check_timers = [t for t in self._buffer_check_timers if t.is_alive()]

            if hasattr(self.buffer, 'channel_id') and hasattr(self.buffer, 'redis_client'):
                channel_id = self.buffer.channel_id
                redis_client = self.buffer.redis_client

                # IMPORTANT: Read from Redis, not local buffer.index
                buffer_index_key = RedisKeys.buffer_index(channel_id)
                current_buffer_index = 0
                try:
                    redis_index = redis_client.get(buffer_index_key)
                    if redis_index:
                        current_buffer_index = int(redis_index)
                except Exception as e:
                    logger.error(f"Error reading buffer index from Redis: {e}")

                initial_chunks_needed = ConfigHelper.initial_behind_chunks()  # Use ConfigHelper for consistency

                if current_buffer_index >= initial_chunks_needed:
                    # We now have enough buffer, call _set_waiting_for_clients again
                    logger.info(f"Buffer threshold reached for channel {channel_id}: {current_buffer_index}/{initial_chunks_needed} chunks")
                    self._set_waiting_for_clients()
                else:
                    # Still waiting, log progress and schedule another check
                    logger.debug(f"Buffer filling for channel {channel_id}: {current_buffer_index}/{initial_chunks_needed} chunks")

                    # Schedule another check - NOW WITH STOPPING CHECK
                    if self.running and not getattr(self, 'stopping', False):
                        timer = threading.Timer(0.5, self._check_buffer_and_set_state)
                        timer.daemon = True
                        timer.start()
                        self._buffer_check_timers.append(timer)

            return True  # Return value to indicate check was successful
        except Exception as e:
            logger.error(f"Error in buffer check for channel {self.channel_id}: {e}")
            return False

    def _try_next_stream(self):
        """
        Try to switch to the next available stream for this channel.
        Will iterate through multiple alternate streams if needed to find one with a different URL.

        Returns:
            bool: True if successfully switched to a new stream, False otherwise
        """
        try:
            logger.info(f"Trying to find alternative stream for channel {self.channel_id}, current stream ID: {self.current_stream_id}")

            # Get alternate streams excluding the current one
            alternate_streams = get_alternate_streams(self.channel_id, self.current_stream_id)
            logger.info(f"Found {len(alternate_streams)} potential alternate streams for channel {self.channel_id}")

            # Filter out streams we've already tried
            untried_streams = [s for s in alternate_streams if s['stream_id'] not in self.tried_stream_ids]
            if untried_streams:
                ids_to_try = ', '.join([str(s['stream_id']) for s in untried_streams])
                logger.info(f"Found {len(untried_streams)} untried streams for channel {self.channel_id}: [{ids_to_try}]")
            else:
                logger.warning(f"No untried streams available for channel {self.channel_id}, tried: {self.tried_stream_ids}")

            if not untried_streams:
                # Check if we have streams but they've all been tried
                if alternate_streams and len(self.tried_stream_ids) > 0:
                    logger.warning(f"All {len(alternate_streams)} alternate streams have been tried for channel {self.channel_id}")
                return False

            # IMPROVED: Try multiple streams until we find one with a different URL
            for next_stream in untried_streams:
                stream_id = next_stream['stream_id']
                profile_id = next_stream['profile_id']  # This is the M3U profile ID we need

                # Add to tried streams
                self.tried_stream_ids.add(stream_id)

                # Get stream info including URL using the profile_id we already have
                logger.info(f"Trying next stream ID {stream_id} with profile ID {profile_id} for channel {self.channel_id}")
                stream_info = get_stream_info_for_switch(self.channel_id, stream_id)

                if 'error' in stream_info or not stream_info.get('url'):
                    logger.error(f"Error getting info for stream {stream_id} for channel {self.channel_id}: {stream_info.get('error', 'No URL')}")
                    continue  # Try next stream instead of giving up

                # Update URL and user agent
                new_url = stream_info['url']
                new_user_agent = stream_info['user_agent']
                new_transcode = stream_info['transcode']

                # CRITICAL FIX: Check if the new URL is the same as current URL
                # This can happen when current_stream_id is None and we accidentally select the same stream
                if new_url == self.url:
                    logger.warning(f"Stream ID {stream_id} generates the same URL as current stream ({new_url}). "
                                 f"Skipping this stream and trying next alternative.")
                    continue  # Try next stream instead of giving up

                logger.info(f"Switching from URL {self.url} to {new_url} for channel {self.channel_id}")

                # IMPORTANT: Just update the URL, don't stop the channel or release resources
                switch_result = self.update_url(new_url, stream_id, profile_id)
                if not switch_result:
                    logger.error(f"Failed to update URL for stream ID {stream_id} for channel {self.channel_id}")
                    continue  # Try next stream

                # Update stream ID tracking
                self.current_stream_id = stream_id

                # Store the new user agent and transcode settings
                self.user_agent = new_user_agent
                self.transcode = new_transcode

                # Update stream metadata in Redis - use the profile_id we got from get_alternate_streams
                if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                    metadata_key = RedisKeys.channel_metadata(self.channel_id)
                    self.buffer.redis_client.hset(metadata_key, mapping={
                        ChannelMetadataField.URL: new_url,
                        ChannelMetadataField.USER_AGENT: new_user_agent,
                        ChannelMetadataField.STREAM_PROFILE: stream_info['stream_profile'],
                        ChannelMetadataField.M3U_PROFILE: str(profile_id),  # Use the profile_id from get_alternate_streams
                        ChannelMetadataField.STREAM_ID: str(stream_id),
                        ChannelMetadataField.STREAM_SWITCH_TIME: str(time.time()),
                        ChannelMetadataField.STREAM_SWITCH_REASON: "max_retries_exceeded"
                    })

                    # Log the switch
                    logger.info(f"Stream metadata updated for channel {self.channel_id} to stream ID {stream_id} with M3U profile {profile_id}")

                logger.info(f"Successfully switched to stream ID {stream_id} with URL {new_url} for channel {self.channel_id}")
                return True

            # If we get here, we tried all streams but none worked
            logger.error(f"Tried {len(untried_streams)} alternate streams but none were suitable for channel {self.channel_id}")
            return False

        except Exception as e:
            logger.error(f"Error trying next stream for channel {self.channel_id}: {e}", exc_info=True)
            return False

    # Add a new helper method to safely reset the URL switching state
    def _reset_url_switching_state(self):
        """Safely reset the URL switching state if it gets stuck"""
        self.url_switching = False
        self.url_switch_start_time = 0
        logger.info(f"Reset URL switching state for channel {self.channel_id}")