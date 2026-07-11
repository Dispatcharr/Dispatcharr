"""REST API for native catch-up playback session setup."""

from django.http import Http404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsStandardUser
from apps.channels.models import Channel
from apps.channels.utils import get_channel_catchup_streams
from dispatcharr.utils import network_access_allowed

from .helpers import parse_catchup_timestamp
from .sessions import (
    HANDSHAKE_TTL_SECONDS,
    SESSION_IDLE_TTL_SECONDS,
    create_catchup_session,
    delete_catchup_session,
    user_owns_catchup_session,
)
from .views import _user_can_access_channel


class CatchupSessionCreateSerializer(serializers.Serializer):
    channel_uuid = serializers.UUIDField(
        help_text="Dispatcharr channel UUID to play catch-up from.",
    )
    start = serializers.CharField(
        help_text=(
            "UTC programme start time (which archived show to play). "
            "ISO-8601 (2026-07-09T14:00:00Z), Unix epoch, or XC wall-clock shapes."
        ),
    )


class CatchupSessionResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    playback_url = serializers.CharField()
    expires_at = serializers.IntegerField(
        help_text="Unix timestamp. Handshake deadline: first playback GET within this window.",
    )
    channel_uuid = serializers.UUIDField()
    start = serializers.CharField()


class CatchupSessionCreateAPIView(APIView):
    """Mint a server-side playback session for headerless video players."""

    permission_classes = [IsStandardUser]

    @extend_schema(
        description=(
            "Create a catch-up playback session for a single archived programme.\n\n"
            "Call this once per programme with a JWT or API key. The response "
            "includes a ``playback_url`` for the video player **without** an "
            "embedded access token.\n\n"
            "**``start``** is the programme's broadcast start time in UTC "
            "(from EPG ``start_time``). It selects *which* archived show to "
            "fetch, not when the viewer pressed play.\n\n"
            f"The player should open ``playback_url`` within "
            f"**{HANDSHAKE_TTL_SECONDS} seconds** (see ``expires_at``). After the "
            "first byte request, the session stays valid with a "
            f"**{SESSION_IDLE_TTL_SECONDS // 60}-minute sliding idle window** "
            "(refreshed on each range/seek request).\n\n"
            "Start a **new** session for each different programme."
        ),
        request=CatchupSessionCreateSerializer,
        responses={
            201: CatchupSessionResponseSerializer,
            400: inline_serializer(
                name="CatchupSessionCreateError",
                fields={"error": serializers.CharField()},
            ),
            403: inline_serializer(
                name="CatchupSessionForbidden",
                fields={"error": serializers.CharField()},
            ),
            404: inline_serializer(
                name="CatchupSessionNotFound",
                fields={"error": serializers.CharField()},
            ),
        },
        tags=["catchup"],
    )
    def post(self, request):
        user = request.user
        if not network_access_allowed(request, "STREAMS", user):
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        body = CatchupSessionCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        start = body.validated_data["start"].strip()
        if parse_catchup_timestamp(start) is None:
            return Response(
                {"error": "Invalid start timestamp"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        channel_uuid = body.validated_data["channel_uuid"]
        try:
            channel = Channel.objects.get(uuid=channel_uuid)
        except Channel.DoesNotExist:
            raise Http404("Channel not found") from None

        if not _user_can_access_channel(user, channel):
            return Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)

        if not channel.is_catchup:
            return Response(
                {"error": "Catch-up not supported for this channel"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not get_channel_catchup_streams(channel):
            return Response(
                {"error": "Catch-up not supported for this channel"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = create_catchup_session(user=user, channel=channel, start=start)
        except RuntimeError:
            return Response(
                {"error": "Session service unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            CatchupSessionResponseSerializer(payload).data,
            status=status.HTTP_201_CREATED,
        )


class CatchupSessionDestroyAPIView(APIView):
    """Revoke a catch-up playback session early."""

    permission_classes = [IsStandardUser]

    @extend_schema(
        description=(
            "Delete a catch-up session before it expires. Only the user who "
            "created the session may revoke it. Returns 404 when the session "
            "is missing or owned by another user."
        ),
        responses={
            204: None,
            403: inline_serializer(
                name="CatchupSessionDestroyForbidden",
                fields={"error": serializers.CharField()},
            ),
            404: inline_serializer(
                name="CatchupSessionDestroyNotFound",
                fields={"error": serializers.CharField()},
            ),
        },
        tags=["catchup"],
    )
    def delete(self, request, session_id):
        if not network_access_allowed(request, "STREAMS", request.user):
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        if not user_owns_catchup_session(session_id, request.user.id):
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

        delete_catchup_session(session_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
