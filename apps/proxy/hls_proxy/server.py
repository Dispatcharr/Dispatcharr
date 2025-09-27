"""
HLS Proxy Server with Advanced Stream Switching Support
This proxy handles HLS live streams with support for:
- Stream switching with proper discontinuity handling
- Buffer management
- Segment validation
- Connection pooling and reuse
"""

import requests
import threading
import logging
import m3u8
import time
from urllib.parse import urlparse, urljoin
import argparse
from typing import Optional, Dict, List, Set, Deque
import sys
import os
from apps.proxy.config import HLSConfig as Config

# Global state management
manifest_buffer = None  # Stores current manifest content
segment_buffers = {}   # Maps sequence numbers to segment data
buffer_lock = threading.Lock()  # Synchronizes access to buffers

class StreamBuffer:
    """
    Manages buffering of stream segments with thread-safe access.
    
    Attributes:
        buffer (Dict[int, bytes]): Maps sequence numbers to segment data
        lock (threading.Lock): Thread safety for buffer access
        
    Features:
        - Thread-safe segment storage and retrieval
        - Automatic cleanup of old segments
        - Sequence number based indexing
    """
    
    def __init__(self):
        self.buffer: Dict[int, bytes] = {}  # Maps sequence numbers to segment data
        self.lock: threading.Lock = threading.Lock()

    def __getitem__(self, key: int) -> Optional[bytes]:
        """Get segment data by sequence number"""
        return self.buffer.get(key)

    def __setitem__(self, key: int, value: bytes):
        """Store segment data by sequence number"""
        self.buffer[key] = value
        # Cleanup old segments if we exceed MAX_SEGMENTS
        if len(self.buffer) > Config.MAX_SEGMENTS:
            keys = sorted(self.buffer.keys())
            # Keep the most recent MAX_SEGMENTS
            to_remove = keys[:-Config.MAX_SEGMENTS]
            for k in to_remove:
                del self.buffer[k]

    def __contains__(self, key: int) -> bool:
        """Check if sequence number exists in buffer"""
        return key in self.buffer

    def keys(self) -> List[int]:
        """Get list of available sequence numbers"""
        return list(self.buffer.keys())

    def cleanup(self, keep_sequences: List[int]):
        """Remove segments not in keep list"""
        for seq in list(self.buffer.keys()):
            if seq not in keep_sequences:
                del self.buffer[seq]

class ClientManager:
    """Manages client connections and activity tracking"""
    
    def __init__(self):
        self.last_activity = {}  # Maps client IPs to last activity timestamp
        self.lock = threading.Lock()
        
    def record_activity(self, client_ip: str):
        """Record client activity timestamp"""
        with self.lock:
            prev_time = self.last_activity.get(client_ip)
            current_time = time.time()
            self.last_activity[client_ip] = current_time
            if not prev_time:
                logging.info(f"New client connected: {client_ip}")
            else:
                logging.debug(f"Client activity: {client_ip}")
                
    def cleanup_inactive(self, timeout: float) -> bool:
        """Remove inactive clients"""
        now = time.time()
        with self.lock:
            active_clients = {
                ip: last_time 
                for ip, last_time in self.last_activity.items()
                if (now - last_time) < timeout
            }
            
            removed = set(self.last_activity.keys()) - set(active_clients.keys())
            if removed:
                for ip in removed:
                    inactive_time = now - self.last_activity[ip]
                    logging.warning(f"Client {ip} inactive for {inactive_time:.1f}s, removing")
            
            self.last_activity = active_clients
            if active_clients:
                oldest = min(now - t for t in active_clients.values())
                logging.debug(f"Active clients: {len(active_clients)}, oldest activity: {oldest:.1f}s ago")
            
            return len(active_clients) == 0

