"""Log parsers for FFmpeg, Streamlink, and VLC output."""
import re
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


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

            codec_match = re.search(r'Audio:\s*([a-zA-Z0-9_]+)', line)
            if codec_match:
                result['audio_codec'] = codec_match.group(1)

            sample_rate_match = re.search(r'(\d+)\s*Hz', line)
            if sample_rate_match:
                result['sample_rate'] = int(sample_rate_match.group(1))

            channel_match = re.search(r'\b(mono|stereo|5\.1|7\.1|quad|2\.1)\b', line, re.IGNORECASE)
            if channel_match:
                result['audio_channels'] = channel_match.group(1)

            bitrate_match = re.search(r'(\d+(?:\.\d+)?)\s*kb/s', line)
            if bitrate_match:
                result['audio_bitrate'] = float(bitrate_match.group(1))

            if result:
                return result

        except Exception as e:
            logger.debug(f"Error parsing FFmpeg audio stream info: {e}")

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
        
        # VLC TS demux codec detection
        if 'ts demux debug' in lower and 'type=' in lower:
            if 'video' in lower:
                return 'vlc_video'
            elif 'audio' in lower:
                return 'vlc_audio'
        
        # VLC decoder output
        if 'decoder' in lower and ('channels:' in lower or 'samplerate:' in lower or 'x' in line or 'fps' in lower):
            if 'audio' in lower or 'channels:' in lower or 'samplerate:' in lower:
                return 'vlc_audio'
            else:
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
            
            # Fallback: try to extract FPS from generic format
            if 'source_fps' not in result:
                fps_match = re.search(r'(\d+\.?\d*)\s*fps', lower)
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
            
            # Codec detection from TS demux
            audio_codec_map = {
                ('type=0xf', 'adts'): "aac",
                ('type=0x03', 'type=0x04'): "mp3",
                ('type=0x06', 'type=0x81'): "ac3",
                ('type=0x0b', 'lpcm'): "pcm"
            }
            
            for patterns, codec in audio_codec_map.items():
                if any(p in lower for p in patterns):
                    result['audio_codec'] = codec
                    break
            
            # VLC decoder format: "AAC channels: 2 samplerate: 48000"
            if 'channels:' in lower:
                channels_match = re.search(r'channels:\s*(\d+)', lower)
                if channels_match:
                    num_channels = int(channels_match.group(1))
                    # Convert number to name
                    channel_names = {1: 'mono', 2: 'stereo', 6: '5.1', 8: '7.1'}
                    result['audio_channels'] = channel_names.get(num_channels, str(num_channels))
            
            if 'samplerate:' in lower:
                samplerate_match = re.search(r'samplerate:\s*(\d+)', lower)
                if samplerate_match:
                    result['sample_rate'] = int(samplerate_match.group(1))
            
            # Try to extract sample rate (Hz format)
            sample_rate_match = re.search(r'(\d+)\s*hz', lower)
            if sample_rate_match and 'sample_rate' not in result:
                result['sample_rate'] = int(sample_rate_match.group(1))
            
            # Try to extract channels (word format)
            if 'audio_channels' not in result:
                channel_match = re.search(r'\b(mono|stereo|5\.1|7\.1|quad|2\.1)\b', lower)
                if channel_match:
                    result['audio_channels'] = channel_match.group(1)
            
            return result if result else None

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
