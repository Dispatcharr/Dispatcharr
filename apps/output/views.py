from django.http import HttpResponse, JsonResponse, Http404, HttpResponseForbidden, StreamingHttpResponse
import json
from django.urls import reverse
from apps.channels.models import Channel, ChannelProfile, ChannelGroup, Stream
from apps.channels.utils import format_channel_number, is_catchup_enabled
from apps.vod.utils import is_vod_movies_enabled, is_vod_series_enabled
from django.db.models import Prefetch
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from apps.epg.models import ProgramData
from apps.accounts.models import User
from dispatcharr.utils import get_client_ip, network_access_allowed
from django.utils import timezone as django_timezone
from django.shortcuts import get_object_or_404
from datetime import datetime, timedelta, timezone as dt_timezone
import html
import time
from urllib.parse import urlencode, urlparse
from ipaddress import ip_address
import base64
import logging
from django.db.models.functions import Lower
import os
from apps.m3u.utils import calculate_tuner_count
from apps.proxy.utils import get_user_active_connections
import regex
from core.models import CoreSettings
from core.utils import log_system_event, build_absolute_uri_with_port
import hashlib
from apps.output.dummy_epg import (
    generate_dummy_programs,
    prefetch_streams_for_stream_named_sources,
    resolve_channel_parse_name,
)
from apps.output.epg import generate_epg
from apps.vod.image_proxy import (
    is_proxyable_image_url,
    prefer_relation_artwork,
    rewrite_backdrop_paths,
    rewrite_single_image_url,
    vod_image_url_parts,
)

logger = logging.getLogger(__name__)


def get_client_identifier(request):
    """Get client information including IP, user agent, and a unique hash identifier

    Returns:
        tuple: (client_id_hash, client_ip, user_agent)
    """
    client_ip = get_client_ip(request) or "unknown"
    user_agent = request.META.get("HTTP_USER_AGENT", "unknown")

    # Create a hash for a shorter cache key
    client_str = f"{client_ip}:{user_agent}"
    client_id_hash = hashlib.md5(client_str.encode()).hexdigest()[:12]

    return client_id_hash, client_ip, user_agent


def _direct_m3u_provider_url(streams, allowed_m3u_profiles):
    """Resolve a provider URL for ``direct=true`` M3U output.

    When ``allowed_m3u_profiles`` is set, walk streams in channel order and use
    the first stream whose M3U account has an allowed profile, applying that
    profile's credential/URL transform. Returns ``None`` when no stream is
    usable (caller should omit the channel).

    When unrestricted (``allowed_m3u_profiles is None``), keep historical
    behavior: the first stream's stored URL, or ``None`` if missing.
    """
    from apps.proxy.live_proxy.url_utils import _resolve_live_stream_url

    streams = list(streams)
    if allowed_m3u_profiles is not None:
        for stream in streams:
            profiles = allowed_m3u_profiles.get(stream.m3u_account_id) or []
            if not profiles:
                continue
            profile = profiles[0]
            account = profile.m3u_account or stream.m3u_account
            if not account:
                continue
            url = _resolve_live_stream_url(stream, account, profile)
            if url:
                return url
        return None

    stream = streams[0] if streams else None
    if stream and stream.url:
        return stream.url
    return None

def m3u_endpoint(request, profile_name=None, user=None):
    logger.debug("m3u_endpoint called: method=%s, profile=%s", request.method, profile_name)
    if not network_access_allowed(request, "M3U_EPG"):
        # Log blocked M3U download
        from core.utils import log_system_event
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='m3u_blocked',
            profile=profile_name or 'all',
            reason='Network access denied',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({"error": "Forbidden"}, status=403)

    # Handle HEAD requests efficiently without generating content
    if request.method == "HEAD":
        logger.debug("Handling HEAD request for M3U")
        response = HttpResponse(content_type="audio/x-mpegurl")
        response["Content-Disposition"] = 'attachment; filename="channels.m3u"'
        return response

    return generate_m3u(request, profile_name, user)

def epg_endpoint(request, profile_name=None, user=None):
    logger.debug("epg_endpoint called: method=%s, profile=%s", request.method, profile_name)
    if not network_access_allowed(request, "M3U_EPG"):
        # Log blocked EPG download
        from core.utils import log_system_event
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='epg_blocked',
            profile=profile_name or 'all',
            reason='Network access denied',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({"error": "Forbidden"}, status=403)

    # Handle HEAD requests efficiently without generating content
    if request.method == "HEAD":
        logger.debug("Handling HEAD request for EPG")
        response = HttpResponse(content_type="application/xml")
        response["Content-Disposition"] = 'attachment; filename="Dispatcharr.xml"'
        response["Cache-Control"] = "no-cache"
        return response

    return generate_epg(request, profile_name, user)

