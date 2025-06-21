import logging
import threading
import time
import uuid
import json

from core.utils import RedisClient
from .redis_keys import HLSRedisKeys
from .constants import HLSChannelState
from .process_handler import FFmpegHLSProcessHandler
from .config import get_hls_setting # For stall detection settings

# Attempt to import EventType, define placeholder if it fails (for isolated dev)
try:
    from apps.proxy.ts_proxy.constants import EventType
except ImportError:
    logger.warning("Could not import EventType from ts_proxy.constants. Using placeholder values.")
    class EventType: # Placeholder
        STREAM_SWITCHED = "stream_switched" # Placeholder event name
        # Add other event types if needed by HLS manager in future

logger = logging.getLogger(__name__)

DEFAULT_OWNERSHIP_TTL = 60  # seconds
CLEANUP_INTERVAL = 15       # seconds
WORKER_HEARTBEAT_TTL = CLEANUP_INTERVAL * 3 # Should be longer than cleanup interval


class HLSOutputManager:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        if HLSOutputManager._instance is not None:
            raise Exception("HLSOutputManager is a singleton, use get_instance()")

        self.worker_id = f"hls-worker-{uuid.uuid4()}"
        logger.info(f"Initializing HLSOutputManager with worker_id: {self.worker_id}")

        self.redis_client = RedisClient().get_client()

        self.ffmpeg_handlers = {}  # {channel_uuid: FFmpegHLSProcessHandler_instance}
        self.channel_threads = {}  # {channel_uuid: threading.Thread_instance}

        self._stop_event = threading.Event()
        self._cleanup_thread = None
        self._event_listener_thread = None # For Redis Pub/Sub
        self._pubsub = None # PubSub object

        self._start_cleanup_thread()
        self._start_event_listener() # Start listening to Redis events

        HLSOutputManager._instance = self

    def _execute_redis_command(self, command, *args, **kwargs):
        """Helper to execute Redis commands with error handling."""
        try:
            return getattr(self.redis_client, command)(*args, **kwargs)
        except Exception as e:
            logger.error(f"Redis command '{command}' failed: {e}", exc_info=True)
            return None

    # --- Channel Ownership ---
    def get_channel_owner(self, channel_uuid):
        owner_key = HLSRedisKeys.owner(channel_uuid)
        owner_data = self._execute_redis_command("get", owner_key)
        if owner_data:
            try:
                return json.loads(owner_data).get("worker_id")
            except json.JSONDecodeError:
                logger.warning(f"Could not decode owner data for channel {channel_uuid}: {owner_data}")
                return None
        return None

    def am_i_owner(self, channel_uuid):
        return self.get_channel_owner(channel_uuid) == self.worker_id

    def try_acquire_ownership(self, channel_uuid, ttl=DEFAULT_OWNERSHIP_TTL):
        owner_key = HLSRedisKeys.owner(channel_uuid)
        owner_data = json.dumps({"worker_id": self.worker_id, "acquired_at": time.time()})

        # Try to set the key if it doesn't exist (nx=True) with an expiration (ex=ttl)
        acquired = self._execute_redis_command("set", owner_key, owner_data, ex=ttl, nx=True)
        if acquired:
            logger.info(f"Worker {self.worker_id} acquired ownership of channel {channel_uuid} for {ttl}s.")
            return True
        else:
            current_owner = self.get_channel_owner(channel_uuid)
            logger.warning(f"Worker {self.worker_id} failed to acquire ownership of channel {channel_uuid}. Currently owned by: {current_owner}")
            return False

    def release_ownership(self, channel_uuid):
        if self.am_i_owner(channel_uuid):
            owner_key = HLSRedisKeys.owner(channel_uuid)
            self._execute_redis_command("delete", owner_key)
            logger.info(f"Worker {self.worker_id} released ownership of channel {channel_uuid}.")
            return True
        return False

    def extend_ownership(self, channel_uuid, ttl=DEFAULT_OWNERSHIP_TTL):
        if self.am_i_owner(channel_uuid):
            owner_key = HLSRedisKeys.owner(channel_uuid)
            owner_data = json.dumps({"worker_id": self.worker_id, "extended_at": time.time()})
            # Set the key, updating its TTL (xx=False means only if it exists, but we are owner so it should)
            # For extend, we just set it again with new TTL if we are the owner.
            # Using "set" with "ex" will update the TTL. We ensure we are the owner first.
            if self._execute_redis_command("set", owner_key, owner_data, ex=ttl):
                 logger.debug(f"Worker {self.worker_id} extended ownership of channel {channel_uuid} for {ttl}s.")
                 return True
            else:
                 logger.warning(f"Worker {self.worker_id} failed to extend ownership for channel {channel_uuid}, though am_i_owner was true.")
                 return False
        return False

    # --- Channel Lifecycle ---
    def initialize_channel_hls(self, channel_uuid, input_stream_url, stream_profile_id, user_agent_string):
        logger.info(f"Attempting to initialize HLS for channel {channel_uuid} by worker {self.worker_id}")

        # Check if channel is already active or owned by another worker
        metadata_key = HLSRedisKeys.channel_metadata(channel_uuid)
        existing_metadata_str = self._execute_redis_command("get", metadata_key)

        if existing_metadata_str:
            try:
                existing_metadata = json.loads(existing_metadata_str)
                current_owner = existing_metadata.get("owner")
                current_state = existing_metadata.get("state")
                if current_owner and current_owner != self.worker_id:
                    logger.info(f"Channel {channel_uuid} is already owned by worker {current_owner}. Current state: {current_state}. Worker {self.worker_id} will not take action.")
                    return True # Successfully handled by another worker
                elif current_owner == self.worker_id and channel_uuid in self.ffmpeg_handlers:
                    logger.info(f"Channel {channel_uuid} is already being managed by this worker {self.worker_id}. State: {current_state}")
                    return True
            except json.JSONDecodeError:
                logger.warning(f"Could not decode existing metadata for channel {channel_uuid}: {existing_metadata_str}")
                # Proceed to try and acquire if metadata is corrupt

        if not self.try_acquire_ownership(channel_uuid):
            return False # Failed to acquire ownership or already owned by another

        try:
            logger.info(f"Worker {self.worker_id} acquired ownership for channel {channel_uuid}. Proceeding with initialization.")

            metadata = {
                "channel_uuid": channel_uuid,
                "state": HLSChannelState.STARTING_FFMPEG,
                "owner": self.worker_id,
                "input_url": input_stream_url,
                "stream_profile_id": stream_profile_id,
                "user_agent": user_agent_string,
                "started_at": time.time(),
                "hls_output_path": f"/opt/dispatcharr/hls/{channel_uuid}/" # Example path
            }
            self._execute_redis_command("set", metadata_key, json.dumps(metadata), ex=DEFAULT_OWNERSHIP_TTL * 2) # Metadata TTL longer than ownership

            handler = FFmpegHLSProcessHandler(
                channel_uuid=channel_uuid,
                input_stream_url=input_stream_url,
                stream_profile_id=stream_profile_id,
                user_agent_string=user_agent_string,
                redis_client=self.redis_client,
                worker_id=self.worker_id
            )
            self.ffmpeg_handlers[channel_uuid] = handler

            thread = threading.Thread(target=handler.start, name=f"HLSHandler-{channel_uuid}")
            self.channel_threads[channel_uuid] = thread
            thread.start()

            logger.info(f"Successfully initialized HLS and started handler for channel {channel_uuid} by worker {self.worker_id}.")
            return True

        except Exception as e:
            logger.error(f"Error during HLS initialization for channel {channel_uuid} by {self.worker_id}: {e}", exc_info=True)
            self.release_ownership(channel_uuid) # Release if setup failed
            # Clean up partial setup
            if channel_uuid in self.ffmpeg_handlers:
                del self.ffmpeg_handlers[channel_uuid]
            if channel_uuid in self.channel_threads:
                # Ensure thread is not left running if it started
                # This is tricky if handler.start() is blocking or long.
                # For a stub, it's okay. Real implementation needs care.
                del self.channel_threads[channel_uuid]
            self._execute_redis_command("delete", metadata_key) # Remove potentially partial metadata
            return False

    def stop_channel_hls(self, channel_uuid):
        logger.info(f"Attempting to stop HLS for channel {channel_uuid} by worker {self.worker_id}")

        # Check if we are the owner before trying to stop
        if not self.am_i_owner(channel_uuid) and channel_uuid not in self.ffmpeg_handlers:
            logger.warning(f"Worker {self.worker_id} is not the owner of channel {channel_uuid} and has no local handler. Cannot stop.")
            # It might be prudent to still clean up Redis keys if this worker *thought* it was owner
            # but this function is usually called when this worker *is* the owner.
            return False

        handler = self.ffmpeg_handlers.get(channel_uuid)
        if handler:
            try:
                handler.stop()
                thread = self.channel_threads.get(channel_uuid)
                if thread and thread.is_alive():
                    thread.join(timeout=10) # Wait for thread to finish
                    if thread.is_alive():
                        logger.warning(f"Thread for channel {channel_uuid} did not terminate in time.")
            except Exception as e:
                logger.error(f"Exception while stopping handler for channel {channel_uuid}: {e}", exc_info=True)

        # Local cleanup
        if channel_uuid in self.ffmpeg_handlers:
            del self.ffmpeg_handlers[channel_uuid]
        if channel_uuid in self.channel_threads:
            del self.channel_threads[channel_uuid]

        # Redis cleanup (only if we were the definitive owner)
        # If ownership was lost, the new owner should manage Redis state.
        # However, if we are explicitly stopping, we should clean up.
        if self.release_ownership(channel_uuid) or not self.get_channel_owner(channel_uuid): # if successfully released or no owner
            logger.info(f"Cleaning up Redis keys for channel {channel_uuid} after stopping.")
            self._execute_redis_command("delete", HLSRedisKeys.channel_metadata(channel_uuid))
            self._execute_redis_command("delete", HLSRedisKeys.ffmpeg_stats(channel_uuid))
            # Owner key is deleted by release_ownership

        logger.info(f"HLS channel {channel_uuid} stopped and cleaned up by worker {self.worker_id}.")
        return True

    # --- Cleanup Thread ---
    def _start_cleanup_thread(self):
        self._cleanup_thread = threading.Thread(target=self._cleanup_task, daemon=True, name="HLSManagerCleanup")
        self._cleanup_thread.start()
        logger.info(f"HLSOutputManager cleanup thread started for worker {self.worker_id}.")

    def _cleanup_task(self):
        while not self._stop_event.is_set():
            try:
                # Send worker heartbeat
                heartbeat_key = HLSRedisKeys.worker_heartbeat(self.worker_id)
                self._execute_redis_command("set", heartbeat_key, time.time(), ex=WORKER_HEARTBEAT_TTL)

                # Iterate over a copy of keys in case of modification during iteration
                for channel_uuid in list(self.ffmpeg_handlers.keys()):
                    handler = self.ffmpeg_handlers.get(channel_uuid)
                    if not handler: # Should not happen if list(keys()) is used but good practice
                        continue

                    if self.am_i_owner(channel_uuid):
                        self.extend_ownership(channel_uuid)

                        # Health Check Logic
                        try:
                            stats_key = HLSRedisKeys.ffmpeg_stats(channel_uuid)
                            metadata_key = HLSRedisKeys.channel_metadata(channel_uuid)

                            ffmpeg_stats_str = self._execute_redis_command("get", stats_key)
                            channel_metadata_str = self._execute_redis_command("get", metadata_key)

                            ffmpeg_stats = json.loads(ffmpeg_stats_str) if ffmpeg_stats_str else {}
                            channel_metadata = json.loads(channel_metadata_str) if channel_metadata_str else {}

                            current_channel_state = channel_metadata.get("state")
                            last_stats_update = ffmpeg_stats.get("last_updated_at_timestamp", 0)
                            ffmpeg_speed = float(ffmpeg_stats.get("speed_float", 1.0) if ffmpeg_stats.get("speed_float") is not None else 1.0) # Default to 1.0 if None

                            max_age_stats = int(get_hls_setting("hls_ffmpeg_stats_max_age"))
                            stall_speed_threshold = float(get_hls_setting("hls_ffmpeg_stall_speed_threshold"))
                            # stall_duration_threshold = int(get_hls_setting("hls_ffmpeg_stall_duration_threshold")) # This needs more complex state over time

                            restart_reason = None

                            if current_channel_state == HLSChannelState.ERROR:
                                restart_reason = "Channel in ERROR state."
                            elif time.time() - last_stats_update > max_age_stats:
                                restart_reason = f"FFmpeg stats outdated (last update: {time.time() - last_stats_update:.0f}s ago, max_age: {max_age_stats}s)."
                            elif current_channel_state == HLSChannelState.GENERATING_HLS or current_channel_state == HLSChannelState.ACTIVE:
                                if ffmpeg_speed < stall_speed_threshold:
                                    # Basic stall check. A more robust check would track speed over a duration.
                                    # For now, if speed is low on a check, flag it.
                                    # We'd need to store "first_stalled_at" in Redis or handler to implement duration.
                                    # Let's assume for now a single low speed check is enough to trigger concern.
                                    restart_reason = f"FFmpeg speed too low ({ffmpeg_speed:.2f}x, threshold: {stall_speed_threshold:.2f}x)."

                            if restart_reason:
                                logger.warning(f"Health check failed for channel {channel_uuid} (owner: {self.worker_id}). Reason: {restart_reason}. Attempting restart.")

                                # Retrieve necessary info for restart BEFORE stopping/cleaning
                                stored_input_url = channel_metadata.get("input_url")
                                stored_profile_id = channel_metadata.get("stream_profile_id")
                                stored_user_agent = channel_metadata.get("user_agent")

                                if stored_input_url and stored_profile_id:
                                    self.stop_channel_hls(channel_uuid) # Stop existing process and clean up
                                    logger.info(f"Restarting HLS for channel {channel_uuid} due to health check failure.")
                                    # Brief pause before restarting
                                    time.sleep(5)
                                    self.initialize_channel_hls(channel_uuid, stored_input_url, stored_profile_id, stored_user_agent)
                                else:
                                    logger.error(f"Cannot restart channel {channel_uuid}: missing input_url or stream_profile_id in metadata.")
                                    # Potentially set to error state if critical info missing
                                    self.stop_channel_hls(channel_uuid) # Stop it anyway if info is missing for restart

                        except json.JSONDecodeError as jde:
                            logger.error(f"Error decoding JSON for health check of channel {channel_uuid}: {jde}", exc_info=True)
                        except Exception as e_health:
                            logger.error(f"Error during health check for channel {channel_uuid}: {e_health}", exc_info=True)

                    else: # Lost ownership
                        logger.warning(f"Worker {self.worker_id} lost ownership of channel {channel_uuid} (or it expired). Cleaning up local resources.")
                        if handler:
                            handler.stop() # Stop the process
                            thread = self.channel_threads.get(channel_uuid)
                            if thread and thread.is_alive():
                                thread.join(timeout=5)
                        # Remove from local dictionaries
                        if channel_uuid in self.ffmpeg_handlers:
                            del self.ffmpeg_handlers[channel_uuid]
                        if channel_uuid in self.channel_threads:
                            del self.channel_threads[channel_uuid]
                        logger.info(f"Local resources for channel {channel_uuid} cleaned up by worker {self.worker_id} after ownership loss.")
            except Exception as e:
                logger.error(f"Error in HLSOutputManager cleanup task for worker {self.worker_id}: {e}", exc_info=True)

            time.sleep(CLEANUP_INTERVAL)
        logger.info(f"HLSOutputManager cleanup thread stopped for worker {self.worker_id}.")

    def shutdown(self):
        logger.info(f"Shutting down HLSOutputManager for worker {self.worker_id}...")
        self._stop_event.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=CLEANUP_INTERVAL + 5) # Wait for cleanup to finish its cycle

        # Stop all managed channels by this worker
        for channel_uuid in list(self.ffmpeg_handlers.keys()):
            logger.info(f"Shutting down channel {channel_uuid} as part of manager shutdown for worker {self.worker_id}.")
            self.stop_channel_hls(channel_uuid) # This will also attempt to release ownership

        # Final heartbeat to mark as offline (or delete heartbeat)
        self._execute_redis_command("delete", HLSRedisKeys.worker_heartbeat(self.worker_id))

        if self._pubsub:
            try:
                self._pubsub.unsubscribe()
                self._pubsub.close() # Close the pubsub connection
                logger.info(f"HLSOutputManager {self.worker_id} PubSub unsubscribed and closed.")
            except Exception as e:
                logger.error(f"Error during PubSub cleanup for {self.worker_id}: {e}", exc_info=True)

        if self._event_listener_thread and self._event_listener_thread.is_alive():
            self._event_listener_thread.join(timeout=5) # Wait for listener to finish

        logger.info(f"HLSOutputManager {self.worker_id} shut down complete.")


    # --- Event Listener for Input Stream Failover ---
    def _start_event_listener(self):
        self._pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)

        # Define the event pattern to subscribe to.
        # This pattern should match events indicating an input stream URL change.
        # Using ts_proxy events as a placeholder, adjust if a different system is used.
        event_pattern = f"{EventType.STREAM_SWITCHED}:*" # Subscribe to all stream switched events
        # Or a more generic one if applicable: "dispatcharr:stream_updated:*"

        try:
            self._pubsub.psubscribe(event_pattern) # Using psubscribe for pattern matching
            logger.info(f"HLSOutputManager {self.worker_id} subscribed to Redis event pattern: {event_pattern}")
        except Exception as e:
            logger.error(f"HLSOutputManager {self.worker_id} failed to subscribe to Redis events ({event_pattern}): {e}", exc_info=True)
            return

        self._event_listener_thread = threading.Thread(target=self._event_loop, daemon=True, name="HLSEventListener")
        self._event_listener_thread.start()
        logger.info(f"HLSOutputManager event listener thread started for worker {self.worker_id}.")

    def _event_loop(self):
        logger.info(f"HLSOutputManager {self.worker_id} event loop started.")
        while not self._stop_event.is_set():
            try:
                message = self._pubsub.get_message(timeout=1.0) # Timeout to allow periodic check of _stop_event
                if message:
                    self._handle_event_message(message)
            except ConnectionError as ce: # Handle Redis connection errors
                logger.error(f"HLSOutputManager {self.worker_id} Redis PubSub connection error: {ce}. Attempting to reconnect...", exc_info=True)
                # Attempt to re-establish pubsub or wait before retrying
                time.sleep(10) # Wait before trying to get messages again
                try:
                    # Re-subscribe if connection was lost. This might need more robust handling.
                    event_pattern = f"{EventType.STREAM_SWITCHED}:*"
                    self._pubsub.psubscribe(event_pattern)
                    logger.info(f"HLSOutputManager {self.worker_id} re-subscribed to Redis events after connection error.")
                except Exception as resub_e:
                    logger.error(f"HLSOutputManager {self.worker_id} failed to re-subscribe to Redis events: {resub_e}", exc_info=True)
                    time.sleep(10) # Wait longer if re-subscribe fails
            except Exception as e:
                logger.error(f"HLSOutputManager {self.worker_id} error in event loop: {e}", exc_info=True)
                time.sleep(5) # Brief pause on other exceptions
        logger.info(f"HLSOutputManager {self.worker_id} event loop stopped.")

    def _handle_event_message(self, message):
        try:
            if message.get("type") != "pmessage": # We used psubscribe
                return

            event_channel = message.get("channel")
            if isinstance(event_channel, bytes):
                event_channel = event_channel.decode('utf-8')

            event_data_str = message.get("data")
            if isinstance(event_data_str, bytes):
                event_data_str = event_data_str.decode('utf-8')

            logger.info(f"HLS Manager {self.worker_id} received event on channel '{event_channel}': {event_data_str}")

            # Assuming the actual event name is part of the channel string with psubscribe
            # e.g., "ts_proxy:events:stream_switched:channel_uuid_here"
            # Or, the event_type is inside the JSON data. For now, let's assume data contains event_type.

            event_payload = json.loads(event_data_str)
            actual_event_type = event_payload.get("event_type") # Or determine from event_channel if structured that way

            if actual_event_type == EventType.STREAM_SWITCHED:
                data = event_payload.get("data", {})
                channel_uuid = data.get("channel_id") # Assuming this is the HLS output channel's UUID
                new_input_url = data.get("new_stream_url")

                if not channel_uuid or not new_input_url:
                    logger.warning(f"HLS Manager {self.worker_id} received incomplete STREAM_SWITCHED event: {data}")
                    return

                if self.am_i_owner(channel_uuid):
                    logger.info(f"HLS Manager {self.worker_id} (owner of {channel_uuid}) received STREAM_SWITCHED event. New URL: {new_input_url}. Attempting HLS restart.")

                    # Retrieve other necessary parameters from current HLS metadata
                    metadata_key = HLSRedisKeys.channel_metadata(channel_uuid)
                    channel_metadata_str = self._execute_redis_command("get", metadata_key)
                    if not channel_metadata_str:
                        logger.error(f"Cannot restart HLS for {channel_uuid}: Failed to retrieve current metadata.")
                        return

                    try:
                        channel_metadata = json.loads(channel_metadata_str)
                    except json.JSONDecodeError:
                        logger.error(f"Cannot restart HLS for {channel_uuid}: Failed to parse current metadata: {channel_metadata_str}")
                        return

                    stored_profile_id = channel_metadata.get("stream_profile_id")
                    stored_user_agent = channel_metadata.get("user_agent")

                    if not stored_profile_id: # user_agent might be optional or default
                        logger.error(f"Cannot restart HLS for {channel_uuid}: stream_profile_id missing from metadata.")
                        return

                    # Stop current HLS process
                    self.stop_channel_hls(channel_uuid)

                    # Small delay before re-initializing
                    time.sleep(2)

                    # Re-initialize with the new input URL
                    logger.info(f"Re-initializing HLS for channel {channel_uuid} with new URL: {new_input_url}")
                    self.initialize_channel_hls(channel_uuid, new_input_url, stored_profile_id, stored_user_agent)
                else:
                    logger.debug(f"HLS Manager {self.worker_id} received STREAM_SWITCHED for {channel_uuid} but is not the owner. Ignoring.")
            else:
                logger.debug(f"HLS Manager {self.worker_id} received unhandled event type '{actual_event_type}' on channel '{event_channel}'.")

        except json.JSONDecodeError:
            logger.error(f"HLS Manager {self.worker_id} failed to decode JSON from event message: {message.get('data')}", exc_info=True)
        except Exception as e:
            logger.error(f"HLS Manager {self.worker_id} error handling event message: {e}", exc_info=True)


# Example of how to get the manager (optional, for direct testing or specific app integration)
# if __name__ == '__main__':
#     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     manager = HLSOutputManager.get_instance()
#     try:
#         # Keep main thread alive to observe worker
#         while True:
#             time.sleep(1)
#     except KeyboardInterrupt:
#         logger.info("Shutdown signal received.")
#     finally:
#         manager.shutdown()
