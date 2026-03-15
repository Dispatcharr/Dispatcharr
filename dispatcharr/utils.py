# dispatcharr/utils.py
import asyncio
import ipaddress
import os
import threading
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from core.models import CoreSettings, NETWORK_ACCESS_KEY


def _is_async_context():
    """
    Return True when the current thread is running inside an event loop.

    This catches both pure-asyncio contexts (e.g. Daphne/ASGI coroutines)
    and gevent-patched asyncio contexts where ``get_running_loop()`` raises
    RuntimeError but the event loop is still marked as running.
    """
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        pass
    try:
        return asyncio.get_event_loop().is_running()
    except RuntimeError:
        return False


def ensure_sync(func, *args, **kwargs):
    """
    Ensure a function with database access runs in a synchronous context.

    When running under an ASGI server (e.g. Daphne) or a gevent-based server
    whose hub patches asyncio's event-loop, Django may detect that the current
    thread has a running event loop and raise ``SynchronousOnlyOperation`` for
    any ORM call.

    This helper detects that situation and re-executes the callable in a
    dedicated worker thread.  ``DJANGO_ALLOW_ASYNC_UNSAFE`` is set inside the
    worker so that Django's ``@async_unsafe`` guard on the database cursor is
    bypassed – the call is genuinely synchronous and isolated from the event
    loop.
    """
    if not _is_async_context():
        return func(*args, **kwargs)

    result = [None]
    exception = [None]

    def _worker():
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        try:
            result[0] = func(*args, **kwargs)
        except BaseException as e:
            exception[0] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()

    if exception[0] is not None:
        raise exception[0]
    return result[0]


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


def _fetch_network_access_settings():
    try:
        return CoreSettings.objects.get(key=NETWORK_ACCESS_KEY).value
    except CoreSettings.DoesNotExist:
        return {}


def network_access_allowed(request, settings_key):
    network_access = ensure_sync(_fetch_network_access_settings)
    local_cidrs = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7", "fe80::/10"]
    # Set defaults based on endpoint type
    if settings_key == "M3U_EPG":
        # M3U/EPG endpoints: local IPv4 and IPv6 only by default
        default_cidrs = local_cidrs
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

    return network_allowed
