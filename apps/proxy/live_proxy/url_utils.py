"""
Utilities for handling stream URLs and transformations.
"""

import logging
import regex
from typing import Optional, Tuple, List
from django.shortcuts import get_object_or_404
from apps.channels.models import Channel, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.connection_pool import (
    get_profile_connection_count,
    profile_available_for_channel_switch,
)
from core.models import UserAgent, CoreSettings, StreamProfile
from .utils import get_logger
from uuid import UUID
import requests

logger = get_logger()


def _resolve_live_stream_url(stream, m3u_account, m3u_profile):
    """
    Build the upstream URL for live playback.

    XC accounts use current transformed credentials plus provider stream_id so
    playback matches the account login (not a stale stream.url from an old sync).
    STD/M3U accounts keep using the URL stored on the stream row.
    """
    if (
        m3u_account.account_type == M3UAccount.Types.XC
        and stream.stream_id
    ):
        from apps.m3u.tasks import get_transformed_credentials

        server_url, username, password = get_transformed_credentials(
            m3u_account, m3u_profile
        )
        if server_url and username and password:
            base = server_url.rstrip("/")
            return f"{base}/live/{username}/{password}/{stream.stream_id}.ts"

    return transform_url(
        stream.url or "",
        m3u_profile.search_pattern,
        m3u_profile.replace_pattern,
    )


def get_stream_object(id: str):
    try:
        logger.info(f"Fetching channel ID {id}")
        return get_object_or_404(Channel, uuid=id)
    except:
        # UUID check failed, assume stream hash
        logger.info(f"Fetching stream hash {id}")
        return get_object_or_404(Stream, stream_hash=id)

def generate_stream_url(
    channel_id: str,
) -> Tuple[str, str, bool, Optional[int], bool, Optional[str]]:
    """
    Generate the appropriate stream URL for a channel or stream based on its profile settings.

    Returns:
        Tuple: (stream_url, user_agent, transcode_flag, profile_id, slot_reserved, error_reason)
    """
    try:
        channel_or_stream = get_stream_object(channel_id)

        # Handle direct stream preview (custom streams)
        if isinstance(channel_or_stream, Stream):
            stream = channel_or_stream
            logger.info(f"Previewing stream directly: {stream.id} ({stream.name})")

            if not stream.m3u_account:
                logger.error(f"Stream {stream.id} has no M3U account")
                return None, None, False, None, False, "Stream has no M3U account"

            stream_id, profile_id, error_reason, slot_reserved = stream.get_stream()
            if not stream_id or not profile_id:
                logger.error(f"No profile available for stream {stream.id}: {error_reason}")
                return None, None, False, None, False, error_reason

            try:
                profile = M3UAccountProfile.objects.get(id=profile_id)
                m3u_account = stream.m3u_account

                stream_user_agent = m3u_account.get_user_agent().user_agent
                if stream_user_agent is None:
                    stream_user_agent = UserAgent.objects.get(id=CoreSettings.get_default_user_agent_id())
                    logger.debug(f"No user agent found for account, using default: {stream_user_agent}")

                stream_url = _resolve_live_stream_url(stream, m3u_account, profile)

                stream_profile = stream.get_stream_profile()
                logger.debug(f"Using stream profile: {stream_profile.name}")

                transcode = not stream_profile.is_proxy()
                stream_profile_id = stream_profile.id

                return stream_url, stream_user_agent, transcode, stream_profile_id, slot_reserved, None
            except Exception as e:
                logger.error(f"Error generating stream URL for stream {stream.id}: {e}")
                if slot_reserved:
                    stream.release_stream()
                return None, None, False, None, False, str(e)


        # Handle channel preview (existing logic)
        channel = channel_or_stream

        # Get stream and profile for this channel
        stream_id, profile_id, error_reason, slot_reserved = channel.get_stream()

        if not stream_id or not profile_id:
            logger.error(f"No stream available for channel {channel_id}: {error_reason}")
            return None, None, False, None, False, error_reason

        # get_stream() allocated a connection slot - ensure it's released on any error
        try:
            # Look up the Stream and Profile objects
            stream = Stream.objects.get(id=stream_id)
            profile = M3UAccountProfile.objects.get(id=profile_id)

            # Get the M3U account profile for URL pattern
            m3u_profile = profile

            # Get the appropriate user agent
            m3u_account = M3UAccount.objects.get(id=m3u_profile.m3u_account.id)
            stream_user_agent = m3u_account.get_user_agent().user_agent

            if stream_user_agent is None:
                stream_user_agent = UserAgent.objects.get(id=CoreSettings.get_default_user_agent_id())
                logger.debug(f"No user agent found for account, using default: {stream_user_agent}")

            stream_url = _resolve_live_stream_url(stream, m3u_account, m3u_profile)

            # Check if transcoding is needed
            stream_profile = channel.get_stream_profile()
            if stream_profile.is_proxy() or stream_profile is None:
                transcode = False
            else:
                transcode = True

            stream_profile_id = stream_profile.id

            return stream_url, stream_user_agent, transcode, stream_profile_id, slot_reserved, None
        except Exception as e:
            logger.error(f"Error generating stream URL for channel {channel_id}: {e}")
            if slot_reserved:
                if not channel.release_stream():
                    logger.warning(f"Failed to release stream for channel {channel_id} after URL generation error")
            return None, None, False, None, False, str(e)
    except Exception as e:
        logger.error(f"Error generating stream URL: {e}")
        return None, None, False, None, False, str(e)

