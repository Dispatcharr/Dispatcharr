import logging
import re
import struct
from urllib.parse import urlparse
import inspect

logger = logging.getLogger("live_proxy")

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

def _mpeg_crc32(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def create_ts_pat_pmt_packets():
    """
    Return two valid TS packets: PAT (PID 0x0000) and PMT (PID 0x0100).

    Declares program 1 with an H.264 video track at PID 0x0101.
    TS clients like VLC need PAT/PMT to recognise a stream as valid; without
    them they time out waiting for program info even while receiving null packets.
    Returns exactly 376 bytes (2 x 188-byte TS packets).
    """
    # PAT section: program 1 mapped to PMT at PID 0x0100
    pat_body = bytes([
        0x00, 0xB0, 0x0D,      # table_id=PAT, section_length=13
        0x00, 0x01,             # transport_stream_id=1
        0xC1, 0x00, 0x00,      # version=0, current=1, section 0/0
        0x00, 0x01,             # program_number=1
        0xE1, 0x00,             # PMT PID=0x0100 (reserved 0b111 | PID)
    ])
    pat_body += struct.pack('>I', _mpeg_crc32(pat_body))
    pat_packet = bytes([0x47, 0x40, 0x00, 0x10, 0x00]) + pat_body + bytes([0xFF] * (183 - len(pat_body)))

    # PMT section: program 1, H.264 video at PID 0x0101
    pmt_body = bytes([
        0x02, 0xB0, 0x12,      # table_id=PMT, section_length=18
        0x00, 0x01,             # program_number=1
        0xC1, 0x00, 0x00,      # version=0, current=1, section 0/0
        0xE1, 0x01,             # PCR_PID=0x0101
        0xF0, 0x00,             # program_info_length=0
        0x1B, 0xE1, 0x01, 0xF0, 0x00,  # stream_type=H.264, PID=0x0101
    ])
    pmt_body += struct.pack('>I', _mpeg_crc32(pmt_body))
    pmt_packet = bytes([0x47, 0x41, 0x00, 0x10, 0x00]) + pmt_body + bytes([0xFF] * (183 - len(pmt_body)))

    return pat_packet + pmt_packet


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
        msg_bytes = message.encode('utf-8', errors='replace') if isinstance(message, str) else message
        packet[4:4+min(len(msg_bytes), 180)] = msg_bytes[:180]

    return bytes(packet)

def get_logger(component_name=None):
    """
    Get a standardized logger with live_proxy prefix and optional component name.

    Args:
        component_name (str, optional): Name of the component. If not provided,
                                      will try to detect from the calling module.

    Returns:
        logging.Logger: A configured logger with standardized naming.
    """
    if component_name:
        logger_name = f"live_proxy.{component_name}"
    else:
        # Try to get the calling module name if not explicitly specified
        frame = inspect.currentframe().f_back
        module = inspect.getmodule(frame)
        if module:
            # Extract just the filename without extension
            module_name = module.__name__.split('.')[-1]
            logger_name = f"live_proxy.{module_name}"
        else:
            # Default if detection fails
            logger_name = "live_proxy"

    return logging.getLogger(logger_name)


def posix_spawn_proc(cmd):
    """
    Spawn a subprocess using os.posix_spawn() with stdin, stdout, and stderr piped.

    Returns an object compatible with subprocess.Popen(cmd, stdin=PIPE,
    stdout=PIPE, stderr=PIPE).  Under gevent+uWSGI, fork() hangs indefinitely
    in gevent's _before_fork atfork handler regardless of whether it is called
    from a hub greenlet or a threadpool thread.  os.posix_spawn() is explicitly
    defined by POSIX to not call pthread_atfork handlers.
    """
    import os
    import shutil
    import signal
    import subprocess
    import time

    stdin_r, stdin_w = os.pipe()    # child reads stdin  (FD 0) from here
    stdout_r, stdout_w = os.pipe()  # child writes stdout (FD 1) here; parent reads
    stderr_r, stderr_w = os.pipe()  # child writes stderr (FD 2) here; parent reads

    stdin_w_ok = stdout_r_ok = stderr_r_ok = False
    try:
        executable = shutil.which(cmd[0]) or cmd[0]
        child_pid = os.posix_spawn(
            executable, cmd, os.environ,
            file_actions=[
                (os.POSIX_SPAWN_DUP2, stdin_r,  0),
                (os.POSIX_SPAWN_DUP2, stdout_w, 1),
                (os.POSIX_SPAWN_DUP2, stderr_w, 2),
                (os.POSIX_SPAWN_CLOSE, stdin_r),
                (os.POSIX_SPAWN_CLOSE, stdout_w),
                (os.POSIX_SPAWN_CLOSE, stderr_w),
            ],
        )

        import fcntl
        fcntl.fcntl(stdin_w, fcntl.F_SETFL, fcntl.fcntl(stdin_w, fcntl.F_GETFL) | os.O_NONBLOCK)
        stdin_file  = os.fdopen(stdin_w,  'wb', buffering=0)
        stdin_w_ok  = True
        stdout_file = os.fdopen(stdout_r, 'rb', buffering=0)
        stdout_r_ok = True
        stderr_file = os.fdopen(stderr_r, 'rb', buffering=0)
        stderr_r_ok = True

        class _Proc:
            stdin  = stdin_file
            stdout = stdout_file
            stderr = stderr_file

            def __init__(self):
                self.pid = child_pid
                self.returncode = None

            def _reap(self, status):
                if os.WIFEXITED(status):
                    self.returncode = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    self.returncode = -os.WTERMSIG(status)
                else:
                    self.returncode = -1

            def poll(self):
                if self.returncode is not None:
                    return self.returncode
                try:
                    rpid, status = os.waitpid(self.pid, os.WNOHANG)
                    if rpid:
                        self._reap(status)
                except ChildProcessError:
                    self.returncode = -1
                return self.returncode

            def wait(self, timeout=None):
                if self.returncode is not None:
                    return self.returncode
                import gevent as _gevent
                deadline = time.monotonic() + timeout if timeout is not None else None
                while True:
                    try:
                        rpid, status = os.waitpid(self.pid, os.WNOHANG)
                    except ChildProcessError:
                        self.returncode = -1
                        return self.returncode
                    if rpid:
                        self._reap(status)
                        return self.returncode
                    if deadline is not None and time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(self.pid, timeout)
                    _gevent.sleep(0.01)

            def kill(self):
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

            def terminate(self):
                try:
                    os.kill(self.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

        return _Proc()

    except Exception:
        if not stdin_w_ok:
            os.close(stdin_w)
        if not stdout_r_ok:
            os.close(stdout_r)
        if not stderr_r_ok:
            os.close(stderr_r)
        raise
    finally:
        os.close(stdin_r)
        os.close(stdout_w)
        os.close(stderr_w)
