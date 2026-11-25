"""Shared helpers for safer outbound HTTP fetches (SSRF prevention)."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from requests.adapters import DEFAULT_POOLBLOCK, HTTPAdapter
from requests.utils import should_bypass_proxies

# Shared default for hop-by-hop redirect following (plugins, similar fetchers).
DEFAULT_MAX_REDIRECTS = 5


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _ascii_hostname(hostname: str) -> str:
    """Return an ASCII hostname suitable for Host and TLS SNI."""
    if _is_ip_literal(hostname):
        return hostname
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return hostname


def _host_header_value(hostname: str, port: int | None, scheme: str) -> str:
    """Build a Host header for the original hostname (IPv6 bracketed when needed)."""
    host = _ascii_hostname(hostname)
    if ":" in host and _is_ip_literal(host):
        host = f"[{host}]"
    if port is None:
        return host
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return host
    return f"{host}:{port}"


def _url_with_fixed_ip(url: str, ip: str) -> str:
    """Rewrite *url* so the netloc host is *ip*, keeping userinfo, port, and path."""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError("URL has no hostname.")

    # Keep the original userinfo text. Rebuilding it from the parsed
    # username and password can change escaping.
    userinfo, sep, hostport = parsed.netloc.rpartition("@")
    if hostport.startswith("["):
        bracket_end = hostport.find("]")
        port_suffix = hostport[bracket_end + 1 :] if bracket_end != -1 else ""
    else:
        _host, port_sep, port = hostport.rpartition(":")
        port_suffix = f":{port}" if port_sep and port.isdigit() else ""

    ip_host = f"[{ip}]" if ":" in ip else ip
    new_hostport = f"{ip_host}{port_suffix}"
    netloc = f"{userinfo}@{new_hostport}" if sep else new_hostport
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _dedupe_ips(ips: list[str]) -> list[str]:
    """Drop duplicate addresses. getaddrinfo repeats each IP per socket type."""
    seen: set[str] = set()
    unique: list[str] = []
    for raw in ips:
        key = str(ipaddress.ip_address(raw))
        if key in seen:
            continue
        seen.add(key)
        unique.append(key)
    return unique


def _private_session(source: Any | None) -> requests.Session:
    """Session used for one pinned request.

    A caller-supplied session is not used directly: mounting an HTTPS adapter
    on it would force later requests on that session to one SNI name.
    Transport settings are copied so verify, proxies, and auth still apply.
    """
    sess = requests.Session()
    if source is None:
        return sess
    sess.trust_env = source.trust_env
    sess.verify = source.verify
    sess.cert = source.cert
    sess.auth = source.auth
    if source.proxies:
        sess.proxies.update(source.proxies)
    if source.headers:
        sess.headers.update(source.headers)
    if source.cookies is not None:
        sess.cookies = source.cookies
    return sess


def _proxy_override(url: str, source: Any | None) -> dict[str, None] | None:
    """Return a no-proxy override when the original *url* is exempt via NO_PROXY.

    The pinned request URL carries an IP, so requests would match NO_PROXY
    against that IP instead of the hostname. Without this, a LAN artwork host
    listed in NO_PROXY would be sent through the proxy after pinning.
    """
    if source is not None and not source.trust_env:
        return None
    no_proxy = (source.proxies or {}).get("no_proxy") if source is not None else None
    if should_bypass_proxies(url, no_proxy=no_proxy):
        return {"http": None, "https": None, "all": None}
    return None


class _TLSServerHostnameAdapter(HTTPAdapter):
    """HTTPS adapter that verifies TLS for *server_hostname* while dialing the URL host.

    Used when the request URL host is a validated IP literal so DNS cannot be
    consulted again, but SNI and certificate checks still use the original name.
    """

    def __init__(self, server_hostname: str, **kwargs: Any):
        self._server_hostname = server_hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=DEFAULT_POOLBLOCK, **pool_kwargs):
        pool_kwargs["assert_hostname"] = self._server_hostname
        pool_kwargs["server_hostname"] = self._server_hostname
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["assert_hostname"] = self._server_hostname
        proxy_kwargs["server_hostname"] = self._server_hostname
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _pin_tls_hostname(sess: requests.Session, server_hostname: str) -> None:
    """Verify TLS as *server_hostname* while the URL host stays the pinned IP."""
    previous = sess.get_adapter("https://")
    sess.mount("https://", _TLSServerHostnameAdapter(server_hostname))
    if previous is not None and previous is not sess.get_adapter("https://"):
        previous.close()


def validate_outbound_http_url(
    url: str,
    *,
    allow_private: bool = False,
    allow_loopback: bool = False,
) -> list[str]:
    """Raise ValueError if *url* must not be fetched; otherwise return safe IPs.

    Only ``http`` and ``https`` are allowed. After DNS resolution, addresses
    that are link-local, reserved, unspecified, or multicast are always
    rejected. Loopback and RFC1918-style private addresses are rejected
    unless explicitly allowed via *allow_loopback* / *allow_private*.

    Image proxies typically set ``allow_private=True`` so LAN-hosted artwork
    still works, while plugin installs keep the stricter default.

    Returns the validated IP address strings from DNS (in resolver order).
    Callers that open a connection should dial one of these addresses rather
    than resolving the hostname again (DNS rebinding / TOCTOU).
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

    validated: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr_str)
        except ValueError:
            continue

        # Classify loopback/private carefully:
        # link-local (including cloud metadata 169.254.0.0/16) must stay blocked
        # even when allow_private is set, because Python marks it is_private too.
        if ip.is_loopback:
            if not allow_loopback:
                raise ValueError(
                    f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
                )
            validated.append(addr_str)
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
            validated.append(addr_str)
            continue
        if ip.is_reserved:
            raise ValueError(
                f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
            )
        validated.append(addr_str)

    if not validated:
        raise ValueError(f"Could not resolve hostname '{hostname}' to an IP address.")
    return validated