def transform_url(input_url: str, search_pattern: str, replace_pattern: str) -> str:
    """
    Transform a URL using regex pattern replacement.

    Args:
        input_url: The base URL to transform
        search_pattern: The regex search pattern
        replace_pattern: The replacement pattern

    Returns:
        str: The transformed URL
    """
    try:
        logger.debug("Executing URL pattern replacement:")
        logger.debug(f"  base URL: {input_url}")
        logger.debug(f"  search: {search_pattern}")

        # Convert JS-style backreferences in replace pattern: $<name> -> \g<name>, $1 -> \1
        safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', replace_pattern)
        safe_replace_pattern = regex.sub(r'\$(\d+)', r'\\\1', safe_replace_pattern)
        logger.debug(f"  replace: {replace_pattern}")
        logger.debug(f"  safe replace: {safe_replace_pattern}")

        # Apply the transformation (regex module accepts JS-style (?<name>...) natively)
        stream_url, match_count = regex.subn(search_pattern, safe_replace_pattern, input_url)
        if match_count == 0:
            logger.warning(f"URL pattern '{search_pattern}' did not match, falling back to original URL: {input_url}")
        else:
            logger.info(f"Generated stream url: {stream_url}")

        return stream_url
    except Exception as e:
        logger.error(f"Error transforming URL: {e}")
        return input_url  # Return original URL on error

def get_stream_info_for_switch(channel_id: str, target_stream_id: Optional[int] = None) -> dict:
    """
    Get stream information for a channel switch, optionally to a specific stream ID.

    Args:
        channel_id: The UUID of the channel
        target_stream_id: Optional specific stream ID to switch to

    Returns:
        dict: Stream information including URL, user agent and transcode flag
    """
    slot_reserved = False
    channel = None
    try:
        from core.utils import RedisClient

        channel = get_object_or_404(Channel, uuid=channel_id)
        redis_client = RedisClient.get_client()

        # Use the target stream if specified, otherwise use current stream
        if target_stream_id:
            stream_id = target_stream_id

            # Get the stream object
            stream = get_object_or_404(Stream, pk=stream_id)

            # Find compatible profile for this stream with connection availability check
            m3u_account = stream.m3u_account
            if not m3u_account:
                return {'error': 'Stream has no M3U account'}

            m3u_profiles = m3u_account.profiles.filter(is_active=True)
            default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)

            if not default_profile:
                return {'error': 'M3U account has no default profile'}

            # Check profiles in order: default first, then others
            profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]

            selected_profile = None
            for profile in profiles:
                if redis_client:
                    channel_using_profile = False
                    existing_stream_id = redis_client.get(f"channel_stream:{channel.id}")
                    if existing_stream_id:
                        existing_profile_id = redis_client.get(
                            f"stream_profile:{existing_stream_id}"
                        )
                        if existing_profile_id and int(existing_profile_id) == profile.id:
                            channel_using_profile = True

                    if profile_available_for_channel_switch(
                        profile,
                        redis_client,
                        channel_already_on_profile=channel_using_profile,
                    ):
                        current_connections = get_profile_connection_count(
                            profile, redis_client
                        )
                        selected_profile = profile
                        logger.debug(
                            f"Selected profile {profile.id} with "
                            f"{current_connections}/{profile.max_streams} connections"
                        )
                        break
                    logger.debug(
                        f"Profile {profile.id} unavailable for channel switch"
                    )
                else:
                    selected_profile = profile
                    break

            if not selected_profile:
                return {'error': 'No profiles available with connection capacity'}

            m3u_profile_id = selected_profile.id
        else:
            stream_id, m3u_profile_id, error_reason, slot_reserved = channel.get_stream()
            if stream_id is None or m3u_profile_id is None:
                return {'error': error_reason or 'No stream assigned to channel'}

        stream = get_object_or_404(Stream, pk=stream_id)
        profile = get_object_or_404(M3UAccountProfile, pk=m3u_profile_id)

        m3u_account = M3UAccount.objects.get(id=profile.m3u_account.id)
        user_agent = m3u_account.get_user_agent().user_agent

        stream_url = _resolve_live_stream_url(stream, m3u_account, profile)

        stream_profile = channel.get_stream_profile()
        transcode = not (stream_profile.is_proxy() or stream_profile is None)
        profile_value = stream_profile.id

        return {
            'url': stream_url,
            'user_agent': user_agent,
            'transcode': transcode,
            'stream_profile': profile_value,
            'stream_id': stream_id,
            'm3u_profile_id': m3u_profile_id,
            'stream_name': stream.name,
        }
    except Exception as e:
        if slot_reserved and channel is not None:
            channel.release_stream()
        logger.error(f"Error getting stream info for switch: {e}", exc_info=True)
        return {'error': f'Error: {str(e)}'}

