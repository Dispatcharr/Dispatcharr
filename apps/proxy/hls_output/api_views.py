import logging
import json

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated # Assuming standard DRF auth

from django.shortcuts import get_object_or_404
from django.http import Http404

from apps.channels.models import Channel
from core.models import StreamProfile, UserAgent, CoreSettings # UserAgent for default UA string
from core.utils import RedisClient # For HLSChannelStatusView direct access

from .manager import HLSOutputManager # Corrected relative import
from .constants import HLSChannelState
from .redis_keys import HLSRedisKeys

logger = logging.getLogger(__name__)

class HLSChannelStartStopView(APIView):
    permission_classes = [IsAuthenticated] # Or your project's default

    def post(self, request, channel_uuid, action):
        manager = HLSOutputManager.get_instance()

        try:
            # Ensure channel_uuid is a string for consistency, though path converter handles UUID object
            channel_uuid_str = str(channel_uuid)
            channel = get_object_or_404(Channel, uuid=channel_uuid_str)
        except Http404:
            return Response({"error": "Channel not found"}, status=status.HTTP_404_NOT_FOUND)

        if action.lower() == "start":
            logger.info(f"API request to START HLS for channel: {channel_uuid_str}")

            first_stream = channel.streams.filter(enabled=True, is_backup=False).order_by('priority').first()
            if not first_stream or not first_stream.url:
                first_stream = channel.streams.filter(enabled=True, is_backup=True).order_by('priority').first()
                if not first_stream or not first_stream.url:
                    logger.warning(f"No active source streams found for channel {channel_uuid_str} to start HLS.")
                    return Response({"error": "Channel has no active source streams"}, status=status.HTTP_400_BAD_REQUEST)

            source_stream_url = first_stream.url

            try:
                hls_proxy_profile = StreamProfile.objects.get(name="HLS Proxy", command="ffmpeg")
            except StreamProfile.DoesNotExist:
                logger.error("HLS Proxy stream profile not found in database.")
                return Response({"error": "HLS Proxy stream profile not found"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            default_ua_string = "Dispatcharr/1.0 HLS API" # Fallback
            try:
                default_user_agent_obj = UserAgent.objects.filter(is_default=True).first()
                if default_user_agent_obj:
                    default_ua_string = default_user_agent_obj.user_agent_string
                else:
                    default_ua_string = CoreSettings.get_setting("default_user_agent", default_ua_string)
            except Exception as e:
                logger.warning(f"Could not fetch default UserAgent for HLS init via API: {e}")

            success = manager.initialize_channel_hls(
                channel_uuid_str,
                source_stream_url,
                hls_proxy_profile.id,
                default_ua_string
            )
            if success:
                return Response({"message": f"HLS generation initiated for channel {channel_uuid_str}."}, status=status.HTTP_200_OK)
            else:
                # Check current state, maybe another worker owns it or an error occurred
                metadata_key = HLSRedisKeys.channel_metadata(channel_uuid_str)
                metadata_str = manager.redis_client.get(metadata_key)
                current_owner = None
                current_state = "Unknown"
                if metadata_str:
                    try:
                        metadata = json.loads(metadata_str)
                        current_owner = metadata.get("owner")
                        current_state = metadata.get("state", "Unknown")
                    except json.JSONDecodeError:
                        pass

                if current_owner and current_owner != manager.worker_id:
                    logger.info(f"HLS for channel {channel_uuid_str} already managed by worker {current_owner}.")
                    return Response({"message": f"HLS for channel {channel_uuid_str} already managed by another worker ({current_owner}). Current state: {current_state}."}, status=status.HTTP_200_OK)

                logger.error(f"Failed to start HLS generation for channel {channel_uuid_str} via API. Current state: {current_state}, Owner: {current_owner}")
                return Response({"error": f"Failed to start HLS generation for channel {channel_uuid_str}. Current state: {current_state}."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        elif action.lower() == "stop":
            logger.info(f"API request to STOP HLS for channel: {channel_uuid_str}")
            manager.stop_channel_hls(channel_uuid_str)
            return Response({"message": f"HLS generation stop requested for channel {channel_uuid_str}."}, status=status.HTTP_200_OK)

        else:
            logger.warning(f"Invalid action '{action}' requested for HLS channel {channel_uuid_str} via API.")
            return Response({"error": f"Invalid action: {action}. Must be 'start' or 'stop'."}, status=status.HTTP_400_BAD_REQUEST)


class HLSChannelStatusView(APIView):
    permission_classes = [IsAuthenticated] # Or your project's default

    def get(self, request, channel_uuid):
        # manager = HLSOutputManager.get_instance() # Not strictly needed if we only use redis_client from RedisClient()
        channel_uuid_str = str(channel_uuid)

        try:
            # Validate channel exists, though status can exist even if channel is deleted later
            get_object_or_404(Channel, uuid=channel_uuid_str)
        except Http404:
            # Allow fetching status even if channel deleted, as Redis keys might persist for a while
            logger.warning(f"Channel {channel_uuid_str} not found in DB, but fetching HLS status from Redis.")
            pass


        redis_client = RedisClient().get_client()
        response_data = {
            "channel_id": channel_uuid_str,
            "metadata": None,
            "ffmpeg_stats": None,
        }

        if not redis_client:
            logger.error("Redis client not available for HLSChannelStatusView.")
            return Response({"error": "Redis client not available"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            metadata_key = HLSRedisKeys.channel_metadata(channel_uuid_str)
            metadata_str = redis_client.get(metadata_key)
            if metadata_str:
                response_data["metadata"] = json.loads(metadata_str)
            else:
                response_data["metadata"] = {"state": HLSChannelState.STOPPED, "message": "No metadata found in Redis."}

            stats_key = HLSRedisKeys.ffmpeg_stats(channel_uuid_str)
            stats_str = redis_client.get(stats_key)
            if stats_str:
                response_data["ffmpeg_stats"] = json.loads(stats_str)
            else:
                 response_data["ffmpeg_stats"] = {"message": "No FFmpeg stats found in Redis."}
                 if response_data["metadata"].get("state") not in [HLSChannelState.STOPPED, HLSChannelState.IDLE, HLSChannelState.ERROR]:
                     # If metadata suggests it should be running but no stats, it's a potential issue
                     response_data["ffmpeg_stats"]["warning"] = "Process might be active but no detailed stats available."


        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from Redis for HLS status of {channel_uuid_str}: {e}")
            # Return partial data if some was fetched
            if response_data["metadata"] is None and response_data["ffmpeg_stats"] is None:
                 return Response({"error": "Failed to decode HLS status data from Redis"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"Generic error fetching HLS status for {channel_uuid_str} from Redis: {e}", exc_info=True)
            return Response({"error": "Failed to fetch HLS status data from Redis"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(response_data, status=status.HTTP_200_OK)
