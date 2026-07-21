import logging
import os
import re
import time
from rest_framework import viewsets, status, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter, inline_serializer
from drf_spectacular.types import OpenApiTypes
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from .models import EPGSource, ProgramData, EPGData
from .serializers import (
    ProgramDataSerializer,
    ProgramDetailSerializer,
    EPGSourceSerializer,
    EPGDataSerializer,
    ProgramSearchResultSerializer,
)
from .tasks import refresh_epg_data, find_current_program_for_tvg_id
from .query_utils import parse_text_query
from apps.accounts.permissions import (
    Authenticated,
    IsAdmin,
    IsStandardUser,
    permission_classes_by_action,
    permission_classes_by_method,
)
from core.utils import safe_upload_path

logger = logging.getLogger(__name__)


# ─────────────────────────────
# 1) EPG Source API (CRUD)
# ─────────────────────────────
class EPGSourceViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows EPG sources to be viewed or edited.
    """

    queryset = EPGSource.objects.select_related(
        "refresh_task__crontab", "refresh_task__interval"
    ).all()
    serializer_class = EPGSourceSerializer

    def get_permissions(self):
        if self.action == "upload":
            return [IsAdmin()]
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            if self.action in ('sd_lineups', 'sd_lineups_search'):
                if self.request.method == 'GET':
                    return [IsStandardUser()]
                return [IsAdmin()]
            return [IsAdmin()]

    def get_queryset(self):
        from django.db.models import Exists, OuterRef
        from apps.channels.models import Channel
        return EPGSource.objects.select_related(
            "refresh_task__crontab", "refresh_task__interval"
        ).annotate(
            has_channels=Exists(
                Channel.objects.filter(epg_data__epg_source_id=OuterRef('pk'))
            )
        )

    def list(self, request, *args, **kwargs):
        logger.debug("Listing all EPG sources.")
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["post"])
    def upload(self, request):
        if "file" not in request.FILES:
            return Response(
                {"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST
            )

        file = request.FILES["file"]
        try:
            file_path = safe_upload_path(file.name, "/data/uploads/epgs")
        except ValueError:
            return Response(
                {"error": "Invalid filename"}, status=status.HTTP_400_BAD_REQUEST
            )

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb+") as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        new_obj_data = request.data.copy()
        new_obj_data["file_path"] = file_path

        serializer = self.get_serializer(data=new_obj_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        """Handle partial updates with special logic for is_active field"""
        instance = self.get_object()

        # Check if we're toggling is_active
        if (
            "is_active" in request.data
            and instance.is_active != request.data["is_active"]
        ):
            # Set appropriate status based on new is_active value
            if request.data["is_active"]:
                request.data["status"] = "idle"
            else:
                request.data["status"] = "disabled"

        # Continue with regular partial update
        return super().partial_update(request, *args, **kwargs)


    def _sd_authenticate(self, source):
        """
        Authenticate with Schedules Direct using stored credentials.
        Returns (token, None) on success or (None, Response) on failure.
        """
        from apps.epg.sd_utils import (
            SD_AUTH_CREDENTIAL_LOCKOUT_CODES,
            sd_obtain_token,
        )

        result = sd_obtain_token(source, timeout=15)
        if result.ok:
            return result.token, None

        if result.debug_rejected:
            return None, Response(
                {"error": result.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if result.message == 'Username and password are required.':
            http_status = status.HTTP_400_BAD_REQUEST
        elif result.code in SD_AUTH_CREDENTIAL_LOCKOUT_CODES:
            http_status = status.HTTP_401_UNAUTHORIZED
        elif result.lockout or result.soft or result.code:
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            http_status = status.HTTP_502_BAD_GATEWAY

        return None, Response({"error": result.message}, status=http_status)

    def _get_sd_reset_at(self, source):
        """Retrieve stored reset timestamp from EPGSource model field."""
        reset_at_str = (source.custom_properties or {}).get('sd_changes_reset_at')
        return reset_at_str

    def _get_sd_changes_remaining(self, source):
        """
        Retrieve stored changesRemaining from EPGSource model field.
        If a reset timestamp exists and has passed (midnight UTC), clears the
        lockout automatically so the user can make adds again.
        """
        from django.utils import timezone

        cp = source.custom_properties or {}
        changes_remaining = cp.get('sd_changes_remaining')
        reset_at_str = cp.get('sd_changes_reset_at')
        from django.utils.dateparse import parse_datetime
        reset_at = parse_datetime(reset_at_str) if reset_at_str else None

        # If we have a reset timestamp and it has passed, clear the lockout
        if changes_remaining == 0 and reset_at:
            if timezone.now() >= reset_at:
                cp = source.custom_properties or {}
                cp.pop('sd_changes_remaining', None)
                cp.pop('sd_changes_reset_at', None)
                source.custom_properties = cp
                source.save(update_fields=['custom_properties'])
                return None

        return changes_remaining

    def _save_sd_changes_remaining(self, source, changes_remaining):
        """
        Persist changesRemaining on the EPG source.

        When remaining hits 0, also store sd_changes_reset_at (next midnight UTC)
        so the lockout can clear automatically. A positive remaining clears any
        prior reset timestamp.
        """
        from apps.epg.sd_utils import sd_next_midnight_utc

        cp = dict(source.custom_properties or {})
        cp['sd_changes_remaining'] = changes_remaining
        if changes_remaining == 0:
            cp['sd_changes_reset_at'] = sd_next_midnight_utc().isoformat()
        else:
            cp.pop('sd_changes_reset_at', None)
        source.custom_properties = cp
        source.save(update_fields=['custom_properties'])

    def _save_sd_lockout(self, source):
        """
        Persist a hard lockout when SD returns 4100 MAX_LINEUP_CHANGES_REACHED.

        SD lineup change counters reset at 00:00Z (midnight UTC). Lockout clears
        automatically when that reset time passes.
        """
        self._save_sd_changes_remaining(source, 0)
        reset_at = (source.custom_properties or {}).get('sd_changes_reset_at')
        logger.warning(
            f"SD source {source.id}: daily lineup change limit reached (4100). "
            f"Lockout set until {reset_at}."
        )

    def _fetch_sd_countries(self):
        """Fetch the SD country list (token not required; User-Agent is)."""
        import requests as http_requests
        from apps.epg.tasks import SD_BASE_URL
        from core.utils import dispatcharr_http_headers

        try:
            resp = http_requests.get(
                f"{SD_BASE_URL}/available/countries",
                headers=dispatcharr_http_headers(content_type=None),
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except http_requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch SD countries: {e}")
            return None

    @action(detail=True, methods=["get", "post", "delete"], url_path="sd-lineups")
    def sd_lineups(self, request, pk=None):
        """
        GET    — list lineups currently on the SD account
        POST   — add a lineup (body: {"lineup": "USA-NJ29486-X"})
        DELETE — remove a lineup (body: {"lineup": "USA-NJ29486-X"})
        """
        import requests as http_requests
        from apps.epg.tasks import SD_BASE_URL
        from apps.epg.sd_utils import sd_handle_2055, sd_headers_for_source

        source = self.get_object()
        if source.source_type != 'schedules_direct':
            return Response(
                {"error": "This action is only available for Schedules Direct sources."},
                status=status.HTTP_400_BAD_REQUEST
            )

        token, error = self._sd_authenticate(source)
        if error:
            return error

        headers = sd_headers_for_source(source, token=token)

        if request.method == "GET":
            countries = self._fetch_sd_countries()
            try:
                resp = http_requests.get(
                    f"{SD_BASE_URL}/lineups",
                    headers=headers,
                    timeout=15,
                )
                if resp.status_code == 400:
                    sd_data = resp.json()
                    sd_code = sd_data.get('code')
                    if sd_code == 4102:
                        return Response({
                            "lineups": [],
                            "max_lineups": 4,
                            "changes_remaining": self._get_sd_changes_remaining(source),
                            "changes_reset_at": self._get_sd_reset_at(source),
                            "notice": "No lineups are currently configured on this Schedules Direct account. Use the search below to add one.",
                            "countries": countries,
                        })
                resp.raise_for_status()
                data = resp.json()
                lineups = [l for l in data.get('lineups', []) if not l.get('isDeleted', False)]
                return Response({
                    "lineups": lineups,
                    "max_lineups": 4,
                    "changes_remaining": self._get_sd_changes_remaining(source),
                    "changes_reset_at": self._get_sd_reset_at(source),
                    "countries": countries,
                })
            except http_requests.exceptions.RequestException as e:
                return Response(
                    {"error": f"Failed to fetch lineups: {str(e)}"},
                    status=status.HTTP_502_BAD_GATEWAY
                )

        elif request.method == "POST":
            lineup_id = request.data.get('lineup')
            if not lineup_id:
                return Response({"error": "lineup field is required."}, status=status.HTTP_400_BAD_REQUEST)

            # Honor a known daily change lockout without calling SD again.
            if self._get_sd_changes_remaining(source) == 0:
                return Response({
                    "error": "daily_limit_reached",
                    "message": (
                        "You have reached your daily Schedules Direct lineup "
                        "change limit (6 add/delete operations per 24 hours). "
                        "Resets at midnight UTC."
                    ),
                    "changes_remaining": 0,
                    "changes_reset_at": self._get_sd_reset_at(source),
                    "docs_url": "https://github.com/SchedulesDirect/JSON-Service/wiki/API-20141201#tasks-your-client-must-perform",
                }, status=status.HTTP_200_OK)

            try:
                resp = http_requests.put(
                    f"{SD_BASE_URL}/lineups/{lineup_id}",
                    headers=headers,
                    timeout=15,
                )
                sd_data = resp.json()
                sd_code = sd_data.get('code')

                if resp.status_code == 400 or resp.status_code == 403:
                    if sd_code == 4100:
                        self._save_sd_lockout(source)
                        return Response({
                            "error": "daily_limit_reached",
                            "message": (
                                "You have reached your daily Schedules Direct lineup "
                                "change limit (6 add/delete operations per 24 hours). "
                                "Resets at midnight UTC."
                            ),
                            "changes_remaining": 0,
                            "docs_url": "https://github.com/SchedulesDirect/JSON-Service/wiki/API-20141201#tasks-your-client-must-perform",
                        }, status=status.HTTP_200_OK)
                    if sd_code == 4101:
                        return Response({
                            "error": "max_lineups_reached",
                            "message": "Your Schedules Direct account has reached the maximum of 4 lineups. Remove one before adding another.",
                            "changes_remaining": self._get_sd_changes_remaining(source),
                        }, status=status.HTTP_200_OK)
                    if sd_code == 2100:
                        return Response({
                            "error": "duplicate_lineup",
                            "message": "This lineup is already on your Schedules Direct account.",
                            "changes_remaining": self._get_sd_changes_remaining(source),
                        }, status=status.HTTP_200_OK)
                    return Response({
                        "error": sd_data.get('message', 'Failed to add lineup.'),
                        "changes_remaining": self._get_sd_changes_remaining(source),
                    }, status=status.HTTP_200_OK)

                resp.raise_for_status()

                # Persist changesRemaining to custom_properties
                changes_remaining = sd_data.get('changesRemaining')
                if changes_remaining is not None:
                    self._save_sd_changes_remaining(source, changes_remaining)

                logger.info(
                    f"SD lineup added for source {source.id}: {lineup_id}. "
                    f"changesRemaining: {changes_remaining}"
                )

                # Re-fetch stations so the new lineup's stations are available for matching
                from apps.epg.tasks import fetch_schedules_direct_stations
                fetch_schedules_direct_stations.delay(source.id)

                return Response({
                    **sd_data,
                    "changes_remaining": changes_remaining,
                })
            except http_requests.exceptions.RequestException as e:
                return Response(
                    {"error": f"Failed to add lineup: {str(e)}"},
                    status=status.HTTP_502_BAD_GATEWAY
                )

        elif request.method == "DELETE":
            lineup_id = request.data.get('lineup')
            if not lineup_id:
                return Response({"error": "lineup field is required."}, status=status.HTTP_400_BAD_REQUEST)

            if self._get_sd_changes_remaining(source) == 0:
                return Response({
                    "error": "daily_limit_reached",
                    "message": (
                        "You have reached your daily Schedules Direct lineup "
                        "change limit (6 add/delete operations per 24 hours). "
                        "Resets at midnight UTC."
                    ),
                    "changes_remaining": 0,
                    "changes_reset_at": self._get_sd_reset_at(source),
                    "docs_url": "https://github.com/SchedulesDirect/JSON-Service/wiki/API-20141201#tasks-your-client-must-perform",
                }, status=status.HTTP_200_OK)

            try:
                resp = http_requests.delete(
                    f"{SD_BASE_URL}/lineups/{lineup_id}",
                    headers=headers,
                    timeout=15,
                )
                if resp.status_code == 400:
                    sd_data = resp.json()
                    sd_code = sd_data.get('code')
                    if sd_code == 2103:
                        return Response({
                            "response": "OK",
                            "code": 0,
                            "message": "Lineup not found on account — already removed.",
                            "changes_remaining": self._get_sd_changes_remaining(source),
                        })
                    if sd_code == 4100:
                        self._save_sd_lockout(source)
                        return Response({
                            "error": "daily_limit_reached",
                            "message": (
                                "You have reached your daily Schedules Direct lineup "
                                "change limit (6 add/delete operations per 24 hours). "
                                "Resets at midnight UTC."
                            ),
                            "changes_remaining": 0,
                            "docs_url": "https://github.com/SchedulesDirect/JSON-Service/wiki/API-20141201#tasks-your-client-must-perform",
                        }, status=status.HTTP_200_OK)
                resp.raise_for_status()
                sd_data = resp.json()
                # SD returns changesRemaining on deletes — persist it
                changes_remaining = sd_data.get('changesRemaining')
                if changes_remaining is not None:
                    self._save_sd_changes_remaining(source, changes_remaining)
                logger.info(f"SD lineup deleted for source {source.id}: {lineup_id}")
                return Response({
                    **sd_data,
                    "changes_remaining": self._get_sd_changes_remaining(source),
                })
            except http_requests.exceptions.RequestException as e:
                return Response(
                    {"error": f"Failed to remove lineup: {str(e)}"},
                    status=status.HTTP_502_BAD_GATEWAY
                )

    @action(detail=True, methods=["post"], url_path="sd-lineups/search")
    def sd_lineups_search(self, request, pk=None):
        """
        Search available headends/lineups by country and postal code.
        Body: {"country": "USA", "postalcode": "07030"}
        Returns a flat list of lineups across all matching headends.
        """
        import requests as http_requests
        from apps.epg.tasks import SD_BASE_URL
        from apps.epg.sd_utils import sd_handle_2055, sd_headers_for_source

        source = self.get_object()
        if source.source_type != 'schedules_direct':
            return Response(
                {"error": "This action is only available for Schedules Direct sources."},
                status=status.HTTP_400_BAD_REQUEST
            )

        country = request.data.get('country', '').strip()
        postalcode = request.data.get('postalcode', '').strip()
        if not country or not postalcode:
            return Response(
                {"error": "country and postalcode are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        token, error = self._sd_authenticate(source)
        if error:
            return error

        headers = sd_headers_for_source(source, token=token)

        try:
            resp = http_requests.get(
                f"{SD_BASE_URL}/headends",
                params={'country': country, 'postalcode': postalcode},
                headers=headers,
                timeout=15,
            )
            try:
                headends = resp.json()
            except ValueError:
                headends = None
            if isinstance(headends, dict) and sd_handle_2055(source, headends):
                return Response(
                    {
                        "error": (
                            "Schedules Direct rejected the debug routing header "
                            "(code 2055). Extra Schedules Direct Debugging has "
                            "been turned off."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            resp.raise_for_status()
            if not isinstance(headends, list):
                headends = []
            lineups = []
            for headend in headends:
                for lineup in headend.get('lineups', []):
                    lineups.append({
                        'lineup': lineup.get('lineup'),
                        'name': lineup.get('name'),
                        'transport': headend.get('transport'),
                        'location': headend.get('location'),
                        'headend': headend.get('headend'),
                    })
            return Response({"lineups": lineups})
        except http_requests.exceptions.RequestException as e:
            return Response(
                {"error": f"Failed to search headends: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )
# ─────────────────────────────
# 2) Program API (CRUD)
# ─────────────────────────────
class ProgramSearchPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class ProgramViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for EPG programs"""

    queryset = ProgramData.objects.select_related("epg").all()
    serializer_class = ProgramDataSerializer

    # Short process-local cooldown for transient poster errors (auth/network).
    # Image download limits are persisted on the EPG source (shared across workers).
    _sd_poster_error_cache: dict = {}

    def get_permissions(self):
        if self.action == 'poster':
            return [AllowAny()]
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProgramDetailSerializer
        return ProgramDataSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='poster', permission_classes=[AllowAny])
    def poster(self, request, pk=None):
        """Proxy endpoint for SD program poster images. Nginx caches the response."""
        import requests as http_requests
        from apps.epg.sd_utils import (
            SD_CODE_IMAGE_NOT_FOUND,
            SD_IMAGE_LIMIT_CODES,
            sd_auth_lockout_active,
            sd_clear_cached_token,
            sd_get_cached_token,
            sd_handle_2055,
            sd_headers_for_source,
            sd_image_limit_active,
            sd_mark_icon_missing,
            sd_obtain_token,
            sd_parse_response_payload,
            sd_save_image_limit_lockout,
            sd_set_cached_token,
        )

        program = self.get_object()
        cp = program.custom_properties or {}
        if cp.get('sd_icon_missing'):
            return Response(status=status.HTTP_404_NOT_FOUND)
        poster_sd_url = cp.get('sd_icon')
        if not poster_sd_url:
            return Response(status=status.HTTP_404_NOT_FOUND)

        source = program.epg.epg_source if program.epg else None
        if not source or source.source_type != 'schedules_direct':
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Persisted lockout (shared across workers) until next midnight UTC.
        limit_active, limit_reason = sd_image_limit_active(source)
        if limit_active:
            ProgramViewSet._sd_poster_error_cache[source.id] = {
                'until': time.time() + 300,
                'reason': limit_reason,
            }
            return Response(
                {'error': f"SD temporarily unavailable: {limit_reason}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        auth_lockout_active, auth_lockout_reason, _lockout_code = (
            sd_auth_lockout_active(source)
        )
        if auth_lockout_active:
            # Rely on the persisted lockout only. Do not seed the process-local
            # poster error cache here: that cache outlives credential changes and
            # cooldown expiry and would keep returning 503 afterward.
            return Response(
                {'error': auth_lockout_reason},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        error_cache = ProgramViewSet._sd_poster_error_cache.get(source.id)
        if error_cache and time.time() < error_cache['until']:
            return Response(
                {'error': f"SD temporarily unavailable: {error_cache['reason']}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        token = sd_get_cached_token(source.id)

        if not token:
            auth = sd_obtain_token(source, timeout=10)
            if auth.debug_rejected:
                return Response(
                    {'error': auth.message},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not auth.ok:
                # Lockout codes are persisted by sd_obtain_token. Other failures
                # use a short process-local cache so workers do not hammer /token.
                if not auth.lockout:
                    ProgramViewSet._sd_poster_error_cache[source.id] = {
                        'until': time.time() + (3600 if auth.code else 300),
                        'reason': auth.message or 'Authentication failed',
                    }
                return Response(
                    {'error': auth.message},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            token = auth.token
            ProgramViewSet._sd_poster_error_cache.pop(source.id, None)
            sd_set_cached_token(source.id, token, auth.token_expires)

        try:
            img_resp = http_requests.get(
                poster_sd_url,
                headers=sd_headers_for_source(source, token=token, content_type=None),
                timeout=15,
                allow_redirects=True,
            )
            err_code, err_data = sd_parse_response_payload(img_resp)
            if err_data is not None and sd_handle_2055(source, err_data):
                return Response(
                    {
                        'error': (
                            'Schedules Direct rejected the debug routing header '
                            '(code 2055). Extra Schedules Direct Debugging has '
                            'been turned off.'
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # SD documents 5002/5003 as HTTP 200 + JSON. Also accept 4xx.
            if err_code in SD_IMAGE_LIMIT_CODES:
                sd_save_image_limit_lockout(source, err_code)
                ProgramViewSet._sd_poster_error_cache[source.id] = {
                    'until': time.time() + 300,
                    'reason': (
                        f'Daily image download limit reached (SD error {err_code})'
                    ),
                }
                return Response(status=status.HTTP_429_TOO_MANY_REQUESTS)

            # Only blacklist on explicit IMAGE_NOT_FOUND (5000). Bare HTTP 404 can
            # be a transient CDN/S3 miss for ephemeral URIs and must not permanently
            # clear sd_icon (SD docs: code 5000 + HTTP 404).
            if err_code == SD_CODE_IMAGE_NOT_FOUND:
                sd_mark_icon_missing(program)
                return Response(status=status.HTTP_404_NOT_FOUND)

            if img_resp.status_code == 404:
                return Response(status=status.HTTP_404_NOT_FOUND)

            if img_resp.status_code in (401, 403):
                sd_clear_cached_token(source.id)
                ProgramViewSet._sd_poster_error_cache[source.id] = {
                    'until': time.time() + 3600,
                    'reason': f'SD returned {img_resp.status_code}',
                }
                return Response(status=status.HTTP_502_BAD_GATEWAY)

            # JSON error body (even on HTTP 200) is never a valid image.
            if err_data is not None and err_code not in (None, 0):
                logger.warning(
                    "SD poster proxy: unexpected JSON error code %s for program %s",
                    err_code,
                    program.id,
                )
                return Response(status=status.HTTP_502_BAD_GATEWAY)

            if img_resp.status_code != 200:
                return Response(status=status.HTTP_502_BAD_GATEWAY)

            from django.http import HttpResponse
            content_type = img_resp.headers.get('Content-Type', 'image/jpeg')
            if 'json' in (content_type or '').lower():
                return Response(status=status.HTTP_502_BAD_GATEWAY)
            response = HttpResponse(img_resp.content, content_type=content_type)
            response['Cache-Control'] = 'public, max-age=86400'
            return response

        except http_requests.exceptions.RequestException:
            return Response(status=status.HTTP_502_BAD_GATEWAY)

    def list(self, request, *args, **kwargs):
        logger.debug("Listing all EPG programs.")
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Search EPG programs",
        description="""
**Advanced EPG program search with multiple filter types and complex query support.**

### Text Search Features

**Title and Description Search**:
- Supports AND/OR logical operators (case-insensitive: `and`/`AND` both work)
- Wrap phrases in double quotes to match them literally: `"Law and Order"`
- Parenthetical grouping for complex queries: `(Newcastle OR NEW) AND (Villa OR AST)`
- Regex pattern matching with `title_regex=true` (evaluated by the database engine)
- Whole word matching with `title_whole_words=true` to avoid partial matches

**Examples**:
- Simple: `title=football`
- AND operator: `title=premier AND league`
- OR operator: `title=Newcastle OR Villa`
- Quoted phrase: `title="Law and Order"` (matches the exact phrase; 'and' is literal)
- Mixed: `title="Law and Order" AND crime`
- Nested groups: `title=(Newcastle OR NEW) AND (Villa OR AST)`
- Regex: `title=^Premier&title_regex=true` (programs starting with "Premier")
- Whole words: `title=NEW&title_whole_words=true` (matches "NEW" but not "News")

### Time Filtering

**airing_at**: Find programs airing at a specific moment (start_time ≤ airing_at < end_time)

**Time ranges**: Use combinations of start_after, start_before, end_after, end_before

### Response Customization

**fields**: Comma-separated list to include only specific fields in response
- Available: id, title, sub_title, description, start_time, end_time, tvg_id, custom_properties, epg_source, epg_name, epg_icon_url, channels, streams

### Pagination

- Default: 50 results per page
- Maximum: 500 results per page
- Use `page` and `page_size` parameters to navigate results
        """,
        parameters=[
            OpenApiParameter(
                'title',
                OpenApiTypes.STR,
                description='Title search query. Supports AND/OR operators (case-insensitive), quoted phrases, and parentheses. Double-quote a phrase to match it literally: `"Law and Order"`. Unquoted space-separated terms are matched as a phrase; use AND/OR to combine separate terms.',
            ),
            OpenApiParameter('title_regex', OpenApiTypes.BOOL, description='Enable regex matching for title (case-insensitive, default: false). e.g. `^The` matches titles starting with "The".'),
            OpenApiParameter('title_whole_words', OpenApiTypes.BOOL, description='Match whole words only in title (default: false). e.g. `new` matches "Newcastle" normally but not with whole words enabled.'),
            OpenApiParameter(
                'description',
                OpenApiTypes.STR,
                description='Description search query. Same syntax and features as title search.'
            ),
            OpenApiParameter('description_regex', OpenApiTypes.BOOL, description='Enable regex matching for description (case-insensitive, default: false).'),
            OpenApiParameter('description_whole_words', OpenApiTypes.BOOL, description='Match whole words only in description (default: false). Same behaviour as title_whole_words.'),
            OpenApiParameter('start_after', OpenApiTypes.DATETIME, description='Filter programs starting at or after this time. ISO 8601 format, e.g. `2026-02-14T18:00:00Z`.'),
            OpenApiParameter('start_before', OpenApiTypes.DATETIME, description='Filter programs starting at or before this time. ISO 8601 format.'),
            OpenApiParameter('end_after', OpenApiTypes.DATETIME, description='Filter programs ending at or after this time. ISO 8601 format.'),
            OpenApiParameter('end_before', OpenApiTypes.DATETIME, description='Filter programs ending at or before this time. ISO 8601 format.'),
            OpenApiParameter('airing_at', OpenApiTypes.DATETIME, description='Find programs airing at this exact moment (start_time ≤ airing_at < end_time). ISO 8601 format, e.g. `2026-02-14T20:00:00Z`.'),
            OpenApiParameter('channel', OpenApiTypes.STR, description='Filter by channel name (case-insensitive substring match). e.g. `BBC One`, `Sky Sports`.'),
            OpenApiParameter('channel_id', OpenApiTypes.INT, description='Filter by exact channel ID.'),
            OpenApiParameter('tvg_id', OpenApiTypes.STR, description='Filter by EPG tvg_id (exact match). e.g. `bbcone.uk`.'),
            OpenApiParameter('stream', OpenApiTypes.STR, description='Filter by stream name (case-insensitive substring match).'),
            OpenApiParameter('group', OpenApiTypes.STR, description='Filter by channel group or stream group name (case-insensitive substring match). e.g. `Sports`, `UK Channels`.'),
            OpenApiParameter('epg_source', OpenApiTypes.INT, description='Filter by EPG source ID.'),
            OpenApiParameter('fields', OpenApiTypes.STR, description='Comma-separated list of fields to include. Omit to return all fields. e.g. `title,start_time,end_time`.'),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number for pagination (default: 1).'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Results per page (default: 50, max: 500).'),
        ],
        responses={200: ProgramSearchResultSerializer(many=True)},
        tags=['EPG'],
    )
    @action(detail=False, methods=['get'], url_path='search', permission_classes=[IsStandardUser])
    def search(self, request):
        params = request.query_params

        # Build base queryset with prefetching
        queryset = ProgramData.objects.select_related(
            'epg', 'epg__epg_source'
        ).prefetch_related(
            'epg__channels', 'epg__channels__channel_group',
            'epg__channels__streams', 'epg__channels__streams__channel_group',
            'epg__channels__streams__m3u_account',
        )

        filters = Q()

        # Text filters
        title = params.get('title')
        if title:
            title_regex = params.get('title_regex', '').lower() in ('true', '1', 'yes')
            title_whole_words = params.get('title_whole_words', '').lower() in ('true', '1', 'yes')
            filters &= parse_text_query('title', title, use_regex=title_regex, whole_words=title_whole_words)

        description = params.get('description')
        if description:
            desc_regex = params.get('description_regex', '').lower() in ('true', '1', 'yes')
            desc_whole_words = params.get('description_whole_words', '').lower() in ('true', '1', 'yes')
            filters &= parse_text_query('description', description, use_regex=desc_regex, whole_words=desc_whole_words)

        # Time filters with validation
        start_after = params.get('start_after')
        if start_after:
            dt = parse_datetime(start_after)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for start_after: {start_after}. Use ISO 8601 format (e.g., 2026-02-14T18:00:00Z)"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(start_time__gte=dt)

        start_before = params.get('start_before')
        if start_before:
            dt = parse_datetime(start_before)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for start_before: {start_before}. Use ISO 8601 format."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(start_time__lte=dt)

        end_after = params.get('end_after')
        if end_after:
            dt = parse_datetime(end_after)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for end_after: {end_after}. Use ISO 8601 format."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(end_time__gte=dt)

        end_before = params.get('end_before')
        if end_before:
            dt = parse_datetime(end_before)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for end_before: {end_before}. Use ISO 8601 format."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(end_time__lte=dt)

        airing_at = params.get('airing_at')
        if airing_at:
            dt = parse_datetime(airing_at)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for airing_at: {airing_at}. Use ISO 8601 format."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(start_time__lte=dt, end_time__gt=dt)

        # Channel/stream filters
        channel = params.get('channel')
        if channel:
            filters &= Q(epg__channels__name__icontains=channel)

        channel_id = params.get('channel_id')
        if channel_id:
            try:
                filters &= Q(epg__channels__id=int(channel_id))
            except (ValueError, TypeError):
                pass

        tvg_id = params.get('tvg_id')
        if tvg_id:
            filters &= Q(epg__tvg_id=tvg_id)

        stream = params.get('stream')
        if stream:
            filters &= Q(epg__channels__streams__name__icontains=stream)

        group = params.get('group')
        if group:
            filters &= (
                Q(epg__channels__channel_group__name__icontains=group)
                | Q(epg__channels__streams__channel_group__name__icontains=group)
            )

        epg_source = params.get('epg_source')
        if epg_source:
            try:
                filters &= Q(epg__epg_source__id=int(epg_source))
            except (ValueError, TypeError):
                pass

        queryset = queryset.filter(filters).distinct().order_by('start_time')

        # Restrict results to programs on channels the user can access
        user = request.user
        if user.user_level < 10:
            access_filter = Q(epg__channels__user_level__lte=user.user_level)
            custom_props = user.custom_properties or {}
            if custom_props.get('hide_adult_content', False):
                access_filter &= Q(epg__channels__is_adult=False)
            queryset = queryset.filter(access_filter).distinct()

        # Resolve field selection before serialization so expensive methods can short-circuit
        requested_fields = params.get('fields')
        allowed = set(f.strip() for f in requested_fields.split(',')) if requested_fields else None

        # Paginate
        paginator = ProgramSearchPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ProgramSearchResultSerializer(page, many=True, context={'fields': allowed, 'user': request.user})
        data = serializer.data

        if allowed:
            data = [{k: v for k, v in item.items() if k in allowed} for item in data]

        return paginator.get_paginated_response(data)


# ─────────────────────────────
# 3) EPG Grid View
# ─────────────────────────────
class EPGGridAPIView(APIView):
    """Returns all programs airing in the next 24 hours including currently running ones and recent ones"""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Retrieve programs from the previous hour, currently running and upcoming for the next 24 hours",
        responses={200: ProgramDataSerializer(many=True)},
    )
    def get(self, request, format=None):
        # Use current time instead of midnight
        now = timezone.now()
        one_hour_ago = now - timedelta(hours=1)
        twenty_four_hours_later = now + timedelta(hours=24)
        logger.debug(
            f"EPGGridAPIView: Querying programs between {one_hour_ago} and {twenty_four_hours_later}."
        )

        programs = ProgramData.objects.filter(
            end_time__gt=one_hour_ago,
            start_time__lt=twenty_four_hours_later,
        )

        # Generate dummy programs for channels that have no EPG data OR dummy EPG sources
        from apps.channels.models import Channel
        from apps.epg.models import EPGSource
        from django.db.models import Q

        # Get channels with no EPG data at all (standard dummy)
        channels_without_epg = Channel.objects.filter(Q(epg_data__isnull=True))

        # Get channels with custom dummy EPG sources (generate on-demand with patterns)
        channels_with_custom_dummy = Channel.objects.filter(
            epg_data__epg_source__source_type='dummy'
        ).select_related('epg_data__epg_source').distinct()

        # Log what we found
        without_count = channels_without_epg.count()
        custom_count = channels_with_custom_dummy.count()

        if without_count > 0:
            channel_names = [f"{ch.name} (ID: {ch.id})" for ch in channels_without_epg]
            logger.debug(
                f"EPGGridAPIView: Channels needing standard dummy EPG: {', '.join(channel_names)}"
            )

        if custom_count > 0:
            channel_names = [f"{ch.name} (ID: {ch.id})" for ch in channels_with_custom_dummy]
            logger.debug(
                f"EPGGridAPIView: Channels needing custom dummy EPG: {', '.join(channel_names)}"
            )

        logger.debug(
            f"EPGGridAPIView: Found {without_count} channels needing standard dummy, {custom_count} needing custom dummy EPG."
        )

        # Serialize the regular programs using .values() to bypass DRF overhead
        programs_qs = programs.values(
            'id', 'start_time', 'end_time', 'title', 'sub_title',
            'description', 'tvg_id', 'custom_properties',
        )
        serialized_programs = []
        for p in programs_qs:
            cp = p['custom_properties'] or {}
            premiere_text = cp.get('premiere_text', '')
            serialized_programs.append({
                'id': p['id'],
                'start_time': p['start_time'],
                'end_time': p['end_time'],
                'title': p['title'],
                'sub_title': p['sub_title'],
                'description': p['description'],
                'tvg_id': p['tvg_id'],
                'season': cp.get('season'),
                'episode': cp.get('episode'),
                'is_new': bool(cp.get('new')),
                'is_live': bool(cp.get('live')),
                'is_premiere': bool(cp.get('premiere')),
                'is_finale': bool(premiere_text and 'finale' in premiere_text.lower()),
            })
        logger.debug(
            f"EPGGridAPIView: Found {len(serialized_programs)} program(s), including recently ended, currently running, and upcoming shows."
        )

        # Humorous program descriptions based on time of day - same as in output/views.py
        time_descriptions = {
            (0, 4): [
                "Late Night with {channel} - Where insomniacs unite!",
                "The 'Why Am I Still Awake?' Show on {channel}",
                "Counting Sheep - A {channel} production for the sleepless",
            ],
            (4, 8): [
                "Dawn Patrol - Rise and shine with {channel}!",
                "Early Bird Special - Coffee not included",
                "Morning Zombies - Before coffee viewing on {channel}",
            ],
            (8, 12): [
                "Mid-Morning Meetings - Pretend you're paying attention while watching {channel}",
                "The 'I Should Be Working' Hour on {channel}",
                "Productivity Killer - {channel}'s daytime programming",
            ],
            (12, 16): [
                "Lunchtime Laziness with {channel}",
                "The Afternoon Slump - Brought to you by {channel}",
                "Post-Lunch Food Coma Theater on {channel}",
            ],
            (16, 20): [
                "Rush Hour - {channel}'s alternative to traffic",
                "The 'What's For Dinner?' Debate on {channel}",
                "Evening Escapism - {channel}'s remedy for reality",
            ],
            (20, 24): [
                "Prime Time Placeholder - {channel}'s finest not-programming",
                "The 'Netflix Was Too Complicated' Show on {channel}",
                "Family Argument Avoider - Courtesy of {channel}",
            ],
        }

        # Generate and append dummy programs
        dummy_programs = []

        # Import the function from output.views
        from apps.output.views import generate_dummy_programs as gen_dummy_progs

        # Handle channels with CUSTOM dummy EPG sources (with patterns)
        for channel in channels_with_custom_dummy:
            # For dummy EPGs, ALWAYS use channel UUID to ensure unique programs per channel
            # This prevents multiple channels assigned to the same dummy EPG from showing identical data
            # Each channel gets its own unique program data even if they share the same EPG source
            dummy_tvg_id = str(channel.uuid)

            try:
                # Get the custom dummy EPG source
                epg_source = channel.epg_data.epg_source if channel.epg_data else None

                logger.debug(f"Generating custom dummy programs for channel: {channel.name} (ID: {channel.id})")

                # Determine which name to parse based on custom properties
                name_to_parse = channel.name
                if epg_source and epg_source.custom_properties:
                    custom_props = epg_source.custom_properties
                    name_source = custom_props.get('name_source')

                    if name_source == 'stream':
                        # Get the stream index (1-based from user, convert to 0-based)
                        stream_index = custom_props.get('stream_index', 1) - 1

                        # Get streams ordered by channelstream order
                        channel_streams = channel.streams.all().order_by('channelstream__order')

                        if channel_streams.exists() and 0 <= stream_index < channel_streams.count():
                            stream = list(channel_streams)[stream_index]
                            name_to_parse = stream.name
                            logger.debug(f"Using stream name for parsing: {name_to_parse} (stream index: {stream_index})")
                        else:
                            logger.warning(f"Stream index {stream_index} not found for channel {channel.name}, falling back to channel name")
                    elif name_source == 'channel':
                        logger.debug(f"Using channel name for parsing: {name_to_parse}")

                # Generate programs using custom patterns from the dummy EPG source
                # Use the same tvg_id that will be set in the program data
                generated = gen_dummy_progs(
                    channel_id=dummy_tvg_id,
                    channel_name=name_to_parse,
                    num_days=1,
                    program_length_hours=4,
                    epg_source=epg_source,
                    export_lookback=one_hour_ago,
                    export_cutoff=twenty_four_hours_later,
                )

                # Custom dummy should always return data (either from patterns or fallback)
                if generated:
                    logger.debug(f"Generated {len(generated)} custom dummy programs for {channel.name}")
                    # Convert generated programs to API format
                    for program in generated:
                        prog_custom = program.get('custom_properties') or {}
                        dummy_program = {
                            "id": f"dummy-custom-{channel.id}-{program['start_time'].hour}",
                            "epg": {"tvg_id": dummy_tvg_id, "name": channel.name},
                            "start_time": program['start_time'].isoformat(),
                            "end_time": program['end_time'].isoformat(),
                            "title": program['title'],
                            "description": program['description'],
                            "tvg_id": dummy_tvg_id,
                            "sub_title": program.get('sub_title'),
                            "custom_properties": prog_custom if prog_custom else None,
                            "season": None,
                            "episode": None,
                            "is_new": prog_custom.get('new', False),
                            "is_live": bool(prog_custom.get('live')),
                            "is_premiere": False,
                            "is_finale": False,
                        }
                        dummy_programs.append(dummy_program)
                else:
                    logger.warning(f"No programs generated for custom dummy EPG channel: {channel.name}")

            except Exception as e:
                logger.error(
                    f"Error creating custom dummy programs for channel {channel.name} (ID: {channel.id}): {str(e)}"
                )

        # Handle channels with NO EPG data (standard dummy with humorous descriptions)
        for channel in channels_without_epg:
            # For channels with no EPG, use UUID to ensure uniqueness (matches frontend logic)
            # The frontend uses: tvgRecord?.tvg_id ?? channel.uuid
            # Since there's no EPG data, it will fall back to UUID
            dummy_tvg_id = str(channel.uuid)

            try:
                logger.debug(f"Generating standard dummy programs for channel: {channel.name} (ID: {channel.id})")

                # Create programs every 4 hours for the next 24 hours with humorous descriptions
                for hour_offset in range(0, 24, 4):
                    # Use timedelta for time arithmetic instead of replace() to avoid hour overflow
                    start_time = now + timedelta(hours=hour_offset)
                    # Set minutes/seconds to zero for clean time blocks
                    start_time = start_time.replace(minute=0, second=0, microsecond=0)
                    end_time = start_time + timedelta(hours=4)

                    # Get the hour for selecting a description
                    hour = start_time.hour
                    day = 0  # Use 0 as we're only doing 1 day

                    # Find the appropriate time slot for description
                    for time_range, descriptions in time_descriptions.items():
                        start_range, end_range = time_range
                        if start_range <= hour < end_range:
                            # Pick a description using the sum of the hour and day as seed
                            # This makes it somewhat random but consistent for the same timeslot
                            description = descriptions[
                                (hour + day) % len(descriptions)
                            ].format(channel=channel.name)
                            break
                    else:
                        # Fallback description if somehow no range matches
                        description = f"Placeholder program for {channel.name} - EPG data went on vacation"

                    # Create a dummy program in the same format as regular programs
                    dummy_program = {
                        "id": f"dummy-standard-{channel.id}-{hour_offset}",
                        "epg": {"tvg_id": dummy_tvg_id, "name": channel.name},
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "title": f"{channel.name}",
                        "description": description,
                        "tvg_id": dummy_tvg_id,
                        "sub_title": None,
                        "custom_properties": None,
                        "season": None,
                        "episode": None,
                        "is_new": False,
                        "is_live": False,
                        "is_premiere": False,
                        "is_finale": False,
                    }
                    dummy_programs.append(dummy_program)

            except Exception as e:
                logger.error(
                    f"Error creating standard dummy programs for channel {channel.name} (ID: {channel.id}): {str(e)}"
                )

        # Combine regular and dummy programs in place to avoid copying the large list
        serialized_programs.extend(dummy_programs)
        logger.debug(
            f"EPGGridAPIView: Returning {len(serialized_programs)} total programs (including {len(dummy_programs)} dummy programs)."
        )

        # The grid materializes tens of thousands of program dicts plus the
        # rendered JSON; trim once the response is sent so worker RSS does not
        # ratchet up per request.
        from core.utils import spawn_memory_trim
        response = Response({"data": serialized_programs}, status=status.HTTP_200_OK)
        response._resource_closers.append(spawn_memory_trim)
        return response


# ─────────────────────────────
# 4) EPG Import View
# ─────────────────────────────
class EPGImportAPIView(APIView):
    """Triggers an EPG data refresh"""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Triggers an EPG data refresh for the given source.",
        request=inline_serializer(
            name="EPGImportRequest",
            fields={
                "id": serializers.IntegerField(help_text="ID of the EPG source to refresh."),
            },
        ),
    )
    def post(self, request, format=None):
        logger.info("EPGImportAPIView: Received request to import EPG data.")
        epg_id = request.data.get("id", None)
        force = bool(request.data.get("force", False))

        # Reject dummy sources with a narrow existence query, no full row load.
        if epg_id is not None:
            from .models import EPGSource

            if EPGSource.objects.filter(
                id=epg_id, source_type="dummy"
            ).exists():
                logger.info(
                    "EPGImportAPIView: Skipping refresh for dummy EPG source %s",
                    epg_id,
                )
                return Response(
                    {
                        "success": False,
                        "message": "Dummy EPG sources do not require refreshing.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        refresh_epg_data.delay(epg_id, force=force)  # Trigger Celery task
        logger.info("EPGImportAPIView: Task dispatched to refresh EPG data.")
        return Response(
            {"success": True, "message": "EPG data refresh initiated."},
            status=status.HTTP_202_ACCEPTED,
        )


# ─────────────────────────────
# 5) EPG Data View
# ─────────────────────────────
class EPGDataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows EPGData objects to be viewed.
    """

    queryset = EPGData.objects.all()
    serializer_class = EPGDataSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]


# ─────────────────────────────
# 6) Current Programs API
# ─────────────────────────────
class CurrentProgramsAPIView(APIView):
    """
    Lightweight endpoint that returns currently playing programs for specified channel IDs.
    Accepts POST with JSON body containing channel_ids array, or null/empty to fetch all channels.
    """

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Get currently playing programs for specified channels or all channels",
        request=inline_serializer(
            name="CurrentProgramsRequest",
            fields={
                "channel_uuids": serializers.ListField(
                    child=serializers.CharField(),
                    required=False,
                    allow_null=True,
                    help_text="Array of channel UUIDs. If null or omitted, returns all channels with current programs.",
                ),
                "epg_data_ids": serializers.ListField(
                    child=serializers.IntegerField(),
                    required=False,
                    allow_null=True,
                    help_text="Array of EPG data IDs. Can be used instead of channel_ids.",
                ),
            },
        ),
        responses={200: ProgramDataSerializer(many=True)},
    )
    def post(self, request, format=None):
        # Get IDs from request body
        channel_uuids = request.data.get('channel_uuids', None)
        epg_data_ids = request.data.get('epg_data_ids', None)

        # Validate that at most one type of ID is provided
        if channel_uuids is not None and epg_data_ids is not None:
            return Response(
                {"error": "Provide either channel_uuids or epg_data_ids, not both"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get current time
        now = timezone.now()

        # If epg_data_ids are provided, query directly by EPG data
        if epg_data_ids is not None:
            if not isinstance(epg_data_ids, list):
                return Response(
                    {"error": "epg_data_ids must be an array of integers or null"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                epg_data_ids = [int(eid) for eid in epg_data_ids]
            except (ValueError, TypeError):
                return Response(
                    {"error": "epg_data_ids must contain valid integers"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Limit to 50 IDs per request
            epg_data_ids = epg_data_ids[:50]

            epg_data_entries = EPGData.objects.select_related('epg_source').filter(
                id__in=epg_data_ids
            )

            # Batch-fetch current programs for all requested EPG entries in one query
            db_programs = ProgramData.objects.filter(
                epg__in=epg_data_entries, start_time__lte=now, end_time__gt=now
            ).select_related('epg')
            # Map epg_data id -> first matching program
            programs_by_epg = {}
            for prog in db_programs:
                if prog.epg_id not in programs_by_epg:
                    programs_by_epg[prog.epg_id] = prog

            current_programs = []
            for epg_data in epg_data_entries:
                # Check batch-fetched DB results first
                program = programs_by_epg.get(epg_data.id)

                if program:
                    program_data = ProgramDataSerializer(program).data
                    program_data['epg_data_id'] = epg_data.id
                    current_programs.append(program_data)
                    continue

                # Skip dummy sources
                if epg_data.epg_source and epg_data.epg_source.source_type == 'dummy':
                    continue

                # Fall back to byte-offset index lookup, pass the object to avoid re-fetch
                result = find_current_program_for_tvg_id(epg_data)

                if result == "timeout":
                    current_programs.append({
                        "epg_data_id": epg_data.id,
                        "parsing": True,
                    })
                elif result is not None:
                    result['epg_data_id'] = epg_data.id
                    current_programs.append(result)

            return Response(current_programs, status=status.HTTP_200_OK)

        # Otherwise, use channel-based query
        # Import Channel model
        from apps.channels.models import Channel

        # Build query for channels with EPG data
        query = Channel.objects.filter(epg_data__isnull=False)

        if channel_uuids is not None:
            if not isinstance(channel_uuids, list):
                return Response(
                    {"error": "channel_uuids must be an array of strings or null"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            query = query.filter(uuid__in=channel_uuids)

        # Get channels with EPG data
        channels = query.select_related('epg_data')

        # Build list of current programs
        current_programs = []

        for channel in channels:
            # Query for current program
            program = ProgramData.objects.select_related("epg").filter(
                epg=channel.epg_data,
                start_time__lte=now,
                end_time__gt=now
            ).first()

            if program:
                program_data = ProgramDataSerializer(program).data
                program_data['channel_uuid'] = str(channel.uuid)
                current_programs.append(program_data)


        return Response(current_programs, status=status.HTTP_200_OK)
