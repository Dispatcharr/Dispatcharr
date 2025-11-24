import json
import threading
import time
import random
import re
import pathlib
from django.http import StreamingHttpResponse, JsonResponse, HttpResponseRedirect, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from apps.proxy.config import TSConfig as Config
from .server import ProxyServer
from .channel_status import ChannelStatus
from .stream_generator import create_stream_generator
from .utils import get_client_ip
from .redis_keys import RedisKeys
import logging
from apps.channels.models import Channel, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.accounts.models import User
from core.models import UserAgent, CoreSettings, PROXY_PROFILE_NAME
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from apps.accounts.permissions import (
    IsAdmin,
    permission_classes_by_method,
    permission_classes_by_action,
)
from .constants import ChannelState, EventType, StreamType, ChannelMetadataField
from .config_helper import ConfigHelper
from .services.channel_service import ChannelService
from core.utils import send_websocket_update
from .url_utils import (
    generate_stream_url,
    transform_url,
    get_stream_info_for_switch,
    get_stream_object,
    get_alternate_streams,
)
from .utils import get_logger
from uuid import UUID
import gevent
from dispatcharr.utils import network_access_allowed

logger = get_logger()


@api_view(["GET"])
def stream_ts(request, channel_id):
    if not network_access_allowed(request, "STREAMS"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    """Stream TS data to client with immediate response and keep-alive packets during initialization"""
    channel = get_stream_object(channel_id)

    client_user_agent = None
    proxy_server = ProxyServer.get_instance()

    try:
        # Generate a unique client ID
        client_id = f"client_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        client_ip = get_client_ip(request)
        logger.info(f"[{client_id}] Requested stream for channel {channel_id}")

        # Extract client user agent early
        for header in ["HTTP_USER_AGENT", "User-Agent", "user-agent"]:
            if header in request.META:
                client_user_agent = request.META[header]
                logger.debug(
                    f"[{client_id}] Client connected with user agent: {client_user_agent}"
                )
                break

        # Check if we need to reinitialize the channel
        needs_initialization = True
        channel_state = None
        channel_initializing = False

        # Get current channel state from Redis if available
        if proxy_server.redis_client:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            if proxy_server.redis_client.exists(metadata_key):
                metadata = proxy_server.redis_client.hgetall(metadata_key)
                state_field = ChannelMetadataField.STATE.encode("utf-8")
                if state_field in metadata:
                    channel_state = metadata[state_field].decode("utf-8")

                    # Active/running states - channel is operational, don't reinitialize
                    if channel_state in [
                        ChannelState.ACTIVE,
                        ChannelState.WAITING_FOR_CLIENTS,
                        ChannelState.BUFFERING,
                        ChannelState.INITIALIZING,
                        ChannelState.CONNECTING,
                        ChannelState.STOPPING,
                    ]:
                        needs_initialization = False
                        logger.debug(
                            f"[{client_id}] Channel {channel_id} in state {channel_state}, skipping initialization"
                        )

                        # Special handling for initializing/connecting states
                        if channel_state in [
                            ChannelState.INITIALIZING,
                            ChannelState.CONNECTING,
                        ]:
                            channel_initializing = True
                            logger.debug(
                                f"[{client_id}] Channel {channel_id} is still initializing, client will wait"
                            )
                    # Terminal states - channel needs cleanup before reinitialization
                    elif channel_state in [
                        ChannelState.ERROR,
                        ChannelState.STOPPED,
                    ]:
                        needs_initialization = True
                        logger.info(
                            f"[{client_id}] Channel {channel_id} in terminal state {channel_state}, will reinitialize"
                        )
                    # Unknown/empty state - check if owner is alive
                    else:
                        owner_field = ChannelMetadataField.OWNER.encode("utf-8")
                        if owner_field in metadata:
                            owner = metadata[owner_field].decode("utf-8")
                            owner_heartbeat_key = f"ts_proxy:worker:{owner}:heartbeat"
                            if proxy_server.redis_client.exists(owner_heartbeat_key):
                                # Owner is still active with unknown state - don't reinitialize
                                needs_initialization = False
                                logger.debug(
                                    f"[{client_id}] Channel {channel_id} has active owner {owner}, skipping init"
                                )
                            else:
                                # Owner dead - needs reinitialization
                                needs_initialization = True
                                logger.warning(
                                    f"[{client_id}] Channel {channel_id} owner {owner} is dead, will reinitialize"
                                )

        # Start initialization if needed
        if needs_initialization or not proxy_server.check_if_channel_exists(channel_id):
            logger.info(f"[{client_id}] Starting channel {channel_id} initialization")
            # Force cleanup of any previous instance if in terminal state
            if channel_state in [
                ChannelState.ERROR,
                ChannelState.STOPPING,
                ChannelState.STOPPED,
            ]:
                logger.warning(
                    f"[{client_id}] Channel {channel_id} in state {channel_state}, forcing cleanup"
                )
                ChannelService.stop_channel(channel_id)

            # Use fixed retry interval and timeout
            retry_timeout = 3  # 3 seconds total timeout
            retry_interval = 0.1  # 100ms between attempts
            wait_start_time = time.time()

            stream_url = None
            stream_user_agent = None
            transcode = False
            profile_value = None
            error_reason = None
            attempt = 0
            should_retry = True

            # Try to get a stream with fixed interval retries
            while should_retry and time.time() - wait_start_time < retry_timeout:
                attempt += 1
                stream_url, stream_user_agent, transcode, profile_value = (
                    generate_stream_url(channel_id)
                )

                if stream_url is not None:
                    logger.info(
                        f"[{client_id}] Successfully obtained stream for channel {channel_id} after {attempt} attempts"
                    )
                    break

                # On first failure, check if the error is retryable
                if attempt == 1:
                    _, _, error_reason = channel.get_stream()
                    if error_reason and "maximum connection limits" not in error_reason:
                        logger.warning(
                            f"[{client_id}] Can't retry - error not related to connection limits: {error_reason}"
                        )
                        should_retry = False
                        break

                # Check if we have time remaining for another sleep cycle
                elapsed_time = time.time() - wait_start_time
                remaining_time = retry_timeout - elapsed_time

                # If we don't have enough time for the next sleep interval, break
                # but only after we've already made an attempt (the while condition will try one more time)
                if remaining_time <= retry_interval:
                    logger.info(
                        f"[{client_id}] Insufficient time ({remaining_time:.1f}s) for another sleep cycle, will make one final attempt"
                    )
                    break

                # Wait before retrying
                logger.info(
                    f"[{client_id}] Waiting {retry_interval*1000:.0f}ms for a connection to become available (attempt {attempt}, {remaining_time:.1f}s remaining)"
                )
                gevent.sleep(retry_interval)
                retry_interval += 0.025  # Increase wait time by 25ms for next attempt

            # Make one final attempt if we still don't have a stream, should retry, and haven't exceeded timeout
            if stream_url is None and should_retry and time.time() - wait_start_time < retry_timeout:
                attempt += 1
                logger.info(
                    f"[{client_id}] Making final attempt {attempt} at timeout boundary"
                )
                stream_url, stream_user_agent, transcode, profile_value = (
                    generate_stream_url(channel_id)
                )
                if stream_url is not None:
                    logger.info(
                        f"[{client_id}] Successfully obtained stream on final attempt for channel {channel_id}"
                    )

            if stream_url is None:
                # Release the channel's stream lock if one was acquired
                # Note: Only call this if get_stream() actually assigned a stream
                # In our case, if stream_url is None, no stream was ever assigned, so don't release

                # Get the specific error message if available
                wait_duration = f"{int(time.time() - wait_start_time)}s"
                error_msg = (
                    error_reason
                    if error_reason
                    else "No available streams for this channel"
                )
                logger.info(
                    f"[{client_id}] Failed to obtain stream after {attempt} attempts over {wait_duration}: {error_msg}"
                )
                return JsonResponse(
                    {"error": error_msg, "waited": wait_duration}, status=503
                )  # 503 Service Unavailable is appropriate here

            # Get the stream ID from the channel
            stream_id, m3u_profile_id, _ = channel.get_stream()
            logger.info(
                f"Channel {channel_id} using stream ID {stream_id}, m3u account profile ID {m3u_profile_id}"
            )

            # Generate transcode command if needed
            stream_profile = channel.get_stream_profile()
            if stream_profile.is_redirect():
                # Validate the stream URL before redirecting
                from .url_utils import (
                    validate_stream_url,
                    get_alternate_streams,
                    get_stream_info_for_switch,
                )

                # Try initial URL
                logger.info(f"[{client_id}] Validating redirect URL: {stream_url}")
                is_valid, final_url, status_code, message = validate_stream_url(
                    stream_url, user_agent=stream_user_agent, timeout=(5, 5)
                )

                # If first URL doesn't validate, try alternates
                if not is_valid:
                    logger.warning(
                        f"[{client_id}] Primary stream URL failed validation: {message}"
                    )

                    # Track tried streams to avoid loops
                    tried_streams = {stream_id}

                    # Get alternate streams
                    alternates = get_alternate_streams(channel_id, stream_id)

                    # Try each alternate until one works
                    for alt in alternates:
                        if alt["stream_id"] in tried_streams:
                            continue

                        tried_streams.add(alt["stream_id"])

                        # Get stream info
                        alt_info = get_stream_info_for_switch(
                            channel_id, alt["stream_id"]
                        )
                        if "error" in alt_info:
                            logger.warning(
                                f"[{client_id}] Error getting alternate stream info: {alt_info['error']}"
                            )
                            continue

                        # Validate the alternate URL
                        logger.info(
                            f"[{client_id}] Trying alternate stream #{alt['stream_id']}: {alt_info['url']}"
                        )
                        is_valid, final_url, status_code, message = validate_stream_url(
                            alt_info["url"],
                            user_agent=alt_info["user_agent"],
                            timeout=(5, 5),
                        )

                        if is_valid:
                            logger.info(
                                f"[{client_id}] Alternate stream #{alt['stream_id']} validated successfully"
                            )
                            break
                        else:
                            logger.warning(
                                f"[{client_id}] Alternate stream #{alt['stream_id']} failed validation: {message}"
                            )
                # Release stream lock before redirecting
                channel.release_stream()
                # Final decision based on validation results
                if is_valid:
                    logger.info(
                        f"[{client_id}] Redirecting to validated URL: {final_url} ({message})"
                    )

                    # For non-HTTP protocols (RTSP/RTP/UDP), we need to manually create the redirect
                    # because Django's HttpResponseRedirect blocks them for security
                    if final_url.startswith(('rtsp://', 'rtp://', 'udp://')):
                        logger.info(f"[{client_id}] Using manual redirect for non-HTTP protocol")
                        response = HttpResponse(status=301)
                        response['Location'] = final_url
                        return response

                    return HttpResponseRedirect(final_url)
                else:
                    logger.error(
                        f"[{client_id}] All available redirect URLs failed validation"
                    )
                    return JsonResponse(
                        {"error": "All available streams failed validation"}, status=502
                    )  # 502 Bad Gateway

            # Initialize channel with the stream's user agent (not the client's)
            success = ChannelService.initialize_channel(
                channel_id,
                stream_url,
                stream_user_agent,
                transcode,
                profile_value,
                stream_id,
                m3u_profile_id,
            )

            if not success:
                return JsonResponse(
                    {"error": "Failed to initialize channel"}, status=500
                )

            # If we're the owner, wait for connection to establish
            if proxy_server.am_i_owner(channel_id):
                manager = proxy_server.stream_managers.get(channel_id)
                if manager:
                    wait_start = time.time()
                    timeout = ConfigHelper.connection_timeout()
                    while not manager.connected:
                        if time.time() - wait_start > timeout:
                            proxy_server.stop_channel(channel_id)
                            return JsonResponse(
                                {"error": "Connection timeout"}, status=504
                            )

                        # Check if this manager should keep retrying or stop
                        if not manager.should_retry():
                            # Check channel state in Redis to make a better decision
                            metadata_key = RedisKeys.channel_metadata(channel_id)
                            current_state = None

                            if proxy_server.redis_client:
                                try:
                                    state_bytes = proxy_server.redis_client.hget(
                                        metadata_key, ChannelMetadataField.STATE
                                    )
                                    if state_bytes:
                                        current_state = state_bytes.decode("utf-8")
                                        logger.debug(
                                            f"[{client_id}] Current state of channel {channel_id}: {current_state}"
                                        )
                                except Exception as e:
                                    logger.warning(
                                        f"[{client_id}] Error getting channel state: {e}"
                                    )

                            # Allow normal transitional states to continue
                            if current_state in [
                                ChannelState.INITIALIZING,
                                ChannelState.CONNECTING,
                            ]:
                                logger.info(
                                    f"[{client_id}] Channel {channel_id} is in {current_state} state, continuing to wait"
                                )
                                # Reset wait timer to allow the transition to complete
                                wait_start = time.time()
                                continue

                            # Check if we're switching URLs
                            if (
                                hasattr(manager, "url_switching")
                                and manager.url_switching
                            ):
                                logger.info(
                                    f"[{client_id}] Stream manager is currently switching URLs for channel {channel_id}"
                                )
                                # Reset wait timer to give the switch a chance
                                wait_start = time.time()
                                continue

                            # If we reach here, we've exhausted retries and the channel isn't in a valid transitional state
                            logger.warning(
                                f"[{client_id}] Channel {channel_id} failed to connect and is not in transitional state"
                            )
                            proxy_server.stop_channel(channel_id)
                            return JsonResponse(
                                {"error": "Failed to connect"}, status=502
                            )

                        gevent.sleep(
                            0.1
                        )  # FIXED: Using gevent.sleep instead of time.sleep

            logger.info(f"[{client_id}] Successfully initialized channel {channel_id}")
            channel_initializing = True

        # Register client - can do this regardless of initialization state
        # Create local resources if needed
        if (
            channel_id not in proxy_server.stream_buffers
            or channel_id not in proxy_server.client_managers
        ):
            logger.debug(
                f"[{client_id}] Channel {channel_id} exists in Redis but not initialized in this worker - initializing now"
            )

            # Get URL from Redis metadata
            url = None
            stream_user_agent = None  # Initialize the variable

            if proxy_server.redis_client:
                metadata_key = RedisKeys.channel_metadata(channel_id)
                url_bytes = proxy_server.redis_client.hget(
                    metadata_key, ChannelMetadataField.URL
                )
                ua_bytes = proxy_server.redis_client.hget(
                    metadata_key, ChannelMetadataField.USER_AGENT
                )
                profile_bytes = proxy_server.redis_client.hget(
                    metadata_key, ChannelMetadataField.STREAM_PROFILE
                )

                if url_bytes:
                    url = url_bytes.decode("utf-8")
                if ua_bytes:
                    stream_user_agent = ua_bytes.decode("utf-8")
                # Extract transcode setting from Redis
                if profile_bytes:
                    profile_str = profile_bytes.decode("utf-8")
                    use_transcode = (
                        profile_str == PROXY_PROFILE_NAME or profile_str == "None"
                    )
                    logger.debug(
                        f"Using profile '{profile_str}' for channel {channel_id}, transcode={use_transcode}"
                    )
                else:
                    # Default settings when profile not found in Redis
                    profile_str = "None"  # Default profile name
                    use_transcode = (
                        False  # Default to direct streaming without transcoding
                    )
                    logger.debug(
                        f"No profile found in Redis for channel {channel_id}, defaulting to transcode={use_transcode}"
                    )

            # Use client_user_agent as fallback if stream_user_agent is None
            success = proxy_server.initialize_channel(
                url, channel_id, stream_user_agent or client_user_agent, use_transcode
            )
            if not success:
                logger.error(
                    f"[{client_id}] Failed to initialize channel {channel_id} locally"
                )
                return JsonResponse(
                    {"error": "Failed to initialize channel locally"}, status=500
                )

            logger.info(
                f"[{client_id}] Successfully initialized channel {channel_id} locally"
            )

        # Register client
        buffer = proxy_server.stream_buffers[channel_id]
        client_manager = proxy_server.client_managers[channel_id]
        client_manager.add_client(client_id, client_ip, client_user_agent)
        logger.info(f"[{client_id}] Client registered with channel {channel_id}")

        # Create a stream generator for this client
        generate = create_stream_generator(
            channel_id, client_id, client_ip, client_user_agent, channel_initializing
        )

        # Return the StreamingHttpResponse from the main function
        response = StreamingHttpResponse(
            streaming_content=generate(), content_type="video/mp2t"
        )
        response["Cache-Control"] = "no-cache"
        return response

    except Exception as e:
        logger.error(f"Error in stream_ts: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@api_view(["GET"])
def stream_xc(request, username, password, channel_id):
    user = get_object_or_404(User, username=username)

    extension = pathlib.Path(channel_id).suffix
    channel_id = pathlib.Path(channel_id).stem

    custom_properties = user.custom_properties or {}

    if "xc_password" not in custom_properties:
        return Response({"error": "Invalid credentials"}, status=401)

    if custom_properties["xc_password"] != password:
        return Response({"error": "Invalid credentials"}, status=401)

    print(f"Fetchin channel with ID: {channel_id}")
    if user.user_level < 10:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channels based on user_level
            filters = {
                "id": int(channel_id),
                "user_level__lte": user.user_level
            }
            channel = Channel.objects.filter(**filters).first()
        else:
            # User has specific limited profiles assigned
            filters = {
                "id": int(channel_id),
                "channelprofilemembership__enabled": True,
                "user_level__lte": user.user_level,
                "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
            }
            channel = Channel.objects.filter(**filters).distinct().first()

        if not channel:
            return JsonResponse({"error": "Not found"}, status=404)
    else:
        channel = get_object_or_404(Channel, id=channel_id)

    # @TODO: we've got the  file 'type' via extension, support this when we support multiple outputs
    return stream_ts(request._request, str(channel.uuid))


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def change_stream(request, channel_id):
    """Change stream URL for existing channel with enhanced diagnostics"""
    proxy_server = ProxyServer.get_instance()

    try:
        data = json.loads(request.body)
        new_url = data.get("url")
        user_agent = data.get("user_agent")
        stream_id = data.get("stream_id")

        # If stream_id is provided, get the URL and user_agent from it
        if stream_id:
            logger.info(
                f"Stream ID {stream_id} provided, looking up stream info for channel {channel_id}"
            )
            stream_info = get_stream_info_for_switch(channel_id, stream_id)

            if "error" in stream_info:
                return JsonResponse(
                    {"error": stream_info["error"], "stream_id": stream_id}, status=404
                )

            # Use the info from the stream
            new_url = stream_info["url"]
            user_agent = stream_info["user_agent"]
            m3u_profile_id = stream_info.get("m3u_profile_id")
            # Stream ID will be passed to change_stream_url later
        elif not new_url:
            return JsonResponse(
                {"error": "Either url or stream_id must be provided"}, status=400
            )

        logger.info(
            f"Attempting to change stream for channel {channel_id} to {new_url}"
        )

        # Use the service layer instead of direct implementation
        # Pass stream_id to ensure proper connection tracking
        result = ChannelService.change_stream_url(
            channel_id, new_url, user_agent, stream_id, m3u_profile_id
        )

        # Get the stream manager before updating URL
        stream_manager = proxy_server.stream_managers.get(channel_id)

        # If we have a stream manager, reset its tried_stream_ids when manually changing streams
        if stream_manager:
            # Reset tried streams when manually switching URL via API
            stream_manager.tried_stream_ids = set()
            logger.debug(
                f"Reset tried stream IDs for channel {channel_id} during manual stream change"
            )

        if result.get("status") == "error":
            return JsonResponse(
                {
                    "error": result.get("message", "Unknown error"),
                    "diagnostics": result.get("diagnostics", {}),
                },
                status=404,
            )

        # Format response based on whether it was a direct update or event-based
        response_data = {
            "message": "Stream changed successfully",
            "channel": channel_id,
            "url": new_url,
            "owner": result.get("direct_update", False),
            "worker_id": proxy_server.worker_id,
        }

        # Include stream_id in response if it was used
        if stream_id:
            response_data["stream_id"] = stream_id

        return JsonResponse(response_data)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error(f"Failed to change stream: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([IsAdmin])
def channel_status(request, channel_id=None):
    """
    Returns status information about channels with detail level based on request:
    - /status/ returns basic summary of all channels
    - /status/{channel_id} returns detailed info about specific channel
    """
    proxy_server = ProxyServer.get_instance()

    try:
        # Check if Redis is available
        if not proxy_server.redis_client:
            return JsonResponse({"error": "Redis connection not available"}, status=500)

        # Handle single channel or all channels
        if channel_id:
            # Detailed info for specific channel
            channel_info = ChannelStatus.get_detailed_channel_info(channel_id)
            if channel_info:
                return JsonResponse(channel_info)
            else:
                return JsonResponse(
                    {"error": f"Channel {channel_id} not found"}, status=404
                )
        else:
            # Basic info for all channels
            channel_pattern = "ts_proxy:channel:*:metadata"
            all_channels = []

            # Extract channel IDs from keys
            cursor = 0
            while True:
                cursor, keys = proxy_server.redis_client.scan(
                    cursor, match=channel_pattern
                )
                for key in keys:
                    channel_id_match = re.search(
                        r"ts_proxy:channel:(.*):metadata", key.decode("utf-8")
                    )
                    if channel_id_match:
                        ch_id = channel_id_match.group(1)
                        channel_info = ChannelStatus.get_basic_channel_info(ch_id)
                        if channel_info:
                            all_channels.append(channel_info)

                if cursor == 0:
                    break

            # Send WebSocket update with the stats
            # Format it the same way the original Celery task did
            send_websocket_update(
                "updates",
                "update",
                {
                    "success": True,
                    "type": "channel_stats",
                    "stats": json.dumps({'channels': all_channels, 'count': len(all_channels)})
                }
            )

            return JsonResponse({"channels": all_channels, "count": len(all_channels)})

    except Exception as e:
        logger.error(f"Error in channel_status: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@api_view(["POST", "DELETE"])
@permission_classes([IsAdmin])
def stop_channel(request, channel_id):
    """Stop a channel and release all associated resources using PubSub events"""
    try:
        logger.info(f"Request to stop channel {channel_id} received")

        # Use the service layer instead of direct implementation
        result = ChannelService.stop_channel(channel_id)

        if result.get("status") == "error":
            return JsonResponse(
                {"error": result.get("message", "Unknown error")}, status=404
            )

        return JsonResponse(
            {
                "message": "Channel stop request sent",
                "channel_id": channel_id,
                "previous_state": result.get("previous_state"),
            }
        )

    except Exception as e:
        logger.error(f"Failed to stop channel: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def stop_client(request, channel_id):
    """Stop a specific client connection using existing client management"""
    try:
        # Parse request body to get client ID
        data = json.loads(request.body)
        client_id = data.get("client_id")

        if not client_id:
            return JsonResponse({"error": "No client_id provided"}, status=400)

        # Use the service layer instead of direct implementation
        result = ChannelService.stop_client(channel_id, client_id)

        if result.get("status") == "error":
            return JsonResponse({"error": result.get("message")}, status=404)

        return JsonResponse(
            {
                "message": "Client stop request processed",
                "channel_id": channel_id,
                "client_id": client_id,
                "locally_processed": result.get("locally_processed", False),
            }
        )

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error(f"Failed to stop client: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def next_stream(request, channel_id):
    """Switch to the next available stream for a channel"""
    proxy_server = ProxyServer.get_instance()

    try:
        logger.info(
            f"Request to switch to next stream for channel {channel_id} received"
        )

        # Check if the channel exists
        channel = get_stream_object(channel_id)

        # First check if channel is active in Redis
        current_stream_id = None
        profile_id = None

        if proxy_server.redis_client:
            metadata_key = RedisKeys.channel_metadata(channel_id)
            if proxy_server.redis_client.exists(metadata_key):
                # Get current stream ID from Redis
                stream_id_bytes = proxy_server.redis_client.hget(
                    metadata_key, ChannelMetadataField.STREAM_ID
                )
                if stream_id_bytes:
                    current_stream_id = int(stream_id_bytes.decode("utf-8"))
                    logger.info(
                        f"Found current stream ID {current_stream_id} in Redis for channel {channel_id}"
                    )

                    # Get M3U profile from Redis if available
                    profile_id_bytes = proxy_server.redis_client.hget(
                        metadata_key, ChannelMetadataField.M3U_PROFILE
                    )
                    if profile_id_bytes:
                        profile_id = int(profile_id_bytes.decode("utf-8"))
                        logger.info(
                            f"Found M3U profile ID {profile_id} in Redis for channel {channel_id}"
                        )

        if not current_stream_id:
            # Channel is not running
            return JsonResponse(
                {"error": "No current stream found for channel"}, status=404
            )

        # Get all streams for this channel in their defined order
        streams = list(channel.streams.all().order_by("channelstream__order"))

        if len(streams) <= 1:
            return JsonResponse(
                {
                    "error": "No alternate streams available for this channel",
                    "current_stream_id": current_stream_id,
                },
                status=404,
            )

        # Find the current stream's position in the list
        current_index = None
        for i, stream in enumerate(streams):
            if stream.id == current_stream_id:
                current_index = i
                break

        if current_index is None:
            logger.warning(
                f"Current stream ID {current_stream_id} not found in channel's streams list"
            )
            # Fall back to the first stream that's not the current one
            next_stream = next((s for s in streams if s.id != current_stream_id), None)
            if not next_stream:
                return JsonResponse(
                    {
                        "error": "Could not find current stream in channel list",
                        "current_stream_id": current_stream_id,
                    },
                    status=404,
                )
        else:
            # Get the next stream in the rotation (with wrap-around)
            next_index = (current_index + 1) % len(streams)
            next_stream = streams[next_index]

        next_stream_id = next_stream.id
        logger.info(
            f"Rotating to next stream ID {next_stream_id} for channel {channel_id}"
        )

        # Get full stream info including URL for the next stream
        stream_info = get_stream_info_for_switch(channel_id, next_stream_id)

        if "error" in stream_info:
            return JsonResponse(
                {
                    "error": stream_info["error"],
                    "current_stream_id": current_stream_id,
                    "next_stream_id": next_stream_id,
                },
                status=404,
            )

        # Now use the ChannelService to change the stream URL
        result = ChannelService.change_stream_url(
            channel_id,
            stream_info["url"],
            stream_info["user_agent"],
            next_stream_id,  # Pass the stream_id to be stored in Redis
        )

        if result.get("status") == "error":
            return JsonResponse(
                {
                    "error": result.get("message", "Unknown error"),
                    "diagnostics": result.get("diagnostics", {}),
                    "current_stream_id": current_stream_id,
                    "next_stream_id": next_stream_id,
                },
                status=404,
            )

        # Format success response
        response_data = {
            "message": "Stream switched to next available",
            "channel": channel_id,
            "previous_stream_id": current_stream_id,
            "new_stream_id": next_stream_id,
            "new_url": stream_info["url"],
            "owner": result.get("direct_update", False),
            "worker_id": proxy_server.worker_id,
        }

        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Failed to switch to next stream: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)
