"""REST API for native catch-up playback session setup."""

from django.http import Http404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsStandardUser
from apps.channels.models import Channel
from apps.channels.utils import get_channel_catchup_streams
from core.utils import RedisClient
from dispatcharr.utils import network_access_allowed

from .helpers import MAX_DURATION_MINUTES, parse_catchup_timestamp
from .sessions import (
    HANDSHAKE_TTL_SECONDS,
    SESSION_IDLE_TTL_SECONDS,
    create_catchup_session,
    delete_catchup_session,
    user_owns_catchup_session,
)
from .stats import update_catchup_session_position
from .views import _trigger_timeshift_stats_update, _user_can_access_channel

# Programme length cap expressed in seconds for position reports.
_MAX_POSITION_SECS = MAX_DURATION_MINUTES * 60


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
    duration = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_DURATION_MINUTES,
        help_text=(
            "Optional programme length in minutes. Preferred over EPG when "
            "supplied. A short buffer is added for provider archive lag. "
            "Omit to derive the length from EPG."
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
    duration = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Programme length in minutes if supplied at creation, else null.",
    )


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
            "**``duration``** is optional programme length in minutes. Native "
            "clients should send it when their guide knows the programme "
            "length. Dispatcharr uses it before local EPG duration, adds a "
            "short provider-lag buffer, and falls back to EPG duration, then "
            "the default archive window when omitted.\n\n"
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
            payload = create_catchup_session(
                user=user,
                channel=channel,
                start=start,
                duration=body.validated_data.get("duration"),
            )
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


class CatchupSessionPositionSerializer(serializers.Serializer):
    position_secs = serializers.FloatField(
        min_value=0,
        max_value=_MAX_POSITION_SECS,
        help_text=(
            "Current playhead within the programme, in seconds from programme start."
        ),
    )
    paused = serializers.BooleanField(
        required=False,
        help_text=(
            "When true, admin stats freeze at ``position_secs`` (no wall-clock "
            "advance). When false, clear pause. Omit to leave pause state unchanged."
        ),
    )


class CatchupSessionPositionAPIView(APIView):
    """Native clients report local playhead / pause for catch-up stats polish."""

    permission_classes = [IsStandardUser]

    @extend_schema(
        description=(
            "Update the reported playhead for an active catch-up session.\n\n"
            "Native apps can call this while paused or after local scrubbing so "
            "admin stats stay aligned with what the viewer sees. This does "
            "**not** seek the provider stream; HTTP ``Range`` / a new archive "
            "open still control bytes.\n\n"
            "Requires an active playback connection for ``session_id``. Also "
            "refreshes the session idle TTL."
        ),
        request=CatchupSessionPositionSerializer,
        responses={
            204: None,
            400: inline_serializer(
                name="CatchupSessionPositionError",
                fields={"error": serializers.CharField()},
            ),
            403: inline_serializer(
                name="CatchupSessionPositionForbidden",
                fields={"error": serializers.CharField()},
            ),
            404: inline_serializer(
                name="CatchupSessionPositionNotFound",
                fields={"error": serializers.CharField()},
            ),
        },
        tags=["catchup"],
    )
    def post(self, request, session_id):
        if not network_access_allowed(request, "STREAMS", request.user):
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        if not user_owns_catchup_session(session_id, request.user.id):
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

        body = CatchupSessionPositionSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        updated = update_catchup_session_position(
            session_id,
            position_secs=body.validated_data["position_secs"],
            paused=body.validated_data.get("paused"),
            user_id=request.user.id,
        )
        if not updated:
            return Response(
                {"error": "No active playback for this session"},
                status=status.HTTP_404_NOT_FOUND,
            )

        _trigger_timeshift_stats_update(RedisClient.get_client())
        return Response(status=status.HTTP_204_NO_CONTENT)