def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = None, current_profile_id: Optional[int] = None) -> List[dict]:
    """
    Get alternative streams for a channel when the current stream fails.
    
    IMPORTANT: Returns ALL available profiles for each stream, not just the first one!
    This enables full profile failover (try all profiles of stream 1, then all profiles of stream 2, etc.)

    Args:
        channel_id: The UUID of the channel
        current_stream_id: The currently failing stream ID
        current_profile_id: The currently failing profile ID to exclude

    Returns:
        List[dict]: List of stream information dictionaries with stream_id and profile_id
    """
    try:
        from core.utils import RedisClient

        # Get channel or stream object
        channel_or_stream = get_stream_object(channel_id)

        # ============================================================
        # STREAM PREVIEW: Return all profiles for THIS stream only
        # ============================================================
        if isinstance(channel_or_stream, Stream):
            stream = channel_or_stream
            logger.info(f"Stream preview: Getting alternate profiles for stream {stream.id}")
            
            # Get all profiles for this specific stream
            m3u_account = stream.m3u_account
            if not m3u_account:
                logger.warning(f"Stream {stream.id} has no M3U account")
                return []
            
            if not m3u_account.is_active:
                logger.warning(f"M3U account {m3u_account.id} is inactive")
                return []
            
            # Get all active profiles
            m3u_profiles = m3u_account.profiles.filter(is_active=True)
            default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)
            
            if not default_profile:
                logger.warning(f"M3U account {m3u_account.id} has no default profile")
                return []
            
            # Order: default first, then others
            profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]
            
            alternate_profiles = []
            redis_client = RedisClient.get_client()
            
            for profile in profiles:
                # Skip the currently failing profile
                if current_profile_id and profile.id == current_profile_id:
                    logger.debug(f"Skipping current failing profile {profile.id} for stream {stream.id}")
                    continue
                
                # Check connection availability with error handling
                if redis_client:
                    try:
                        profile_connections_key = f"profile_connections:{profile.id}"
                        current_connections = int(redis_client.get(profile_connections_key) or 0)
                        
                        if profile.max_streams == 0 or current_connections < profile.max_streams:
                            logger.debug(f"Found available profile {profile.id} for stream {stream.id}: {current_connections}/{profile.max_streams}")
                            alternate_profiles.append({
                                'stream_id': stream.id,
                                'profile_id': profile.id,
                                'name': stream.name
                            })
                        else:
                            logger.debug(f"Profile {profile.id} at max connections: {current_connections}/{profile.max_streams}")
                    except Exception as e:
                        # Redis error - assume profile is available (fail-open for resilience)
                        logger.warning(f"Redis error checking profile {profile.id} connections: {e}, assuming available")
                        alternate_profiles.append({
                            'stream_id': stream.id,
                            'profile_id': profile.id,
                            'name': stream.name
                        })
                else:
                    # No Redis client - add all profiles
                    alternate_profiles.append({
                        'stream_id': stream.id,
                        'profile_id': profile.id,
                        'name': stream.name
                    })
            
            logger.info(f"Stream preview: Found {len(alternate_profiles)} alternate profiles for stream {stream.id}")
            return alternate_profiles

        # ============================================================
        # CHANNEL: Return all stream+profile combinations
        # ============================================================
        channel = channel_or_stream
        redis_client = RedisClient.get_client()
        logger.debug(f"Looking for alternate streams for channel {channel_id}, current stream ID: {current_stream_id}, current profile ID: {current_profile_id}")

        # Get all assigned streams for this channel using the correct ordering
        streams = channel.streams.all().order_by('channelstream__order')
        logger.debug(f"Channel {channel_id} has {streams.count()} total assigned streams")

        if not streams.exists():
            logger.warning(f"No streams assigned to channel {channel_id}")
            return []

        alternate_streams = []

        # Process each stream in the user-defined order
        for stream in streams:
            logger.debug(f"Checking stream ID {stream.id} ({stream.name}) for channel {channel_id}")

            # BUGFIX: Do NOT skip the current stream entirely - we may want to try different profiles!
            # Only skip the specific (stream_id, profile_id) combination that failed

            # Find compatible profiles for this stream with connection checking
            try:
                m3u_account = stream.m3u_account
                if not m3u_account:
                    logger.debug(f"Stream {stream.id} has no M3U account")
                    continue
                if m3u_account.is_active == False:
                    logger.debug(f"M3U account {m3u_account.id} is inactive, skipping.")
                    continue
                m3u_profiles = m3u_account.profiles.filter(is_active=True)
                default_profile = next((obj for obj in m3u_profiles if obj.is_default), None)

                if not default_profile:
                    logger.debug(f"M3U account {m3u_account.id} has no default profile")
                    continue

                # Check profiles in order with connection availability
                profiles = [default_profile] + [obj for obj in m3u_profiles if not obj.is_default]

                # BUGFIX: Try ALL profiles for this stream, not just the first available one!
                for profile in profiles:
                    # Skip the current stream+profile combination that just failed
                    if current_stream_id and stream.id == current_stream_id and current_profile_id and profile.id == current_profile_id:
                        logger.debug(f"Skipping current failing stream+profile combination: stream={current_stream_id}, profile={current_profile_id}")
                        continue
                    
                    if redis_client:
                        channel_using_profile = False
                        existing_stream_id = redis_client.get(f"channel_stream:{channel.id}")
                        if existing_stream_id:
                            existing_profile_id = redis_client.get(
                                f"stream_profile:{existing_stream_id}"
                            )
                            if existing_profile_id and int(existing_profile_id) == profile.id:
                                channel_using_profile = True
                                logger.debug(
                                    f"Channel {channel.id} already using profile {profile.id}"
                                )

                        if profile_available_for_channel_switch(
                            profile,
                            redis_client,
                            channel_already_on_profile=channel_using_profile,
                        ):
                            current_connections = get_profile_connection_count(
                                profile, redis_client
                            )
                            # BUGFIX: Don't break here - add ALL available profiles!
                            logger.debug(
                                f"Found available profile {profile.id} for stream {stream.id}: "
                                f"{current_connections}/{profile.max_streams} "
                                f"(already using: {channel_using_profile})"
                            )
                            alternate_streams.append({
                                'stream_id': stream.id,
                                'profile_id': profile.id,
                                'name': stream.name
                            })
                            # DON'T break - continue to check other profiles!
                        else:
                            logger.debug(
                                f"Profile {profile.id} unavailable for alternate stream {stream.id}"
                            )
                    else:
                        # No Redis available, add all profiles
                        alternate_streams.append({
                            'stream_id': stream.id,
                            'profile_id': profile.id,
                            'name': stream.name
                        })

            except Exception as inner_e:
                logger.error(f"Error finding profiles for stream {stream.id}: {inner_e}")
                continue

        if alternate_streams:
            stream_profile_pairs = ', '.join([f"({s['stream_id']},{s['profile_id']})" for s in alternate_streams])
            logger.info(f"Found {len(alternate_streams)} alternate stream+profile combinations for channel {channel_id}: [{stream_profile_pairs}]")
        else:
            logger.warning(f"No alternate streams with available connections found for channel {channel_id}")

        return alternate_streams
    except Exception as e:
        logger.error(f"Error getting alternate streams for channel {channel_id}: {e}", exc_info=True)
        return []