class StreamManager:
    """
    Manages HLS stream state and switching logic.
    
    Attributes:
        current_url (str): Current stream URL
        channel_id (str): Unique channel identifier
        running (bool): Stream activity flag
        next_sequence (int): Next sequence number to assign
        buffered_sequences (set): Currently buffered sequence numbers
        source_changes (set): Sequences where stream source changed
        
    Features:
        - Stream URL management
        - Sequence number assignment
        - Discontinuity tracking
        - Thread coordination
        - Buffer state management
    """
    def __init__(self, initial_url: str, channel_id: str, user_agent: Optional[str] = None):
        # Stream state
        self.current_url = initial_url
        self.channel_id = channel_id
        self.user_agent = user_agent or Config.DEFAULT_USER_AGENT
        self.running = True
        self.switching_stream = False
        
        # Sequence tracking
        self.next_sequence = 0
        self.highest_sequence = 0
        self.buffered_sequences = set()
        self.downloaded_sources = {}
        self.segment_durations = {}
        
        # Source tracking
        self.current_source = None
        self.source_changes = set()
        self.stream_switch_count = 0
        
        # Threading
        self.fetcher = None
        self.fetch_thread = None
        self.url_changed = threading.Event()
        
        # Add manifest info
        self.target_duration = 10.0  # Default, will be updated from manifest
        self.manifest_version = 3    # Default, will be updated from manifest
        
        self.cleanup_thread = None
        self.cleanup_running = False  # New flag to control cleanup thread
        self.cleanup_enabled = False  # New flag to control when cleanup starts
        self.initialization_time = time.time()  # Add initialization timestamp
        self.first_client_connected = False
        self.cleanup_started = False  # New flag to track cleanup state

        # Add client manager reference
        self.client_manager = None
        self.proxy_server = None  # Reference to proxy server for cleanup
        self.cleanup_thread = None
        self.cleanup_interval = Config.CLIENT_CLEANUP_INTERVAL
        
        logging.info(f"Initialized stream manager for channel {channel_id}")

        # Buffer state tracking
        self.buffer_ready = threading.Event()
        self.buffered_duration = 0.0
        self.initial_buffering = True

    def update_url(self, new_url: str) -> bool:
        """
        Handle stream URL changes with proper discontinuity marking.
        
        Args:
            new_url: New stream URL to switch to
            
        Returns:
            bool: True if URL changed, False if unchanged
            
        Side effects:
            - Sets switching_stream flag
            - Updates current_url
            - Maintains sequence numbering
            - Marks discontinuity point
            - Signals fetch thread
        """
        if new_url != self.current_url:
            with buffer_lock:
                self.switching_stream = True
                self.current_url = new_url
                
                # Continue sequence numbering from last sequence
                if self.buffered_sequences:
                    self.next_sequence = max(self.buffered_sequences) + 1
                
                # Mark discontinuity at next sequence
                self.source_changes.add(self.next_sequence)
                
                logging.info(f"Stream switch - next sequence will start at {self.next_sequence}")
                
                # Clear state but maintain sequence numbers
                self.downloaded_sources.clear()
                self.segment_durations.clear()
                self.current_source = None
                
                # Signal thread to switch URL
                self.url_changed.set()
                
            return True
        return False

    def get_next_sequence(self, source_id: str) -> Optional[int]:
        """
        Assign sequence numbers to segments with source change detection.
        
        Args:
            source_id: Unique identifier for segment source
            
        Returns:
            int: Next available sequence number
            None: If segment already downloaded
            
        Side effects:
            - Updates buffered sequences set
            - Tracks source changes for discontinuity
            - Maintains sequence numbering
        """
        if source_id in self.downloaded_sources:
            return None
            
        seq = self.next_sequence
        while (seq in self.buffered_sequences):
            seq += 1
        
        # Track source changes for discontinuity markers
        source_prefix = source_id.split('_')[0]
        if not self.switching_stream and self.current_source and self.current_source != source_prefix:
            self.source_changes.add(seq)
            logging.debug(f"Source change detected at sequence {seq}")
        self.current_source = source_prefix
            
        # Update tracking
        self.downloaded_sources[source_id] = seq
        self.buffered_sequences.add(seq)
        self.next_sequence = seq + 1
        self.highest_sequence = max(self.highest_sequence, seq)
        
        return seq

    def _fetch_loop(self):
        """Background thread for continuous stream fetching"""
        while self.running:
            try:
                fetcher = StreamFetcher(self, self.buffer)
                fetch_stream(fetcher, self.url_changed, self.next_sequence)
            except Exception as e:
                logging.error(f"Stream error: {e}")
                time.sleep(5)  # Wait before retry
            
            self.url_changed.clear()

    def start(self):
        """Start the background fetch thread"""
        if not self.fetch_thread or not self.fetch_thread.is_alive():
            self.running = True
            self.fetch_thread = threading.Thread(
                target=self._fetch_loop,
                name="StreamFetcher",
                daemon=True  # Thread will exit when main program does
            )
            self.fetch_thread.start()
            logging.info("Stream manager started")

    def stop(self):
        """Stop the stream manager and cleanup resources"""
        self.running = False
        self.cleanup_running = False
        if self.fetch_thread and self.fetch_thread.is_alive():
            self.url_changed.set()
            self.fetch_thread.join(timeout=5)
        logging.info(f"Stream manager stopped for channel {self.channel_id}")

    def enable_cleanup(self):
        """Enable cleanup after first client connects"""
        if not self.first_client_connected:
            self.first_client_connected = True
            logging.info(f"First client connected to channel {self.channel_id}")

    def start_cleanup_thread(self):
        """Start background thread for client activity monitoring"""
        def cleanup_loop():
            # Wait for initial connection window
            start_time = time.time()
            while self.cleanup_running and (time.time() - start_time) < Config.INITIAL_CONNECTION_WINDOW:
                if self.first_client_connected:
                    break
                time.sleep(1)
                
            if not self.first_client_connected:
                logging.info(f"Channel {self.channel_id}: No clients connected within {Config.INITIAL_CONNECTION_WINDOW}s window")
                self.proxy_server.stop_channel(self.channel_id)
                return
                
            # Normal client activity monitoring
            while self.cleanup_running and self.running:
                try:
                    timeout = self.target_duration * Config.CLIENT_TIMEOUT_FACTOR
                    if self.client_manager.cleanup_inactive(timeout):
                        logging.info(f"Channel {self.channel_id}: All clients disconnected for {timeout:.1f}s")
                        self.proxy_server.stop_channel(self.channel_id)
                        break
                except Exception as e:
                    logging.error(f"Cleanup error: {e}")
                    if "cannot join current thread" not in str(e):
                        time.sleep(Config.CLIENT_CLEANUP_INTERVAL)
                time.sleep(Config.CLIENT_CLEANUP_INTERVAL)

        if not self.cleanup_started:
            self.cleanup_started = True
            self.cleanup_running = True
            self.cleanup_thread = threading.Thread(
                target=cleanup_loop,
                name=f"Cleanup-{self.channel_id}",
                daemon=True
            )
            self.cleanup_thread.start()
            logging.info(f"Started cleanup thread for channel {self.channel_id}")

