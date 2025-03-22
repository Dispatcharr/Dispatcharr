"""
Utilities for handling stream URLs and transformations.
"""

import logging
import re
from typing import Optional, Tuple, List
from django.shortcuts import get_object_or_404
from apps.channels.models import Channel, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from core.models import UserAgent, CoreSettings
from .utils import get_logger

logger = get_logger()

def generate_stream_url(channel_id: str) -> Tuple[str, str, bool]:
    """
    Generate the appropriate stream URL for a channel based on its profile settings.

    Args:
        channel_id: The UUID of the channel

    Returns:
        Tuple[str, str, bool]: (stream_url, user_agent, transcode_flag)
    """
    # Get channel and related objects
    channel = get_object_or_404(Channel, uuid=channel_id)
    stream_id, profile_id = channel.get_stream()

    if stream_id is None or profile_id is None:
        logger.error(f"No stream assigned to channel {channel_id}")
        return None, None, False

    # Get the M3U account profile for URL pattern
    stream = get_object_or_404(Stream, pk=stream_id)
    profile = get_object_or_404(M3UAccountProfile, pk=profile_id)

    # Get the appropriate user agent
    m3u_account = M3UAccount.objects.get(id=profile.m3u_account.id)
    stream_user_agent = UserAgent.objects.get(id=m3u_account.user_agent.id).user_agent

    if stream_user_agent is None:
        stream_user_agent = UserAgent.objects.get(id=CoreSettings.get_default_user_agent_id())
        logger.debug(f"No user agent found for account, using default: {stream_user_agent}")

    # Generate stream URL based on the selected profile
    input_url = stream.url
    stream_url = transform_url(input_url, profile.search_pattern, profile.replace_pattern)

    # Check if transcoding is needed
    stream_profile = channel.get_stream_profile()
    if stream_profile.is_proxy() or stream_profile is None:
        transcode = False
    else:
        transcode = True

    # Get profile name as string
    profile_value = stream_profile.id

    return stream_url, stream_user_agent, transcode, profile_value

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

        # Handle backreferences in the replacement pattern
        safe_replace_pattern = re.sub(r'\$(\d+)', r'\\\1', replace_pattern)
        logger.debug(f"  replace: {replace_pattern}")
        logger.debug(f"  safe replace: {safe_replace_pattern}")

        # Apply the transformation
        stream_url = re.sub(search_pattern, safe_replace_pattern, input_url)
        logger.debug(f"Generated stream url: {stream_url}")

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
    try:
        channel = get_object_or_404(Channel, uuid=channel_id)

        # Use the target stream if specified, otherwise use current stream
        if target_stream_id:
            stream_id = target_stream_id

            # Get the stream object
            stream = get_object_or_404(Stream, pk=stream_id)

            # Find compatible profile for this stream
            profiles = M3UAccountProfile.objects.filter(m3u_account=stream.m3u_account)

            if not profiles.exists():
                # Try to get default profile
                default_profile = M3UAccountProfile.objects.filter(
                    m3u_account=stream.m3u_account,
                    is_default=True
                ).first()

                if default_profile:
                    profile_id = default_profile.id
                else:
                    logger.error(f"No profile found for stream {stream_id}")
                    return {'error': 'No profile found for stream'}
            else:
                # Use first available profile
                profile_id = profiles.first().id
        else:
            stream_id, profile_id = channel.get_stream()
            if stream_id is None or profile_id is None:
                return {'error': 'No stream assigned to channel'}

        # Get the stream and profile objects directly
        stream = get_object_or_404(Stream, pk=stream_id)
        profile = get_object_or_404(M3UAccountProfile, pk=profile_id)

        # Get the user agent from the M3U account
        m3u_account = M3UAccount.objects.get(id=profile.m3u_account.id)
        user_agent = UserAgent.objects.get(id=m3u_account.user_agent.id).user_agent
        if not user_agent:
            user_agent = UserAgent.objects.get(id=CoreSettings.get_default_user_agent_id()).user_agent

        # Generate URL using the transform function directly
        stream_url = transform_url(stream.url, profile.search_pattern, profile.replace_pattern)

        # Get transcode info from the channel's stream profile
        stream_profile = channel.get_stream_profile()
        transcode = not (stream_profile.is_proxy() or stream_profile is None)
        profile_value = str(stream_profile)

        return {
            'url': stream_url,
            'user_agent': user_agent,
            'transcode': transcode,
            'profile': profile_value,
            'stream_id': stream_id,
            'profile_id': profile_id
        }
    except Exception as e:
        logger.error(f"Error getting stream info for switch: {e}", exc_info=True)
        return {'error': f'Error: {str(e)}'}

def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = None) -> List[dict]:
    """
    Get alternative streams for a channel when the current stream fails.

    Args:
        channel_id: The UUID of the channel
        current_stream_id: The currently failing stream ID to exclude

    Returns:
        List[dict]: List of stream information dictionaries with stream_id and profile_id
    """
    try:
        # Get channel object
        channel = get_object_or_404(Channel, uuid=channel_id)
        logger.debug(f"Looking for alternate streams for channel {channel_id}, current stream ID: {current_stream_id}")

        # Get all assigned streams for this channel
        streams = channel.streams.all()
        logger.debug(f"Channel {channel_id} has {streams.count()} total assigned streams")

        if not streams.exists():
            logger.warning(f"No streams assigned to channel {channel_id}")
            return []

        alternate_streams = []

        # Process each stream
        for stream in streams:
            # Log each stream we're checking
            logger.debug(f"Checking stream ID {stream.id} ({stream.name}) for channel {channel_id}")

            # Skip the current failing stream
            if current_stream_id and stream.id == current_stream_id:
                logger.debug(f"Skipping current stream ID {current_stream_id}")
                continue

            # Find compatible profiles for this stream
            # FIX: Looking at the error message, M3UAccountProfile doesn't have a 'stream' field
            # We need to find which field relates M3UAccountProfile to Stream
            try:
                # Check if we can find profiles via m3u_account
                profiles = M3UAccountProfile.objects.filter(m3u_account=stream.m3u_account)
                if not profiles.exists():
                    logger.debug(f"No profiles found via m3u_account for stream {stream.id}")
                    # Fallback to the default profile of the account
                    default_profile = M3UAccountProfile.objects.filter(
                        m3u_account=stream.m3u_account,
                        is_default=True
                    ).first()
                    if default_profile:
                        profiles = [default_profile]
                    else:
                        logger.warning(f"No default profile found for m3u_account {stream.m3u_account.id}")
                        continue

                # Get first compatible profile
                profile = profiles.first()
                if profile:
                    logger.debug(f"Found compatible profile ID {profile.id} for stream ID {stream.id}")

                    alternate_streams.append({
                        'stream_id': stream.id,
                        'profile_id': profile.id,
                        'name': stream.name
                    })
                else:
                    logger.debug(f"No compatible profile found for stream ID {stream.id}")
            except Exception as inner_e:
                logger.error(f"Error finding profiles for stream {stream.id}: {inner_e}")
                continue

        if alternate_streams:
            stream_ids = ', '.join([str(s['stream_id']) for s in alternate_streams])
            logger.info(f"Found {len(alternate_streams)} alternate streams for channel {channel_id}: [{stream_ids}]")
        else:
            logger.warning(f"No alternate streams found for channel {channel_id}")

        return alternate_streams
    except Exception as e:
        logger.error(f"Error getting alternate streams for channel {channel_id}: {e}", exc_info=True)
        return []
