"""Log parsers for FFmpeg, Streamlink, and VLC output."""
import json
import re
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Named layouts ordered by usefulness for a "best audio" summary badge.
_CHANNEL_RANK = {
    "mono": 1,
    "stereo": 2,
    "2.1": 3,
    "3.0": 3,
    "quad": 4,
    "4.0": 4,
    "5.0": 5,
    "5.1": 6,
    "6.1": 7,
    "7.1": 8,
    "octagonal": 8,
    "hexadecagonal": 16,
    "9.1.6": 16,
}

# Keep numeric layouts tight (5.1, 7.1, 9.1.6). Do not use a loose
# "digits.digits" pattern: FFmpeg lines also contain start timestamps
# like 45961.400000 which would false-match.
_CHANNEL_NAME_RE = re.compile(
    r"\b(mono|stereo|quad|octagonal|hexadecagonal|"
    r"(?:[1-9]|1[0-6])\.\d(?:\.\d)?)\b",
    re.IGNORECASE,
)
_N_CHANNELS_RE = re.compile(r"\b(\d+)\s*channels?\b", re.IGNORECASE)
_UNDETERMINED_LANGUAGE = "und"
_STREAM_INDEX_LANG_RE = re.compile(
    r"Stream\s+#\d+:(\d+)(?:\[[^\]]*\])?(?:\(([^)]+)\))?:",
    re.IGNORECASE,
)


def normalize_channel_layout(value: Optional[str]) -> Optional[str]:
    """Normalize a channel layout token (e.g. 5.1(side) -> 5.1)."""
    if not value:
        return None
    text = value.strip()
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text or None


def channel_layout_rank(channels: Optional[str]) -> int:
    """Higher is better. Unknown layouts rank below mono."""
    if not channels:
        return 0
    normalized = normalize_channel_layout(str(channels))
    if not normalized:
        return 0
    key = normalized.lower()
    if key in _CHANNEL_RANK:
        return _CHANNEL_RANK[key]
    n_match = re.match(r"^(\d+)\s*channels?$", key)
    if n_match:
        return int(n_match.group(1))
    try:
        # e.g. "7.1.4"
        parts = key.split(".")
        return sum(int(p) for p in parts)
    except ValueError:
        return 0