class StreamFetcher:
    """
    Handles HTTP requests for stream segments with connection pooling.
    
    Attributes:
        manager (StreamManager): Associated stream manager instance
        buffer (StreamBuffer): Buffer for storing segments
        session (requests.Session): Persistent HTTP session
        redirect_cache (dict): Cache for redirect responses
        
    Features:
        - Connection pooling and reuse
        - Redirect caching
        - Rate limiting
        - Automatic retries
        - Host fallback
    """
    def __init__(self, manager: StreamManager, buffer: StreamBuffer):
        self.manager = manager
        self.buffer = buffer
        self.stream_url = manager.current_url
        self.session = requests.Session()
        
        # Configure session headers
        self.session.headers.update({
            'User-Agent': manager.user_agent,
            'Connection': 'keep-alive'
        })
        
        # Set up connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=2,    # Number of connection pools
            pool_maxsize=4,       # Connections per pool
            max_retries=3,        # Auto-retry failed requests
            pool_block=False      # Don't block when pool is full
        )
        
        # Apply adapter to both HTTP and HTTPS
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Request optimization
        self.last_request_time = 0
        self.min_request_interval = 0.05  # Minimum time between requests
        self.last_host = None            # Cache last successful host
        self.redirect_cache = {}         # Cache redirect responses
        self.redirect_cache_limit = 1000
        
    def cleanup_redirect_cache(self):
        """Remove old redirect cache entries"""
        if len(self.redirect_cache) > self.redirect_cache_limit:
            self.redirect_cache.clear()

    def get_base_host(self, url: str) -> str:
        """
        Extract base host from URL.
        
        Args:
            url: Full URL to parse
            
        Returns:
            str: Base host in format 'scheme://hostname'
            
        Example:
            'http://example.com/path' -> 'http://example.com'
        """
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception as e:
            logging.error(f"Error extracting base host: {e}")
            return url
    
    def download(self, url: str) -> tuple[bytes, str]:
        """
        Download content with connection reuse and redirect handling.
        
        Args:
            url: URL to download from
            
        Returns:
            tuple containing:
                bytes: Downloaded content
                str: Final URL after any redirects
                
        Features:
            - Connection pooling/reuse
            - Redirect caching
            - Rate limiting
            - Host fallback on failure
            - Automatic retries
        """
        now = time.time()
        wait_time = self.last_request_time + self.min_request_interval - now
        if (wait_time > 0):
            time.sleep(wait_time)
            
        try:
            # Use cached redirect if available
            if url in self.redirect_cache:
                logging.debug(f"Using cached redirect for {url}")
                final_url = self.redirect_cache[url]
                response = self.session.get(final_url, timeout=10)
            else:
                response = self.session.get(url, allow_redirects=True, timeout=10)
                if response.history:  # Cache redirects
                    logging.debug(f"Caching redirect for {url} -> {response.url}")
                    self.redirect_cache[url] = response.url
                    
            self.last_request_time = time.time()
            
            if response.status_code == 200:
                self.last_host = self.get_base_host(response.url)
            
            return response.content, response.url
            
        except Exception as e:
            logging.error(f"Download error: {e}")
            if self.last_host and not url.startswith(self.last_host):
                # Use urljoin to handle path resolution
                new_url = urljoin(self.last_host + '/', url.split('://')[-1].split('/', 1)[-1])
                logging.debug(f"Retrying with last host: {new_url}")
                return self.download(new_url)
            raise

    def fetch_loop(self):
        """Main fetch loop for stream data"""
        retry_delay = 1
        max_retry_delay = 8
        last_manifest_time = 0
        downloaded_segments = set()  # Track downloaded segment URIs

        while self.manager.running:
            try:
                current_time = time.time()
                
                # Check manifest update timing
                if last_manifest_time:
                    time_since_last = current_time - last_manifest_time
                    if time_since_last < (self.manager.target_duration * 0.5):
                        time.sleep(self.manager.target_duration * 0.5 - time_since_last)
                        continue

                # Get manifest data
                manifest_data, final_url = self.download(self.manager.current_url)
                manifest = m3u8.loads(manifest_data.decode())
                
                # Update manifest info
                if manifest.target_duration:
                    self.manager.target_duration = float(manifest.target_duration)
                if manifest.version:
                    self.manager.manifest_version = manifest.version

                if not manifest.segments:
                    continue

                if self.manager.initial_buffering:
                    segments_to_fetch = []
                    current_duration = 0.0
                    successful_downloads = 0  # Initialize counter here
                    
                    # Start from the end of the manifest
                    for segment in reversed(manifest.segments):
                        current_duration += float(segment.duration)
                        segments_to_fetch.append(segment)
                        
                        # Stop when we have enough duration or hit max segments
                        if (current_duration >= Config.INITIAL_BUFFER_SECONDS or 
                            len(segments_to_fetch) >= Config.MAX_INITIAL_SEGMENTS):
                            break
                    
                    # Reverse back to chronological order
                    segments_to_fetch.reverse()
                    
                    # Download initial segments
                    for segment in segments_to_fetch:
                        try:
                            segment_url = urljoin(final_url, segment.uri)
                            segment_data, _ = self.download(segment_url)
                            
                            validation = verify_segment(segment_data)
                            if validation.get('valid', False):
                                with self.buffer.lock:
                                    seq = self.manager.next_sequence
                                    self.buffer[seq] = segment_data
                                    duration = float(segment.duration)
                                    self.manager.segment_durations[seq] = duration
                                    self.manager.buffered_duration += duration
                                    self.manager.next_sequence += 1
                                    successful_downloads += 1
                                    logging.debug(f"Buffered initial segment {seq} (source: {segment.uri}, duration: {duration}s)")
                        except Exception as e:
                            logging.error(f"Initial segment download error: {e}")
                    
                    # Only mark buffer ready if we got some segments
                    if successful_downloads > 0:
                        self.manager.initial_buffering = False
                        self.manager.buffer_ready.set()
                        logging.info(f"Initial buffer ready with {successful_downloads} segments "
                                   f"({self.manager.buffered_duration:.1f}s of content)")
                    continue

                # Normal operation - get latest segment if we haven't already
                latest_segment = manifest.segments[-1]
                if (latest_segment.uri in downloaded_segments):
                    # Wait for next manifest update
                    time.sleep(self.manager.target_duration * 0.5)
                    continue

                try:
                    segment_url = urljoin(final_url, latest_segment.uri)
                    segment_data, _ = self.download(segment_url)
                    
                    # Try several times if segment validation fails
                    max_retries = 3
                    retry_count = 0
                    while retry_count < max_retries:
                        verification = verify_segment(segment_data)
                        if verification.get('valid', False):
                            break
                        logging.warning(f"Invalid segment, retry {retry_count + 1}/{max_retries}: {verification.get('error')}")
                        time.sleep(0.5)  # Short delay before retry
                        segment_data, _ = self.download(segment_url)
                        retry_count += 1

                    if verification.get('valid', False):
                        with self.buffer.lock:
                            seq = self.manager.next_sequence
                            self.buffer[seq] = segment_data
                            self.manager.segment_durations[seq] = float(latest_segment.duration)
                            self.manager.next_sequence += 1
                            downloaded_segments.add(latest_segment.uri)
                            logging.debug(f"Stored segment {seq} (source: {latest_segment.uri}, "
                                       f"duration: {latest_segment.duration}s, "
                                       f"size: {len(segment_data)})")

                        # Update timing
                        last_manifest_time = time.time()
                        retry_delay = 1  # Reset retry delay on success
                    else:
                        logging.error(f"Segment validation failed after {max_retries} retries")

                except Exception as e:
                    logging.error(f"Segment download error: {e}")
                    continue

                # Cleanup old segment URIs from tracking
                if len(downloaded_segments) > 100:
                    downloaded_segments.clear()

            except Exception as e:
                logging.error(f"Fetch error: {e}")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