def validate_stream_url(url, user_agent=None, timeout=(5, 5)):
    """
    Validate if a stream URL is accessible without downloading the full content.

    Note: UDP/RTP/RTSP streams are automatically considered valid as they cannot
    be validated via HTTP methods.

    Args:
        url (str): The URL to validate
        user_agent (str): User agent to use for the request
        timeout (tuple): Connection and read timeout in seconds

    Returns:
        tuple: (is_valid, final_url, status_code, message)
    """
    # Check if URL uses non-HTTP protocols (UDP/RTP/RTSP)
    # These cannot be validated via HTTP methods, so we skip validation
    if url.startswith(('udp://', 'rtp://', 'rtsp://')):
        logger.info(f"Skipping HTTP validation for non-HTTP protocol: {url}")
        return True, url, 200, "Non-HTTP protocol (UDP/RTP/RTSP) - validation skipped"

    try:
        # Create session with proper headers
        session = requests.Session()
        headers = {
            'User-Agent': user_agent,
            'Connection': 'close'  # Don't keep connection alive
        }
        session.headers.update(headers)

        # Make HEAD request first as it's faster and doesn't download content
        head_request_success = True
        try:
            head_response = session.head(
                url,
                timeout=timeout,
                allow_redirects=True
            )
        except requests.exceptions.RequestException as e:
            head_request_success = False
            logger.warning(f"Request error (HEAD), assuming HEAD not supported: {str(e)}")

        # If HEAD not supported, server will return 405 or other error
        if head_request_success and (200 <= head_response.status_code < 300):
            # HEAD request successful
            return True, url, head_response.status_code, "Valid (HEAD request)"

        # Try a GET request with stream=True to avoid downloading all content
        get_response = session.get(
            url,
            stream=True,
            timeout=timeout,
            allow_redirects=True
        )

        # IMPORTANT: Check status code first before checking content
        if not (200 <= get_response.status_code < 300):
            logger.warning(f"Stream validation failed with HTTP status {get_response.status_code}")
            return False, url, get_response.status_code, f"Invalid HTTP status: {get_response.status_code}"

        # Only check content if status code is valid
        try:
            chunk = next(get_response.iter_content(chunk_size=188*10))
            is_valid = len(chunk) > 0
            message = f"Valid (GET request, received {len(chunk)} bytes)"
        except StopIteration:
            is_valid = False
            message = "Empty response from server"

        # Check content type for additional validation
        content_type = get_response.headers.get('Content-Type', '').lower()

        # Expanded list of valid content types for streaming media
        valid_content_types = [
            'video/',
            'audio/',
            'mpegurl',
            'octet-stream',
            'mp2t',
            'mp4',
            'mpeg',
            'dash+xml',
            'application/mp4',
            'application/mpeg',
            'application/x-mpegurl',
            'application/vnd.apple.mpegurl',
            'application/ogg',
            'm3u',
            'playlist',
            'binary/',
            'rtsp',
            'rtmp',
            'hls',
            'ts'
        ]

        content_type_valid = any(type_str in content_type for type_str in valid_content_types)

        # Always consider the stream valid if we got data, regardless of content type
        # But add content type info to the message for debugging
        if content_type:
            content_type_msg = f" (Content-Type: {content_type}"
            if content_type_valid:
                content_type_msg += ", recognized as valid stream format)"
            else:
                content_type_msg += ", unrecognized but may still work)"
            message += content_type_msg

        # Clean up connection
        get_response.close()

        # If we have content, consider it valid even with unrecognized content type
        return is_valid, url, get_response.status_code, message

    except requests.exceptions.Timeout:
        return False, url, 0, "Timeout connecting to stream"
    except requests.exceptions.TooManyRedirects:
        return False, url, 0, "Too many redirects"
    except requests.exceptions.RequestException as e:
        return False, url, 0, f"Request error: {str(e)}"
    except Exception as e:
        return False, url, 0, f"Validation error: {str(e)}"
    finally:
        if 'session' in locals():
            session.close()

