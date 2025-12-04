import logging
import re
from urllib.parse import urlparse
import inspect

logger = logging.getLogger("ts_proxy")

def detect_stream_type(url):
    """
    Detect if stream URL is HLS, RTSP/RTP, UDP, or TS format.

    Args:
        url (str): The stream URL to analyze

    Returns:
        str: 'hls', 'rtsp', 'udp', or 'ts' depending on detected format
    """
    if not url:
        return 'unknown'

    url_lower = url.lower()

    # Check for UDP streams (requires FFmpeg)
    if url_lower.startswith('udp://'):
        return 'udp'

    # Check for RTSP/RTP streams (requires FFmpeg)
    if url_lower.startswith('rtsp://') or url_lower.startswith('rtp://'):
        return 'rtsp'

    # Look for common HLS indicators
    if (url_lower.endswith('.m3u8') or
        '.m3u8?' in url_lower or
        '/playlist.m3u' in url_lower):
        return 'hls'

    # Additional HLS patterns
    parsed = urlparse(url)
    path = parsed.path.lower()
    if ('playlist' in path and ('.m3u' in path or '.m3u8' in path)) or \
       ('manifest' in path and ('.m3u' in path or '.m3u8' in path)) or \
       ('master' in path and ('.m3u' in path or '.m3u8' in path)):
        return 'hls'

    # Default to TS
    return 'ts'

def get_client_ip(request):
    """
    Extract client IP address from request.
    Handles cases where request is behind a proxy by checking X-Forwarded-For.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def create_ts_packet(packet_type='null', message=None):
    """
    Create a Transport Stream (TS) packet for various purposes.

    Args:
        packet_type (str): Type of packet - 'null', 'error', 'keepalive', etc.
        message (str): Optional message to include in packet payload

    Returns:
        bytes: A properly formatted 188-byte TS packet
    """
    packet = bytearray(188)

    # TS packet header
    packet[0] = 0x47  # Sync byte

    # PID - Use different PIDs based on packet type
    if packet_type == 'error':
        packet[1] = 0x1F  # PID high bits
        packet[2] = 0xFF  # PID low bits
    else:  # null/keepalive packets
        packet[1] = 0x1F  # PID high bits (null packet)
        packet[2] = 0xFF  # PID low bits (null packet)

    # Add message to payload if provided
    if message:
        msg_bytes = message.encode('utf-8')
        packet[4:4+min(len(msg_bytes), 180)] = msg_bytes[:180]

    return bytes(packet)

def get_logger(component_name=None):
    """
    Get a standardized logger with ts_proxy prefix and optional component name.

    Args:
        component_name (str, optional): Name of the component. If not provided,
                                      will try to detect from the calling module.

    Returns:
        logging.Logger: A configured logger with standardized naming.
    """
    if component_name:
        logger_name = f"ts_proxy.{component_name}"
    else:
        # Try to get the calling module name if not explicitly specified
        frame = inspect.currentframe().f_back
        module = inspect.getmodule(frame)
        if module:
            # Extract just the filename without extension
            module_name = module.__name__.split('.')[-1]
            logger_name = f"ts_proxy.{module_name}"
        else:
            # Default if detection fails
            logger_name = "ts_proxy"

    return logging.getLogger(logger_name)