def get_segment_sequence(segment_uri: str) -> Optional[int]:
    """
    Extract sequence number from segment URI pattern.
    
    Args:
        segment_uri: Segment filename or path
        
    Returns:
        int: Extracted sequence number if found
        None: If no valid sequence number can be extracted
        
    Handles common patterns like:
    - Numerical sequences (e.g., segment_1234.ts)
    - Complex patterns with stream IDs (e.g., stream_123_456.ts)
    """

    try:
        # Try numerical sequence (e.g., 1038_3693.ts)
        if '_' in segment_uri:
            return int(segment_uri.split('_')[-1].split('.')[0])
        return None
    except ValueError:
        return None

# Update verify_segment with more thorough checks
def verify_segment(data: bytes) -> dict:
    """
    Verify MPEG-TS segment integrity and structure.
    
    Args:
        data: Raw segment data bytes
        
    Returns:
        dict containing:
            valid (bool): True if segment passes all checks
            packets (int): Number of valid packets found
            size (int): Total segment size in bytes
            error (str): Description if validation fails
            
    Checks:
    - Minimum size requirements
    - Packet size alignment
    - Sync byte presence
    - Transport error indicators
    """

    # Check minimum size
    if len(data) < 188:
        return {'valid': False, 'error': 'Segment too short'}
        
    # Verify segment size is multiple of packet size
    if len(data) % 188 != 0:
        return {'valid': False, 'error': 'Invalid segment size'}
    
    valid_packets = 0
    total_packets = len(data) // 188
    
    # Scan all packets in segment
    for i in range(0, len(data), 188):
        packet = data[i:i+188]
        
        # Check packet completeness
        if len(packet) != 188:
            return {'valid': False, 'error': 'Incomplete packet'}
            
        # Verify sync byte
        if packet[0] != 0x47:
            return {'valid': False, 'error': f'Invalid sync byte at offset {i}'}
            
        # Check transport error indicator
        if packet[1] & 0x80:
            return {'valid': False, 'error': 'Transport error indicator set'}
            
        valid_packets += 1
    
    return {
        'valid': True,
        'packets': valid_packets,
        'size': len(data)
    }