def get_connections_left(m3u_profile_id: int) -> int:
    """
    Get the number of available connections left for an M3U profile.

    Args:
        m3u_profile_id: The ID of the M3U profile

    Returns:
        int: Number of connections available (0 if none available)
    """
    try:
        from core.utils import RedisClient

        # Get the M3U profile
        m3u_profile = M3UAccountProfile.objects.get(id=m3u_profile_id)

        # If max_streams is 0, it means unlimited
        if m3u_profile.max_streams == 0:
            return 999999  # Return a large number to indicate unlimited

        # Get Redis client
        redis_client = RedisClient.get_client()
        if not redis_client:
            logger.warning("Redis not available, assuming connections available")
            return max(0, m3u_profile.max_streams - 1)  # Conservative estimate

        # Check current connections for this specific profile
        profile_connections_key = f"profile_connections:{m3u_profile_id}"
        current_connections = int(redis_client.get(profile_connections_key) or 0)

        # Calculate available connections
        connections_left = max(0, m3u_profile.max_streams - current_connections)

        logger.debug(f"M3U profile {m3u_profile_id}: {current_connections}/{m3u_profile.max_streams} used, {connections_left} available")

        return connections_left

    except M3UAccountProfile.DoesNotExist:
        logger.error(f"M3U profile {m3u_profile_id} not found")
        return 0
    except Exception as e:
        logger.error(f"Error getting connections left for M3U profile {m3u_profile_id}: {e}")
        return 0