def select_best_audio_track(tracks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the richest audio track (channels, then bitrate, then earliest index)."""
    if not tracks:
        return None

    def sort_key(track: Dict[str, Any]):
        index = track.get("index")
        # Unknown index sorts after known ones when other scores tie.
        index_key = index if isinstance(index, int) else 10_000
        bitrate = track.get("audio_bitrate") or 0
        return (channel_layout_rank(track.get("audio_channels")), bitrate, -index_key)

    return max(tracks, key=sort_key)


_TRACK_IDENTITY_KEYS = (
    "pid",
    "audio_codec",
    "audio_channels",
    "sample_rate",
    "audio_language",
    "audio_bitrate",
)


def _audio_track_fingerprint(track: Dict[str, Any]) -> tuple:
    """Stable identity for tracks that lack an FFmpeg stream index (e.g. VLC)."""
    return tuple(track.get(key) for key in _TRACK_IDENTITY_KEYS)


def _compare_track_identity(current: Dict[str, Any], incoming: Dict[str, Any]) -> tuple:
    """Return (overlap, conflict) across the identity keys both tracks set.

    ``overlap`` means at least one key was set on both sides and matched.
    ``conflict`` means a key was set on both sides with different values.
    """
    overlap = False
    for key in _TRACK_IDENTITY_KEYS:
        current_value = current.get(key)
        incoming_value = incoming.get(key)
        if current_value is None or incoming_value is None:
            continue
        if current_value != incoming_value:
            return overlap, True
        overlap = True
    return overlap, False


def _unindexed_tracks_compatible(current: Dict[str, Any], incoming: Dict[str, Any]) -> bool:
    """True when two partial VLC lines describe the same track.

    A later line often adds channels or sample rate the first line lacked.
    Conflicting values mean a different track.
    """
    overlap, conflict = _compare_track_identity(current, incoming)
    return overlap and not conflict


def _is_language_only_track(track: Dict[str, Any]) -> bool:
    """VLC emits `found language: eng` on its own line after the ES pid."""
    if track.get("audio_language") is None:
        return False
    return not any(
        track.get(key) is not None
        for key in (
            "index",
            "pid",
            "audio_codec",
            "audio_channels",
            "sample_rate",
            "audio_bitrate",
        )
    )


def _merge_track_fields(current: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(current)
    merged.update({key: value for key, value in incoming.items() if value is not None})
    return merged


def merge_audio_track(
    existing: Optional[List[Dict[str, Any]]],
    track: Dict[str, Any],
    *,
    accept_language: bool = False,
) -> List[Dict[str, Any]]:
    """Upsert one parsed audio track into the session list.

    ``accept_language`` is set only for the VLC line that follows an audio
    elementary stream. Subtitle and video ES also log ``found language``, and
    those must not become tracks or overwrite an audio language.
    """
    tracks = list(existing or [])
    index = track.get("index")
    if isinstance(index, int):
        for i, current in enumerate(tracks):
            if current.get("index") == index:
                tracks[i] = _merge_track_fields(current, track)
                return tracks
        tracks.append(track)
        return tracks

    pid = track.get("pid")
    if isinstance(pid, int):
        for i, current in enumerate(tracks):
            if current.get("pid") == pid:
                tracks[i] = _merge_track_fields(current, track)
                return tracks
        tracks.append(track)
        return tracks

    # VLC logs language on the next line after an audio ES pid. Attach it only
    # to that latest track, and only when the caller saw the audio ES first.
    # Never append a language-only row: a later subtitle language would inflate
    # the track count.
    if _is_language_only_track(track):
        if (
            accept_language
            and tracks
            and tracks[-1].get("index") is None
            and not tracks[-1].get("audio_language")
        ):
            tracks[-1] = _merge_track_fields(tracks[-1], track)
        return tracks

    # No stream index (typical for VLC). Exact repeats update in place.
    # A later, richer line merges into the one partial track it extends.
    fingerprint = _audio_track_fingerprint(track)
    compatible = []
    for i, current in enumerate(tracks):
        if current.get("index") is not None:
            continue
        if _audio_track_fingerprint(current) == fingerprint:
            tracks[i] = _merge_track_fields(current, track)
            return tracks
        if _unindexed_tracks_compatible(current, track):
            compatible.append(i)
    if len(compatible) == 1:
        tracks[compatible[0]] = _merge_track_fields(tracks[compatible[0]], track)
        return tracks

    # Decoder lines carry channels but no pid. Fill the first shell that still
    # lacks channels. _compare_track_identity already rejects a codec mismatch
    # when both sides name one, so an AC3 line cannot land on an AAC shell.
    # Among shells of the same codec, VLC's log order is the only order we
    # have. Two AAC lines can therefore swap sample rate if VLC logs them
    # opposite the PMT, and there is no pid on the line to stop it.
    if track.get("audio_channels") is not None:
        for i, current in enumerate(tracks):
            if current.get("index") is not None:
                continue
            if current.get("audio_channels") is not None:
                continue
            if _compare_track_identity(current, track)[1]:
                continue
            tracks[i] = _merge_track_fields(current, track)
            return tracks

    # This line has no pid or index. Once demux shells exist, a line that did
    # not fill an empty shell is a repeat (two AAC tracks look the same), so
    # drop it instead of appending a duplicate.
    if any(
        current.get("pid") is not None or current.get("index") is not None
        for current in tracks
    ):
        return tracks

    tracks.append(track)
    return tracks


def decode_audio_streams(value: Any) -> Optional[List[Dict[str, Any]]]:
    """Decode a stored audio track list (JSON text from Redis, or a list).

    Returns None when there is nothing usable, so callers can skip the field.
    """
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, list) and value:
        return value
    return None


def extract_channel_layout(line: str) -> Optional[str]:
    """Pull a channel layout token from an FFmpeg/VLC audio line."""
    # Prefer the Audio: payload and drop trailing ", start N" timestamps.
    audio_part = line
    audio_match = re.search(r"Audio:\s*(.*)$", line, re.IGNORECASE)
    if audio_match:
        audio_part = audio_match.group(1)
    audio_part = re.split(r",\s*start\s+", audio_part, maxsplit=1)[0]

    match = _CHANNEL_NAME_RE.search(audio_part)
    if match:
        return normalize_channel_layout(match.group(1))
    n_match = _N_CHANNELS_RE.search(audio_part)
    if n_match:
        count = int(n_match.group(1))
        if count <= 0:
            return None
        names = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}
        return names.get(count, f"{count} channels")
    return None


class BaseLogParser(ABC):
    """Base class for log parsers"""
    
    # Map of stream_type -> method_name that this parser handles
    STREAM_TYPE_METHODS: Dict[str, str] = {}

    @abstractmethod
    def can_parse(self, line: str) -> Optional[str]:
        """
        Check if this parser can handle the line.
        Returns the stream_type if it can parse, None otherwise.
        e.g., 'video', 'audio', 'vlc_video', 'vlc_audio', 'streamlink'
        """
        pass

    @abstractmethod
    def parse_input_format(self, line: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def parse_video_stream(self, line: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def parse_audio_stream(self, line: str) -> Optional[Dict[str, Any]]:
        pass


class FFmpegLogParser(BaseLogParser):
    """Parser for FFmpeg log output"""
    
    STREAM_TYPE_METHODS = {
        'input': 'parse_input_format',
        'video': 'parse_video_stream',
        'audio': 'parse_audio_stream'
    }

    def can_parse(self, line: str) -> Optional[str]:
        """Check if this is an FFmpeg line we can parse"""
        lower = line.lower()
        
        # Input format detection
        if lower.startswith('input #'):
            return 'input'
        
        # Stream info (only during input phase, but we'll let stream_manager handle phase tracking)
        if 'stream #' in lower:
            if 'video:' in lower:
                return 'video'
            elif 'audio:' in lower:
                return 'audio'
        
        return None

    def parse_input_format(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse FFmpeg input format (e.g., mpegts, hls)"""
        try:
            input_match = re.search(r'Input #\d+,\s*([^,]+)', line)
            input_format = input_match.group(1).strip() if input_match else None

            if input_format:
                logger.debug(f"Input format info - Format: {input_format}")
                return {'stream_type': input_format}
        except Exception as e:
            logger.debug(f"Error parsing FFmpeg input format: {e}")
        
        return None

    def parse_video_stream(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse FFmpeg video stream info"""
        try:
            result = {}

            # Extract codec, resolution, fps, pixel format, bitrate
            codec_match = re.search(r'Video:\s*([a-zA-Z0-9_]+)', line)
            if codec_match:
                result['video_codec'] = codec_match.group(1)

            resolution_match = re.search(r'\b(\d{3,5})x(\d{3,5})\b', line)
            if resolution_match:
                width = int(resolution_match.group(1))
                height = int(resolution_match.group(2))
                if 100 <= width <= 10000 and 100 <= height <= 10000:
                    result['resolution'] = f"{width}x{height}"
                    result['width'] = width
                    result['height'] = height

            fps_match = re.search(r'(\d+(?:\.\d+)?)\s*fps', line)
            if fps_match:
                result['source_fps'] = float(fps_match.group(1))

            pixel_format_match = re.search(r'Video:\s*[^,]+,\s*([^,(]+)', line)
            if pixel_format_match:
                pf = pixel_format_match.group(1).strip()
                if '(' in pf:
                    pf = pf.split('(')[0].strip()
                result['pixel_format'] = pf

            bitrate_match = re.search(r'(\d+(?:\.\d+)?)\s*kb/s', line)
            if bitrate_match:
                result['video_bitrate'] = float(bitrate_match.group(1))

            if result:
                logger.info(f"Video stream info - Codec: {result.get('video_codec')}, "
                           f"Resolution: {result.get('resolution')}, "
                           f"Source FPS: {result.get('source_fps')}, "
                           f"Pixel Format: {result.get('pixel_format')}, "
                           f"Video Bitrate: {result.get('video_bitrate')} kb/s")
                return result

        except Exception as e:
            logger.debug(f"Error parsing FFmpeg video stream info: {e}")

        return None

    def parse_audio_stream(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse FFmpeg audio stream info"""
        try:
            result = {}

            index_lang = _STREAM_INDEX_LANG_RE.search(line)
            if index_lang:
                result["index"] = int(index_lang.group(1))
                language = (index_lang.group(2) or "").lower()
                # "und" is FFmpeg's placeholder for an untagged track. Treat it
                # as no language so it is not shown as "UND".
                if language and language != _UNDETERMINED_LANGUAGE:
                    result["audio_language"] = language

            codec_match = re.search(r'Audio:\s*([a-zA-Z0-9_]+)', line)
            if codec_match:
                result['audio_codec'] = codec_match.group(1)

            sample_rate_match = re.search(r'(\d+)\s*Hz', line)
            if sample_rate_match:
                result['sample_rate'] = int(sample_rate_match.group(1))

            channels = extract_channel_layout(line)
            if channels:
                result['audio_channels'] = channels

            bitrate_match = re.search(r'(\d+(?:\.\d+)?)\s*kb/s', line)
            if bitrate_match:
                result['audio_bitrate'] = float(bitrate_match.group(1))

            if result.get("audio_codec") or result.get("audio_channels"):
                result["audio_track"] = {
                    key: result[key]
                    for key in (
                        "index",
                        "audio_language",
                        "audio_codec",
                        "audio_channels",
                        "audio_bitrate",
                        "sample_rate",
                    )
                    if key in result
                }
                return result

        except Exception as e:
            logger.debug(f"Error parsing FFmpeg audio stream info: {e}")

        return None


_VLC_AUDIO_TYPE_RE = re.compile(r"type=0x([0-9a-f]+)", re.IGNORECASE)
_VLC_PID_RE = re.compile(r"\bpid[= ](\d+)\b", re.IGNORECASE)
_VLC_LANGUAGE_RE = re.compile(r"found language:\s*([a-z0-9]{2,3})\b", re.IGNORECASE)
_VLC_CHANNELS_RE = re.compile(r"channels:\s*(\d+)", re.IGNORECASE)
_VLC_SAMPLERATE_RE = re.compile(r"samplerate:\s*(\d+)", re.IGNORECASE)
_VLC_BITRATE_RE = re.compile(r"bitrate:\s*(\d+)", re.IGNORECASE)
_VLC_DECODER_CODEC_RE = re.compile(
    r"\b(A/?52B?|e?ac-?3|AAC|MP3|MPGA|DTS|LPCM|PCM)\b",
    re.IGNORECASE,
)
# MPEG-TS stream_type values that identify an audio codec (ISO 13818-1 / ATSC).
# 0x06 (private PES) is deliberately absent: it can carry AC-3, DTS, AAC or
# subtitles, so it says nothing about the codec on its own.
_VLC_AUDIO_STREAM_TYPES = {
    0x03: "mp3",
    0x04: "mp3",
    0x0F: "aac",
    0x11: "aac",
    0x81: "ac3",
    0x87: "eac3",
}


def _vlc_audio_codec_from_type(lower: str) -> Optional[str]:
    """Codec for the `type=0x..` stream type on a TS demux line, if audio."""
    type_match = _VLC_AUDIO_TYPE_RE.search(lower)
    if not type_match:
        return None
    return _VLC_AUDIO_STREAM_TYPES.get(int(type_match.group(1), 16))


def _vlc_codec_from_name(token: str) -> Optional[str]:
    """Map a VLC decoder/packetizer codec token to our codec id."""
    key = token.lower().replace("-", "").replace("/", "")
    if key in ("a52", "ac3"):
        return "ac3"
    if key in ("a52b", "eac3"):
        return "eac3"
    if key == "aac":
        return "aac"
    if key in ("mp3", "mpga"):
        return "mp3"
    if key == "dts":
        return "dts"
    if key in ("lpcm", "pcm"):
        return "pcm"
    return None


class VLCLogParser(BaseLogParser):
    """Parser for VLC log output"""
    
    STREAM_TYPE_METHODS = {
        'vlc_video': 'parse_video_stream',
        'vlc_audio': 'parse_audio_stream'
    }

    def can_parse(self, line: str) -> Optional[str]:
        """Check if this is a VLC line we can parse"""
        lower = line.lower()
        
        if 'unable to open the mrl' in lower:
            return 'vlc_input_failed'

        # ISO-639 descriptor from the TS demux (own line after the ES pid).
        if 'found language:' in lower:
            return 'vlc_audio'
        
        # VLC TS demux codec detection
        if 'ts demux' in lower and 'type=' in lower:
            if _vlc_audio_codec_from_type(lower):
                return 'vlc_audio'
            if 'video' in lower:
                return 'vlc_video'
            if 'audio' in lower:
                return 'vlc_audio'

        has_channels = 'channels:' in lower
        has_samplerate = 'samplerate:' in lower

        # Packetizer lines: "A/52 channels:6 samplerate:48000 bitrate:384000"
        # and "AAC channels: 2 samplerate: 48000". They do not say "decoder", so
        # require both fields plus a codec token or bitrate. Audio-output
        # modules also report "PCM channels: N samplerate: N" for the sink
        # format; that is not an elementary stream.
        if (
            has_channels
            and has_samplerate
            and "aout" not in lower
            and "audio output" not in lower
            and (
                _VLC_DECODER_CODEC_RE.search(line) or "bitrate:" in lower
            )
        ):
            return "vlc_audio"

        # VLC decoder output
        if 'decoder' in lower and (
            has_channels or has_samplerate or 'x' in line or 'fps' in lower
        ):
            if 'audio' in lower or has_channels or has_samplerate:
                return 'vlc_audio'
            return 'vlc_video'
        
        # VLC transcode output for resolution/FPS
        if 'stream_out_transcode' in lower and ('source fps' in lower or ('source ' in lower and 'x' in line)):
            return 'vlc_video'
        
        return None

    def parse_input_format(self, line: str) -> Optional[Dict[str, Any]]:
        return None

    def parse_video_stream(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse VLC TS demux output and decoder info for video"""
        try:
            lower = line.lower()
            result = {}
            
            # Codec detection from TS demux
            video_codec_map = {
                ('avc', 'h.264', 'type=0x1b'): "h264",
                ('hevc', 'h.265', 'type=0x24'): "hevc",
                ('mpeg-2', 'type=0x02'): "mpeg2video",
                ('mpeg-4', 'type=0x10'): "mpeg4"
            }
            
            for patterns, codec in video_codec_map.items():
                if any(p in lower for p in patterns):
                    result['video_codec'] = codec
                    break
            
            # Extract FPS from transcode output: "source fps 30/1"
            fps_fraction_match = re.search(r'source fps\s+(\d+)/(\d+)', lower)
            if fps_fraction_match:
                numerator = int(fps_fraction_match.group(1))
                denominator = int(fps_fraction_match.group(2))
                if denominator > 0:
                    result['source_fps'] = numerator / denominator
            
            # Extract resolution from transcode output: "source 1280x720"
            source_res_match = re.search(r'source\s+(\d{3,4})x(\d{3,4})', lower)
            if source_res_match:
                width = int(source_res_match.group(1))
                height = int(source_res_match.group(2))
                if 100 <= width <= 10000 and 100 <= height <= 10000:
                    result['resolution'] = f"{width}x{height}"
                    result['width'] = width
                    result['height'] = height
            else:
                # Fallback: generic resolution pattern
                resolution_match = re.search(r'(\d{3,4})x(\d{3,4})', line)
                if resolution_match:
                    width = int(resolution_match.group(1))
                    height = int(resolution_match.group(2))
                    if 100 <= width <= 10000 and 100 <= height <= 10000:
                        result['resolution'] = f"{width}x{height}"
                        result['width'] = width
                        result['height'] = height
            
            # Fallback: try to extract FPS from generic format. Prefer the
            # explicit "fps=25.000" form: the decoder line reads
            # "size 640x360/640x368 fps=25.000", and a bare "N fps" match
            # would take the coded height (368) as the frame rate.
            if 'source_fps' not in result:
                fps_match = (
                    re.search(r'fps[=:]\s*(\d+\.?\d*)', lower)
                    or re.search(r'(\d+\.?\d*)\s*fps', lower)
                )
                if fps_match:
                    result['source_fps'] = float(fps_match.group(1))
            
            return result if result else None

        except Exception as e:
            logger.debug(f"Error parsing VLC video stream info: {e}")

        return None

    def parse_audio_stream(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse VLC TS demux output and decoder info for audio"""
        try:
            lower = line.lower()
            result = {}

            language_match = _VLC_LANGUAGE_RE.search(line)
            if language_match:
                language = language_match.group(1).lower()
                if language != _UNDETERMINED_LANGUAGE:
                    result["audio_language"] = language

            codec = _vlc_audio_codec_from_type(lower)
            if codec:
                result["audio_codec"] = codec

            if "audio_codec" not in result:
                # Demux text fallbacks and decoder tokens (A/52, AAC, ...).
                for patterns, codec in (
                    (("adts",), "aac"),
                    (("lpcm",), "pcm"),
                ):
                    if any(p in lower for p in patterns):
                        result["audio_codec"] = codec
                        break
                if "audio_codec" not in result:
                    codec_token = _VLC_DECODER_CODEC_RE.search(line)
                    if codec_token:
                        mapped = _vlc_codec_from_name(codec_token.group(1))
                        if mapped:
                            result["audio_codec"] = mapped

            # Only a PMT line ("* pid=257 type=0x81 ...") names an ES. A pid
            # mentioned elsewhere (for example a discontinuity warning) does not.
            pid_match = _VLC_PID_RE.search(line)
            if pid_match and "type=" in lower:
                result["pid"] = int(pid_match.group(1))

            channels_match = _VLC_CHANNELS_RE.search(lower)
            if channels_match:
                num_channels = int(channels_match.group(1))
                channel_names = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}
                result["audio_channels"] = channel_names.get(
                    num_channels, str(num_channels)
                )

            samplerate_match = _VLC_SAMPLERATE_RE.search(lower)
            if samplerate_match:
                result["sample_rate"] = int(samplerate_match.group(1))
            else:
                sample_rate_match = re.search(r"(\d+)\s*hz", lower)
                if sample_rate_match:
                    result["sample_rate"] = int(sample_rate_match.group(1))

            bitrate_match = _VLC_BITRATE_RE.search(lower)
            if bitrate_match and int(bitrate_match.group(1)) > 0:
                # VLC reports bits/s; store kbps like the FFmpeg parser. A zero
                # means the packetizer does not know it, so leave it unset.
                result["audio_bitrate"] = round(int(bitrate_match.group(1)) / 1000.0, 1)

            if "audio_channels" not in result:
                channels = extract_channel_layout(line)
                if channels:
                    result["audio_channels"] = channels

            if result:
                result["audio_track"] = {
                    key: result[key]
                    for key in (
                        "pid",
                        "audio_language",
                        "audio_codec",
                        "audio_channels",
                        "audio_bitrate",
                        "sample_rate",
                    )
                    if key in result
                }
                return result

            return None

        except Exception as e:
            logger.error(f"[VLC AUDIO PARSER] Error parsing VLC audio stream info: {e}")

        return None


class StreamlinkLogParser(BaseLogParser):
    """Parser for Streamlink log output"""
    
    STREAM_TYPE_METHODS = {
        'streamlink': 'parse_video_stream'
    }

    def can_parse(self, line: str) -> Optional[str]:
        """Check if this is a Streamlink line we can parse"""
        lower = line.lower()
        
        if 'opening stream:' in lower or 'available streams:' in lower:
            return 'streamlink'
        
        return None

    def parse_input_format(self, line: str) -> Optional[Dict[str, Any]]:
        return None

    def parse_video_stream(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse Streamlink quality/resolution"""
        try:
            quality_match = re.search(r'(\d+p|\d+x\d+)', line)
            if quality_match:
                quality = quality_match.group(1)
                
                if 'x' in quality:
                    resolution = quality
                    width, height = map(int, quality.split('x'))
                else:
                    resolutions = {
                        '2160p': ('3840x2160', 3840, 2160),
                        '1080p': ('1920x1080', 1920, 1080),
                        '720p': ('1280x720', 1280, 720),
                        '480p': ('854x480', 854, 480),
                        '360p': ('640x360', 640, 360)
                    }
                    resolution, width, height = resolutions.get(quality, ('1920x1080', 1920, 1080))
                
                return {
                    'video_codec': 'h264',
                    'resolution': resolution,
                    'width': width,
                    'height': height,
                    'pixel_format': 'yuv420p'
                }

        except Exception as e:
            logger.debug(f"Error parsing Streamlink video info: {e}")

        return None

    def parse_audio_stream(self, line: str) -> Optional[Dict[str, Any]]:
        return None


class LogParserFactory:
    """Factory to get the appropriate log parser"""

    _parsers = {
        'ffmpeg': FFmpegLogParser(),
        'vlc': VLCLogParser(),
        'streamlink': StreamlinkLogParser()
    }

    @classmethod
    def _get_parser_and_method(cls, stream_type: str) -> Optional[tuple[BaseLogParser, str]]:
        """Determine parser and method from stream_type"""
        # Check each parser to see if it handles this stream_type
        for parser in cls._parsers.values():
            method_name = parser.STREAM_TYPE_METHODS.get(stream_type)
            if method_name:
                return (parser, method_name)
        
        return None

    @classmethod
    def parse(cls, stream_type: str, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a log line based on stream type.
        Returns parsed data or None if parsing fails.
        """
        result = cls._get_parser_and_method(stream_type)
        if not result:
            return None
        
        parser, method_name = result
        method = getattr(parser, method_name, None)
        if method:
            return method(line)
        
        return None

    @classmethod
    def auto_parse(cls, line: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """
        Automatically detect which parser can handle this line and parse it.
        Returns (stream_type, parsed_data) or None if no parser can handle it.
        """
        # Try each parser to see if it can handle this line
        for parser in cls._parsers.values():
            stream_type = parser.can_parse(line)
            if stream_type:
                # Parser can handle this line, now parse it
                parsed_data = cls.parse(stream_type, line)
                if parsed_data:
                    return (stream_type, parsed_data)
        
        return None
