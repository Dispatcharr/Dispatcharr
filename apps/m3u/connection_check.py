"""Read-only, bounded connection checks for the account editor."""

import json
from time import monotonic
from urllib.parse import urlencode

import requests

from core.http_security import get_with_validated_redirects
from core.xtream_codes import normalize_server_url


def check_account_connection(values):
    """Probe a public provider without saving or returning upstream text."""
    is_xc = values["account_type"] == "XC"
    url = values["server_url"]
    if is_xc:
        if not values.get("password"):
            return _failure(
                "password_required",
                "Re-enter the password to check a new or changed "
                "Xtream Codes server URL.",
            )
        query = urlencode({
            "username": values["username"],
            "password": values["password"],
        })
        url = f"{normalize_server_url(url)}/player_api.php?{query}"

    try:
        started = monotonic()
        # GET matches imports; HEAD is rejected by some working providers.
        # Every redirect is checked. Private, loopback and metadata targets
        # remain blocked by the shared outbound HTTP policy.
        with get_with_validated_redirects(
            url,
            headers={"User-Agent": values["user_agent_string"]},
            timeout=(3, 5),
            max_redirects=2,
            stream=True,
        ) as response:
            if not 200 <= response.status_code < 300:
                return {
                    "success": False,
                    "code": "http_error",
                    "message": (
                        f"The provider returned HTTP {response.status_code}. "
                        "Check the URL, credentials and provider "
                        "access restrictions."
                    ),
                    "http_status": response.status_code,
                }

            # Inspect a prefix only; never download a complete playlist.
            limit = 65536 if is_xc else 4096
            body = bytearray()
            for chunk in response.iter_content(chunk_size=1024):
                if monotonic() - started > 10:
                    raise requests.exceptions.Timeout()
                body.extend(chunk[:limit - len(body)])
                if len(body) >= limit or (not is_xc and b"\n" in body):
                    break

        if not is_xc:
            prefix = bytes(body).decode("utf-8-sig", errors="replace").lstrip()
            if prefix.startswith("#EXTM3U"):
                return _success()
            return _failure(
                "invalid_playlist",
                "The URL responded, but an M3U header could not be verified.",
            )

        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            data = None
        user_info = data.get("user_info") if isinstance(data, dict) else None
        if not isinstance(user_info, dict) or not user_info:
            return _failure(
                "invalid_response",
                "The server responded, but did not return valid "
                "Xtream Codes account information.",
            )
        if (
            "auth" not in user_info
            and str(user_info.get("status", "")).lower() != "active"
        ):
            return _failure(
                "invalid_response",
                "The server did not confirm a valid Xtream Codes login.",
            )
        if (
            "auth" in user_info
            and str(user_info["auth"]).lower() not in {"1", "true"}
        ):
            return _failure(
                "authentication_failed",
                "The provider did not accept these credentials.",
            )
        if str(user_info.get("status", "active")).lower() != "active":
            return _failure(
                "account_unavailable",
                "The provider reports that this account is not active.",
            )
        return _success()
    except requests.exceptions.SSLError:
        return _failure(
            "tls_error", "The server's TLS certificate could not be verified."
        )
    except requests.exceptions.Timeout:
        return _failure(
            "timeout",
            "The provider did not respond within the connection-check timeout.",
        )
    except requests.exceptions.ConnectionError:
        return _failure(
            "connection_error",
            "A connection to the provider could not be established.",
        )
    except requests.exceptions.RequestException:
        return _failure(
            "request_failed", "The connection check could not be completed."
        )
    except ValueError:
        # DNS/redirect-policy errors can contain hosts or IPs. Never echo them.
        return _failure(
            "unavailable",
            "The URL could not be resolved or safely checked. "
            "Internal network addresses are not probed.",
        )


def _failure(code, message):
    return {"success": False, "code": code, "message": message}


def _success():
    return {"success": True, "code": "connected", "message": "Connection verified."}
