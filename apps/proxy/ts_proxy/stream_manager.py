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
from django.utils import timezone
from urllib.parse import urlparse, parse_qs
from urllib3.exceptions import ReadTimeoutError
from apps.proxy.config import TSConfig as Config
from apps.channels.models import Channel, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile, M3UAccountMac
from core.models import UserAgent, CoreSettings
from .stream_buffer import StreamBuffer
from .utils import detect_stream_type, get_logger
from .redis_keys import RedisKeys
from .constants import ChannelState, EventType, StreamType, ChannelMetadataField, TS_PACKET_SIZE
from .config_helper import ConfigHelper
from .url_utils import get_alternate_streams, get_stream_info_for_switch, get_stream_object, get_next_profiles_for_stream, get_stream_info_for_profile

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
        self.tried_profile_ids = set()

        # MAC tracking properties for failover (NEU)
        self.mac_address: Optional[str] = None
        self.mac_entry_id: Optional[int] = None

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

    # HILFSMETHODE: Zum Setzen von Metadaten in Redis (neu hinzugefügt)
    def _set_channel_metadata(self, field, value):
        """Helper to set a single metadata field in Redis."""
        if hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
            try:
                metadata_key = RedisKeys.channel_metadata(self.channel_id)
                self.buffer.redis_client.hset(metadata_key, field, str(value))
            except Exception as e:
                logger.error(f"Failed to set metadata field {field} in Redis: {e}", exc_info=True)

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
            pool_connections=1,      # Single connection for this stream
            pool_maxsize=1,          # Max size of connection pool
            max_retries=3,           # Auto-retry for failed requests
            pool_block=False         # Don't block when pool is full
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
                            # Mark MAC as busy in Redis once the stream is actually running
                            try:
                                if hasattr(self, 'buffer') and hasattr(self.buffer, 'redis_client') and self.buffer.redis_client:
                                    parsed = urlparse(self.url or '')
                                    qs = parse_qs(parsed.query or '')
                                    mac_vals = qs.get('mac') or qs.get('MAC') or []
                                    if mac_vals:
                                        mac_value = mac_vals[0]
                                        try:
                                            # WICHTIG: Verwenden Sie M3UAccountMac aus den Imports
                                            mac_entry = M3UAccountMac.objects.filter(address__iexact=mac_value).first()
                                        except Exception:
                                            mac_entry = None
                                        if mac_entry:
                                            busy_key = RedisKeys.mac_busy(mac_entry.id)
                                            self.buffer.redis_client.set(busy_key, '1')
                                            
                                            # Speichern der MAC-Informationen im Manager für Failover-Zwecke
                                            self.mac_address = mac_value
                                            self.mac_entry_id = mac_entry.id
                                            
                                            logger.debug(
                                                'Marked MAC %s (id=%s) as busy for channel %s',
                                                mac_value,
                                                mac_entry.id,
                                                self.channel_id,
                                            )
                            except Exception:
                                logger.debug(
                                    'Failed to set busy marker for current MAC on channel %s',
                                    self.channel_id,
                                    exc_info=True,
                                )


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
                        else:
                            # Wait with exponential backoff before retrying
                            timeout = min(.25 * self.retry_count, 3)  # Cap at 3 seconds
                            logger.info(f"Reconnecting in {timeout} seconds after error... (attempt {self.retry_count}/{self.max_retries}) for channel: {self.channel_id}")
                
                # If URL failed and we're still running, try MAC failover first (for MAC accounts), then profile/stream failover
                if url_failed and self.running:
                    # First, try to recover by switching to another MAC on the same account/profile (if applicable)
                    mac_switched = False
                    try:
                        mac_switched = self._try_next_mac() # HIER WIRD DIE NEUE METHODE AUFGERUFEN
                    except Exception:
                        logger.error("Error while attempting MAC-level failover on channel %s", self.channel_id, exc_info=True)
                        mac_switched = False
                    if mac_switched:
                        # Reset retry counter and continue outer loop with the new URL/MAC
                        self.retry_count = 0
                        url_failed = False
                        stream_switch_attempts += 1
                        logger.info(f"Successfully switched MAC for channel {self.channel_id}; continuing streaming")
                        continue
                    # MAC failover did not succeed or is not applicable -> fall back to profile/stream failover
                    self._set_profile_cooldown()
                    logger.info(f"URL {self.url} failed after {self.retry_count} attempts, trying next stream for channel: {self.channel_id}")

                    # Try to switch to next stream/profile
                    switch_result = self._try_next_stream()
                    if switch_result:
                        # Successfully switched to a new stream/profile, continue with the new URL
                        stream_switch_attempts += 1
                        logger.info(f"Successfully switched to new stream/profile (attempt {stream_switch_attempts}/{max_stream_switches}) for channel: {self.channel_id}")
                        # Reset retry count for the new stream - important for the loop to work correctly
                        self.retry_count = 0
                        # Continue outer loop with new URL - DON'T add a break statement here
                    else:
                        # No more streams to try
                        logger.error(f"Failed to find alternative stream/profile after {stream_switch_attempts} attempts for channel: {self.channel_id}")
                        break
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

    # NEUE METHODE: Versuch, zur nächsten MAC-Adresse zu wechseln
    def _try_next_mac(self) -> bool:
        """
        Attempt to switch to another MAC address on the same account/profile.
        Integrates MAC cooldown logic (6h in Redis) and respects mac_busy status.

        Returns:
            bool: True on successful MAC switch, False otherwise
        """
        # 1. MAC-Wert ermitteln: Zuerst von der Instanz-Eigenschaft, dann von der URL.
        current_mac_value = getattr(self, 'mac_address', None)
        
        if not current_mac_value:
             # Fallback: Extrahiere MAC aus der URL (falls noch nicht in der Eigenschaft gespeichert)
             parsed = urlparse(self.url or '')
             qs = parse_qs(parsed.query or '')
             mac_vals = qs.get('mac') or qs.get('MAC') or []
             if mac_vals:
                 current_mac_value = mac_vals[0]
                 
        if not current_mac_value:
            logger.debug("No MAC address found in current stream URL for channel %s. Cannot perform MAC failover.", self.channel_id)
            return False

        try:
            # Holen Sie sich das M3U-Konto, das diesen Kanal verwendet.
            m3u_account = M3UAccount.objects.select_related("profile").filter(
                channels__id=self.channel_id
            ).first()
        except Exception as e:
            logger.error(
                "Failed to get M3U account for channel %s during MAC failover: %s",
                self.channel_id,
                e,
                exc_info=True,
            )
            return False

        if not m3u_account or not m3u_account.profile:
            return False

        mac_entry = None
        try:
            # Finde den Datenbank-Eintrag für die fehlerhafte MAC-Adresse
            mac_entry = m3u_account.macs.filter(address__iexact=current_mac_value).first()
        except Exception:
            pass 

        # Redis Client aus dem Buffer holen
        redis_client = getattr(self.buffer, 'redis_client', None)

        # ----------------------------------------------------------------------
        # MAC Cooldown setzen und Busy-Flag löschen (für die fehlerhafte MAC)
        # ----------------------------------------------------------------------
        
        if mac_entry and redis_client:
            COOLDOWN_DURATION = 6 * 3600  # 6 Stunden Cooldown
            
            # 1. MAC temporär in Cooldown setzen (in Redis)
            try:
                mac_cooldown_key = RedisKeys.mac_cooldown(mac_entry.id)
                redis_client.setex(mac_cooldown_key, COOLDOWN_DURATION, "1")

                logger.warning(
                    "Put failed MAC %s (ID: %s) on %dh cooldown due to runtime failure on channel %s.",
                    current_mac_value,
                    mac_entry.id,
                    COOLDOWN_DURATION // 3600,
                    self.channel_id,
                )
            except Exception:
                logger.warning(
                    "Failed to set MAC Cooldown in Redis for MAC %s",
                    current_mac_value,
                    exc_info=True,
                )

            # 2. Busy-Markierung löschen (Aufräumschritt)
            try:
                busy_key = RedisKeys.mac_busy(mac_entry.id)
                redis_client.delete(busy_key)
                logger.debug(
                    "Cleared busy marker for failed MAC %s (id=%s) on account %s",
                    current_mac_value,
                    mac_entry.id,
                    m3u_account.id,
                )
            except Exception:
                logger.debug(
                    "Failed to clear busy marker for MAC %s",
                    current_mac_value,
                    exc_info=True,
                )
        elif not mac_entry:
            logger.debug(
                "Could not find M3UAccountMac entry for MAC %s to apply cooldown.",
                current_mac_value,
            )
        elif not redis_client:
            logger.warning(
                "No Redis client available. Could not set cooldown or clear busy key for MAC %s.",
                current_mac_value,
            )
        
        # ----------------------------------------------------------------------
        # Auswahl der nächsten MAC (mit Cooldown- und Busy-Prüfung)
        # ----------------------------------------------------------------------

        try:
            # 1. Alle aktiven MACs abrufen (aus der Datenbank)
            macs = m3u_account.macs.filter(
                status=M3UAccountMac.Status.ACTIVE
            ).order_by("last_checked")
        except Exception:
            logger.error("Failed to query next MACs for account %s", m3u_account.id)
            return False

        if not macs:
            logger.warning(
                "No ACTIVE MACs found for account %s to switch to.",
                m3u_account.id,
            )
            return False

        next_mac_entry = None
        for mac in macs:
            # Überspringen Sie die gerade fehlerhafte MAC
            if str(mac.address).upper() == current_mac_value.upper():
                continue
            
            if redis_client:
                # Cooldown-Prüfung
                cooldown_key = RedisKeys.mac_cooldown(mac.id)
                if redis_client.exists(cooldown_key):
                    logger.debug(
                        "MAC %s (ID: %s) is currently in cooldown in Redis. Skipping.",
                        mac.address,
                        mac.id,
                    )
                    continue
            
                # Busy-Prüfung (Wird von einem anderen StreamManager verwendet?)
                busy_key = RedisKeys.mac_busy(mac.id)
                if redis_client.exists(busy_key):
                    logger.debug(
                        "MAC %s (ID: %s) is currently busy in Redis. Skipping.",
                        mac.address,
                        mac.id,
                    )
                    continue

            # Diese MAC ist verfügbar
            next_mac_entry = mac
            break
        
        if not next_mac_entry:
            logger.warning(
                "All remaining ACTIVE MACs for account %s are either busy or in COOLDOWN.",
                m3u_account.id,
            )
            return False
            
        # Nächste MAC gefunden, URL und Metadaten aktualisieren
        self.mac_address = next_mac_entry.address
        self.mac_entry_id = next_mac_entry.id
        # Ersetzen Sie die alte MAC in der URL durch die neue MAC
        self.url = re.sub(
            r"([?&](mac|MAC)=)" + re.escape(current_mac_value),
            r"\1" + self.mac_address,
            self.url,
            flags=re.IGNORECASE,
        )
        
        # Setzen der neuen MAC in den Metadaten
        try:
            self._set_channel_metadata(ChannelMetadataField.M3U_MAC, self.mac_address)
            self._set_channel_metadata(ChannelMetadataField.M3U_MAC_ID, self.mac_entry_id)
        except Exception:
            logger.error("Failed to set new MAC metadata.")

        logger.warning(
            "Successfully switched from MAC %s to MAC %s for account %s on channel %s",
            current_mac_value,
            self.mac_address,
            m3u_account.id,
            self.channel_id,
        )
        return True

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
                bufsize=188 * 64         # Buffer optimized for TS packets
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
        # ... (rest of _read_stderr is assumed to be here, but cut off in the prompt)