@csrf_exempt
@require_http_methods(["GET", "POST", "HEAD"])
def generate_m3u(request, profile_name=None, user=None):
    """
    Dynamically generate an M3U file from channels.
    The stream URL points to the live TS proxy (``/proxy/ts/stream/``).
    Supports both GET and POST methods for compatibility with IPTVSmarters.
    """
    # Check if this is a POST request and the body is not empty (which we don't want to allow)
    logger.debug("Generating M3U for profile: %s, user: %s, method: %s", profile_name, user.username if user else "Anonymous", request.method)

    if request.method == "POST" and request.body:
        if request.body.decode() != '{}':
            return HttpResponseForbidden("POST requests with body are not allowed.")

    # Check cache for recent identical request (helps with double-GET from browsers)
    from django.core.cache import cache

    request_origin = build_absolute_uri_with_port(request, "")
    cache_params = (
        f"{profile_name or 'all'}:{user.username if user else 'anonymous'}"
        f":{request.GET.urlencode()}:origin={request_origin}"
    )
    content_cache_key = f"m3u_content:{cache_params}"

    cached_content = cache.get(content_cache_key)
    if cached_content:
        logger.debug("Serving M3U from cache")
        response = HttpResponse(cached_content, content_type="audio/x-mpegurl")
        response["Content-Disposition"] = 'attachment; filename="channels.m3u"'
        return response

    if user is not None:
        if user.user_level < 10:
            user_profile_count = user.channel_profiles.count()

            # If user has ALL profiles or NO profiles, give unrestricted access
            if user_profile_count == 0:
                # No profile filtering - user sees all channels based on user_level
                filters = {"user_level__lte": user.user_level}
                # Hide adult content if user preference is set
                if (user.custom_properties or {}).get('hide_adult_content', False):
                    filters["is_adult"] = False
                base_qs = Channel.objects.filter(**filters).select_related('channel_group', 'logo')
            else:
                # User has specific limited profiles assigned
                filters = {
                    "channelprofilemembership__enabled": True,
                    "user_level__lte": user.user_level,
                    "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
                }
                # Hide adult content if user preference is set
                if (user.custom_properties or {}).get('hide_adult_content', False):
                    filters["is_adult"] = False
                base_qs = Channel.objects.filter(**filters).select_related('channel_group', 'logo').distinct()
        else:
            base_qs = Channel.objects.filter(user_level__lte=user.user_level).select_related('channel_group', 'logo')

    else:
        if profile_name is not None:
            try:
                channel_profile = ChannelProfile.objects.get(name=profile_name)
            except ChannelProfile.DoesNotExist:
                logger.warning("Requested channel profile (%s) during m3u generation does not exist", profile_name)
                raise Http404(f"Channel profile '{profile_name}' not found")
            base_qs = Channel.objects.filter(
                channelprofilemembership__channel_profile=channel_profile,
                channelprofilemembership__enabled=True
            ).select_related('channel_group', 'logo')
        else:
            base_qs = Channel.objects.select_related('channel_group', 'logo')

    # Resolve effective (override | provider) values at SQL level so ordering,
    # naming, and logo resolution honor user overrides. `exclude(hidden_from_output=True)`
    # is the consumer-facing hide guarantee.
    from apps.channels.managers import with_effective_values
    channels = (
        with_effective_values(base_qs, select_related_fks=True)
        .exclude(hidden_from_output=True)
        .order_by("effective_channel_number")
    )

    # Check if the request wants to use direct logo URLs instead of cache
    use_cached_logos = request.GET.get('cachedlogos', 'true').lower() != 'false'

    # Output profile ID to append to proxy stream URLs (triggers pre-delivery transcode)
    output_profile_id = request.GET.get('output_profile')

    # Output format to append to proxy stream URLs (native ?output_format= or XC-style ?output=)
    output_format_param = request.GET.get('output_format') or request.GET.get('output')

    # Get the source to use for tvg-id value
    # Options: 'channel_number' (default), 'tvg_id', 'gracenote'
    tvg_id_source = request.GET.get('tvg_id_source', 'channel_number').lower()

    # Build EPG URL with query parameters if needed
    # Check if this is an XC API request (has username/password in GET params and user is authenticated)
    xc_username = request.GET.get('username')
    xc_password = request.GET.get('password')
    is_xc_request = user is not None and xc_username and xc_password
    _base_url = request_origin

    # Raw provider URLs (`direct=true`) are for trusted/local use.
    # Non-XC /output/m3u: always allowed (IP-locked self-host surface).
    # XC playlists: only admins (user_level >= 10). Streamers must keep
    # /live/... URLs so provider credentials never appear in their lineup.
    want_direct = request.GET.get('direct', 'false').lower() == 'true'
    use_direct_urls = want_direct and (
        not is_xc_request
        or (user is not None and user.user_level >= 10)
    )
    allowed_m3u_profiles = None
    if use_direct_urls and user is not None:
        from apps.m3u.utils import get_allowed_m3u_profiles

        allowed_m3u_profiles = get_allowed_m3u_profiles(user)

    # Prefetch streams only when direct URLs are requested (avoids N+1 per channel)
    if use_direct_urls:
        channels = channels.prefetch_related(
            Prefetch(
                'streams',
                queryset=Stream.objects.select_related('m3u_account').order_by(
                    'channelstream__order'
                ),
            )
        )

    if is_xc_request:
        # This is an XC API request - use XC-style EPG URL
        epg_url = f"{_base_url}/xmltv.php?username={xc_username}&password={xc_password}"
        # Build the query-string suffix for stream URLs once - it's the same for every channel
        xc_qs = {}
        if output_profile_id:
            xc_qs['output_profile'] = output_profile_id
        if output_format_param:
            xc_qs['output_format'] = output_format_param
        xc_qs_suffix = f"?{urlencode(xc_qs)}" if xc_qs else ""
    else:
        # Pre-compute proxy query-string suffix (same for every channel in this request)
        proxy_qs = {}
        if output_profile_id:
            proxy_qs['output_profile'] = output_profile_id
        if output_format_param:
            proxy_qs['output_format'] = output_format_param
        proxy_qs_suffix = f"?{urlencode(proxy_qs)}" if proxy_qs else ""
        # Regular request - use standard EPG endpoint
        epg_path = reverse('output:epg_endpoint', args=[profile_name]) if profile_name else reverse('output:epg_endpoint')
        epg_base_url = f"{_base_url}{epg_path}"

        # Optionally preserve certain query parameters
        preserved_params = ['tvg_id_source', 'cachedlogos', 'days', 'prev_days']
        query_params = {k: v for k, v in request.GET.items() if k in preserved_params}
        if query_params:
            epg_url = f"{epg_base_url}?{urlencode(query_params)}"
        else:
            epg_url = epg_base_url

    # Add x-tvg-url and url-tvg attribute for EPG URL
    m3u_content = f'#EXTM3U x-tvg-url="{epg_url}" url-tvg="{epg_url}"\n'

    # Host/port/scheme are constant per request; precompute URL prefixes once.
    # XC without direct has no proxy fallback; admin XC+direct may fall back.
    _stream_url_prefix = (
        None
        if is_xc_request and not use_direct_urls
        else f"{_base_url}/proxy/ts/stream/"
    )
    _sample_logo_path = reverse("api:channels:logo-cache", args=[0])
    _logo_prefix_raw, _, _logo_suffix_raw = _sample_logo_path.partition("/0/")
    _logo_url_prefix = _base_url + _logo_prefix_raw + "/"
    _logo_url_suffix = "/" + _logo_suffix_raw

    # Start building M3U content
    channel_count = 0
    for channel in channels:
        direct_provider_url = None
        if use_direct_urls:
            direct_provider_url = _direct_m3u_provider_url(
                channel.streams.all(), allowed_m3u_profiles
            )
            # Allowlisted users only get channels they can actually open with a
            # permitted provider profile. Unrestricted direct keeps the old
            # first-stream / proxy-fallback behavior when no URL is resolved.
            if allowed_m3u_profiles is not None and not direct_provider_url:
                continue

        channel_count += 1
        effective_group = channel.effective_channel_group_obj
        effective_logo = channel.effective_logo_obj
        effective_name = channel.effective_name
        effective_tvg_id_val = channel.effective_tvg_id
        effective_tvc_guide = channel.effective_tvc_guide_stationid
        effective_number = channel.effective_channel_number

        group_title = effective_group.name if effective_group else "Default"

        formatted_channel_number = format_channel_number(effective_number)

        # Determine the tvg-id based on the selected source
        if tvg_id_source == 'tvg_id' and effective_tvg_id_val:
            tvg_id = effective_tvg_id_val
        elif tvg_id_source == 'gracenote' and effective_tvc_guide:
            tvg_id = effective_tvc_guide
        else:
            # Default to channel number (original behavior)
            tvg_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

        tvg_name = effective_name

        tvg_logo = ""
        if effective_logo:
            if use_cached_logos:
                tvg_logo = f"{_logo_url_prefix}{effective_logo.id}{_logo_url_suffix}"
            else:
                # Try to find direct logo URL from channel's streams
                direct_logo = effective_logo.url if effective_logo.url.startswith(('http://', 'https://')) else None
                # If direct logo found, use it; otherwise fall back to cached version
                if direct_logo:
                    tvg_logo = direct_logo
                else:
                    tvg_logo = f"{_logo_url_prefix}{effective_logo.id}{_logo_url_suffix}"

        # create possible gracenote id insertion
        tvc_guide_stationid = ""
        if effective_tvc_guide:
            tvc_guide_stationid = (
                f'tvc-guide-stationid="{effective_tvc_guide}" '
            )

        extinf_line = (
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" '
            f'tvg-chno="{formatted_channel_number}" {tvc_guide_stationid}group-title="{group_title}",{effective_name}\n'
        )

        # Determine the stream URL based on request type
        if use_direct_urls:
            if direct_provider_url:
                stream_url = direct_provider_url
                # Restore VLC-style @ for multicast UDP
                if stream_url.startswith("udp://") and "udp://@" not in stream_url:
                    try:
                        if ip_address(urlparse(stream_url).hostname).is_multicast:
                            stream_url = stream_url.replace("udp://", "udp://@", 1)
                    except ValueError:
                        pass
            else:
                # Fall back to proxy URL if no direct URL available
                stream_url = f"{_stream_url_prefix}{channel.uuid}"
        elif is_xc_request:
            stream_url = f"{_base_url}/live/{xc_username}/{xc_password}/{channel.id}{xc_qs_suffix}"
        else:
            # Standard behavior - use proxy URL
            stream_url = f"{_stream_url_prefix}{channel.uuid}{proxy_qs_suffix}"

        m3u_content += extinf_line + stream_url + "\n"

    # Cache the generated content for 2 seconds to handle double-GET requests
    cache.set(content_cache_key, m3u_content, 2)

    # Log system event for M3U download (with deduplication based on client)
    client_id, client_ip, user_agent = get_client_identifier(request)
    event_cache_key = f"m3u_download:{user.username if user else 'anonymous'}:{profile_name or 'all'}:{client_id}"
    if not cache.get(event_cache_key):
        log_system_event(
            event_type='m3u_download',
            profile=profile_name or 'all',
            user=user.username if user else 'anonymous',
            channels=channel_count,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        cache.set(event_cache_key, True, 2)  # Prevent duplicate events for 2 seconds

    response = HttpResponse(m3u_content, content_type="audio/x-mpegurl")
    response["Content-Disposition"] = 'attachment; filename="channels.m3u"'
    return response


def xc_get_user(request):
    username = request.GET.get("username")
    password = request.GET.get("password")

    if not username or not password:
        return None

    user = get_object_or_404(User, username=username)

    custom_properties = user.custom_properties or {}

    if "xc_password" not in custom_properties:
        return None

    if custom_properties["xc_password"] != password:
        return None

    if not network_access_allowed(request, 'XC_API', user):
        return None

    return user


def _xc_allowed_output_formats(user):
    """Return the list of allowed output formats for the XC API user_info response."""
    return ['ts', 'mp4']


def _build_xc_server_info(request, hostname, port):
    """Build XC ``server_info``; keep timezone, ``time_now``, and EPG times in UTC.

    XC clients use ``server_info.timezone`` to interpret EPG start/end strings.
    Provider-local conversion happens in the timeshift proxy at request time.
    """
    # datetime.timezone.utc, not ZoneInfo("UTC"); avoids mis-set Docker /etc/timezone.
    return {
        "url": hostname,
        "server_protocol": request.scheme,
        "port": port,
        "timezone": "UTC",
        "timestamp_now": int(time.time()),
        "time_now": datetime.now(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "process": True,
    }


def xc_get_info(request, full=False):
    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    raw_host = request.get_host()
    if ":" in raw_host:
        hostname, port = raw_host.split(":", 1)
    else:
        hostname = raw_host
        port = "443" if request.is_secure() else "80"

    if user.stream_limit and user.stream_limit > 0:
        active_cons = len(get_user_active_connections(user.id))
        max_connections = user.stream_limit
    else:
        active_cons = len(get_user_active_connections(None))
        max_connections = calculate_tuner_count(minimum=1, unlimited_default=50)

    info = {
        "user_info": {
            "username": request.GET.get("username"),
            "password": request.GET.get("password"),
            "message": "Dispatcharr XC API",
            "auth": 1,
            "status": "Active",
            "exp_date": str(int(time.time()) + (90 * 24 * 60 * 60)),
            "active_cons": str(active_cons),
            "max_connections": str(max_connections),
            "allowed_output_formats": _xc_allowed_output_formats(user),
        },
        "server_info": _build_xc_server_info(request, hostname, port),
    }

    if full == True:
        info['categories'] = {
            "series": [],
            "movie": [],
            "live": xc_get_live_categories(user),
        }
        info['available_channels'] = {channel["stream_id"]: channel for channel in xc_get_live_streams(request, user, request.GET.get("category_id"))}

    return info


def xc_player_api(request, full=False):
    action = request.GET.get("action")
    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    if action == "get_live_categories":
        return JsonResponse(xc_get_live_categories(user), safe=False)
    elif action == "get_live_streams":
        return StreamingHttpResponse(
            _xc_stream_live_streams_then_refresh(
                request,
                user,
                request.GET.get("category_id"),
            ),
            content_type="application/json",
        )
    elif action == "get_short_epg":
        return JsonResponse(xc_get_epg(request, user, short=True), safe=False)
    elif action == "get_simple_data_table":
        return JsonResponse(xc_get_epg(request, user, short=False), safe=False)
    elif action == "get_vod_categories":
        return JsonResponse(xc_get_vod_categories(user, request=request), safe=False)
    elif action == "get_vod_streams":
        return JsonResponse(xc_get_vod_streams(request, user, request.GET.get("category_id")), safe=False)
    elif action == "get_series_categories":
        return JsonResponse(xc_get_series_categories(user, request=request), safe=False)
    elif action == "get_series":
        return JsonResponse(xc_get_series(request, user, request.GET.get("category_id")), safe=False)
    elif action == "get_series_info":
        return JsonResponse(xc_get_series_info(request, user, request.GET.get("series_id")), safe=False)
    elif action == "get_vod_info":
        return JsonResponse(xc_get_vod_info(request, user, request.GET.get("vod_id")), safe=False)
    else:
        # For any other action (including get_account_info or unknown actions),
        # return server_info/account_info to match provider behavior
        server_info = xc_get_info(request)
        return JsonResponse(server_info, safe=False)


def xc_panel_api(request):
    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return JsonResponse(xc_get_info(request, True))


def xc_get(request):
    if not network_access_allowed(request, 'XC_API'):
        # Log blocked M3U download
        from core.utils import log_system_event
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='m3u_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Network access denied (XC API)',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Forbidden'}, status=403)

    action = request.GET.get("action")
    user = xc_get_user(request)

    if user is None:
        # Log blocked M3U download due to invalid credentials
        from core.utils import log_system_event
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='m3u_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Invalid XC credentials',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return generate_m3u(request, None, user)


def xc_xmltv(request):
    if not network_access_allowed(request, 'XC_API'):
        # Log blocked EPG download
        from core.utils import log_system_event
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='epg_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Network access denied (XC API)',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Forbidden'}, status=403)

    user = xc_get_user(request)

    if user is None:
        # Log blocked EPG download due to invalid credentials
        from core.utils import log_system_event
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='epg_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Invalid XC credentials',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return generate_epg(request, None, user, xc_catchup_prev_days=True)


def xc_get_live_categories(user):
    from django.db.models import Min
    from django.db.models.functions import Coalesce

    response = []

    # Rank categories by the minimum EFFECTIVE channel number across their
    # visible (not hidden_from_output) channels so overridden numbers drive the
    # ordering, not the underlying provider values.
    effective_min = Min(
        Coalesce("channels__override__channel_number", "channels__channel_number")
    )
    hidden_exclusion = {"channels__hidden_from_output": False}

    if user.user_level < 10:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channel groups
            channel_groups = ChannelGroup.objects.filter(
                channels__isnull=False,
                channels__user_level__lte=user.user_level,
                **hidden_exclusion,
            ).distinct().annotate(min_channel_number=effective_min).order_by('min_channel_number')
        else:
            # User has specific limited profiles assigned
            filters = {
                "channels__channelprofilemembership__enabled": True,
                "channels__user_level": 0,
                "channels__channelprofilemembership__channel_profile__in": user.channel_profiles.all(),
                **hidden_exclusion,
            }
            channel_groups = ChannelGroup.objects.filter(**filters).distinct().annotate(min_channel_number=effective_min).order_by('min_channel_number')
    else:
        channel_groups = ChannelGroup.objects.filter(
            channels__isnull=False,
            channels__user_level__lte=user.user_level,
            **hidden_exclusion,
        ).distinct().annotate(min_channel_number=effective_min).order_by('min_channel_number')

    for group in channel_groups:
        response.append(
            {
                "category_id": str(group.id),
                "category_name": group.name,
                "parent_id": 0,
            }
        )

    return response


def _xc_live_streams_setup(request, user, category_id):
    from apps.channels.managers import with_effective_values

    if user.user_level < 10:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channels based on user_level
            filters = {"user_level__lte": user.user_level}
            if category_id is not None:
                filters["channel_group__id"] = category_id
            # Hide adult content if user preference is set
            if (user.custom_properties or {}).get('hide_adult_content', False):
                filters["is_adult"] = False
            base_qs = Channel.objects.filter(**filters).select_related('channel_group', 'logo')
        else:
            # User has specific limited profiles assigned
            filters = {
                "channelprofilemembership__enabled": True,
                "user_level__lte": user.user_level,
                "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
            }
            if category_id is not None:
                filters["channel_group__id"] = category_id
            # Hide adult content if user preference is set
            if (user.custom_properties or {}).get('hide_adult_content', False):
                filters["is_adult"] = False
            base_qs = Channel.objects.filter(**filters).select_related('channel_group', 'logo').distinct()
    else:
        if not category_id:
            base_qs = Channel.objects.filter(user_level__lte=user.user_level).select_related('channel_group', 'logo')
        else:
            base_qs = Channel.objects.filter(
                channel_group__id=category_id, user_level__lte=user.user_level
            ).select_related('channel_group', 'logo')

    channels = (
        with_effective_values(base_qs, select_related_fks=True)
        .exclude(hidden_from_output=True)
        .order_by("effective_channel_number")
    )

    _default_group_id = None

    def _get_default_group_id():
        nonlocal _default_group_id
        if _default_group_id is None:
            _default_group_id = ChannelGroup.objects.get_or_create(name="Default Group")[0].id
        return _default_group_id

    # Build collision-free integer channel number mapping.
    # Channels with integer effective numbers are assigned immediately; those with
    # fractional numbers are deferred until all integers are known, then assigned
    # the nearest available integer to avoid collisions.
    channel_num_map = {}
    used_numbers = set()
    float_channels = []  # (channel.id, effective_num) for deferred resolution

    for channel in channels:  # evaluates and caches the queryset
        effective_num = channel.effective_channel_number
        if effective_num is None:
            float_channels.append((channel.id, None))
        elif effective_num == int(effective_num):
            num = int(effective_num)
            channel_num_map[channel.id] = num
            used_numbers.add(num)
        else:
            float_channels.append((channel.id, effective_num))

    for channel_id, effective_num in float_channels:
        if effective_num is None:
            candidate = 1
        else:
            candidate = int(effective_num)
        while candidate in used_numbers:
            candidate += 1
        channel_num_map[channel_id] = candidate
        used_numbers.add(candidate)

    # Precompute base URL and logo path template once for the entire response
    # to avoid calling reverse() + build_absolute_uri_with_port() per channel.
    _base_url = build_absolute_uri_with_port(request, "")
    _sample_logo_path = reverse("api:channels:logo-cache", args=[0])
    _logo_prefix_raw, _, _logo_suffix_raw = _sample_logo_path.partition("/0/")
    _logo_url_prefix = _base_url + _logo_prefix_raw + "/"
    _logo_url_suffix = "/" + _logo_suffix_raw

    return channels, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix


def _xc_channel_entry(
    channel,
    channel_num_map,
    _get_default_group_id,
    _logo_url_prefix,
    _logo_url_suffix,
    *,
    catchup_allowed=True,
):
    channel_num_int = channel_num_map.get(channel.id)
    if channel_num_int is None:
        effective_num = channel.effective_channel_number
        channel_num_int = (
            int(effective_num) if effective_num is not None else channel.id
        )
    effective_logo = channel.effective_logo_obj
    effective_group = channel.effective_channel_group_obj
    group_id = effective_group.id if effective_group else _get_default_group_id()

    if catchup_allowed and channel.is_catchup:
        tv_archive = 1
        tv_archive_duration = channel.catchup_days
    else:
        tv_archive = 0
        tv_archive_duration = 0

    return {
        "num": channel_num_int,
        "name": channel.effective_name,
        "stream_type": "live",
        "stream_id": channel.id,
        "stream_icon": (
            f"{_logo_url_prefix}{effective_logo.id}{_logo_url_suffix}"
            if effective_logo else None
        ),
        "epg_channel_id": str(channel_num_int),
        "added": str(int(channel.created_at.timestamp())),
        "is_adult": int(channel.is_adult),
        "category_id": str(group_id),
        "category_ids": [group_id],
        "custom_sid": "",
        "tv_archive": tv_archive,
        "direct_source": "",
        "tv_archive_duration": tv_archive_duration,
    }


def xc_get_live_streams(request, user, category_id=None):
    channels, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix = \
        _xc_live_streams_setup(request, user, category_id)
    catchup_allowed = is_catchup_enabled(user=user)
    return [
        _xc_channel_entry(
            ch, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix,
            catchup_allowed=catchup_allowed,
        )
        for ch in channels
    ]


def _xc_stream_live_streams(request, user, category_id=None):
    channels, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix = \
        _xc_live_streams_setup(request, user, category_id)
    catchup_allowed = is_catchup_enabled(user=user)
    yield "["
    sep = ""
    for channel in channels:
        yield sep + json.dumps(
            _xc_channel_entry(
                channel, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix,
                catchup_allowed=catchup_allowed,
            )
        )
        sep = ","
    yield "]"


def _xc_stream_live_streams_then_refresh(request, user, category_id=None):
    """Optionally refresh XC Live providers before or after serving the catalog."""
    refresh_already_requested = False
    try:
        from apps.m3u.client_refresh import (
            get_xc_live_refresh_wait_timeout,
            handle_xc_live_catalog_request,
            wait_for_xc_live_refresh,
        )

        wait_timeout = get_xc_live_refresh_wait_timeout(user)
        if wait_timeout is not None:
            refresh_already_requested = True
            refresh = handle_xc_live_catalog_request(
                request,
                user,
                wait_for_completion=True,
                wait_timeout_seconds=wait_timeout,
            )
            wait_for_xc_live_refresh(
                refresh.get("completion_keys", []),
                wait_timeout,
            )
            yield from _xc_stream_live_streams(request, user, category_id)
            return
    except Exception:
        # Experimental same-response waiting must always fall back to the
        # existing catalog instead of returning a broken XC response.
        logger.warning(
            "Could not wait for an XC Live catalog refresh",
            exc_info=True,
        )

    completed = False
    try:
        yield from _xc_stream_live_streams(request, user, category_id)
        completed = True
    finally:
        if completed and not refresh_already_requested:
            try:
                from apps.m3u.client_refresh import handle_xc_live_catalog_request

                handle_xc_live_catalog_request(request, user)
            except Exception:
                # Observability and background freshness must never corrupt an
                # otherwise valid XC response that has already been streamed.
                logger.warning(
                    "Could not process XC Live catalog refresh request",
                    exc_info=True,
                )


def xc_get_epg(request, user, short=False):
    from apps.channels.managers import with_effective_values

    channel_id = request.GET.get('stream_id')
    if not channel_id:
        raise Http404()

    try:
        resolved_channel_id = int(channel_id)
    except (TypeError, ValueError):
        raise Http404()

    channel = None
    def _annotate(qs):
        return (
            with_effective_values(qs, select_related_fks=True)
            .exclude(hidden_from_output=True)
            .select_related('epg_data__epg_source', 'override__epg_data__epg_source')
        )

    if user.user_level < 10:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channels based on user_level
            filters = {
                "id": resolved_channel_id,
                "user_level__lte": user.user_level
            }
            # Hide adult content if user preference is set
            if (user.custom_properties or {}).get('hide_adult_content', False):
                filters["is_adult"] = False
            channel = _annotate(Channel.objects.filter(**filters)).first()
        else:
            # User has specific limited profiles assigned
            filters = {
                "id": resolved_channel_id,
                "channelprofilemembership__enabled": True,
                "user_level__lte": user.user_level,
                "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
            }
            # Hide adult content if user preference is set
            if (user.custom_properties or {}).get('hide_adult_content', False):
                filters["is_adult"] = False
            channel = _annotate(Channel.objects.filter(**filters).distinct()).first()

        if not channel:
            raise Http404()
    else:
        channel = _annotate(Channel.objects.filter(id=resolved_channel_id)).first()
        if not channel:
            raise Http404()

    if not channel:
        raise Http404()

    prefetch_streams_for_stream_named_sources([channel])

    # Calculate the collision-free integer channel number for this channel
    # This must match the logic in xc_get_live_streams to ensure consistency.
    # The category channels must be filtered by the channel's EFFECTIVE group
    # (an override can move a channel into a different group), then annotated
    # so the comparison runs on effective numbers.
    effective_group = channel.effective_channel_group_obj
    category_channels = (
        with_effective_values(
            Channel.objects.filter(channel_group=effective_group) if effective_group else Channel.objects.none()
        )
        .exclude(hidden_from_output=True)
        .order_by("effective_channel_number")
    )

    channel_num_map = {}
    used_numbers = set()

    # First pass: assign integers for channels that already have integer effective numbers
    for ch in category_channels:
        effective_num = ch.effective_channel_number
        if effective_num is not None and effective_num == int(effective_num):
            num = int(effective_num)
            channel_num_map[ch.id] = num
            used_numbers.add(num)

    # Second pass: assign integers for channels with float effective numbers
    for ch in category_channels:
        effective_num = ch.effective_channel_number
        if effective_num is not None and effective_num != int(effective_num):
            candidate = int(effective_num)
            while candidate in used_numbers:
                candidate += 1
            channel_num_map[ch.id] = candidate
            used_numbers.add(candidate)

    # Get the mapped integer for this specific channel
    channel_num_int = channel_num_map.get(
        channel.id,
        int(channel.effective_channel_number) if channel.effective_channel_number is not None else 0,
    )

    from apps.channels.utils import resolve_xc_epg_prev_days

    limit = int(request.GET.get('limit', 4))
    user_custom = user.custom_properties or {}
    try:
        num_days = int(request.GET.get('days', user_custom.get('epg_days', 0)))
        num_days = max(0, min(num_days, 365))
    except (ValueError, TypeError):
        num_days = 0
    prev_days = resolve_xc_epg_prev_days(request, user, auto_detect_fallback=False)
    now = django_timezone.now()

    # XC catch-up clients expect past programmes when prev_days was not set.
    # Only expand from channel.catchup_days while catch-up is allowed; when
    # disabled, honor URL / user epg_prev_days alone (no forced lookback).
    catchup_allowed = is_catchup_enabled(user=user)
    channel_is_catchup = getattr(channel, "is_catchup", False)
    _channel_catchup_days = min(getattr(channel, "catchup_days", 0) or 0, 30)
    if catchup_allowed and channel_is_catchup and prev_days == 0:
        prev_days = _channel_catchup_days

    lookback_cutoff = now - timedelta(days=prev_days)
    forward_cutoff = now + timedelta(days=num_days) if num_days > 0 else None
    dummy_days = num_days if num_days > 0 else 3
    effective_epg_data = channel.effective_epg_data_obj
    effective_name = channel.effective_name

    # Short EPG: current/upcoming only, stop after `limit` programmes (XC default 4).
    dummy_lookback = now if short else lookback_cutoff
    dummy_max_programs = limit if short else None

    if effective_epg_data:
        # Check if this is a dummy EPG that generates on-demand
        if effective_epg_data.epg_source and effective_epg_data.epg_source.source_type == 'dummy':
            if not effective_epg_data.programs.exists():
                parse_name = resolve_channel_parse_name(
                    channel,
                    effective_epg_data.epg_source,
                    fallback_name=effective_name,
                )
                programs = generate_dummy_programs(
                    channel_id=channel_id,
                    channel_name=parse_name,
                    num_days=dummy_days,
                    epg_source=effective_epg_data.epg_source,
                    export_lookback=dummy_lookback,
                    export_cutoff=forward_cutoff,
                    max_programs=dummy_max_programs,
                )
            else:
                # Has stored programs, use them
                if short:
                    # Short EPG: current and upcoming only (never historical), limited count
                    programs = effective_epg_data.programs.filter(
                        end_time__gt=now
                    ).order_by('start_time')[:limit]
                else:
                    qs = effective_epg_data.programs.filter(end_time__gt=lookback_cutoff)
                    if forward_cutoff:
                        qs = qs.filter(start_time__lt=forward_cutoff)
                    programs = qs.order_by('start_time')
        else:
            # Regular EPG with stored programs
            if short:
                # Short EPG: current and upcoming only (never historical), limited count
                programs = effective_epg_data.programs.filter(
                    end_time__gt=now
                ).order_by('start_time')[:limit]
            else:
                qs = effective_epg_data.programs.filter(end_time__gt=lookback_cutoff)
                if forward_cutoff:
                    qs = qs.filter(start_time__lt=forward_cutoff)
                programs = qs.order_by('start_time')
    else:
        # No EPG data assigned, generate default dummy
        programs = generate_dummy_programs(
            channel_id=channel_id,
            channel_name=effective_name,
            num_days=dummy_days,
            epg_source=None,
            export_lookback=dummy_lookback,
            export_cutoff=forward_cutoff,
            max_programs=dummy_max_programs,
        )

    output = {"epg_listings": []}

    if channel_is_catchup and catchup_allowed:
        archive_window = timedelta(days=_channel_catchup_days)
    else:
        archive_window = None

    _epg_utc = dt_timezone.utc

    for program in programs:
        title = program['title'] if isinstance(program, dict) else program.title
        description = program['description'] if isinstance(program, dict) else program.description

        start = program["start_time"] if isinstance(program, dict) else program.start_time
        end = program["end_time"] if isinstance(program, dict) else program.end_time

        # For database programs, use actual ID; for generated dummy programs, create synthetic ID
        if isinstance(program, dict):
            # Generated dummy program - create unique ID from channel + timestamp
            program_id = str(abs(hash(f"{channel_id}_{int(start.timestamp())}")))
        else:
            # Database program - use actual ID
            program_id = str(program.id)

        # epg_id refers to the EPG source/channel mapping in XC panels
        # Use the actual EPGData ID when available, otherwise fall back to 0
        epg_id = str(effective_epg_data.id) if effective_epg_data else "0"

        program_output = {
            "id": program_id,
            "epg_id": epg_id,
            "title": base64.b64encode((title or "").encode()).decode(),
            "lang": "",
            "start": start.astimezone(_epg_utc).strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.astimezone(_epg_utc).strftime("%Y-%m-%d %H:%M:%S"),
            "description": base64.b64encode((description or "").encode()).decode(),
            "channel_id": str(channel_num_int),
            "start_timestamp": str(int(start.timestamp())),
            "stop_timestamp": str(int(end.timestamp())),
            "stream_id": f"{channel_id}",
        }

        if archive_window is not None and end < now and end > now - archive_window:
            program_output["has_archive"] = 1
        else:
            program_output["has_archive"] = 0

        if short == False:
            program_output["now_playing"] = 1 if start <= now <= end else 0

        output['epg_listings'].append(program_output)

    return output


XC_MOVIE_VALUE_FIELDS = (
    'id', 'movie_id', 'category_id', 'container_extension', 'tmdb_override_id',
    'movie__id', 'movie__name', 'movie__clean_title', 'movie__display_name',
    'movie__rating', 'movie__created_at',
    'movie__tmdb_id', 'movie__imdb_id', 'movie__description', 'movie__genre',
    'movie__year', 'movie__is_adult', 'movie__custom_properties', 'movie__logo_id',
    'movie__tmdb_match_id', 'movie__tmdb_imdb_id',
    'movie__tmdb_poster_url', 'movie__tmdb_backdrop_url',
    # Lean relation-artwork extracts (see _xc_annotate_relation_artwork).
    'rel_movie_image', 'rel_backdrop', 'rel_source_name',
)

XC_SERIES_VALUE_FIELDS = (
    'id', 'series_id', 'category_id', 'updated_at', 'tmdb_override_id',
    'series__id', 'series__name', 'series__clean_title', 'series__display_name',
    'series__description', 'series__genre',
    'series__year', 'series__rating', 'series__custom_properties', 'series__logo_id',
    'series__tmdb_id', 'series__imdb_id',
    'series__tmdb_match_id', 'series__tmdb_imdb_id',
    'series__tmdb_poster_url', 'series__tmdb_backdrop_url',
    # Lean relation-artwork extracts (see _xc_annotate_relation_artwork).
    'rel_movie_image', 'rel_backdrop', 'rel_source_name',
)

XC_CURATED_VALUE_FIELDS = (
    'rel_curated_title', 'rel_curated_overview',
    'rel_curated_release_date', 'rel_curated_rating',
    'rel_curated_runtime', 'rel_curated_genres',
)


def _xc_uses_curated_metadata(policy):
    """Whether the profile projects canonical/TMDB descriptive metadata."""
    if not policy:
        return False
    return getattr(policy, "metadata_source", "provider") == "canonical"


def _xc_genre_names(value):
    if not isinstance(value, list):
        return ""
    return ", ".join(
        str(row.get("name") or "").strip()
        for row in value
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    )


def _xc_curated_row_values(row, prefix):
    """Return lightweight enriched values selected for an XC list row."""
    release_date = str(row.get("rel_curated_release_date") or "").strip()
    year = row.get(f"{prefix}__year") or ""
    if release_date[:4].isdigit():
        year = int(release_date[:4])
    rating = row.get("rel_curated_rating")
    if rating in (None, ""):
        rating = row.get(f"{prefix}__rating")
    elif isinstance(rating, str):
        try:
            rating = float(rating)
        except ValueError:
            pass
    runtime = row.get("rel_curated_runtime")
    if isinstance(runtime, str) and runtime.isdigit():
        runtime = int(runtime)
    return {
        "title": str(row.get("rel_curated_title") or "").strip(),
        "overview": str(row.get("rel_curated_overview") or "").strip()
        or row.get(f"{prefix}__description")
        or "",
        "release_date": release_date,
        "year": year,
        "rating": rating,
        "runtime": runtime,
        "genre": _xc_genre_names(row.get("rel_curated_genres"))
        or row.get(f"{prefix}__genre")
        or "",
    }


def _xc_curated_object_values(content):
    """Resolve the same enriched fields for a single movie/series detail."""
    metadata = content.tmdb_metadata if isinstance(content.tmdb_metadata, dict) else {}
    languages = CoreSettings.get_tmdb_languages()
    localized = metadata.get("localized") or {}
    localized_values = localized.get(languages[0]) or {}
    if not localized_values:
        localized_values = next(
            (row for row in localized.values() if isinstance(row, dict)),
            {},
        )
    release_date = str(metadata.get("release_date") or "").strip()
    year = content.year or ""
    if release_date[:4].isdigit():
        year = int(release_date[:4])
    rating = metadata.get("rating")
    if rating in (None, ""):
        rating = content.rating
    provider_properties = content.custom_properties or {}
    return {
        "title": str(localized_values.get("title") or content.display_name or "").strip(),
        "overview": str(
            localized_values.get("overview")
            or metadata.get("overview")
            or content.description
            or ""
        ).strip(),
        "release_date": release_date,
        "year": year,
        "rating": rating,
        "runtime": metadata.get("runtime_minutes"),
        "genre": _xc_genre_names(metadata.get("genres")) or content.genre or "",
        "director": (
            metadata.get("director")
            or provider_properties.get("director")
            or ""
        ),
        "actors": (
            metadata.get("actors")
            or provider_properties.get("actors")
            or provider_properties.get("cast")
            or ""
        ),
        "crew": metadata.get("crew") or provider_properties.get("crew") or "",
        "country": (
            metadata.get("country")
            or provider_properties.get("country")
            or ""
        ),
        "age_rating": (
            metadata.get("age_rating")
            or provider_properties.get("age")
            or ""
        ),
        "youtube_trailer": (
            metadata.get("youtube_trailer")
            or provider_properties.get("youtube_trailer")
            or ""
        ),
    }


# Same key precedence get_relation_artwork uses for a single cover/still.
XC_RELATION_IMAGE_KEYS = ('movie_image', 'cover_big', 'stream_icon', 'cover')


def _xc_annotate_relation_artwork(qs):
    """Annotate lean artwork fields from relation custom_properties JSON.

    Avoids selecting the full JSON blob (basic_data holds the raw provider list
    entry and detailed_info the advanced payload, which add up across 50k+ VOD
    rows) while keeping get_relation_artwork's preference order for movie/series
    relations: detailed_info, then basic_data. Blank / whitespace-only strings and
    empty backdrop arrays are treated as missing, matching the Python helper,
    since raw basic_data is stored uncleaned and often carries empty image keys.
    """
    from django.db.models import CharField, F, Value
    from django.db.models.fields.json import JSONField, KeyTextTransform, KeyTransform
    from django.db.models.functions import Coalesce, NullIf, Trim

    basic = KeyTransform('basic_data', 'custom_properties')
    detailed = KeyTransform('detailed_info', 'custom_properties')
    movie_data = KeyTransform('movie_data', 'custom_properties')
    content_field = (
        "movie" if qs.model.__name__ == "M3UMovieRelation" else "series"
    )
    tmdb_metadata = F(f"{content_field}__tmdb_metadata")
    localized = KeyTransform("localized", tmdb_metadata)
    primary_language = CoreSettings.get_tmdb_languages()[0]
    primary_values = KeyTransform(primary_language, localized)

    def image_candidates(container):
        return [
            NullIf(Trim(KeyTextTransform(key, container)), Value(''))
            for key in XC_RELATION_IMAGE_KEYS
        ]

    def backdrop_candidates(container):
        path = KeyTransform('backdrop_path', container)
        # Nested NullIf so an empty array is not kept by the empty-string check
        # (Coalesce would otherwise stop on [] because [] != '').
        return [
            NullIf(
                NullIf(path, Value([], output_field=JSONField())),
                Value('', output_field=JSONField()),
            )
        ]

    return qs.annotate(
        rel_movie_image=Coalesce(
            *image_candidates(detailed),
            *image_candidates(basic),
            Value(''),
            output_field=CharField(),
        ),
        rel_backdrop=Coalesce(
            *backdrop_candidates(detailed),
            *backdrop_candidates(basic),
        ),
        # Extract only the source title instead of selecting the often-large
        # relation JSON payload for every XC list row.
        rel_source_name=Coalesce(
            NullIf(Trim(KeyTextTransform('name', basic)), Value('')),
            NullIf(Trim(KeyTextTransform('name', movie_data)), Value('')),
            NullIf(Trim(KeyTextTransform('name', detailed)), Value('')),
            NullIf(Trim(KeyTextTransform('original_name', detailed)), Value('')),
            NullIf(Trim(KeyTextTransform('o_name', detailed)), Value('')),
            NullIf(Trim(KeyTextTransform('original_name', basic)), Value('')),
            NullIf(Trim(KeyTextTransform('o_name', basic)), Value('')),
            Value(''),
            output_field=CharField(),
        ),
        rel_curated_title=Coalesce(
            NullIf(Trim(KeyTextTransform('title', primary_values)), Value('')),
            Value(''),
            output_field=CharField(),
        ),
        rel_curated_overview=Coalesce(
            NullIf(Trim(KeyTextTransform('overview', primary_values)), Value('')),
            NullIf(Trim(KeyTextTransform('overview', tmdb_metadata)), Value('')),
            Value(''),
            output_field=CharField(),
        ),
        rel_curated_release_date=Coalesce(
            NullIf(Trim(KeyTextTransform('release_date', tmdb_metadata)), Value('')),
            Value(''),
            output_field=CharField(),
        ),
        rel_curated_rating=KeyTextTransform('rating', tmdb_metadata),
        rel_curated_runtime=KeyTextTransform('runtime_minutes', tmdb_metadata),
        rel_curated_genres=KeyTransform('genres', tmdb_metadata),
    )


def _xc_relation_artwork_from_row(
    row, object_custom_properties, *, prefix, prefer_tmdb
):
    """Build prefer_relation_artwork input from lean list-row extracts."""
    return prefer_relation_artwork(
        {
            'movie_image': row.get('rel_movie_image') or '',
            'backdrop_path': row.get('rel_backdrop') or [],
        },
        object_custom_properties,
        tmdb_poster_url=row.get(f'{prefix}__tmdb_poster_url') or '',
        tmdb_backdrop_url=row.get(f'{prefix}__tmdb_backdrop_url') or '',
        prefer_tmdb=prefer_tmdb,
    )


def _xc_vodlogo_url_parts(request):
    """Return (prefix, suffix) for VODLogo cache URLs.

    Precomputed once per response so each row is a string concat instead of a
    reverse() plus absolute-URI build.
    """
    base_url = build_absolute_uri_with_port(request, "")
    sample_path = reverse("api:vod:vodlogo-cache", args=[0])
    prefix_raw, _, suffix_raw = sample_path.partition("/0/")
    return base_url + prefix_raw + "/", "/" + suffix_raw


def _xc_cover_or_logo(
    request, resource, pk, artwork_movie_image, *, logo_id, logo_url_parts, url_parts
):
    """Relation/object still first; synced VODLogo only when no proxyable still exists."""
    if is_proxyable_image_url(artwork_movie_image):
        return rewrite_single_image_url(
            request,
            resource,
            pk,
            'movie_image',
            artwork_movie_image,
            url_parts=url_parts,
        )
    if logo_id:
        logo_prefix, logo_suffix = logo_url_parts
        return f"{logo_prefix}{logo_id}{logo_suffix}"
    return None


def _xc_fetch_priority_distinct_relations(
    *,
    manager,
    rel_filters,
    distinct_field,
    value_fields,
    order_by_name_field,
    policy=None,
    canonical_field=None,
    prepared_filters=None,
):
    """
    Return one row dict per selected source key.

    On PostgreSQL, dedupe on narrow relation rows first, then fetch display
    columns via values() (no ORM model instantiation). That avoids sorting
    wide joined rows during DISTINCT ON and reduces parallel worker /dev/shm
    pressure in Docker. With a VOD user policy, the streaming selector chooses
    by language, subtitles, and resolution before the wide rows are fetched.
    """
    from django.db import connection, transaction

    narrow_qs = manager.filter(**rel_filters)
    distinct_fields = (
        (distinct_field,)
        if isinstance(distinct_field, str)
        else tuple(distinct_field)
    )

    def _fetch_by_ids(ids):
        # Avoid database parameter limits and oversized SQL statements on very
        # large libraries. Sorting is done once after all narrow chunks arrive.
        rows = []
        chunk_size = 2000
        for offset in range(0, len(ids), chunk_size):
            chunk = ids[offset:offset + chunk_size]
            rows.extend(
                _xc_annotate_relation_artwork(manager.filter(pk__in=chunk))
                .values(*value_fields)
            )
        rows.sort(key=lambda row: (row[order_by_name_field] or '').lower())
        return rows

    if policy is not None:
        from apps.vod.policies import (
            allowed_category_query,
            select_relation_ids_for_policy,
        )
        from apps.vod.profile_selection import prepared_relation_rows

        narrow_qs = narrow_qs.filter(allowed_category_query(policy))

        prepared_rows = prepared_relation_rows(
            policy,
            manager.model,
            rel_filters,
            selection_filters=prepared_filters,
        )
        if prepared_rows is not None:
            rows = _fetch_by_ids(list(prepared_rows))
            for row in rows:
                snapshot = prepared_rows.get(row["id"], {})
                row.update(
                    profile_edition_key=snapshot.get("edition_key", ""),
                    profile_edition_name=snapshot.get("edition_name", ""),
                    profile_edition_suffix=snapshot.get("edition_suffix", ""),
                    profile_output_name=snapshot.get("output_name", ""),
                )
            return rows

        candidate_iterator = (
            narrow_qs.select_related(
                "m3u_account",
            )
            .order_by("pk")
            .iterator(chunk_size=2000)
        )
        selected_ids = select_relation_ids_for_policy(
            candidate_iterator,
            policy,
            canonical_field=canonical_field,
        )
        return _fetch_by_ids(selected_ids)

    if connection.vendor == 'postgresql':
        winning_ids_qs = (
            narrow_qs
            .order_by(
                *distinct_fields,
                '-m3u_account__priority',
                'id',
            )
            .distinct(*distinct_fields)
            .values('pk')
        )
        with transaction.atomic():
            winning_ids = list(winning_ids_qs.values_list('pk', flat=True))
            if not winning_ids:
                return []
            return _fetch_by_ids(winning_ids)

    seen = {}
    for row in _xc_annotate_relation_artwork(narrow_qs).values(*value_fields).order_by(
        '-m3u_account__priority', 'id'
    ):
        key = tuple(row[field] for field in distinct_fields)
        if key not in seen:
            seen[key] = row
    rows = list(seen.values())
    rows.sort(key=lambda r: (r[order_by_name_field] or '').lower())
    return rows


def _xc_policy_for_user(user):
    from apps.vod.policies import policy_for_user

    if not hasattr(user, "_vod_access_policy"):
        user._vod_access_policy = policy_for_user(user)
    return user._vod_access_policy


def xc_get_vod_categories(user, request=None):
    """Get VOD categories for XtreamCodes API"""
    if not is_vod_movies_enabled(user=user):
        return []

    from apps.vod.models import VODCategory, M3UMovieRelation

    from apps.vod.catalog_cache import (
        catalog_cache_key, safe_cache_get, safe_cache_set,
    )

    policy = _xc_policy_for_user(user)
    cache_key = catalog_cache_key(request, user, "movie-categories")
    cached = safe_cache_get(cache_key)
    if cached is not None:
        return cached

    response = []

    # Before the first post-migration provider refresh, an upgraded catalog can
    # contain concrete movie relations but no category-inventory rows yet. In
    # that short compatibility window, keep the existing categories visible.
    # As soon as inventory exists, it becomes the hard enabled-source boundary.
    from apps.vod.policies import policy_category_map

    allowed_categories = policy_category_map(policy)
    categories = VODCategory.objects.filter(
        category_type='movie',
        m3umovierelation__m3u_account__is_active=True,
    )
    if allowed_categories:
        categories = categories.filter(
            m3u_relations__enabled=True,
            m3u_relations__m3u_account__is_active=True,
            pk__in={category_id for _account_id, category_id in allowed_categories},
        )
    categories = categories.distinct().order_by(Lower("name"))

    for category in categories:
        response.append({
            "category_id": str(category.id),
            "category_name": category.name,
            "parent_id": 0,
        })

    safe_cache_set(cache_key, response, timeout=3600)
    return response


def xc_get_vod_streams(request, user, category_id=None):
    """Get VOD streams (movies) for XtreamCodes API"""
    if not is_vod_movies_enabled(user=user):
        return []

    from apps.vod.models import M3UMovieRelation
    from apps.vod.utils import canonical_output_name

    from apps.vod.catalog_cache import (
        catalog_cache_key, safe_cache_get, safe_cache_set,
    )

    policy = _xc_policy_for_user(user)
    use_curated_metadata = _xc_uses_curated_metadata(policy)
    cache_key = catalog_cache_key(request, user, "movies", category_id)
    cached = safe_cache_get(cache_key)
    if cached is not None:
        return cached

    rel_filters = {"m3u_account__is_active": True}
    compact_policy = bool(policy and policy.export_mode == "compact")
    if category_id and not compact_policy:
        rel_filters["category_id"] = category_id
    # Non-admins with Hide Mature Content skip adult VODs.
    if user.user_level < 10 and (user.custom_properties or {}).get('hide_adult_content', False):
        rel_filters["movie__is_adult"] = False

    relations = _xc_fetch_priority_distinct_relations(
        manager=M3UMovieRelation.objects,
        rel_filters=rel_filters,
        distinct_field=('movie_id', 'category_id'),
        value_fields=(
            XC_MOVIE_VALUE_FIELDS + XC_CURATED_VALUE_FIELDS
            if use_curated_metadata
            else XC_MOVIE_VALUE_FIELDS
        ),
        order_by_name_field='movie__name',
        policy=policy,
        canonical_field="movie_id",
        prepared_filters={"category_id": category_id}
        if category_id and compact_policy
        else None,
    )
    if category_id and compact_policy:
        relations = [
            row
            for row in relations
            if str(row["category_id"] or "0") == str(category_id)
        ]

    _logo_url_parts = _xc_vodlogo_url_parts(request)
    # One reverse for the fallback-icon proxy rewrites below.
    _movie_image_parts = vod_image_url_parts(request, "movie")
    _prefer_tmdb_artwork = CoreSettings.get_tmdb_prefer_artwork()

    streams = []
    append = streams.append
    for num, row in enumerate(relations, 1):
        custom_props = row['movie__custom_properties'] or {}
        category_id = row['category_id']
        category_id_str = str(category_id) if category_id else "0"
        category_id_list = [category_id] if category_id else []
        curated = (
            _xc_curated_row_values(row, "movie")
            if use_curated_metadata
            else None
        )
        rating = curated["rating"] if curated else row['movie__rating']
        artwork = _xc_relation_artwork_from_row(
            row,
            custom_props,
            prefix='movie',
            prefer_tmdb=_prefer_tmdb_artwork,
        )

        append({
            "num": num,
            "name": row.get("profile_output_name") or (
                canonical_output_name(
                    row['movie__name'],
                    display_name=(
                        row['movie__display_name'] or row['movie__clean_title']
                    ),
                    year=row['movie__year'],
                )
                if compact_policy
                else row['rel_source_name'] or row['movie__name']
            ),
            "stream_type": "movie",
            "stream_id": row['id'],
            "stream_icon": _xc_cover_or_logo(
                request,
                'movie',
                row['movie__id'],
                artwork['movie_image'],
                logo_id=row['movie__logo_id'],
                logo_url_parts=_logo_url_parts,
                url_parts=_movie_image_parts,
            ),
            "rating": rating or "0",
            "rating_5based": round(float(rating or 0) / 2, 2) if rating else 0,
            "added": str(int(row['movie__created_at'].timestamp())),
            "is_adult": int(bool(row['movie__is_adult'])),
            "tmdb_id": (
                row['tmdb_override_id']
                or row['movie__tmdb_match_id']
                or row['movie__tmdb_id']
                or ""
            ),
            "imdb_id": row['movie__tmdb_imdb_id'] or row['movie__imdb_id'] or "",
            "trailer": custom_props.get('youtube_trailer') or "",
            "plot": curated["overview"] if curated else row['movie__description'] or "",
            "genre": curated["genre"] if curated else row['movie__genre'] or "",
            "year": curated["year"] if curated else row['movie__year'] or "",
            "director": custom_props.get('director', ''),
            "cast": custom_props.get('actors', ''),
            "release_date": (
                curated["release_date"]
                if curated and curated["release_date"]
                else custom_props.get('release_date', '')
            ),
            "category_id": category_id_str,
            "category_ids": category_id_list,
            "container_extension": row['container_extension'] or "mp4",
            "custom_sid": None,
            "direct_source": "",
            "edition": row.get("profile_edition_name", ""),
            "edition_suffix": row.get("profile_edition_suffix", ""),
        })

    safe_cache_set(cache_key, streams, timeout=3600)
    return streams


def xc_get_series_categories(user, request=None):
    """Get series categories for XtreamCodes API"""
    if not is_vod_series_enabled(user=user):
        return []

    from apps.vod.models import VODCategory, M3USeriesRelation

    from apps.vod.catalog_cache import (
        catalog_cache_key, safe_cache_get, safe_cache_set,
    )

    policy = _xc_policy_for_user(user)
    cache_key = catalog_cache_key(request, user, "series-categories")
    cached = safe_cache_get(cache_key)
    if cached is not None:
        return cached

    response = []

    from apps.vod.policies import policy_category_map

    allowed_categories = policy_category_map(policy)
    categories = VODCategory.objects.filter(
        category_type='series',
        m3useriesrelation__m3u_account__is_active=True,
    )
    if allowed_categories:
        categories = categories.filter(
            m3u_relations__enabled=True,
            m3u_relations__m3u_account__is_active=True,
            pk__in={category_id for _account_id, category_id in allowed_categories},
        )
    categories = categories.distinct().order_by(Lower("name"))

    for category in categories:
        response.append({
            "category_id": str(category.id),
            "category_name": category.name,
            "parent_id": 0,
        })

    safe_cache_set(cache_key, response, timeout=3600)
    return response


def xc_get_series(request, user, category_id=None):
    """Get series list for XtreamCodes API"""
    if not is_vod_series_enabled(user=user):
        return []

    from apps.vod.models import M3USeriesRelation
    from apps.vod.utils import canonical_output_name

    from apps.vod.catalog_cache import (
        catalog_cache_key, safe_cache_get, safe_cache_set,
    )

    policy = _xc_policy_for_user(user)
    use_curated_metadata = _xc_uses_curated_metadata(policy)
    cache_key = catalog_cache_key(request, user, "series", category_id)
    cached = safe_cache_get(cache_key)
    if cached is not None:
        return cached

    rel_filters = {"m3u_account__is_active": True}
    compact_policy = bool(policy and policy.export_mode == "compact")
    if category_id and not compact_policy:
        rel_filters["category_id"] = category_id

    relations = _xc_fetch_priority_distinct_relations(
        manager=M3USeriesRelation.objects,
        rel_filters=rel_filters,
        distinct_field=('series_id', 'category_id'),
        value_fields=(
            XC_SERIES_VALUE_FIELDS + XC_CURATED_VALUE_FIELDS
            if use_curated_metadata
            else XC_SERIES_VALUE_FIELDS
        ),
        order_by_name_field='series__name',
        policy=policy,
        canonical_field="series_id",
        prepared_filters={"category_id": category_id}
        if category_id and compact_policy
        else None,
    )
    if category_id and compact_policy:
        relations = [
            row
            for row in relations
            if str(row["category_id"] or "0") == str(category_id)
        ]

    _logo_url_parts = _xc_vodlogo_url_parts(request)
    # One reverse for all series backdrop rewrites.
    _series_image_parts = vod_image_url_parts(request, "series")

    series_list = []
    append = series_list.append
    _prefer_tmdb_artwork = CoreSettings.get_tmdb_prefer_artwork()
    for num, row in enumerate(relations, 1):
        custom_props = row['series__custom_properties'] or {}
        category_id = row['category_id']
        curated = (
            _xc_curated_row_values(row, "series")
            if use_curated_metadata
            else None
        )
        rating = curated["rating"] if curated else row['series__rating']
        year_value = curated["year"] if curated else row['series__year']
        year_str = str(year_value) if year_value else ""
        release_date = (
            curated["release_date"]
            if curated and curated["release_date"]
            else custom_props.get('release_date', year_str)
        )
        artwork = _xc_relation_artwork_from_row(
            row,
            custom_props,
            prefix='series',
            prefer_tmdb=_prefer_tmdb_artwork,
        )

        append({
            "num": num,
            "name": row.get("profile_output_name") or (
                canonical_output_name(
                    row['series__name'],
                    display_name=(
                        row['series__display_name'] or row['series__clean_title']
                    ),
                    year=row['series__year'],
                )
                if compact_policy
                else row['rel_source_name'] or row['series__name']
            ),
            "series_id": row['id'],
            "cover": _xc_cover_or_logo(
                request,
                'series',
                row['series__id'],
                artwork['movie_image'],
                logo_id=row['series__logo_id'],
                logo_url_parts=_logo_url_parts,
                url_parts=_series_image_parts,
            ),
            "plot": curated["overview"] if curated else row['series__description'] or "",
            "cast": custom_props.get('cast', ''),
            "director": custom_props.get('director', ''),
            "genre": curated["genre"] if curated else row['series__genre'] or "",
            "release_date": release_date,
            "releaseDate": release_date,
            "last_modified": str(int(row['updated_at'].timestamp())),
            "rating": str(rating or "0"),
            "rating_5based": str(round(float(rating or 0) / 2, 2)) if rating else "0",
            "backdrop_path": rewrite_backdrop_paths(
                request,
                'series',
                row['series__id'],
                artwork['backdrop_path'],
                url_parts=_series_image_parts,
            ),
            "youtube_trailer": custom_props.get('youtube_trailer', ''),
            "episode_run_time": (
                curated["runtime"]
                if curated and curated["runtime"]
                else custom_props.get('episode_run_time', '')
            ),
            "category_id": str(category_id) if category_id else "0",
            "category_ids": [category_id] if category_id else [],
            "tmdb_id": (
                row['tmdb_override_id']
                or row['series__tmdb_match_id']
                or row['series__tmdb_id']
                or ""
            ),
            "imdb_id": row['series__tmdb_imdb_id'] or row['series__imdb_id'] or "",
            "edition": row.get("profile_edition_name", ""),
            "edition_suffix": row.get("profile_edition_suffix", ""),
        })

    safe_cache_set(cache_key, series_list, timeout=3600)
    return series_list


def xc_get_series_info(request, user, series_id):
    """Get detailed series information including episodes"""
    if not is_vod_series_enabled(user=user):
        raise Http404()

    from apps.vod.models import M3USeriesRelation, M3UEpisodeRelation

    if not series_id:
        raise Http404()

    from apps.vod.catalog_cache import (
        catalog_cache_key, safe_cache_get, safe_cache_set,
    )
    from apps.vod.policies import relation_allowed

    policy = _xc_policy_for_user(user)
    use_curated_metadata = _xc_uses_curated_metadata(policy)
    cache_key = catalog_cache_key(request, user, "series-info", series_id)
    cached = safe_cache_get(cache_key)
    if cached is not None:
        return cached

    # Access flags are checked above; the profile policy further scopes sources.
    filters = {"id": series_id, "m3u_account__is_active": True}

    series_relations = M3USeriesRelation.objects.select_related(
        'series', 'series__logo', 'm3u_account', 'category'
    )
    series_relation = series_relations.filter(**filters).first()
    if not series_relation:
        # Accept older XC clients whose cached catalog contains the canonical
        # series id rather than the source-relation id.
        series_relation = series_relations.filter(
            series_id=series_id,
            m3u_account__is_active=True,
        ).order_by('-m3u_account__priority', 'id').first()
    if not series_relation:
        raise Http404()
    series = series_relation.series
    if policy and not relation_allowed(series_relation, policy):
        raise Http404()

    # Check if we need to refresh detailed info (similar to vod api_views pattern)
    try:
        should_refresh = (
            not series_relation.last_episode_refresh or
            series_relation.last_episode_refresh < django_timezone.now() - timedelta(hours=24)
        )

        # Check if detailed data has been fetched
        custom_props = series_relation.custom_properties or {}
        episodes_fetched = custom_props.get('episodes_fetched', False)
        detailed_fetched = custom_props.get('detailed_fetched', False)

        # Force refresh if episodes/details have never been fetched or time interval exceeded
        if not episodes_fetched or not detailed_fetched or should_refresh:
            from apps.vod.tasks import refresh_series_episodes
            account = series_relation.m3u_account
            if account and account.is_active:
                refresh_series_episodes(account, series, series_relation.external_series_id)
                # Refresh objects from database after task completion
                series.refresh_from_db()
                series_relation.refresh_from_db()

    except Exception as e:
        logger.error(f"Error refreshing series data for relation {series_relation.id}: {str(e)}")

    # Keep the selected source relation through the episode list. This is one
    # joined query and cannot merge another category's language or season set.
    episode_relations = M3UEpisodeRelation.objects.filter(
        series_relation=series_relation,
        m3u_account__is_active=True,
    ).select_related('episode').order_by(
        'episode__season_number', 'episode__episode_number', 'id'
    )

    # Group episodes by season
    seasons = {}
    # One reverse for all episode image rewrites in this response.
    _episode_image_parts = vod_image_url_parts(request, "episode")
    for episode_relation in episode_relations:
        episode = episode_relation.episode
        season_num = (
            episode.season_number if episode.season_number is not None else 1
        )
        if season_num not in seasons:
            seasons[season_num] = []

        relation_props = episode_relation.custom_properties or {}
        provider_episode = relation_props.get('info') or {}
        if not isinstance(provider_episode, dict):
            provider_episode = {}
        provider_info = provider_episode.get('info') or {}
        if not isinstance(provider_info, dict):
            provider_info = {}

        episode_title = (
            provider_episode.get('title')
            or provider_info.get('name')
            or episode.name
        )
        episode_description = (
            provider_info.get('plot')
            or provider_info.get('overview')
            or episode.description
            or ""
        )
        video = provider_info.get('video') or (
            episode.custom_properties.get('video', {})
            if episode.custom_properties else {}
        )
        audio = provider_info.get('audio') or (
            episode.custom_properties.get('audio', {})
            if episode.custom_properties else {}
        )
        bitrate = provider_info.get('bitrate') or (
            episode.custom_properties.get('bitrate', 0)
            if episode.custom_properties else 0
        )
        provider_duration = provider_info.get('duration_secs')
        raw_duration_secs = (
            provider_duration
            if provider_duration not in (None, '')
            else episode.duration_secs
        )
        try:
            duration_secs = int(float(raw_duration_secs or 0))
        except (TypeError, ValueError):
            duration_secs = int(episode.duration_secs or 0)
        provider_air_date = (
            provider_info.get('air_date')
            or provider_info.get('release_date')
            or provider_info.get('releasedate')
        )
        air_date = provider_air_date or episode.air_date
        rating = provider_info.get('rating')
        if rating in (None, ''):
            rating = episode.rating
        try:
            rating = float(rating or 0)
        except (TypeError, ValueError):
            try:
                rating = float(episode.rating or 0)
            except (TypeError, ValueError):
                rating = 0.0

        episode_custom = episode.custom_properties or {}
        crew = provider_info.get('crew') or episode_custom.get('crew', '')
        director = (
            provider_info.get('director')
            or provider_info.get('directed_by')
            or episode_custom.get('director', '')
        )
        imdb_id = provider_info.get('imdb_id') or episode.imdb_id or ""

        episode_artwork = prefer_relation_artwork(
            relation_props,
            episode.custom_properties,
        )

        seasons[season_num].append({
            "id": episode_relation.id,
            "season": season_num,
            "episode_num": provider_episode.get(
                'episode_num', episode.episode_number or 0
            ),
            "title": episode_title,
            "container_extension": episode_relation.container_extension or "mp4",
            "added": str(int(episode_relation.created_at.timestamp())),
            "custom_sid": None,
            "direct_source": "",
            "info": {
                "id": int(episode_relation.id),
                "name": episode_title,
                "overview": episode_description,
                "crew": str(crew),
                "directed_by": director,
                "imdb_id": imdb_id,
                "tmdb_id": provider_info.get('tmdb_id') or episode.tmdb_id or "",
                "air_date": f"{air_date}" if air_date else "",
                "backdrop_path": rewrite_backdrop_paths(
                    request,
                    'episode',
                    episode.id,
                    episode_artwork['backdrop_path'],
                    url_parts=_episode_image_parts,
                ),
                "movie_image": rewrite_single_image_url(
                    request,
                    'episode',
                    episode.id,
                    'movie_image',
                    episode_artwork['movie_image'],
                    url_parts=_episode_image_parts,
                ),
                "rating": rating,
                "release_date": f"{air_date}" if air_date else "",
                "duration_secs": (duration_secs or 0),
                "duration": format_duration_hms(duration_secs),
                "video": video,
                "audio": audio,
                "bitrate": bitrate,
            }
        })

    # Build response using potentially refreshed data
    series_data = {
        'name': series.name,
        'description': series.description or '',
        'year': series.year,
        'genre': series.genre or '',
        'rating': series.rating or '0',
        'cast': '',
        'director': '',
        'crew': '',
        'country': '',
        'age': '',
        'youtube_trailer': '',
        'episode_run_time': '',
        'backdrop_path': [],
    }

    # Add detailed info from custom_properties if available
    try:
        if series.custom_properties:
            custom_data = series.custom_properties
            series_data.update({
                'cast': custom_data.get('cast', ''),
                'director': custom_data.get('director', ''),
                'youtube_trailer': custom_data.get('youtube_trailer', ''),
                'episode_run_time': custom_data.get('episode_run_time', ''),
                'backdrop_path': custom_data.get('backdrop_path', []),
            })

        # Check relation custom_properties for detailed_info
        if series_relation.custom_properties and 'detailed_info' in series_relation.custom_properties:
            detailed_info = series_relation.custom_properties['detailed_info']

            # Override with detailed_info values where available
            for key in ['name', 'description', 'year', 'genre', 'rating']:
                if not use_curated_metadata and detailed_info.get(key):
                    series_data[key] = detailed_info[key]

            # Handle plot vs description
            if not use_curated_metadata and detailed_info.get('plot'):
                series_data['description'] = detailed_info['plot']
            elif not use_curated_metadata and detailed_info.get('description'):
                series_data['description'] = detailed_info['description']

            # Update additional fields from detailed info
            series_data.update({
                'cast': series_data['cast'] if use_curated_metadata else detailed_info.get('cast', series_data['cast']),
                'director': series_data['director'] if use_curated_metadata else detailed_info.get('director', series_data['director']),
                'youtube_trailer': series_data['youtube_trailer'] if use_curated_metadata else detailed_info.get('youtube_trailer', series_data['youtube_trailer']),
                'episode_run_time': series_data['episode_run_time'] if use_curated_metadata else detailed_info.get('episode_run_time', series_data['episode_run_time']),
                'backdrop_path': series_data['backdrop_path'] if use_curated_metadata else detailed_info.get('backdrop_path', series_data['backdrop_path']),
            })

    except Exception as e:
        logger.error(f"Error parsing series custom_properties: {str(e)}")

    if use_curated_metadata:
        curated = _xc_curated_object_values(series)
        series_data.update(
            name=curated["title"] or series_data["name"],
            description=curated["overview"],
            year=curated["year"],
            genre=curated["genre"],
            rating=curated["rating"],
            episode_run_time=curated["runtime"] or series_data["episode_run_time"],
            cast=curated["actors"],
            director=curated["director"],
            crew=curated["crew"],
            country=curated["country"],
            age=curated["age_rating"],
            youtube_trailer=curated["youtube_trailer"],
        )

    seasons_list = [
        {"season_number": int(season_num), "name": f"Season {season_num}"}
        for season_num in sorted(seasons.keys(), key=lambda x: int(x))
    ]

    series_artwork = prefer_relation_artwork(
        series_relation.custom_properties,
        series.custom_properties,
        tmdb_poster_url=series.tmdb_poster_url,
        tmdb_backdrop_url=series.tmdb_backdrop_url,
        prefer_tmdb=CoreSettings.get_tmdb_prefer_artwork(),
    )
    if is_proxyable_image_url(series_artwork['movie_image']):
        series_cover = rewrite_single_image_url(
            request,
            'series',
            series.id,
            'movie_image',
            series_artwork['movie_image'],
        )
    elif series.logo:
        series_cover = build_absolute_uri_with_port(
            request,
            reverse("api:vod:vodlogo-cache", args=[series.logo.id])
        )
    else:
        series_cover = None

    from apps.vod.utils import get_series_display_name, get_vod_source_name

    clean_series_name = get_series_display_name(series, series_relation)
    source_series_name = get_vod_source_name(
        series_relation,
        clean_series_name,
    )
    if policy:
        from apps.vod.profile_selection import prepared_relation_snapshot

        output_snapshot = prepared_relation_snapshot(
            policy,
            M3USeriesRelation,
            series_relation.id,
        )
        if output_snapshot and output_snapshot.get("output_name"):
            source_series_name = output_snapshot["output_name"]

    info = {
        'seasons': seasons_list,
        "info": {
            "name": source_series_name,
            "o_name": clean_series_name,
            "cover": series_cover,
            "plot": series_data['description'],
            "cast": series_data['cast'],
            "director": series_data['director'],
            "crew": series_data['crew'],
            "country": series_data['country'],
            "age": series_data['age'],
            "genre": series_data['genre'],
            "release_date": (
                curated["release_date"]
                if use_curated_metadata and curated["release_date"]
                else series.custom_properties.get('release_date', str(series.year) if series.year else "") if series.custom_properties else (str(series.year) if series.year else "")
            ),
            "releaseDate": (
                curated["release_date"]
                if use_curated_metadata and curated["release_date"]
                else series.custom_properties.get('release_date', str(series.year) if series.year else "") if series.custom_properties else (str(series.year) if series.year else "")
            ),
            "added": str(int(series_relation.created_at.timestamp())),
            "last_modified": str(int(series_relation.updated_at.timestamp())),
            "rating": str(series_data['rating']),
            "rating_5based": str(round(float(series_data['rating'] or 0) / 2, 2)) if series_data['rating'] else "0",
            "backdrop_path": rewrite_backdrop_paths(
                request,
                'series',
                series.id,
                series_artwork['backdrop_path'],
            ),
            "youtube_trailer": series_data['youtube_trailer'],
            "imdb": str(
                (series.tmdb_metadata or {}).get("imdb_id")
                or series.imdb_id
                or ""
            ),
            "tmdb": str(
                series_relation.tmdb_override_id
                or series.tmdb_match_id
                or series.tmdb_id
                or ""
            ),
            "episode_run_time": str(series_data['episode_run_time']),
            "category_id": str(series_relation.category.id) if series_relation.category else "0",
            "category_ids": [int(series_relation.category.id)] if series_relation.category else [],
        },
        "episodes": dict(seasons)
    }
    safe_cache_set(cache_key, info, timeout=3600)
    return info


def xc_get_vod_info(request, user, vod_id):
    """Get detailed VOD (movie) information"""
    if not is_vod_movies_enabled(user=user):
        raise Http404()

    from apps.vod.models import M3UMovieRelation
    from django.utils import timezone
    from datetime import timedelta

    if not vod_id:
        raise Http404()

    from apps.vod.catalog_cache import (
        catalog_cache_key, safe_cache_get, safe_cache_set,
    )
    from apps.vod.policies import relation_allowed

    policy = _xc_policy_for_user(user)
    use_curated_metadata = _xc_uses_curated_metadata(policy)
    cache_key = catalog_cache_key(request, user, "movie-info", vod_id)
    cached = safe_cache_get(cache_key)
    if cached is not None:
        return cached

    # Access flags are checked above; the profile policy further scopes sources.
    filters = {"id": vod_id, "m3u_account__is_active": True}
    if user.user_level < 10 and (user.custom_properties or {}).get('hide_adult_content', False):
        filters["movie__is_adult"] = False

    movie_relations = M3UMovieRelation.objects.select_related(
        'movie', 'movie__logo', 'm3u_account', 'category'
    )
    movie_relation = movie_relations.filter(**filters).first()
    if not movie_relation:
        fallback_filters = {
            'movie_id': vod_id,
            'm3u_account__is_active': True,
        }
        if 'movie__is_adult' in filters:
            fallback_filters['movie__is_adult'] = filters['movie__is_adult']
        movie_relation = movie_relations.filter(**fallback_filters).order_by(
            '-m3u_account__priority', 'id'
        ).first()
    if not movie_relation:
        raise Http404()
    movie = movie_relation.movie
    if policy and not relation_allowed(movie_relation, policy):
        raise Http404()

    # Initialize basic movie data first
    movie_data = {
        'name': movie.name,
        'description': movie.description or '',
        'year': movie.year,
        'genre': movie.genre or '',
        'rating': movie.rating or 0,
        'tmdb_id': movie.tmdb_id or '',
        'imdb_id': movie.imdb_id or '',
        'director': '',
        'actors': '',
        'crew': '',
        'country': '',
        'age': '',
        'release_date': '',
        'youtube_trailer': '',
        'backdrop_path': [],
        'cover_big': '',
        'bitrate': 0,
        'video': {},
        'audio': {},
    }

    # Duplicate the provider_info logic for detailed information
    try:
        # Check if we need to refresh detailed info (same logic as provider_info)
        detailed_fetched = (movie_relation.custom_properties or {}).get('detailed_fetched', False)
        should_refresh = (
            not detailed_fetched or
            not movie_relation.last_advanced_refresh or
            movie_relation.last_advanced_refresh < timezone.now() - timedelta(hours=24)
        )

        if should_refresh:
            # Trigger refresh of detailed info
            from apps.vod.tasks import refresh_movie_advanced_data
            refresh_movie_advanced_data(movie_relation.id)
            # Refresh objects from database after task completion
            movie.refresh_from_db()
            movie_relation.refresh_from_db()

        # Add detailed info from custom_properties if available
        if movie.custom_properties:
            custom_data = movie.custom_properties or {}

            # Extract detailed info
            #detailed_info = custom_data.get('detailed_info', {})
            detailed_info = movie_relation.custom_properties.get('detailed_info', {})
            # Update movie_data with detailed info
            movie_data.update({
                'director': custom_data.get('director') or ('' if use_curated_metadata else detailed_info.get('director', '')),
                'actors': custom_data.get('actors') or ('' if use_curated_metadata else detailed_info.get('actors', '')),
                'country': custom_data.get('country') or ('' if use_curated_metadata else detailed_info.get('country', '')),
                'release_date': custom_data.get('release_date') or ('' if use_curated_metadata else detailed_info.get('release_date') or detailed_info.get('releasedate', '')),
                'youtube_trailer': custom_data.get('youtube_trailer') or ('' if use_curated_metadata else detailed_info.get('youtube_trailer') or detailed_info.get('trailer', '')),
                'backdrop_path': custom_data.get('backdrop_path') or ([] if use_curated_metadata else detailed_info.get('backdrop_path', [])),
                'cover_big': '' if use_curated_metadata else detailed_info.get('cover_big', ''),
                'bitrate': detailed_info.get('bitrate', 0),
                'video': detailed_info.get('video', {}),
                'audio': detailed_info.get('audio', {}),
            })

            # Override with detailed_info values where available
            for key in ['name', 'description', 'year', 'genre', 'rating', 'tmdb_id', 'imdb_id']:
                if not use_curated_metadata and detailed_info.get(key):
                    movie_data[key] = detailed_info[key]

            # Handle plot vs description
            if not use_curated_metadata and detailed_info.get('plot'):
                movie_data['description'] = detailed_info['plot']
            elif not use_curated_metadata and detailed_info.get('description'):
                movie_data['description'] = detailed_info['description']

    except Exception as e:
        logger.error(f"Failed to process movie data: {e}")

    if use_curated_metadata:
        curated = _xc_curated_object_values(movie)
        movie_data.update(
            name=curated["title"] or movie_data["name"],
            description=curated["overview"],
            year=curated["year"],
            genre=curated["genre"],
            rating=curated["rating"],
            release_date=curated["release_date"] or movie_data["release_date"],
            director=curated["director"],
            actors=curated["actors"],
            crew=curated["crew"],
            country=curated["country"],
            age=curated["age_rating"],
            youtube_trailer=curated["youtube_trailer"],
        )

    # Real XC servers return the same URL for cover_big and movie_image, so both
    # are set from a single resolved cover: winning-provider still first, synced
    # VODLogo only when the relation/object has no proxyable image.
    movie_artwork = prefer_relation_artwork(
        movie_relation.custom_properties,
        movie.custom_properties,
        tmdb_poster_url=movie.tmdb_poster_url,
        tmdb_backdrop_url=movie.tmdb_backdrop_url,
        prefer_tmdb=CoreSettings.get_tmdb_prefer_artwork(),
    )
    if is_proxyable_image_url(movie_artwork['movie_image']):
        movie_cover = rewrite_single_image_url(
            request,
            'movie',
            movie.id,
            'movie_image',
            movie_artwork['movie_image'],
        )
    elif movie.logo:
        movie_cover = build_absolute_uri_with_port(
            request,
            reverse("api:vod:vodlogo-cache", args=[movie.logo.id])
        )
    else:
        movie_cover = None

    from apps.vod.utils import get_vod_source_name

    source_name = get_vod_source_name(movie_relation, movie_data['name'])
    if policy:
        from apps.vod.profile_selection import prepared_relation_snapshot

        output_snapshot = prepared_relation_snapshot(
            policy,
            M3UMovieRelation,
            movie_relation.id,
        )
        if output_snapshot and output_snapshot.get("output_name"):
            source_name = output_snapshot["output_name"]

    # Transform API response to XtreamCodes format
    info = {
        "info": {
            "name": source_name,
            "o_name": movie_data.get('name', movie.name),
            "cover_big": movie_cover,
            "movie_image": movie_cover,
            'description': movie_data.get('description', ''),
            'plot': movie_data.get('description', ''),
            'year': movie_data.get('year', ''),
            'release_date': movie_data.get('release_date', ''),
            'genre': movie_data.get('genre', ''),
            'director': movie_data.get('director', ''),
            'actors': movie_data.get('actors', ''),
            'cast': movie_data.get('actors', ''),
            'crew': movie_data.get('crew', ''),
            'country': movie_data.get('country', ''),
            'age': movie_data.get('age', ''),
            'rating': movie_data.get('rating', 0),
            'imdb_id': (
                (movie.tmdb_metadata or {}).get('imdb_id')
                or movie_data.get('imdb_id', '')
            ),
            "tmdb_id": (
                movie_relation.tmdb_override_id
                or movie.tmdb_match_id
                or movie_data.get('tmdb_id', '')
            ),
            'youtube_trailer': movie_data.get('youtube_trailer', ''),
            'backdrop_path': rewrite_backdrop_paths(
                request,
                'movie',
                movie.id,
                movie_artwork['backdrop_path'],
            ),
            'cover': movie_cover,
            'bitrate': movie_data.get('bitrate', 0),
            'video': movie_data.get('video', {}),
            'audio': movie_data.get('audio', {}),
        },
        "movie_data": {
            "stream_id": movie_relation.id,
            "name": source_name,
            "added": str(int(movie_relation.created_at.timestamp())),
            "category_id": str(movie_relation.category.id) if movie_relation.category else "0",
            "category_ids": [int(movie_relation.category.id)] if movie_relation.category else [],
            "container_extension": movie_relation.container_extension or "mp4",
            "custom_sid": None,
            "direct_source": "",
        }
    }

    safe_cache_set(cache_key, info, timeout=3600)
    return info


def format_duration_hms(seconds):
    """
    Format a duration in seconds as HH:MM:SS zero-padded string.
    """
    seconds = int(seconds or 0)
    return f"{seconds//3600:02}:{(seconds%3600)//60:02}:{seconds%60:02}"