def fetch_stream(fetcher: StreamFetcher, stop_event: threading.Event, start_sequence: int = 0):
    """
    Main streaming function that handles manifest updates and segment downloads.
    
    Args:
        fetcher: StreamFetcher instance to handle HTTP requests
        stop_event: Threading event to signal when to stop fetching
        start_sequence: Initial sequence number to start from
        
    The function implements the core HLS fetching logic:
    - Fetches and parses manifest files
    - Downloads new segments when they become available
    - Handles stream switches with proper discontinuity marking
    - Maintains buffer state and segment sequence numbering
    """
    # Remove global stream_manager reference
    retry_delay = 1
    max_retry_delay = 8
    last_segment_time = 0
    buffer_initialized = False
    manifest_update_needed = True
    segment_duration = None

    while not stop_event.is_set():
        try:
            now = time.time()
            
            # Only update manifest when it's time for next segment
            should_update = (
                manifest_update_needed or 
                not segment_duration or 
                (last_segment_time and (now - last_segment_time) >= segment_duration * 0.8)
            )
            
            if should_update:
                manifest_data, final_url = fetcher.download(fetcher.stream_url)
                manifest = m3u8.loads(manifest_data.decode())
                
                if not manifest.segments:
                    continue
                
                with buffer_lock:
                    manifest_content = manifest_data.decode()
                    new_segments = {}
                    
                    if fetcher.manager.switching_stream:  # Use fetcher.manager instead of stream_manager
                        # Stream switch - only get latest segment
                        manifest_segments = [manifest.segments[-1]]
                        seq_start = fetcher.manager.next_sequence
                        max_segments = 1
                        logging.debug(f"Processing stream switch - getting latest segment at sequence {seq_start}")
                    elif not buffer_initialized:
                        # Initial buffer
                        manifest_segments = manifest.segments[-Config.INITIAL_SEGMENTS:]
                        seq_start = fetcher.manager.next_sequence
                        max_segments = Config.INITIAL_SEGMENTS
                        logging.debug(f"Starting initial buffer at sequence {seq_start}")
                    else:
                        # Normal operation
                        manifest_segments = [manifest.segments[-1]]
                        seq_start = fetcher.manager.next_sequence
                        max_segments = 1

                    # Map segments
                    segments_mapped = 0
                    for segment in manifest_segments:
                        if segments_mapped >= max_segments:
                            break
                            
                        source_id = segment.uri.split('/')[-1].split('.')[0]
                        next_seq = fetcher.manager.get_next_sequence(source_id)
                        
                        if next_seq is not None:
                            duration = float(segment.duration)
                            new_segments[next_seq] = {
                                'uri': segment.uri,
                                'duration': duration,
                                'source_id': source_id
                            }
                            fetcher.manager.segment_durations[next_seq] = duration
                            segments_mapped += 1
                    
                    manifest_buffer = manifest_content

                # Download segments
                for sequence_id, segment_info in new_segments.items():
                    try:
                        segment_url = f"{fetcher.last_host}{segment_info['uri']}"
                        logging.debug(f"Downloading {segment_info['uri']} as segment {sequence_id}.ts "
                                   f"(source: {segment_info['source_id']}, duration: {segment_info['duration']:.3f}s)")
                        
                        segment_data, _ = fetcher.download(segment_url)
                        validation = verify_segment(segment_data)
                        
                        if validation.get('valid', False):
                            with buffer_lock:
                                segment_buffers[sequence_id] = segment_data
                                logging.debug(f"Downloaded and verified segment {sequence_id} (packets: {validation['packets']})")
                                
                                if fetcher.manager.switching_stream:
                                    fetcher.manager.switching_stream = False
                                    stop_event.set()  # Force fetcher restart with new URL
                                    break
                                elif not buffer_initialized and len(segment_buffers) >= Config.INITIAL_SEGMENTS:
                                    buffer_initialized = True
                                    manifest_update_needed = True
                                    break
                    except Exception as e:
                        logging.error(f"Segment download error: {e}")
                        continue

            else:
                # Short sleep to prevent CPU spinning
                threading.Event().wait(0.1)

        except Exception as e:
            logging.error(f"Manifest error: {e}")
            threading.Event().wait(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)
            manifest_update_needed = True

