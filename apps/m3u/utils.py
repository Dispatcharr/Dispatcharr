# apps/m3u/utils.py
import threading
import logging
from django.db import models

lock = threading.Lock()
# Dictionary to track usage: {m3u_account_id: current_usage}
active_streams_map = {}
logger = logging.getLogger(__name__)


def normalize_stream_url(url):
    """
    Normalize stream URLs for compatibility with FFmpeg.

    Handles VLC-specific syntax like udp://@239.0.0.1:1234 by removing the @ symbol.
    FFmpeg doesn't recognize the @ prefix for multicast addresses.

    Args:
        url (str): The stream URL to normalize

    Returns:
        str: The normalized URL
    """
    if not url:
        return url

    # Handle VLC-style UDP multicast URLs: udp://@239.0.0.1:1234 -> udp://239.0.0.1:1234
    # The @ symbol in VLC means "listen on all interfaces" but FFmpeg doesn't use this syntax
    if url.startswith('udp://@'):
        normalized = url.replace('udp://@', 'udp://', 1)
        logger.debug(f"Normalized VLC-style UDP URL: {url} -> {normalized}")
        return normalized

    # Could add other normalizations here in the future (rtp://@, etc.)
    return url


def increment_stream_count(account):
    with lock:
        current_usage = active_streams_map.get(account.id, 0)
        current_usage += 1
        active_streams_map[account.id] = current_usage
        account.active_streams = current_usage
        account.save(update_fields=['active_streams'])

def decrement_stream_count(account):
    with lock:
        current_usage = active_streams_map.get(account.id, 0)
        if current_usage > 0:
            current_usage -= 1
            if current_usage == 0:
                del active_streams_map[account.id]
            else:
                active_streams_map[account.id] = current_usage
            account.active_streams = current_usage
            account.save(update_fields=['active_streams'])


def calculate_tuner_count(minimum=1, unlimited_default=10):
    """
    Calculate tuner/connection count from active M3U profiles and custom streams.
    This is the centralized function used by both HDHR and XtreamCodes APIs.

    Args:
        minimum (int): Minimum number to return (default: 1)
        unlimited_default (int): Default value when unlimited profiles exist (default: 10)

    Returns:
        int: Calculated tuner/connection count
    """
    try:
        from apps.m3u.models import M3UAccountProfile
        from apps.channels.models import Stream

        # Calculate tuner count from active profiles from active M3U accounts (excluding default "custom Default" profile)
        profiles = M3UAccountProfile.objects.filter(
            is_active=True,
            m3u_account__is_active=True,  # Only include profiles from enabled M3U accounts
        ).exclude(id=1)

        # 1. Check if any profile has unlimited streams (max_streams=0)
        has_unlimited = profiles.filter(max_streams=0).exists()

        # 2. Calculate tuner count from limited profiles
        limited_tuners = 0
        if not has_unlimited:
            limited_tuners = (
                profiles.filter(max_streams__gt=0)
                .aggregate(total=models.Sum("max_streams"))
                .get("total", 0)
                or 0
            )

        # 3. Add custom stream count to tuner count
        custom_stream_count = Stream.objects.filter(is_custom=True).count()
        logger.debug(f"Found {custom_stream_count} custom streams")

        # 4. Calculate final tuner count
        if has_unlimited:
            # If there are unlimited profiles, start with unlimited_default plus custom streams
            tuner_count = unlimited_default + custom_stream_count
        else:
            # Otherwise use the limited profile sum plus custom streams
            tuner_count = limited_tuners + custom_stream_count

        # 5. Ensure minimum number
        tuner_count = max(minimum, tuner_count)

        logger.debug(
            f"Calculated tuner count: {tuner_count} (limited profiles: {limited_tuners}, custom streams: {custom_stream_count}, unlimited: {has_unlimited})"
        )

        return tuner_count

    except Exception as e:
        logger.error(f"Error calculating tuner count: {e}")
        return minimum  # Fallback to minimum value
