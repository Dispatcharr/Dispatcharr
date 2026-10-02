"""REST API for native HLS live session control."""

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsStandardUser
from apps.proxy.live_proxy.services.channel_service import ChannelService
from core.utils import RedisClient
from dispatcharr.utils import network_access_allowed

from .session import get_hls_session, hls_session_owned_by


class HlsSessionDestroyAPIView(APIView):
    """Stop the owner's live HLS client for an opaque session token."""

    permission_classes = [IsStandardUser]

    @extend_schema(
        description=(
            "Stop the live HLS client bound to ``token``. Only the user who "
            "minted the session may stop it. Returns 404 when the session is "
            "missing, anonymous, or owned by another user."
        ),
        responses={
            204: None,
            403: inline_serializer(
                name="HlsSessionDestroyForbidden",
                fields={"error": serializers.CharField()},
            ),
            404: inline_serializer(
                name="HlsSessionDestroyNotFound",
                fields={"error": serializers.CharField()},
            ),
        },
        tags=["proxy"],
    )
    def delete(self, request, token):
        if not network_access_allowed(request, "STREAMS", request.user):
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        redis_client = RedisClient.get_client()
        session = get_hls_session(redis_client, token)
        if not hls_session_owned_by(session, request.user.id):
            return Response(
                {"error": "Session not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        ChannelService.stop_client(session["channel_id"], session["client_id"])
        return Response(status=status.HTTP_204_NO_CONTENT)