class ProxyServer:
    """Manages HLS proxy server instance"""
    
    def __init__(self, user_agent: Optional[str] = None):
        self.stream_managers: Dict[str, StreamManager] = {}
        self.stream_buffers: Dict[str, StreamBuffer] = {}
        self.client_managers: Dict[str, ClientManager] = {}
        self.fetch_threads: Dict[str, threading.Thread] = {}
        self.user_agent: str = user_agent or Config.DEFAULT_USER_AGENT

    def initialize_channel(self, url: str, channel_id: str) -> None:
        """Initialize a new channel stream"""
        if channel_id in self.stream_managers:
            self.stop_channel(channel_id)
            
        self.stream_managers[channel_id] = StreamManager(
            url, 
            channel_id,
            user_agent=self.user_agent
        )
        self.stream_buffers[channel_id] = StreamBuffer()
        self.client_managers[channel_id] = ClientManager()
        
        # Set up cleanup references
        self.stream_managers[channel_id].client_manager = self.client_managers[channel_id]
        self.stream_managers[channel_id].proxy_server = self
        
        fetcher = StreamFetcher(
            self.stream_managers[channel_id], 
            self.stream_buffers[channel_id]
        )
        
        self.fetch_threads[channel_id] = threading.Thread(
            target=fetcher.fetch_loop,
            name=f"StreamFetcher-{channel_id}",
            daemon=True
        )
        self.fetch_threads[channel_id].start()
        
        # Start cleanup monitoring
        self.stream_managers[channel_id].start_cleanup_thread()
        logging.info(f"Initialized channel {channel_id} with URL {url}")

    def stop_channel(self, channel_id: str) -> None:
        """Stop and cleanup a channel"""
        if channel_id in self.stream_managers:
            logging.info(f"Stopping channel {channel_id}")
            try:
                # Stop the stream manager
                self.stream_managers[channel_id].stop()
                
                # Wait for fetch thread to finish
                if channel_id in self.fetch_threads:
                    self.fetch_threads[channel_id].join(timeout=5)
                    if self.fetch_threads[channel_id].is_alive():
                        logging.warning(f"Fetch thread for channel {channel_id} did not stop cleanly")
            except Exception as e:
                logging.error(f"Error stopping channel {channel_id}: {e}")
            finally:
                self._cleanup_channel(channel_id)

    def _cleanup_channel(self, channel_id: str) -> None:
        """Remove channel resources"""
        for collection in [self.stream_managers, self.stream_buffers, 
                         self.client_managers, self.fetch_threads]:
            collection.pop(channel_id, None)

    def shutdown(self) -> None:
        """Stop all channels and cleanup"""
        for channel_id in list(self.stream_managers.keys()):
            self.stop_channel(channel_id)

    # Remove Flask-specific routing
    def _setup_routes(self) -> None:
        pass

    # Update methods to return data instead of Flask Response objects
    def stream_endpoint(self, channel_id: str):
        if channel_id not in self.stream_managers:
            return 'Channel not found', 404
            
        manager = self.stream_managers[channel_id]
        
        # Wait for initial buffer
        if not manager.buffer_ready.wait(Config.BUFFER_READY_TIMEOUT):
            logging.error(f"Timeout waiting for initial buffer for channel {channel_id}")
            return 'Initial buffer not ready', 503
        
        try:
            if (channel_id not in self.stream_managers) or (not self.stream_managers[channel_id].running):
                return 'Channel not found', 404
            
            manager = self.stream_managers[channel_id]
            buffer = self.stream_buffers[channel_id]
            
            # Record client activity and enable cleanup
            client_ip = request.remote_addr
            manager.enable_cleanup()
            self.client_managers[channel_id].record_activity(client_ip)
            
            # Wait for first segment with timeout
            start_time = time.time()
            while True:
                with buffer.lock:
                    available = sorted(buffer.keys())
                    if available:
                        break
                    
                if time.time() - start_time > Config.FIRST_SEGMENT_TIMEOUT:
                    logging.warning(f"Timeout waiting for first segment for channel {channel_id}")
                    return 'No segments available', 503
                    
                time.sleep(0.1)  # Short sleep to prevent CPU spinning
            
            # Rest of manifest generation code...
            with buffer.lock:
                max_seq = max(available)
                # Find the first segment after any discontinuity
                discontinuity_start = min(available)
                for seq in available:
                    if seq in manager.source_changes:
                        discontinuity_start = seq
                        break
                
                # Calculate window bounds starting from discontinuity
                if len(available) <= Config.INITIAL_SEGMENTS:
                    min_seq = discontinuity_start
                else:
                    min_seq = max(
                        discontinuity_start,
                        max_seq - Config.WINDOW_SIZE + 1
                    )
                
                # Build manifest with proper tags
                new_manifest = ['#EXTM3U']
                new_manifest.append(f'#EXT-X-VERSION:{manager.manifest_version}')
                new_manifest.append(f'#EXT-X-MEDIA-SEQUENCE:{min_seq}')
                new_manifest.append(f'#EXT-X-TARGETDURATION:{int(manager.target_duration)}')
                
                # Filter segments within window
                window_segments = [s for s in available if min_seq <= s <= max_seq]
                
                # Add segments with discontinuity handling
                for seq in window_segments:
                    if seq in manager.source_changes:
                        new_manifest.append('#EXT-X-DISCONTINUITY')
                        logging.debug(f"Added discontinuity marker before segment {seq}")
                    
                    duration = manager.segment_durations.get(seq, 10.0)
                    new_manifest.append(f'#EXTINF:{duration},')
                    new_manifest.append(f'/stream/{channel_id}/segments/{seq}.ts')
                
                manifest_content = '\n'.join(new_manifest)
                logging.debug(f"Serving manifest with segments {min_seq}-{max_seq} (window: {len(window_segments)})")
                return manifest_content, 200  # Return content and status code
        except ConnectionAbortedError:
            logging.debug("Client disconnected")
            return '', 499
        except Exception as e:
            logging.error(f"Stream endpoint error: {e}")
            return '', 500

    def get_segment(self, channel_id: str, segment_name: str):
        """
        Serve individual MPEG-TS segments to clients.
        
        Args:
            channel_id: Unique identifier for the channel
            segment_name: Segment filename (e.g., '123.ts')
            
        Returns:
            Flask Response:
                - MPEG-TS segment data with video/MP2T content type
                - 404 if segment or channel not found
                
        Error Handling:
            - Logs warning if segment not found
            - Logs error on unexpected exceptions
            - Returns 404 on any error
        """
        if channel_id not in self.stream_managers:
            return 'Channel not found', 404
            
        try:
            # Record client activity
            client_ip = request.remote_addr
            self.client_managers[channel_id].record_activity(client_ip)
            
            segment_id = int(segment_name.split('.')[0])
            buffer = self.stream_buffers[channel_id]
            
            with buffer_lock:
                if segment_id in buffer:
                    return buffer[segment_id], 200  # Return content and status code
                    
            logging.warning(f"Segment {segment_id} not found for channel {channel_id}")
        except Exception as e:
            logging.error(f"Error serving segment {segment_name}: {e}")
        return '', 404

    def change_stream(self, channel_id: str):
        """
        Handle stream URL changes via POST request.
        
        Args:
            channel_id: Channel to modify
            
        Expected JSON body:
            {
                "url": "new_stream_url"
            }
            
        Returns:
            JSON response with:
            - Success/failure message
            - Channel ID
            - New/current URL
            - HTTP 404 if channel not found
            - HTTP 400 if URL missing from request
            
        Side effects:
            - Updates stream manager URL
            - Triggers stream switch sequence
            - Maintains segment numbering
        """
        if channel_id not in self.stream_managers:
            return {'error': 'Channel not found'}, 404
            
        new_url = request.json.get('url')
        if not new_url:
            return {'error': 'No URL provided'}, 400
            
        manager = self.stream_managers[channel_id]
        if manager.update_url(new_url):
            return {
                'message': 'Stream URL updated',
                'channel': channel_id,
                'url': new_url
            }, 200
        return {
            'message': 'URL unchanged',
            'channel': channel_id,
            'url': new_url
        }, 200

