"""
Utility functions for VOD proxy operations.
"""

import logging
from django.http import HttpResponse

from dispatcharr.utils import get_client_ip

logger = logging.getLogger(__name__)

# Stored in place of a client address or user agent the request did not carry.
# Two such requests are not the same client, so session matching never treats
# this value as an identity.
UNKNOWN_CLIENT = "unknown"


def get_client_info(request):
    """
    Extract client IP and User-Agent from request.

    Args:
        request: Django HttpRequest object

    Returns:
        tuple: (client_ip, user_agent), each ``UNKNOWN_CLIENT`` when missing
    """
    client_ip = get_client_ip(request) or UNKNOWN_CLIENT
    user_agent = request.META.get("HTTP_USER_AGENT", UNKNOWN_CLIENT)

    return client_ip, user_agent


def create_vod_response(content, content_type='video/mp4', filename=None):
    """
    Create a streaming HTTP response for VOD content.

    Args:
        content: Content to stream (file-like object or bytes)
        content_type: MIME type of the content
        filename: Optional filename for Content-Disposition header

    Returns:
        HttpResponse: Configured HTTP response for streaming
    """
    response = HttpResponse(content, content_type=content_type)

    if filename:
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # Add headers for streaming
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'

    return response
