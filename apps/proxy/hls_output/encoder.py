"""
HLS Encoder

Manages FFmpeg HLS encoding process.
"""

import subprocess
import logging
import os
import gevent
from typing import List, Dict
from .config import HLSConfig

logger = logging.getLogger(__name__)


class HLSEncoder:
    """Manages FFmpeg HLS encoding process"""
    
    def __init__(self, stream, profile):
        self.stream = stream
        self.profile = profile
        self.process = None
        self.monitor_greenlet = None
    
    def get_storage_path(self) -> str:
        """Get storage path for this stream"""
        if self.profile.use_memory_storage:
            base_path = HLSConfig.MEMORY_STORAGE_PATH
        else:
            base_path = self.profile.storage_path
        
        stream_path = os.path.join(base_path, str(self.stream.stream_id))
        os.makedirs(stream_path, exist_ok=True)
        return stream_path
    
    def get_segment_path(self, quality: str = None) -> str:
        """Get segment storage path for specific quality"""
        base_path = self.get_storage_path()
        
        if quality:
            quality_path = os.path.join(base_path, quality)
            os.makedirs(quality_path, exist_ok=True)
            return quality_path
        
        return base_path
    
    def get_playlist_path(self) -> str:
        """Get playlist storage path"""
        return self.get_storage_path()
    
    def build_ffmpeg_command(self, input_url: str) -> List[str]:
        """Build FFmpeg command for HLS output"""
        
        cmd = ['ffmpeg', '-i', input_url]
        
        # Input options
        cmd.extend(['-re'])  # Read input at native frame rate
        
        if self.profile.enable_abr and self.profile.qualities:
            # Multi-bitrate ladder
            cmd.extend(self._build_abr_command())
        else:
            # Single quality
            cmd.extend(self._build_single_quality_command())
        
        return cmd
    
    def _build_single_quality_command(self) -> List[str]:
        """Build single quality encoding command"""
        cmd = []
        
        # Video encoding
        cmd.extend([
            '-c:v', HLSConfig.VIDEO_CODEC,
            '-preset', HLSConfig.FFMPEG_PRESET,
            '-tune', HLSConfig.FFMPEG_TUNE,
            '-g', str(self.profile.segment_duration * 30),  # GOP size
            '-keyint_min', str(self.profile.segment_duration * 30),
            '-sc_threshold', '0',
        ])
        
        # Audio encoding
        cmd.extend([
            '-c:a', HLSConfig.AUDIO_CODEC,
        ])
        
        # HLS muxer options
        cmd.extend(self._build_hls_muxer_options())
        
        # Output path
        playlist_path = os.path.join(self.get_playlist_path(), 'playlist.m3u8')
        cmd.append(playlist_path)
        
        return cmd
    
    def _build_abr_command(self) -> List[str]:
        """Build multi-bitrate encoding command"""
        cmd = []
        qualities = self.profile.qualities
        
        # Video and audio encoding for each quality
        for i, quality in enumerate(qualities):
            resolution = quality['resolution']
            video_bitrate = quality['video_bitrate']
            audio_bitrate = quality['audio_bitrate']
            quality_name = quality['name']
            
            # Extract bitrate value for calculations
            vbitrate_val = int(video_bitrate.rstrip('k'))
            
            # Video stream
            cmd.extend([
                '-map', '0:v:0',
                f'-c:v:{i}', HLSConfig.VIDEO_CODEC,
                f'-b:v:{i}', video_bitrate,
                f'-maxrate:v:{i}', f"{int(vbitrate_val * HLSConfig.BITRATE_BUFFER_MULTIPLIER)}k",
                f'-bufsize:v:{i}', f"{int(vbitrate_val * HLSConfig.BITRATE_BUFSIZE_MULTIPLIER)}k",
                f'-s:v:{i}', resolution,
                f'-preset:v:{i}', HLSConfig.FFMPEG_PRESET,
                f'-tune:v:{i}', HLSConfig.FFMPEG_TUNE,
                f'-g:v:{i}', str(self.profile.segment_duration * 30),
                f'-keyint_min:v:{i}', str(self.profile.segment_duration * 30),
                f'-sc_threshold:v:{i}', '0',
            ])
            
            # Audio stream
            cmd.extend([
                '-map', '0:a:0',
                f'-c:a:{i}', HLSConfig.AUDIO_CODEC,
                f'-b:a:{i}', audio_bitrate,
            ])
        
        # Variant stream mapping
        var_stream_map = ' '.join([
            f'v:{i},a:{i},name:{qualities[i]["name"]}' 
            for i in range(len(qualities))
        ])
        cmd.extend(['-var_stream_map', var_stream_map])
        
        # HLS muxer options
        cmd.extend(self._build_hls_muxer_options(multi_variant=True))
        
        # Master playlist path
        master_playlist = os.path.join(self.get_playlist_path(), 'master.m3u8')
        cmd.append(master_playlist)

        return cmd

    def _build_hls_muxer_options(self, multi_variant: bool = False) -> List[str]:
        """Build HLS muxer options"""
        cmd = []

        cmd.extend([
            '-f', 'hls',
            '-hls_time', str(self.profile.segment_duration),
            '-hls_list_size', str(self.profile.max_playlist_segments),
            '-hls_segment_type', self.profile.segment_format,
        ])

        # HLS flags
        flags = ['delete_segments', 'append_list', 'program_date_time']
        if self.profile.playlist_type != 'vod':
            flags.append('omit_endlist')

        cmd.extend(['-hls_flags', '+'.join(flags)])

        # Playlist type
        if self.profile.playlist_type == 'event':
            cmd.extend(['-hls_playlist_type', 'event'])
        elif self.profile.playlist_type == 'vod':
            cmd.extend(['-hls_playlist_type', 'vod'])

        # Low-latency HLS
        if self.profile.enable_ll_hls and self.profile.segment_format == 'fmp4':
            cmd.extend([
                '-hls_fmp4_init_filename', 'init.mp4',
                '-hls_segment_filename', os.path.join(
                    self.get_segment_path('%v'),
                    'segment_%03d.m4s'
                ),
            ])
        else:
            # Standard segment naming
            if multi_variant:
                cmd.extend([
                    '-hls_segment_filename', os.path.join(
                        self.get_segment_path('%v'),
                        'segment_%03d.' + ('m4s' if self.profile.segment_format == 'fmp4' else 'ts')
                    ),
                ])
            else:
                cmd.extend([
                    '-hls_segment_filename', os.path.join(
                        self.get_segment_path(),
                        'segment_%03d.' + ('m4s' if self.profile.segment_format == 'fmp4' else 'ts')
                    ),
                ])

        return cmd

    def start(self, input_url: str):
        """Start FFmpeg encoding process"""
        try:
            command = self.build_ffmpeg_command(input_url)

            logger.info(f"Starting HLS encoding for stream {self.stream.stream_id}")
            logger.debug(f"FFmpeg command: {' '.join(command)}")

            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Update stream record
            self.stream.ffmpeg_pid = self.process.pid
            self.stream.ffmpeg_command = ' '.join(command)
            self.stream.status = 'running'
            self.stream.save()

            # Start monitoring greenlet
            self.monitor_greenlet = gevent.spawn(self._monitor_process)

            logger.info(f"HLS encoding started with PID {self.process.pid}")

        except Exception as e:
            logger.error(f"Failed to start HLS encoding: {e}")
            self.stream.status = 'error'
            self.stream.error_message = str(e)
            self.stream.save()
            raise

    def stop(self):
        """Stop FFmpeg encoding process"""
        try:
            if self.monitor_greenlet:
                self.monitor_greenlet.kill()

            if self.process:
                logger.info(f"Stopping HLS encoding for stream {self.stream.stream_id}")
                self.process.terminate()

                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("FFmpeg did not terminate gracefully, killing process")
                    self.process.kill()
                    self.process.wait()

                self.stream.status = 'stopped'
                self.stream.save()

                logger.info(f"HLS encoding stopped for stream {self.stream.stream_id}")

        except Exception as e:
            logger.error(f"Error stopping HLS encoding: {e}")

    def _monitor_process(self):
        """Monitor FFmpeg process output"""
        try:
            while True:
                if self.process.poll() is not None:
                    # Process has ended
                    returncode = self.process.returncode

                    if returncode != 0:
                        stderr = self.process.stderr.read()
                        logger.error(f"FFmpeg process exited with code {returncode}: {stderr}")
                        self.stream.status = 'error'
                        self.stream.error_message = f"FFmpeg exited with code {returncode}"
                        self.stream.save()

                    break

                gevent.sleep(1)

        except Exception as e:
            logger.error(f"Error monitoring FFmpeg process: {e}")