def get_ssrf_safe(
    url: str,
    *,
    timeout: float | tuple[float, float] = 15,
    allow_private: bool = False,
    allow_loopback: bool = False,
    stream: bool = False,
    headers: dict[str, str] | None = None,
    session: Any | None = None,
):
    """GET *url* after SSRF validation, connecting only to validated IPs.

    Resolves and validates once, then dials those addresses in order while
    preserving the original hostname for the ``Host`` header and (for HTTPS)
    TLS SNI / certificate verification. This closes the DNS-rebinding gap
    where a second lookup inside the HTTP client could reach a blocked address.

    Each attempt uses a private session that is closed before this function
    returns, matching ``requests.get``. A streamed response body stays readable
    until the caller closes it. Failing to connect (refused, unreachable,
    connect timeout) tries the next validated address. TLS and proxy errors,
    and HTTP responses including error statuses, are not retried on another
    address.
    """
    validated_ips = _dedupe_ips(
        validate_outbound_http_url(
            url,
            allow_private=allow_private,
            allow_loopback=allow_loopback,
        )
    )
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")

    req_headers = dict(headers or {})
    req_headers["Host"] = _host_header_value(hostname, parsed.port, parsed.scheme)
    sni_hostname = _ascii_hostname(hostname)
    pin_tls = parsed.scheme == "https" and not _is_ip_literal(hostname)
    extra_kwargs: dict[str, Any] = {}
    proxy_override = _proxy_override(url, session)
    if proxy_override is not None:
        extra_kwargs["proxies"] = proxy_override

    last_error: requests.ConnectionError | None = None
    for connect_ip in validated_ips:
        pinned_url = _url_with_fixed_ip(url, connect_ip)
        try:
            # Close before returning so idle pools do not outlive the call.
            # The in-flight streamed connection is checked out of the pool and
            # stays usable until the caller closes the response.
            with _private_session(session) as sess:
                if pin_tls:
                    _pin_tls_hostname(sess, sni_hostname)
                return sess.get(
                    pinned_url,
                    timeout=timeout,
                    allow_redirects=False,
                    stream=stream,
                    headers=req_headers,
                    **extra_kwargs,
                )
        except (requests.exceptions.SSLError, requests.exceptions.ProxyError):
            # Both subclass ConnectionError. Another address would hit the same
            # certificate or proxy, and retrying would hide the real error.
            raise
        except requests.ConnectionError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise ValueError(f"Could not connect to a validated address for '{hostname}'.")


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
    current URL, then passed through :func:`get_ssrf_safe` (validate + pin IP)
    before the next request. Intermediate redirect responses are closed.

    Returns the final non-redirect ``requests.Response``. The caller must close
    it (``with`` or ``.close()``). Raises ``ValueError`` for policy violations
    or redirect loops, and propagates ``requests`` transport errors.
    """
    current_url = url

    for _ in range(max_redirects + 1):
        response = get_ssrf_safe(
            current_url,
            timeout=timeout,
            allow_private=allow_private,
            allow_loopback=allow_loopback,
            stream=stream,
            headers=headers,
            session=session,
        )
        if response.status_code not in (301, 302, 303, 307, 308):
            return response

        location = response.headers.get("Location")
        response.close()
        if not location:
            raise ValueError("Redirect response missing Location header.")
        current_url = urljoin(current_url, location)

    raise ValueError(f"Exceeded maximum of {max_redirects} redirects.")
