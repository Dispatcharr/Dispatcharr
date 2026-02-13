import logging
import mimetypes

from django.conf import settings
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.media_library.metadata import find_local_artwork_path
from apps.media_library.file_utils import primary_media_file_for_item
from apps.media_library.models import MediaItem

logger = logging.getLogger(__name__)


def serve_artwork_response(request, item: MediaItem, asset_type: str):
    logger.debug(
        "Artwork request path=%s item_id=%s asset_type=%s",
        request.path,
        item.id,
        asset_type,
    )
    path = find_local_artwork_path(item, asset_type)
    if not path:
        file = primary_media_file_for_item(item)
        logger.debug(
            "Artwork not found item_id=%s asset_type=%s library_id=%s file_path=%s",
            item.id,
            asset_type,
            item.library_id,
            file.path if file else None,
        )
        response = Response(
            {"detail": "Artwork not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
        if settings.DEBUG:
            response["X-Dispatcharr-Artwork-Status"] = "not-found"
        return response
    try:
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        response = FileResponse(open(path, "rb"), content_type=content_type)
    except OSError:
        logger.debug(
            "Artwork file unavailable item_id=%s asset_type=%s path=%s",
            item.id,
            asset_type,
            path,
        )
        response = Response(
            {"detail": "Artwork not available."},
            status=status.HTTP_404_NOT_FOUND,
        )
        if settings.DEBUG:
            response["X-Dispatcharr-Artwork-Status"] = "unavailable"
        return response
    response["Cache-Control"] = "private, max-age=3600"
    if settings.DEBUG:
        response["X-Dispatcharr-Artwork-Path"] = path
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def artwork_poster(request, pk: int):
    item = get_object_or_404(MediaItem, pk=pk)
    return serve_artwork_response(request, item, "poster")


@api_view(["GET"])
@permission_classes([AllowAny])
def artwork_backdrop(request, pk: int):
    item = get_object_or_404(MediaItem, pk=pk)
    return serve_artwork_response(request, item, "backdrop")
