import logging
import os
import subprocess
import threading
import time
import json
import re # For parsing FFmpeg stats

from core.models import StreamProfile, CoreSettings
from core.utils import RedisClient # Assuming RedisClient is accessible for updates by handler too
from .constants import HLSChannelState
from .redis_keys import HLSRedisKeys
from .config import get_hls_setting # Import the new config helper

class FFmpegHLSProcessHandler:
    def __init__(self, channel_uuid, input_stream_url, stream_profile_id, user_agent_string, redis_client, worker_id):
        self.logger = logging.getLogger(f"{__name__}.FFmpegHLSProcessHandler.{channel_uuid[:8]}")
        self.channel_uuid = channel_uuid
        self.input_stream_url = input_stream_url
        self.stream_profile_id = stream_profile_id # Can be ID or name, assuming ID for now
        self.user_agent_string = user_agent_string
        self.redis_client = redis_client # Instance from HLSOutputManager
        self.worker_id = worker_id

        self.ffmpeg_process = None
        self.monitor_thread = None
        self._stop_event = threading.Event() # Used to signal monitor thread to stop
        self.current_ffmpeg_stats = {} # For holding parsed stats
        self.last_stats_update_to_redis_time = 0
        self.stats_update_interval = 10 # seconds, how often to update Redis with stats

        # Regex for parsing FFmpeg progress (adjust as needed for your FFmpeg version output)
        # Example: frame= 19 인터넷 없음 time=00:00:00.76 bitrate=N/A speed=3.02x
        # Example: frame=   40 fps= 29 q=26.0 size=      46kB time=00:00:01.22 bitrate= 308.2kbits/s speed=0.865x
        self.ffmpeg_stats_regex = re.compile(
            r"frame=\s*(?P<frame>\d+)\s*"
            r"fps=\s*(?P<fps>[\d\.]+)\s*"
            r"(q=\s*(?P<q>[\d\.-]+)\s*)?" # q can be N/A or a number
            r"size=\s*(?P<size>\S+)\s*" # e.g., 1024kB
            r"time=\s*(?P<time>[\d\:\.]+)\s*"
            r"bitrate=\s*(?P<bitrate>\S+)\s*" # e.g., 1500kbits/s or N/A
            r"(speed=\s*(?P<speed>[\d\.]+x))?" # speed can be optional
        )
        # Critical error patterns to detect in FFmpeg stderr
        self.critical_error_patterns = [
            re.compile(r"Input/output error", re.IGNORECASE),
            re.compile(r"Conversion failed!", re.IGNORECASE),
            re.compile(r"No such file or directory", re.IGNORECASE), # Example, if input URL is wrong
            re.compile(r"Connection refused", re.IGNORECASE), # Example for network issues
        ]


        # Load HLS specific configurations
        self.hls_base_path = get_hls_setting("hls_segment_path")
        self.abr_renditions = get_hls_setting("hls_abr_renditions") # This will be a list of dicts or empty

        self.hls_output_dir = os.path.join(self.hls_base_path, self.channel_uuid)
        # Master playlist name is fixed for now, could be configurable
        self.master_playlist_name = "master.m3u8" # Used if ABR, or as the only playlist if not ABR
        self.master_playlist_path = os.path.join(self.hls_output_dir, self.master_playlist_name)

        try:
            os.makedirs(self.hls_output_dir, exist_ok=True)
            self.logger.info(f"Base HLS output directory: {self.hls_output_dir}")
            if self.is_abr_active():
                for rendition in self.abr_renditions:
                    rendition_dir = os.path.join(self.hls_output_dir, rendition.get("name", str(rendition.get("height", "default"))))
                    os.makedirs(rendition_dir, exist_ok=True)
                    self.logger.info(f"Created rendition directory: {rendition_dir}")
        except OSError as e:
            self.logger.error(f"Failed to create HLS output directories for {self.channel_uuid}: {e}", exc_info=True)
            raise

        self.logger.info(f"Initialized FFmpegHLSProcessHandler for Channel: {self.channel_uuid}, Worker: {self.worker_id}. ABR Active: {self.is_abr_active()}")

    def is_abr_active(self):
        return bool(self.abr_renditions)

    def _update_channel_state(self, state):
        metadata_key = HLSRedisKeys.channel_metadata(self.channel_uuid)
        try:
            # Fetch existing metadata
            existing_metadata_str = self.redis_client.get(metadata_key)
            if existing_metadata_str:
                metadata = json.loads(existing_metadata_str)
            else:
                # This case should ideally not happen if manager initializes metadata first
                self.logger.warning(f"No existing metadata found for channel {self.channel_uuid} when updating state to {state}. Creating minimal metadata.")
                metadata = {"channel_uuid": self.channel_uuid, "owner": self.worker_id}

            metadata["state"] = state
            metadata["last_updated_at"] = time.time()
            self.redis_client.set(metadata_key, json.dumps(metadata)) # Consider adding TTL if not set by manager
            self.logger.info(f"Channel {self.channel_uuid} state updated to: {state}")
        except json.JSONDecodeError:
            self.logger.error(f"Could not decode metadata for channel {self.channel_uuid} to update state.", exc_info=True)
        except Exception as e:
            self.logger.error(f"Failed to update channel {self.channel_uuid} state to {state} in Redis: {e}", exc_info=True)

    def _update_ffmpeg_stats_in_redis(self):
        stats_key = HLSRedisKeys.ffmpeg_stats(self.channel_uuid)
        try:
            stats_to_store = self.current_ffmpeg_stats.copy()
            stats_to_store["last_updated_at_timestamp"] = time.time()
            stats_to_store["channel_uuid"] = self.channel_uuid # For easier debugging in Redis

            # TTL for stats can be shorter, e.g., manager's stats_max_age + buffer
            stats_ttl = int(get_hls_setting("hls_ffmpeg_stats_max_age")) + 60
            self.redis_client.set(stats_key, json.dumps(stats_to_store), ex=stats_ttl)
            self.last_stats_update_to_redis_time = time.time()
            self.logger.debug(f"Updated FFmpeg stats in Redis for {self.channel_uuid}: {stats_to_store}")
        except Exception as e:
            self.logger.error(f"Failed to update FFmpeg stats for {self.channel_uuid} in Redis: {e}", exc_info=True)


    def _build_ffmpeg_command(self):
        try:
            profile_model = StreamProfile.objects.get(name="HLS Proxy", command="ffmpeg")
        except StreamProfile.DoesNotExist:
            self.logger.error("Critical: Default StreamProfile 'HLS Proxy' for command 'ffmpeg' not found.", exc_info=True)
            return None
        except Exception as e:
            self.logger.error(f"Error fetching StreamProfile: {e}", exc_info=True)
            return None

        base_command_str = profile_model.parameters.format(
            streamUrl=self.input_stream_url,
            userAgent=self.user_agent_string
        )
        # Common options from profile (e.g., -i, -user_agent)
        # Note: profile.command is "ffmpeg", so it's the first part of the final command list.
        command = [profile_model.command] + base_command_str.split()

        hls_time = str(get_hls_setting("hls_default_segment_time"))
        hls_list_size = str(get_hls_setting("hls_default_list_size"))
        hls_flags_common = get_hls_setting("hls_default_flags") # Common flags for all renditions
        hls_extra_options_global_str = get_hls_setting("hls_extra_ffmpeg_options")

        if hls_extra_options_global_str:
            command.extend(hls_extra_options_global_str.split())

        if self.is_abr_active():
            self.logger.info(f"Building ABR command for {len(self.abr_renditions)} renditions.")
            stream_maps = [] # For -var_stream_map
            output_index = 0 # Keep track of output stream index for mapping

            # Common input stream mapping (assuming one video, one audio from input)
            # This might need to be more dynamic if inputs vary.
            command.extend(["-map", "0:v:0", "-map", "0:a:0"]) # Example, adjust if needed

            for i, rendition in enumerate(self.abr_renditions):
                rendition_name = rendition.get("name", str(rendition.get("height")))
                rendition_dir = os.path.join(self.hls_output_dir, rendition_name)

                # Video options for this rendition
                command.extend([f"-filter:v:{output_index}", f"scale=-2:{rendition['height']}" ]) # Scale output 'i'
                command.extend([f"-c:v:{output_index}", "libx264"]) # Assuming libx264 for encoding
                command.extend([f"-b:v:{output_index}", rendition['bitrate_video']])

                # Audio options for this rendition
                command.extend([f"-c:a:{output_index}", "aac"]) # Assuming AAC for audio
                command.extend([f"-b:a:{output_index}", rendition['bitrate_audio']])

                # Add rendition specific ffmpeg_opts
                if rendition.get("ffmpeg_opts"):
                    # These options need to be applied to specific output streams if they are per-stream
                    # This is tricky. For now, assuming they are general or correctly namespaced if needed by user.
                    # A more robust way would be to parse them or require specific format.
                    # For simplicity, adding them generally, but this might not work for all opts.
                    # Ideally, these opts should be targeted, e.g. -maxrate:v:0, -bufsize:v:0
                    # This part is complex and may need refinement based on typical ffmpeg_opts structure.
                    # For now, we'll just extend. User must ensure opts are correctly targeted.
                    command.extend(rendition["ffmpeg_opts"].split())

                # HLS options for this specific variant stream
                # No need to add -hls_time, -hls_list_size per rendition if using var_stream_map and master playlist
                # command.extend([f"-hls_segment_type", "mpegts"]) # Default
                # command.extend([f"-hls_playlist_type", "vod"]) # Or 'event' for live

                # The segment filename and variant playlist name are typically handled by -var_stream_map
                # and hls_segment_filename in the master HLS options
                stream_maps.append(f"v:{output_index},a:{output_index},name:{rendition_name}")
                output_index += 1

            # Master playlist HLS options
            command.extend(["-f", "hls"])
            command.extend(["-hls_time", hls_time])
            command.extend(["-hls_list_size", hls_list_size])
            if hls_flags_common:
                command.extend(["-hls_flags", hls_flags_common])

            # Segment filename pattern for ABR (FFmpeg replaces %v with stream index/name)
            # The path should be relative to the master playlist's directory if using hls_master_pl_name
            # or FFmpeg needs to know where to put rendition playlists for var_stream_map to work.
            # Let's use absolute paths for segment filenames for clarity with renditions in subdirs.
            # The playlist for each rendition will be in its own subdir.
            # The master playlist will reference these.
            # Segments need to be relative to their respective variant playlist.
            # So, `hls_segment_filename` should be used carefully.
            # For `var_stream_map`, FFmpeg creates variant playlists in subdirectories named after `name:` in map.
            # Segments are relative to those subdirectories.
            command.extend(["-hls_segment_filename", os.path.join(self.hls_output_dir, "%v", "segment%05d.ts")])

            command.extend(["-var_stream_map", " ".join(stream_maps)])
            command.extend(["-master_pl_name", self.master_playlist_name]) # Name of the master playlist
            command.append(os.path.join(self.hls_output_dir, self.master_playlist_name)) # Output path for master (redundant if -master_pl_name is used with -f hls?)
                                                                                       # No, this is the target for the HLS muxer overall.
                                                                                       # FFmpeg will create master.m3u8 and rendition subdirs here.
        else: # Non-ABR
            self.logger.info("Building non-ABR HLS command.")
            command.extend(["-f", "hls"])
            command.extend(["-hls_time", hls_time])
            command.extend(["-hls_list_size", hls_list_size])
            if hls_flags_common:
                command.extend(["-hls_flags", hls_flags_common])

            segment_filename = os.path.join(self.hls_output_dir, "segment%05d.ts")
            command.extend(["-hls_segment_filename", segment_filename])
            command.append(self.master_playlist_path) # Output single playlist

        self.logger.info(f"Constructed FFmpeg command: {' '.join(command)}")
        return command

    def start(self):
        if self.is_process_alive():
            self.logger.warning(f"FFmpeg process already running for channel {self.channel_uuid}.")
            return True

        # Ensure directories exist (primary and for ABR if active)
        try:
            os.makedirs(self.hls_output_dir, exist_ok=True)
            if self.is_abr_active():
                for rendition in self.abr_renditions:
                    rendition_name = rendition.get("name", str(rendition.get("height")))
                    rendition_dir = os.path.join(self.hls_output_dir, rendition_name)
                    os.makedirs(rendition_dir, exist_ok=True)
        except OSError as e:
            self.logger.error(f"Failed to create HLS output directories during start for {self.channel_uuid}: {e}", exc_info=True)
            self._update_channel_state(HLSChannelState.ERROR)
            return False

        command = self._build_ffmpeg_command()
        if not command:
            self.logger.error("FFmpeg command build failed. Cannot start process.")
            self._update_channel_state(HLSChannelState.ERROR)
            return False

        try:
            self.logger.info(f"Starting FFmpeg for channel {self.channel_uuid} (ABR: {self.is_abr_active()})...")
            self.ffmpeg_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE, # Or subprocess.DEVNULL if output is not needed
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            self._update_channel_state(HLSChannelState.GENERATING_HLS)

            self._stop_event.clear()
            self.monitor_thread = threading.Thread(target=self._monitor_ffmpeg, daemon=True, name=f"FFmpegMonitor-{self.channel_uuid[:8]}")
            self.monitor_thread.start()

            self.logger.info(f"FFmpeg process started (PID: {self.ffmpeg_process.pid}) for channel {self.channel_uuid}.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start FFmpeg process for channel {self.channel_uuid}: {e}", exc_info=True)
            self._update_channel_state(HLSChannelState.ERROR)
            self.ffmpeg_process = None
            return False

    def _monitor_ffmpeg(self):
        self.logger.info(f"FFmpeg monitor started for channel {self.channel_uuid}.")

        # Monitor stderr for FFmpeg progress and errors
        if self.ffmpeg_process and self.ffmpeg_process.stderr:
            buffer = ""
            for char_or_line in iter(lambda: self.ffmpeg_process.stderr.read(1), ''): # Read char by char
                if self._stop_event.is_set():
                    self.logger.info(f"Stop event received, exiting FFmpeg monitor for {self.channel_uuid}.")
                    break

                buffer += char_or_line
                if '\n' in buffer or '\r' in buffer: # Process on newline
                    line, buffer = buffer.split('\n', 1) if '\n' in buffer else buffer.split('\r', 1)
                    line = line.strip()

                    if not line:
                        continue

                    self.logger.debug(f"FFMPEG_LOG ({self.channel_uuid}): {line}")

                    # Check for critical errors
                    for pattern in self.critical_error_patterns:
                        if pattern.search(line):
                            self.logger.error(f"Critical FFmpeg error detected for {self.channel_uuid}: {line}")
                            self.current_ffmpeg_stats["last_error_line"] = line
                            self._update_ffmpeg_stats_in_redis() # Update with last error
                            self._update_channel_state(HLSChannelState.ERROR)
                            # No need to break here, let FFmpeg process naturally terminate or be stopped by manager
                            # If FFmpeg exits due to this error, the return code check below will handle it.

                    # Parse stats
                    match = self.ffmpeg_stats_regex.search(line)
                    if match:
                        stats = match.groupdict()
                        self.current_ffmpeg_stats.update({
                            "frame": stats.get("frame"),
                            "fps": stats.get("fps"),
                            "size_kb": stats.get("size"), # Raw size string
                            "time_processed": stats.get("time"),
                            "bitrate_kbits": stats.get("bitrate"), # Raw bitrate string
                            "speed": stats.get("speed", "N/A").replace('x', '') if stats.get("speed") else "N/A",
                            "last_raw_line": line # Store the raw line for debugging
                        })
                        # Convert speed to float if possible
                        try:
                            if self.current_ffmpeg_stats["speed"] != "N/A":
                                self.current_ffmpeg_stats["speed_float"] = float(self.current_ffmpeg_stats["speed"])
                        except ValueError:
                            self.current_ffmpeg_stats["speed_float"] = None # Or some default like 1.0 if N/A

                        # Update Redis periodically
                        if time.time() - self.last_stats_update_to_redis_time > self.stats_update_interval:
                            self._update_ffmpeg_stats_in_redis()

                    # Heuristic for manifest ready (can be improved)
                    if "playlist.m3u8" in line and "writing" in line:
                        # Only update to ACTIVE if currently GENERATING_HLS
                        # This avoids flapping if "writing playlist" appears multiple times
                        metadata_key = HLSRedisKeys.channel_metadata(self.channel_uuid)
                        current_metadata_str = self.redis_client.get(metadata_key)
                        if current_metadata_str:
                            current_meta = json.loads(current_metadata_str)
                            if current_meta.get("state") == HLSChannelState.GENERATING_HLS:
                                self._update_channel_state(HLSChannelState.ACTIVE)

            # After loop, if there's remaining buffer, process it (though char by char read might make this rare)
            if buffer.strip():
                 self.logger.debug(f"FFMPEG_LOG_BUFFER_END ({self.channel_uuid}): {buffer.strip()}")


        if self._stop_event.is_set(): # If monitoring was exited due to stop() call
            self.logger.info(f"FFmpeg monitor for {self.channel_uuid} stopped via signal.")
            return

        # Process has exited on its own
        self.logger.info(f"FFmpeg process for channel {self.channel_uuid} appears to have exited (stderr stream ended).")
        if self.ffmpeg_process: # Check if process object still exists
            return_code = self.ffmpeg_process.wait(timeout=1) # Get return code, with a small timeout
            self.logger.info(f"FFmpeg process for channel {self.channel_uuid} exited with code {return_code}.")

            # If state is already ERROR (set by critical pattern), don't override
            metadata_key = HLSRedisKeys.channel_metadata(self.channel_uuid)
            current_metadata_str = self.redis_client.get(metadata_key)
            current_state = None
            if current_metadata_str:
                current_state = json.loads(current_metadata_str).get("state")

            if current_state != HLSChannelState.ERROR:
                if return_code == 0:
                    self._update_channel_state(HLSChannelState.STOPPED)
                else:
                    self._update_channel_state(HLSChannelState.ERROR)

            self.current_ffmpeg_stats["exit_code"] = return_code
            self._update_ffmpeg_stats_in_redis() # Final stats update
            self.ffmpeg_process = None # Clear the process object
        else:
            self.logger.warning(f"FFmpeg monitor for {self.channel_uuid} found no process object after stderr stream ended, or process already cleared.")
            # Check Redis state, if not already ERROR or STOPPED, mark as ERROR.
            metadata_key = HLSRedisKeys.channel_metadata(self.channel_uuid)
            current_metadata_str = self.redis_client.get(metadata_key)
            if current_metadata_str:
                current_meta = json.loads(current_metadata_str)
                if current_meta.get("state") not in [HLSChannelState.ERROR, HLSChannelState.STOPPED, HLSChannelState.STOPPING_FFMPEG]:
                    self._update_channel_state(HLSChannelState.ERROR)


    def stop(self):
        self.logger.info(f"Attempting to stop FFmpeg process for channel {self.channel_uuid}.")
        self._stop_event.set() # Signal monitor thread to stop

        if not self.ffmpeg_process or not self.is_process_alive():
            self.logger.info(f"FFmpeg process for channel {self.channel_uuid} not running or already stopped.")
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=2) # Give monitor a chance to exit
            self._update_channel_state(HLSChannelState.STOPPED) # Ensure state is correct
            self.ffmpeg_process = None
            return

        try:
            self.logger.info(f"Terminating FFmpeg process (PID: {self.ffmpeg_process.pid}) for {self.channel_uuid}...")
            self.ffmpeg_process.terminate()
            try:
                self.ffmpeg_process.wait(timeout=5) # Wait for graceful termination
                self.logger.info(f"FFmpeg process for {self.channel_uuid} terminated gracefully.")
            except subprocess.TimeoutExpired:
                self.logger.warning(f"FFmpeg process for {self.channel_uuid} did not terminate gracefully after 5s. Killing...")
                self.ffmpeg_process.kill()
                self.ffmpeg_process.wait(timeout=2) # Wait for kill
                self.logger.info(f"FFmpeg process for {self.channel_uuid} killed.")

            self._update_channel_state(HLSChannelState.STOPPED)

        except Exception as e:
            self.logger.error(f"Error stopping FFmpeg process for {self.channel_uuid}: {e}", exc_info=True)
            self._update_channel_state(HLSChannelState.ERROR) # Mark as error if stop fails unexpectedly
        finally:
            self.ffmpeg_process = None
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=5) # Ensure monitor thread is cleaned up
                if self.monitor_thread.is_alive():
                    self.logger.warning(f"FFmpeg monitor thread for {self.channel_uuid} did not exit cleanly after process stop.")

    def is_process_alive(self):
        return self.ffmpeg_process is not None and self.ffmpeg_process.poll() is None

    def get_ffmpeg_stats(self):
        # Future: Parse FFmpeg output for bitrate, FPS, etc.
        # For now, basic status based on process presence and Redis state.
        # Try to fetch latest stats from Redis
        stats_key = HLSRedisKeys.ffmpeg_stats(self.channel_uuid)
        try:
            stats_str = self.redis_client.get(stats_key)
            if stats_str:
                stats = json.loads(stats_str)
                # Add current process status if available locally
                stats["is_process_ объективно_alive_locally"] = self.is_process_alive()
                if self.is_process_alive() and self.ffmpeg_process:
                    stats["local_pid"] = self.ffmpeg_process.pid
                return stats
        except Exception as e:
            self.logger.warning(f"Could not fetch/parse FFmpeg stats from Redis for {self.channel_uuid}: {e}")

        # Fallback if Redis fails or no stats yet
        if self.is_process_alive() and self.ffmpeg_process:
            return {"status": "running_local_check", "pid": self.ffmpeg_process.pid, "message": "Stats not yet in Redis or Redis error."}

        # Fallback to channel metadata state if stats key is missing
        try:
            metadata_key = HLSRedisKeys.channel_metadata(self.channel_uuid)
            metadata_str = self.redis_client.get(metadata_key)
            if metadata_str:
                metadata = json.loads(metadata_str)
                return {"status": metadata.get("state", HLSChannelState.STOPPED), "message": "No detailed FFmpeg stats available."}
        except Exception as e:
            self.logger.warning(f"Could not fetch Redis metadata for {self.channel_uuid} as fallback stats: {e}")

        return {"status": HLSChannelState.STOPPED, "message": "No FFmpeg stats available and metadata fetch failed."}
