from django.http import HttpResponse, JsonResponse, Http404, HttpResponseForbidden, StreamingHttpResponse
import json
from django.urls import reverse
from apps.channels.models import Channel, ChannelProfile, ChannelGroup, Stream
from apps.channels.utils import format_channel_number
from django.db.models import Prefetch
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from apps.epg.models import ProgramData
from apps.accounts.models import User
from dispatcharr.utils import network_access_allowed
from django.utils import timezone as django_timezone
from django.shortcuts import get_object_or_404
from datetime import datetime, timedelta
import html
import time
from tzlocal import get_localzone
from urllib.parse import urlencode
import base64
import logging
from django.db.models.functions import Lower
import os
from apps.m3u.utils import calculate_tuner_count
from apps.proxy.utils import get_user_active_connections
import regex
from core.utils import log_system_event, build_absolute_uri_with_port
import hashlib
from apps.output.epg import generate_epg, generate_dummy_programs

logger = logging.getLogger(__name__)


def get_client_identifier(request):
    """Get client information including IP, user agent, and a unique hash identifier

    Returns:
        tuple: (client_id_hash, client_ip, user_agent)
    """
    # Get client IP (handle proxies)
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        client_ip = x_forwarded_for.split(',')[0].strip()
    else:
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')

    # Get user agent
    user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')

    # Create a hash for a shorter cache key
    client_str = f"{client_ip}:{user_agent}"
    client_id_hash = hashlib.md5(client_str.encode()).hexdigest()[:12]

    return client_id_hash, client_ip, user_agent

