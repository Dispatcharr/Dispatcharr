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


def get_client_ip(request):
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def setup_ip_allowed(request):
    """Whether this client may POST to initialize-superuser.

    Default: private / loopback IPv4 and IPv6 only.
    If DISPATCHARR_SETUP_ALLOWED_IP is set, only that single IP is allowed
    (for remote / VPS first-time web setup).

    Returns:
        tuple[bool, str]: (allowed, client_ip_string)
    """
    client_ip_str = get_client_ip(request) or ""
    try:
        client_ip = ipaddress.ip_address(client_ip_str)
    except ValueError:
        return False, client_ip_str

    # Some proxies present IPv4 clients as IPv4-mapped IPv6 (::ffff:x.x.x.x).
    # Compare using the embedded IPv4 so private-range checks still work.
    compare_ip = client_ip.ipv4_mapped if getattr(client_ip, "ipv4_mapped", None) else client_ip

    override = os.environ.get(SETUP_ALLOWED_IP_ENV, "").strip()
    if override:
        try:
            override_ip = ipaddress.ip_address(override)
        except ValueError:
            logger.warning(
                "Invalid %s=%r; denying initialize-superuser POST",
                SETUP_ALLOWED_IP_ENV,
                override,
            )
            return False, client_ip_str
        override_compare = (
            override_ip.ipv4_mapped
            if getattr(override_ip, "ipv4_mapped", None)
            else override_ip
        )
        return compare_ip == override_compare, client_ip_str

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

    network_allowed = False
    client_ip = ipaddress.ip_address(get_client_ip(request))
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
