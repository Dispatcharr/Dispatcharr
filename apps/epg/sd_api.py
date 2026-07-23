"""
Schedules Direct HTTP API helpers and ViewSet mixins.

Keeps lineup management and poster proxy out of the general EPG view modules.
Protocol/auth helpers live in ``sd_utils``; the refresh pipeline in ``sd_tasks``.
"""

from __future__ import annotations

import logging
import time

import requests as http_requests
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.epg.sd_utils import (
    SD_AUTH_CREDENTIAL_LOCKOUT_CODES,
    SD_BASE_URL,
    SD_CODE_IMAGE_NOT_FOUND,
    SD_IMAGE_LIMIT_CODES,
    sd_auth_lockout_active,
    sd_authorized_request,
    sd_handle_2055,
    sd_image_limit_active,
    sd_mark_icon_missing,
    sd_next_midnight_utc,
    sd_obtain_token,
    sd_parse_response_payload,
    sd_save_image_limit_lockout,
)
from core.utils import dispatcharr_http_headers

logger = logging.getLogger(__name__)


class SchedulesDirectSourceMixin:
    """Lineup management actions and helpers for Schedules Direct EPG sources."""

    def _sd_authenticate(self, source):
        """
        Authenticate with Schedules Direct using stored credentials.
        Returns (token, None) on success or (None, Response) on failure.
        """
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
        cp = source.custom_properties or {}
        changes_remaining = cp.get('sd_changes_remaining')
        reset_at_str = cp.get('sd_changes_reset_at')
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
        source = self.get_object()
        if source.source_type != 'schedules_direct':
            return Response(
                {"error": "This action is only available for Schedules Direct sources."},
                status=status.HTTP_400_BAD_REQUEST
            )

        token, error = self._sd_authenticate(source)
        if error:
            return error

        if request.method == "GET":
            countries = self._fetch_sd_countries()
            try:
                resp, token = sd_authorized_request(
                    'GET',
                    f"{SD_BASE_URL}/lineups",
                    source=source,
                    token=token,
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
                resp, token = sd_authorized_request(
                    'PUT',
                    f"{SD_BASE_URL}/lineups/{lineup_id}",
                    source=source,
                    token=token,
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
                resp, token = sd_authorized_request(
                    'DELETE',
                    f"{SD_BASE_URL}/lineups/{lineup_id}",
                    source=source,
                    token=token,
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

        try:
            resp, token = sd_authorized_request(
                'GET',
                f"{SD_BASE_URL}/headends",
                source=source,
                token=token,
                timeout=15,
                params={'country': country, 'postalcode': postalcode},
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


class SchedulesDirectPosterMixin:
    """Program poster proxy for Schedules Direct artwork URIs."""

    _sd_poster_error_cache: dict = {}

    @action(detail=True, methods=['get'], url_path='poster', permission_classes=[AllowAny])
    def poster(self, request, pk=None):
        """Proxy endpoint for SD program poster images. Nginx caches the response."""
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
            self._sd_poster_error_cache[source.id] = {
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

        error_cache = self._sd_poster_error_cache.get(source.id)
        if error_cache and time.time() < error_cache['until']:
            return Response(
                {'error': f"SD temporarily unavailable: {error_cache['reason']}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

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
                self._sd_poster_error_cache[source.id] = {
                    'until': time.time() + (3600 if auth.code else 300),
                    'reason': auth.message or 'Authentication failed',
                }
            return Response(
                {'error': auth.message},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        token = auth.token
        self._sd_poster_error_cache.pop(source.id, None)

        try:
            img_resp, token = sd_authorized_request(
                'GET',
                poster_sd_url,
                source=source,
                token=token,
                timeout=15,
                content_type=None,
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
                self._sd_poster_error_cache[source.id] = {
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
                # Clear already happened inside sd_authorized_request; seed a short
                # process cache only when the fresh-token retry still failed.
                self._sd_poster_error_cache[source.id] = {
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

            content_type = img_resp.headers.get('Content-Type', 'image/jpeg')
            if 'json' in (content_type or '').lower():
                return Response(status=status.HTTP_502_BAD_GATEWAY)
            response = HttpResponse(img_resp.content, content_type=content_type)
            response['Cache-Control'] = 'public, max-age=86400'
            return response

        except http_requests.exceptions.RequestException:
            return Response(status=status.HTTP_502_BAD_GATEWAY)