def m3u_endpoint(request, profile_name=None, user=None):
    logger.debug("m3u_endpoint called: method=%s, profile=%s", request.method, profile_name)
    if not network_access_allowed(request, "M3U_EPG"):
        # Log blocked M3U download
        from core.utils import log_system_event
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
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
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
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
    The stream URL now points to the new stream_view that uses StreamProfile.
    Supports both GET and POST methods for compatibility with IPTVSmarters.
    """
    # Check if this is a POST request and the body is not empty (which we don't want to allow)
    logger.debug("Generating M3U for profile: %s, user: %s, method: %s", profile_name, user.username if user else "Anonymous", request.method)

    if request.method == "POST" and request.body:
        if request.body.decode() != '{}':
            return HttpResponseForbidden("POST requests with body are not allowed.")

    # Check cache for recent identical request (helps with double-GET from browsers)
    from django.core.cache import cache
    cache_params = f"{profile_name or 'all'}:{user.username if user else 'anonymous'}:{request.GET.urlencode()}"
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

    # Check if direct stream URLs should be used instead of proxy
    use_direct_urls = request.GET.get('direct', 'false').lower() == 'true'

    # Output profile ID to append to proxy stream URLs (triggers pre-delivery transcode)
    output_profile_id = request.GET.get('output_profile')

    # Output format to append to proxy stream URLs (native ?output_format= or XC-style ?output=)
    output_format_param = request.GET.get('output_format') or request.GET.get('output')

    # Prefetch streams only when direct URLs are requested (avoids N+1 per channel)
    if use_direct_urls:
        channels = channels.prefetch_related(
            Prefetch('streams', queryset=Stream.objects.order_by('channelstream__order'))
        )

    # Get the source to use for tvg-id value
    # Options: 'channel_number' (default), 'tvg_id', 'gracenote'
    tvg_id_source = request.GET.get('tvg_id_source', 'channel_number').lower()

    # Build EPG URL with query parameters if needed
    # Check if this is an XC API request (has username/password in GET params and user is authenticated)
    xc_username = request.GET.get('username')
    xc_password = request.GET.get('password')
    is_xc_request = user is not None and xc_username and xc_password
    _base_url = build_absolute_uri_with_port(request, '')

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
        epg_base_url = build_absolute_uri_with_port(request, reverse('output:epg_endpoint', args=[profile_name]) if profile_name else reverse('output:epg_endpoint'))

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
    _stream_url_prefix = None if is_xc_request else f"{_base_url}/proxy/ts/stream/"
    _sample_logo_path = reverse("api:channels:logo-cache", args=[0])
    _logo_prefix_raw, _, _logo_suffix_raw = _sample_logo_path.partition("/0/")
    _logo_url_prefix = _base_url + _logo_prefix_raw + "/"
    _logo_url_suffix = "/" + _logo_suffix_raw

    # Start building M3U content
    channel_count = 0
    for channel in channels:
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
        if is_xc_request:
            stream_url = f"{_base_url}/live/{xc_username}/{xc_password}/{channel.id}{xc_qs_suffix}"
        elif use_direct_urls:
            # Try to get the first stream's direct URL
            all_streams = channel.streams.all()
            first_stream = all_streams[0] if all_streams else None
            if first_stream and first_stream.url:
                # Use the direct stream URL
                stream_url = first_stream.url
            else:
                # Fall back to proxy URL if no direct URL available
                stream_url = f"{_stream_url_prefix}{channel.uuid}"
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
        "server_info": {
            "url": hostname,
            "server_protocol": request.scheme,
            "port": port,
            "timezone": get_localzone().key,
            "timestamp_now": int(time.time()),
            "time_now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "process": True,
        },
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
            _xc_stream_live_streams(request, user, request.GET.get("category_id")),
            content_type="application/json",
        )
    elif action == "get_short_epg":
        return JsonResponse(xc_get_epg(request, user, short=True), safe=False)
    elif action == "get_simple_data_table":
        return JsonResponse(xc_get_epg(request, user, short=False), safe=False)
    elif action == "get_vod_categories":
        return JsonResponse(xc_get_vod_categories(user), safe=False)
    elif action == "get_vod_streams":
        return JsonResponse(xc_get_vod_streams(request, user, request.GET.get("category_id")), safe=False)
    elif action == "get_series_categories":
        return JsonResponse(xc_get_series_categories(user), safe=False)
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
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
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
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
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
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
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
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='epg_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Invalid XC credentials',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return generate_epg(request, None, user)


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
            pass
        elif effective_num == int(effective_num):
            num = int(effective_num)
            channel_num_map[channel.id] = num
            used_numbers.add(num)
        else:
            float_channels.append((channel.id, effective_num))

    for channel_id, effective_num in float_channels:
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


def _xc_channel_entry(channel, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix):
    channel_num_int = channel_num_map[channel.id]
    effective_logo = channel.effective_logo_obj
    effective_group = channel.effective_channel_group_obj
    group_id = effective_group.id if effective_group else _get_default_group_id()
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
        "custom_sid": None,
        "tv_archive": 0,
        "direct_source": "",
        "tv_archive_duration": 0,
    }


def xc_get_live_streams(request, user, category_id=None):
    channels, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix = \
        _xc_live_streams_setup(request, user, category_id)
    return [
        _xc_channel_entry(ch, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix)
        for ch in channels
    ]


def _xc_stream_live_streams(request, user, category_id=None):
    channels, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix = \
        _xc_live_streams_setup(request, user, category_id)
    yield "["
    sep = ""
    for channel in channels:
        yield sep + json.dumps(
            _xc_channel_entry(channel, channel_num_map, _get_default_group_id, _logo_url_prefix, _logo_url_suffix)
        )
        sep = ","
    yield "]"


def xc_get_epg(request, user, short=False):
    from apps.channels.managers import with_effective_values

    channel_id = request.GET.get('stream_id')
    if not channel_id:
        raise Http404()

    channel = None
    # Apply effective-value annotation + hidden-exclusion at every channel
    # resolution path so a single channel lookup honors the same visibility
    # rules as xc_get_live_streams.
    def _annotate(qs):
        return with_effective_values(qs, select_related_fks=True).exclude(hidden_from_output=True)

    if user.user_level < 10:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channels based on user_level
            filters = {
                "id": channel_id,
                "user_level__lte": user.user_level
            }
            # Hide adult content if user preference is set
            if (user.custom_properties or {}).get('hide_adult_content', False):
                filters["is_adult"] = False
            channel = _annotate(Channel.objects.filter(**filters).select_related('epg_data__epg_source')).first()
        else:
            # User has specific limited profiles assigned
            filters = {
                "id": channel_id,
                "channelprofilemembership__enabled": True,
                "user_level__lte": user.user_level,
                "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
            }
            # Hide adult content if user preference is set
            if (user.custom_properties or {}).get('hide_adult_content', False):
                filters["is_adult"] = False
            channel = _annotate(Channel.objects.filter(**filters).select_related('epg_data__epg_source').distinct()).first()

        if not channel:
            raise Http404()
    else:
        channel = _annotate(Channel.objects.filter(id=channel_id).select_related('epg_data__epg_source')).first()
        if not channel:
            raise Http404()

    if not channel:
        raise Http404()

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

    limit = int(request.GET.get('limit', 4))
    user_custom = user.custom_properties or {}
    try:
        num_days = int(request.GET.get('days', user_custom.get('epg_days', 0)))
        num_days = max(0, min(num_days, 365))
    except (ValueError, TypeError):
        num_days = 0
    try:
        prev_days = int(request.GET.get('prev_days', user_custom.get('epg_prev_days', 0)))
        prev_days = max(0, min(prev_days, 30))
    except (ValueError, TypeError):
        prev_days = 0
    now = django_timezone.now()
    lookback_cutoff = now - timedelta(days=prev_days)
    forward_cutoff = now + timedelta(days=num_days) if num_days > 0 else None
    effective_epg_data = channel.effective_epg_data_obj
    effective_name = channel.effective_name

    if effective_epg_data:
        # Check if this is a dummy EPG that generates on-demand
        if effective_epg_data.epg_source and effective_epg_data.epg_source.source_type == 'dummy':
            if not effective_epg_data.programs.exists():
                # Generate on-demand using custom patterns
                programs = generate_dummy_programs(
                    channel_id=channel_id,
                    channel_name=effective_name,
                    epg_source=effective_epg_data.epg_source
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
        programs = generate_dummy_programs(channel_id=channel_id, channel_name=effective_name, epg_source=None)

    output = {"epg_listings": []}

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
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.strftime("%Y-%m-%d %H:%M:%S"),
            "description": base64.b64encode((description or "").encode()).decode(),
            "channel_id": str(channel_num_int),
            "start_timestamp": str(int(start.timestamp())),
            "stop_timestamp": str(int(end.timestamp())),
            "stream_id": f"{channel_id}",
        }

        if short == False:
            program_output["now_playing"] = 1 if start <= django_timezone.now() <= end else 0
            program_output["has_archive"] = 0

        output['epg_listings'].append(program_output)

    return output


XC_MOVIE_VALUE_FIELDS = (
    'id', 'movie_id', 'category_id', 'container_extension',
    'movie__id', 'movie__name', 'movie__rating', 'movie__created_at',
    'movie__tmdb_id', 'movie__imdb_id', 'movie__description', 'movie__genre',
    'movie__year', 'movie__custom_properties', 'movie__logo_id',
)

XC_SERIES_VALUE_FIELDS = (
    'id', 'series_id', 'category_id', 'updated_at',
    'series__id', 'series__name', 'series__description', 'series__genre',
    'series__year', 'series__rating', 'series__custom_properties', 'series__logo_id',
    'series__tmdb_id', 'series__imdb_id',
)


def _xc_fetch_priority_distinct_relations(
    *,
    manager,
    rel_filters,
    distinct_field,
    value_fields,
    order_by_name_field,
):
    """
    Return one row dict per distinct content ID (highest account priority wins).

    On PostgreSQL, dedupe on narrow relation rows first, then fetch display
    columns via values() (no ORM model instantiation). That avoids sorting
    wide joined rows during DISTINCT ON and reduces parallel worker /dev/shm
    pressure in Docker.
    """
    from django.db import connection, transaction

    narrow_qs = manager.filter(**rel_filters)

    def _fetch_by_ids(ids):
        return list(
            manager.filter(pk__in=ids)
            .values(*value_fields)
            .order_by(Lower(order_by_name_field))
        )

    if connection.vendor == 'postgresql':
        winning_ids_qs = (
            narrow_qs
            .order_by(distinct_field, '-m3u_account__priority', 'id')
            .distinct(distinct_field)
            .values('pk')
        )
        with transaction.atomic():
            # Optional: disable parallel gather for this DISTINCT ON query if Docker
            # /dev/shm pressure causes worker OOM on very large VOD libraries.
            #with connection.cursor() as cursor:
            #    cursor.execute("SET LOCAL max_parallel_workers_per_gather = 0")
            winning_ids = list(winning_ids_qs.values_list('pk', flat=True))
            if not winning_ids:
                return []
            return _fetch_by_ids(winning_ids)

    seen = {}
    for row in narrow_qs.values(*value_fields).order_by('-m3u_account__priority', 'id'):
        key = row[distinct_field]
        if key not in seen:
            seen[key] = row
    rows = list(seen.values())
    rows.sort(key=lambda r: (r[order_by_name_field] or '').lower())
    return rows


def xc_get_vod_categories(user):
    """Get VOD categories for XtreamCodes API"""
    from apps.vod.models import VODCategory, M3UMovieRelation

    response = []

    # All authenticated users get access to VOD from all active M3U accounts
    categories = VODCategory.objects.filter(
        category_type='movie',
        m3umovierelation__m3u_account__is_active=True
    ).distinct().order_by(Lower("name"))

    for category in categories:
        response.append({
            "category_id": str(category.id),
            "category_name": category.name,
            "parent_id": 0,
        })

    return response


def xc_get_vod_streams(request, user, category_id=None):
    """Get VOD streams (movies) for XtreamCodes API"""
    from apps.vod.models import M3UMovieRelation

    rel_filters = {"m3u_account__is_active": True}
    if category_id:
        rel_filters["category_id"] = category_id

    relations = _xc_fetch_priority_distinct_relations(
        manager=M3UMovieRelation.objects,
        rel_filters=rel_filters,
        distinct_field='movie_id',
        value_fields=XC_MOVIE_VALUE_FIELDS,
        order_by_name_field='movie__name',
    )

    # Precompute logo URL prefix/suffix once (mirrors _xc_live_streams_setup)
    # so each row only needs a string concat instead of reverse() + URI build.
    _base_url = build_absolute_uri_with_port(request, "")
    _sample_logo_path = reverse("api:vod:vodlogo-cache", args=[0])
    _logo_prefix_raw, _, _logo_suffix_raw = _sample_logo_path.partition("/0/")
    _logo_url_prefix = _base_url + _logo_prefix_raw + "/"
    _logo_url_suffix = "/" + _logo_suffix_raw

    streams = []
    append = streams.append
    for num, row in enumerate(relations, 1):
        custom_props = row['movie__custom_properties'] or {}
        category_id = row['category_id']
        category_id_str = str(category_id) if category_id else "0"
        category_id_list = [category_id] if category_id else []
        rating = row['movie__rating']
        logo_id = row['movie__logo_id']

        append({
            "num": num,
            "name": row['movie__name'],
            "stream_type": "movie",
            "stream_id": row['movie__id'],
            "stream_icon": (
                f"{_logo_url_prefix}{logo_id}{_logo_url_suffix}" if logo_id else None
            ),
            "rating": rating or "0",
            "rating_5based": round(float(rating or 0) / 2, 2) if rating else 0,
            "added": str(int(row['movie__created_at'].timestamp())),
            "is_adult": 0,
            "tmdb_id": row['movie__tmdb_id'] or "",
            "imdb_id": row['movie__imdb_id'] or "",
            "trailer": custom_props.get('youtube_trailer') or "",
            "plot": row['movie__description'] or "",
            "genre": row['movie__genre'] or "",
            "year": row['movie__year'] or "",
            "director": custom_props.get('director', ''),
            "cast": custom_props.get('actors', ''),
            "release_date": custom_props.get('release_date', ''),
            "category_id": category_id_str,
            "category_ids": category_id_list,
            "container_extension": row['container_extension'] or "mp4",
            "custom_sid": None,
            "direct_source": "",
        })

    return streams


def xc_get_series_categories(user):
    """Get series categories for XtreamCodes API"""
    from apps.vod.models import VODCategory, M3USeriesRelation

    response = []

    # All authenticated users get access to series from all active M3U accounts
    categories = VODCategory.objects.filter(
        category_type='series',
        m3useriesrelation__m3u_account__is_active=True
    ).distinct().order_by(Lower("name"))

    for category in categories:
        response.append({
            "category_id": str(category.id),
            "category_name": category.name,
            "parent_id": 0,
        })

    return response


def xc_get_series(request, user, category_id=None):
    """Get series list for XtreamCodes API"""
    from apps.vod.models import M3USeriesRelation

    rel_filters = {"m3u_account__is_active": True}
    if category_id:
        rel_filters["category_id"] = category_id

    relations = _xc_fetch_priority_distinct_relations(
        manager=M3USeriesRelation.objects,
        rel_filters=rel_filters,
        distinct_field='series_id',
        value_fields=XC_SERIES_VALUE_FIELDS,
        order_by_name_field='series__name',
    )

    _base_url = build_absolute_uri_with_port(request, "")
    _sample_logo_path = reverse("api:vod:vodlogo-cache", args=[0])
    _logo_prefix_raw, _, _logo_suffix_raw = _sample_logo_path.partition("/0/")
    _logo_url_prefix = _base_url + _logo_prefix_raw + "/"
    _logo_url_suffix = "/" + _logo_suffix_raw

    series_list = []
    append = series_list.append
    for num, row in enumerate(relations, 1):
        custom_props = row['series__custom_properties'] or {}
        category_id = row['category_id']
        rating = row['series__rating']
        logo_id = row['series__logo_id']
        year_str = str(row['series__year']) if row['series__year'] else ""
        release_date = custom_props.get('release_date', year_str)

        append({
            "num": num,
            "name": row['series__name'],
            "series_id": row['id'],
            "cover": (
                f"{_logo_url_prefix}{logo_id}{_logo_url_suffix}" if logo_id else None
            ),
            "plot": row['series__description'] or "",
            "cast": custom_props.get('cast', ''),
            "director": custom_props.get('director', ''),
            "genre": row['series__genre'] or "",
            "release_date": release_date,
            "releaseDate": release_date,
            "last_modified": str(int(row['updated_at'].timestamp())),
            "rating": str(rating or "0"),
            "rating_5based": str(round(float(rating or 0) / 2, 2)) if rating else "0",
            "backdrop_path": custom_props.get('backdrop_path', []),
            "youtube_trailer": custom_props.get('youtube_trailer', ''),
            "episode_run_time": custom_props.get('episode_run_time', ''),
            "category_id": str(category_id) if category_id else "0",
            "category_ids": [category_id] if category_id else [],
            "tmdb_id": row['series__tmdb_id'] or "",
            "imdb_id": row['series__imdb_id'] or "",
        })

    return series_list


def xc_get_series_info(request, user, series_id):
    """Get detailed series information including episodes"""
    from apps.vod.models import M3USeriesRelation, M3UEpisodeRelation

    if not series_id:
        raise Http404()

    # All authenticated users get access to series from all active M3U accounts
    filters = {"id": series_id, "m3u_account__is_active": True}

    try:
        series_relation = M3USeriesRelation.objects.select_related('series', 'series__logo').get(**filters)
        series = series_relation.series
    except M3USeriesRelation.DoesNotExist:
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

    # Get unique episodes for this series that have relations from any active M3U account
    # We query episodes directly to avoid duplicates when multiple relations exist
    # (e.g., same episode in different languages/qualities)
    from apps.vod.models import Episode
    episodes = Episode.objects.filter(
        series=series,
        m3u_relations__m3u_account__is_active=True
    ).distinct().order_by('season_number', 'episode_number')

    # Group episodes by season
    seasons = {}
    for episode in episodes:
        season_num = episode.season_number or 1
        if season_num not in seasons:
            seasons[season_num] = []

        # Get the highest priority relation for this episode (for container_extension, video/audio/bitrate)
        from apps.vod.models import M3UEpisodeRelation
        best_relation = M3UEpisodeRelation.objects.filter(
            episode=episode,
            m3u_account__is_active=True
        ).select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

        video = audio = bitrate = None
        container_extension = "mp4"
        added_timestamp = str(int(episode.created_at.timestamp()))

        if best_relation:
            container_extension = best_relation.container_extension or "mp4"
            added_timestamp = str(int(best_relation.created_at.timestamp()))
            if best_relation.custom_properties:
                info = best_relation.custom_properties.get('info')
                if info and isinstance(info, dict):
                    info_info = info.get('info')
                    if info_info and isinstance(info_info, dict):
                        video = info_info.get('video', {})
                        audio = info_info.get('audio', {})
                        bitrate = info_info.get('bitrate', 0)

        if video is None:
            video = episode.custom_properties.get('video', {}) if episode.custom_properties else {}
        if audio is None:
            audio = episode.custom_properties.get('audio', {}) if episode.custom_properties else {}
        if bitrate is None:
            bitrate = episode.custom_properties.get('bitrate', 0) if episode.custom_properties else 0

        seasons[season_num].append({
            "id": episode.id,
            "season": season_num,
            "episode_num": episode.episode_number or 0,
            "title": episode.name,
            "container_extension": container_extension,
            "added": added_timestamp,
            "custom_sid": None,
            "direct_source": "",
            "info": {
                "id": int(episode.id),
                "name": episode.name,
                "overview": episode.description or "",
                "crew": str(episode.custom_properties.get('crew', "") if episode.custom_properties else ""),
                "directed_by": episode.custom_properties.get('director', '') if episode.custom_properties else "",
                "imdb_id": episode.imdb_id or "",
                "air_date": f"{episode.air_date}" if episode.air_date else "",
                "backdrop_path": episode.custom_properties.get('backdrop_path', []) if episode.custom_properties else [],
                "movie_image": episode.custom_properties.get('movie_image', '') if episode.custom_properties else "",
                "rating": float(episode.rating or 0),
                "release_date": f"{episode.air_date}" if episode.air_date else "",
                "duration_secs": (episode.duration_secs or 0),
                "duration": format_duration_hms(episode.duration_secs),
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
                if detailed_info.get(key):
                    series_data[key] = detailed_info[key]

            # Handle plot vs description
            if detailed_info.get('plot'):
                series_data['description'] = detailed_info['plot']
            elif detailed_info.get('description'):
                series_data['description'] = detailed_info['description']

            # Update additional fields from detailed info
            series_data.update({
                'cast': detailed_info.get('cast', series_data['cast']),
                'director': detailed_info.get('director', series_data['director']),
                'youtube_trailer': detailed_info.get('youtube_trailer', series_data['youtube_trailer']),
                'episode_run_time': detailed_info.get('episode_run_time', series_data['episode_run_time']),
                'backdrop_path': detailed_info.get('backdrop_path', series_data['backdrop_path']),
            })

    except Exception as e:
        logger.error(f"Error parsing series custom_properties: {str(e)}")

    seasons_list = [
        {"season_number": int(season_num), "name": f"Season {season_num}"}
        for season_num in sorted(seasons.keys(), key=lambda x: int(x))
    ]

    info = {
        'seasons': seasons_list,
        "info": {
            "name": series_data['name'],
            "cover": (
                None if not series.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:vod:vodlogo-cache", args=[series.logo.id])
                )
            ),
            "plot": series_data['description'],
            "cast": series_data['cast'],
            "director": series_data['director'],
            "genre": series_data['genre'],
            "release_date": series.custom_properties.get('release_date', str(series.year) if series.year else "") if series.custom_properties else (str(series.year) if series.year else ""),
            "releaseDate": series.custom_properties.get('release_date', str(series.year) if series.year else "") if series.custom_properties else (str(series.year) if series.year else ""),
            "added": str(int(series_relation.created_at.timestamp())),
            "last_modified": str(int(series_relation.updated_at.timestamp())),
            "rating": str(series_data['rating']),
            "rating_5based": str(round(float(series_data['rating'] or 0) / 2, 2)) if series_data['rating'] else "0",
            "backdrop_path": series_data['backdrop_path'],
            "youtube_trailer": series_data['youtube_trailer'],
            "imdb": str(series.imdb_id) if series.imdb_id else "",
            "tmdb": str(series.tmdb_id) if series.tmdb_id else "",
            "episode_run_time": str(series_data['episode_run_time']),
            "category_id": str(series_relation.category.id) if series_relation.category else "0",
            "category_ids": [int(series_relation.category.id)] if series_relation.category else [],
        },
        "episodes": dict(seasons)
    }
    return info


def xc_get_vod_info(request, user, vod_id):
    """Get detailed VOD (movie) information"""
    from apps.vod.models import M3UMovieRelation
    from django.utils import timezone
    from datetime import timedelta

    if not vod_id:
        raise Http404()

    # All authenticated users get access to VOD from all active M3U accounts
    filters = {"movie_id": vod_id, "m3u_account__is_active": True}

    try:
        # Order by account priority to get the best relation when multiple exist
        movie_relation = M3UMovieRelation.objects.select_related('movie', 'movie__logo').filter(**filters).order_by('-m3u_account__priority', 'id').first()
        if not movie_relation:
            raise Http404()
        movie = movie_relation.movie
    except (M3UMovieRelation.DoesNotExist, M3UMovieRelation.MultipleObjectsReturned):
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
        'country': '',
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
        should_refresh = (
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
                'director': custom_data.get('director') or detailed_info.get('director', ''),
                'actors': custom_data.get('actors') or detailed_info.get('actors', ''),
                'country': custom_data.get('country') or detailed_info.get('country', ''),
                'release_date': custom_data.get('release_date') or detailed_info.get('release_date') or detailed_info.get('releasedate', ''),
                'youtube_trailer': custom_data.get('youtube_trailer') or detailed_info.get('youtube_trailer') or detailed_info.get('trailer', ''),
                'backdrop_path': custom_data.get('backdrop_path') or detailed_info.get('backdrop_path', []),
                'cover_big': detailed_info.get('cover_big', ''),
                'bitrate': detailed_info.get('bitrate', 0),
                'video': detailed_info.get('video', {}),
                'audio': detailed_info.get('audio', {}),
            })

            # Override with detailed_info values where available
            for key in ['name', 'description', 'year', 'genre', 'rating', 'tmdb_id', 'imdb_id']:
                if detailed_info.get(key):
                    movie_data[key] = detailed_info[key]

            # Handle plot vs description
            if detailed_info.get('plot'):
                movie_data['description'] = detailed_info['plot']
            elif detailed_info.get('description'):
                movie_data['description'] = detailed_info['description']

    except Exception as e:
        logger.error(f"Failed to process movie data: {e}")

    # Transform API response to XtreamCodes format
    info = {
        "info": {
            "name": movie_data.get('name', movie.name),
            "o_name": movie_data.get('name', movie.name),
            "cover_big": (
                None if not movie.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:vod:vodlogo-cache", args=[movie.logo.id])
                )
            ),
            "movie_image": (
                None if not movie.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:vod:vodlogo-cache", args=[movie.logo.id])
                )
            ),
            'description': movie_data.get('description', ''),
            'plot': movie_data.get('description', ''),
            'year': movie_data.get('year', ''),
            'release_date': movie_data.get('release_date', ''),
            'genre': movie_data.get('genre', ''),
            'director': movie_data.get('director', ''),
            'actors': movie_data.get('actors', ''),
            'cast': movie_data.get('actors', ''),
            'country': movie_data.get('country', ''),
            'rating': movie_data.get('rating', 0),
            'imdb_id': movie_data.get('imdb_id', ''),
            "tmdb_id": movie_data.get('tmdb_id', ''),
            'youtube_trailer': movie_data.get('youtube_trailer', ''),
            'backdrop_path': movie_data.get('backdrop_path', []),
            'cover': movie_data.get('cover_big', ''),
            'bitrate': movie_data.get('bitrate', 0),
            'video': movie_data.get('video', {}),
            'audio': movie_data.get('audio', {}),
        },
        "movie_data": {
            "stream_id": movie.id,
            "name": movie.name,
            "added": str(int(movie_relation.created_at.timestamp())),
            "category_id": str(movie_relation.category.id) if movie_relation.category else "0",
            "category_ids": [int(movie_relation.category.id)] if movie_relation.category else [],
            "container_extension": movie_relation.container_extension or "mp4",
            "custom_sid": None,
            "direct_source": "",
        }
    }

    return info


def xc_movie_stream(request, username, password, stream_id, extension):
    """Handle XtreamCodes movie streaming requests"""
    from apps.vod.models import M3UMovieRelation

    user = get_object_or_404(User, username=username)

    custom_properties = user.custom_properties or {}

    if "xc_password" not in custom_properties:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    if custom_properties["xc_password"] != password:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    # All authenticated users get access to VOD from all active M3U accounts
    filters = {"movie_id": stream_id, "m3u_account__is_active": True}

    try:
        # Order by account priority to get the best relation when multiple exist
        movie_relation = M3UMovieRelation.objects.select_related('movie').filter(**filters).order_by('-m3u_account__priority', 'id').first()
        if not movie_relation:
            return JsonResponse({"error": "Movie not found"}, status=404)
    except (M3UMovieRelation.DoesNotExist, M3UMovieRelation.MultipleObjectsReturned):
        return JsonResponse({"error": "Movie not found"}, status=404)

    # Redirect to the VOD proxy endpoint
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    vod_url = reverse('proxy:vod_proxy:vod_stream', kwargs={
        'content_type': 'movie',
        'content_id': movie_relation.movie.uuid
    })

    return HttpResponseRedirect(vod_url)


def xc_series_stream(request, username, password, stream_id, extension):
    """Handle XtreamCodes series/episode streaming requests"""
    from apps.vod.models import M3UEpisodeRelation

    user = get_object_or_404(User, username=username)

    custom_properties = user.custom_properties or {}

    if "xc_password" not in custom_properties:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    if custom_properties["xc_password"] != password:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    # All authenticated users get access to series/episodes from all active M3U accounts
    filters = {"episode_id": stream_id, "m3u_account__is_active": True}

    try:
        episode_relation = M3UEpisodeRelation.objects.select_related('episode').filter(**filters).order_by('-m3u_account__priority', 'id').first()
    except M3UEpisodeRelation.DoesNotExist:
        return JsonResponse({"error": "Episode not found"}, status=404)

    # Redirect to the VOD proxy endpoint
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    vod_url = reverse('proxy:vod_proxy:vod_stream', kwargs={
        'content_type': 'episode',
        'content_id': episode_relation.episode.uuid
    })

    return HttpResponseRedirect(vod_url)


def format_duration_hms(seconds):
    """
    Format a duration in seconds as HH:MM:SS zero-padded string.
    """
    seconds = int(seconds or 0)
    return f"{seconds//3600:02}:{(seconds%3600)//60:02}:{seconds%60:02}"
