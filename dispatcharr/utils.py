# dispatcharr/utils.py
import json
import ipaddress
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from core.models import CoreSettings, NETWORK_ACCESS


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
    x_forwarded_for = request.META.get("HTTP_X_REAL_IP")
    if x_forwarded_for:
        # X-Forwarded-For can be a comma-separated list of IPs
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def network_access_allowed(request, settings_key):
    network_access = json.loads(CoreSettings.objects.get(key=NETWORK_ACCESS).value)

    cidrs = (
        network_access[settings_key].split(",")
        if settings_key in network_access
        else ["0.0.0.0/0", "::/0"]
    )

    network_allowed = False
    client_ip = ipaddress.ip_address(get_client_ip(request))
    for cidr in cidrs:
        network = ipaddress.ip_network(cidr)
        if client_ip in network:
            network_allowed = True
            break

    return network_allowed
