# dispatcharr/utils.py
import ipaddress
import logging
import os

from django.core.exceptions import ValidationError
from django.http import JsonResponse

from core.models import CoreSettings

logger = logging.getLogger(__name__)

# Private / loopback ranges used as the default for M3U/EPG ACLs and
# first-time superuser setup (when DISPATCHARR_SETUP_ALLOWED_IP is unset).
LOCAL_NETWORK_CIDRS = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

SETUP_ALLOWED_IP_ENV = "DISPATCHARR_SETUP_ALLOWED_IP"
TRUSTED_PROXIES_ENV = "DISPATCHARR_TRUSTED_PROXIES"

# Parsed trusted-proxy networks. Rebuilt when the config key changes.
# Config key is "__default_local__", "__none__", or the raw env string.
_trusted_proxies_key = None
_trusted_proxies_networks = ()

# Sentinel values for DISPATCHARR_TRUSTED_PROXIES when explicitly disabling
# header trust (env unset still means default local CIDRs).
_TRUSTED_PROXIES_NONE = frozenset({"", "none", "off", "false", "0"})


def json_error_response(message, status=400):
    """Return a standardized error JSON response."""
    return JsonResponse({"success": False, "error": message}, status=status)


def json_success_response(data=None, status=200):
    """Return a standardized success JSON response."""
    response = {"success": True}
    if data is not None:
        response.update(data)
    return JsonResponse(response, status=status)


def validate_logo_file(file):
    """Validate uploaded logo file size and MIME type."""
    valid_mime_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"]
    if file.content_type not in valid_mime_types:
        raise ValidationError("Unsupported file type. Allowed types: JPEG, PNG, GIF, WebP, SVG.")
    if file.size > 5 * 1024 * 1024:  # 5MB
        raise ValidationError("File too large. Max 5MB.")


def _normalize_ip(value):
    """Parse an IP string, returning the IPv4 form for IPv4-mapped IPv6."""
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    return ip.ipv4_mapped if getattr(ip, "ipv4_mapped", None) else ip


def _trusted_proxy_networks():
    """Return networks whose peers may set X-Real-IP / X-Forwarded-For.

    When DISPATCHARR_TRUSTED_PROXIES is unset, defaults to LOCAL_NETWORK_CIDRS
    so Docker/Traefik-style reverse proxies on private networks work without
    configuration. Set the env to a comma-separated IP/CIDR list to narrow
    trust, or to none / off / false / empty to trust no proxy headers.
    """
    global _trusted_proxies_key, _trusted_proxies_networks

    if TRUSTED_PROXIES_ENV not in os.environ:
        key = "__default_local__"
        source = LOCAL_NETWORK_CIDRS
    else:
        raw = os.environ.get(TRUSTED_PROXIES_ENV, "").strip()
        if raw.lower() in _TRUSTED_PROXIES_NONE:
            key = "__none__"
            source = []
        else:
            key = raw
            source = [p.strip() for p in raw.split(",") if p.strip()]

    if key == _trusted_proxies_key:
        return _trusted_proxies_networks

    networks = []
    for part in source:
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("Invalid %s entry %r; ignoring", TRUSTED_PROXIES_ENV, part)
    _trusted_proxies_key = key
    _trusted_proxies_networks = tuple(networks)
    return _trusted_proxies_networks


def _ip_in_trusted(ip):
    if ip is None:
        return False
    return any(ip in network for network in _trusted_proxy_networks())


def get_client_ip(request):
    """Return the client IP for ACLs and logging.

    Proxy headers (X-Real-IP, X-Forwarded-For) are honored only when
    REMOTE_ADDR is a trusted proxy. By default that means private/loopback
    peers (LOCAL_NETWORK_CIDRS). Override with DISPATCHARR_TRUSTED_PROXIES.
    Public peers never get header trust unless explicitly listed.
    IPv4-mapped IPv6 addresses are returned in IPv4 form.
    """
    peer_str = request.META.get("REMOTE_ADDR") or ""
    peer = _normalize_ip(peer_str)
    if peer is None:
        return peer_str or None
    if not _ip_in_trusted(peer):
        return str(peer)

    real_ip = _normalize_ip(request.META.get("HTTP_X_REAL_IP"))
    if real_ip is not None:
        return str(real_ip)

    xff = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
        hop_ip = _normalize_ip(hop)
        if hop_ip is None:
            continue
        if not _ip_in_trusted(hop_ip):
            return str(hop_ip)

    return str(peer)


def setup_ip_allowed(request):
    """Whether this client may POST to initialize-superuser.

    Default: private / loopback IPv4 and IPv6 only.
    If DISPATCHARR_SETUP_ALLOWED_IP is set, only that single IP is allowed
    (for remote / VPS first-time web setup).

    Returns:
        tuple[bool, str]: (allowed, client_ip_string)
    """
    client_ip_str = get_client_ip(request) or ""
    compare_ip = _normalize_ip(client_ip_str)
    if compare_ip is None:
        return False, client_ip_str

    override = os.environ.get(SETUP_ALLOWED_IP_ENV, "").strip()
    if override:
        override_ip = _normalize_ip(override)
        if override_ip is None:
            logger.warning(
                "Invalid %s=%r; denying initialize-superuser POST",
                SETUP_ALLOWED_IP_ENV,
                override,
            )
            return False, client_ip_str
        return compare_ip == override_ip, client_ip_str

    for cidr in LOCAL_NETWORK_CIDRS:
        if compare_ip in ipaddress.ip_network(cidr):
            return True, client_ip_str
    return False, client_ip_str


def network_access_allowed(request, settings_key, user=None):
    network_access = CoreSettings.get_network_access_settings()
    # Set defaults based on endpoint type
    if settings_key == "M3U_EPG":
        # M3U/EPG endpoints: local IPv4 and IPv6 only by default
        default_cidrs = LOCAL_NETWORK_CIDRS
    else:
        # Other endpoints: allow all by default
        default_cidrs = ["0.0.0.0/0", "::/0"]

    cidrs = (
        network_access[settings_key].split(",")
        if settings_key in network_access
        else default_cidrs
    )

    client_ip = _normalize_ip(get_client_ip(request))
    if client_ip is None:
        return False

    network_allowed = False
    for cidr in cidrs:
        network = ipaddress.ip_network(cidr)
        if client_ip in network:
            network_allowed = True
            break

    if not network_allowed:
        return False

    if user is not None:
        user_networks = (getattr(user, 'custom_properties', None) or {}).get('allowed_networks', {})
        raw = user_networks.get(settings_key, '')
        if raw:
            for cidr in (c.strip() for c in raw.split(',') if c.strip()):
                try:
                    if client_ip in ipaddress.ip_network(cidr, strict=False):
                        return True
                except ValueError:
                    continue
            return False

    return True