# Main Application Setup
if __name__ == '__main__':
    # Command line argument parsing
    parser = argparse.ArgumentParser(description='HLS Proxy Server with Stream Switching')
    parser.add_argument(
        '--url', '-u',
        required=True,
        help='Initial HLS stream URL to proxy'
    )
    parser.add_argument(
        '--channel', '-c',
        required=True,
        help='Channel ID for the stream (default: default)'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=5000,
        help='Local port to serve proxy on (default: 5000)'
    )
    parser.add_argument(
        '--host', '-H',
        default=os.environ.get("HLS_PROXY_BIND", "0.0.0.0"),
        help='Interface to bind server to (default: all interfaces)'
    )
    parser.add_argument(
        '--user-agent', '-ua',
        help='Custom User-Agent string'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    try:
        # Initialize proxy server
        proxy = ProxyServer(user_agent=args.user_agent)
        
        # Initialize channel with provided URL
        proxy.initialize_channel(args.url, args.channel)
        
        logging.info(f"Starting HLS proxy server on {args.host}:{args.port}")
        logging.info(f"Initial stream URL: {args.url}")
        logging.info(f"Channel ID: {args.channel}")
        
        # Run Flask development server
        proxy.run(host=args.host, port=args.port)
        
    except Exception as e:
        logging.error(f"Failed to start server: {e}")
        sys.exit(1)
    finally:
        if 'proxy' in locals():
            proxy.shutdown()
