"""Shared helpers for safer outbound HTTP fetches (SSRF prevention)."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

# Shared default for hop-by-hop redirect following (plugins, similar fetchers).
DEFAULT_MAX_REDIRECTS = 5


def validate_outbound_http_url(
    url: str,
    *,
    allow_private: bool = False,
    allow_loopback: bool = False,
) -> None:
    """Raise ValueError if *url* must not be fetched.

    Only ``http`` and ``https`` are allowed. After DNS resolution, addresses
    that are link-local, reserved, unspecified, or multicast are always
    rejected. Loopback and RFC1918-style private addresses are rejected
    unless explicitly allowed via *allow_loopback* / *allow_private*.

    Image proxies typically set ``allow_private=True`` so LAN-hosted artwork
    still works, while plugin installs keep the stricter default.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"URL scheme '{parsed.scheme}' is not allowed; only http and https are permitted."
        )
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname '{hostname}': {exc}") from exc

    if not infos:
        raise ValueError(f"Could not resolve hostname '{hostname}'.")

    saw_ip = False
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        saw_ip = True

        # Classify loopback/private carefully:
        # link-local (including cloud metadata 169.254.0.0/16) must stay blocked
        # even when allow_private is set, because Python marks it is_private too.
        if ip.is_loopback:
            if not allow_loopback:
                raise ValueError(
                    f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
                )
            continue
        if ip.is_unspecified or ip.is_multicast or ip.is_link_local:
            raise ValueError(
                f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
            )
        if ip.is_private:
            if not allow_private:
                raise ValueError(
                    f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
                )
            continue
        if ip.is_reserved:
            raise ValueError(
                f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
            )

    if not saw_ip:
        raise ValueError(f"Could not resolve hostname '{hostname}' to an IP address.")


def get_with_validated_redirects(
    url: str,
    *,
    timeout: float | tuple[float, float] = 15,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_private: bool = False,
    allow_loopback: bool = False,
    stream: bool = False,
    headers: dict[str, str] | None = None,
    session: Any | None = None,
):
    """GET *url*, re-validating SSRF policy on every redirect hop.

    Automatic redirects are disabled. Each ``Location`` is joined against the
    current URL, then passed through :func:`validate_outbound_http_url` before
    the next request. Intermediate redirect responses are closed.

    Returns the final non-redirect ``requests.Response``. The caller must close
    it (``with`` or ``.close()``). Raises ``ValueError`` for policy violations
    or redirect loops, and propagates ``requests`` transport errors.
    """
    getter = session.get if session is not None else requests.get
    current_url = url

    for _ in range(max_redirects + 1):
        validate_outbound_http_url(
            current_url,
            allow_private=allow_private,
            allow_loopback=allow_loopback,
        )
        response = getter(
            current_url,
            timeout=timeout,
            allow_redirects=False,
            stream=stream,
            headers=headers,
        )
        if response.status_code not in (301, 302, 303, 307, 308):
            return response

        location = response.headers.get("Location")
        response.close()
        if not location:
            raise ValueError("Redirect response missing Location header.")
        current_url = urljoin(current_url, location)

    raise ValueError(f"Exceeded maximum of {max_redirects} redirects.")
