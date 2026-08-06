"""
Utility functions for VOD proxy operations.
"""

import logging
from django.http import HttpResponse

from dispatcharr.utils import get_client_ip

logger = logging.getLogger(__name__)


def get_client_info(request):
    """
    Extract client IP and User-Agent from request.

    Args:
        request: Django HttpRequest object

    Returns:
        tuple: (client_ip, user_agent)
    """
    client_ip = get_client_ip(request) or "unknown"
    user_agent = request.META.get("HTTP_USER_AGENT", "unknown")

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
