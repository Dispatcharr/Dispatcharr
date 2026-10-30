"""Django-free redaction shared by log producers, collection and exports.

This is deliberately independent of UI preferences. Do not feed the result back
into application state: only diagnostic output is redacted.
"""

import re
from ipaddress import IPv6Address
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit


REDACTED = "[REDACTED]"
# A valid reserved hostname keeps redacted URLs parseable on repeated passes.
_REDACTED_HOST = "redacted.invalid"
MAX_LINE_BYTES = 256 * 1024
_OVERSIZE_NOTICE = b" ... [log redaction omitted oversized continuation]\n"

_URL = re.compile(
    r"\b[a-z][a-z0-9+.-]*(?::(?:\\*/){2}|%3a(?:%2f){2})[^\s<>\"']+",
    re.IGNORECASE,
)
_KEY = (
    r"(?:[\w-]+[_-])?"
    r"(?:user(?:[_-]?name)?|password|passwd|pwd|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|client[_-]?secret|secret|"
    r"token|authorization|auth|cookie|session[_-]?id)"
)
_SENSITIVE_KEY = re.compile(_KEY, re.IGNORECASE)
_ADDRESS_KEY = re.compile(
    r"(?:[\w-]+[_-])?(?P<kind>url|uri|host(?:name)?)", re.IGNORECASE,
)
_VALUE = (
    re.escape(REDACTED)
    + r'|"(?:\\.|[^"\\])*"'
    + r"|'(?:\\.|[^'\\])*'"
    + r'|"(?:\\.|[^"\\])*$'
    + r"|'(?:\\.|[^'\\])*$"
    + r"|(?:Bearer|Basic)\s+[^\s,;\"']+"
    + r"|[^\s,;&}\])\"']+"
)
_FIELD = re.compile(
    rf"(?P<prefix>\b{_KEY}\b[\"']?(?:\s*[:=]\s*|[ \t]+(?:is[ \t]+)?))"
    rf"(?P<value>{_VALUE})",
    re.IGNORECASE,
)
_CLI = re.compile(
    rf"(?P<prefix>--{_KEY}(?:=|[ \t]+))(?P<value>{_VALUE})",
    re.IGNORECASE,
)
_ADDRESS_FIELD = re.compile(
    r"(?P<prefix>\b(?:[\w-]+[_-])?(?P<key>url|uri|host(?:name)?)\b"
    r"[\"']?(?:\s*[:=]\s*|[ \t]+(?:is[ \t]+)?))"
    r'''(?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s}\)"']+)''',
    re.IGNORECASE,
)
_REQUEST_TARGET = re.compile(
    r"(?P<prefix>\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)[ \t]+)"
    r"(?P<url>/[^\s<>\"']+)",
)
_AUTH = re.compile(r"\b(Bearer|Basic)[ \t]+[^\s,;\"']+", re.IGNORECASE)
_COOKIE = re.compile(
    r"(?P<prefix>\b(?:set[-_])?cookie\b[\"']?\s*[:=]\s*)"
    r'''(?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n]*)''',
    re.IGNORECASE,
)
_XC_PATH = re.compile(
    r"(?P<prefix>/(?:live|movie|series|timeshift)/)"
    r"[^/\s?\"']+/[^/\s?\"']+",
    re.IGNORECASE,
)
_SQL_WRITE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE)\b[^\r\n]*"
    r"\b(?:username|password|passwd|api_key|access_token|refresh_token)\b[^\r\n]*",
    re.IGNORECASE,
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_NETWORK_SCHEMES = {
    "http", "https", "rtsp", "rtsps", "rtmp", "rtmps", "udp", "rtp",
    "redis", "rediss", "postgres", "postgresql",
}
_PUBLIC_PATHS = {
    "image.tmdb.org": re.compile(
        r"/t/p/(?:w\d{2,4}|original)/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp)"
    ),
    "dispatcharr.github.io": re.compile(
        r"/Dispatcharr-Docs(?:/[A-Za-z0-9_.-]+)*/?"
    ),
    "github.com": re.compile(
        r"/Dispatcharr/Dispatcharr(?:/(?:issues(?:/\d+)?|"
        r"blob/(?:main|dev)/(?:README|CONTRIBUTING)\.md))?/?"
    ),
}
_XC_ENDPOINT = re.compile(r"/(?:player_api|get|xmltv)\.php$")
_XC_STREAM = re.compile(
    r"/(?P<kind>live|movie|series|timeshift)/[^/]+/[^/]+/"
    r"(?P<tail>\d+(?:\.(?:ts|m3u8|mp4|mkv|avi|m4v|webm|mov|mpg|mpeg))?)$",
    re.IGNORECASE,
)
_XC_TIMESHIFT = re.compile(
    r"/timeshift/[^/]+/[^/]+/"
    r"(?P<tail>\d+/\d{4}-\d{2}-\d{2}:\d{2}-\d{2}/\d+\.(?:ts|m3u8))$",
    re.IGNORECASE,
)
_LOCAL_API_PATH = re.compile(
    r"/api/(?:status|"
    r"vod/(?:all|movies|series|categories)|m3u/accounts|epg/sources|"
    r"core/(?:logs(?:/dispatcharr\.log(?:-[A-Za-z0-9]{1,16})?(?:\.\d+)?)?|"
    r"events|stats|settings))(?:/\d+)*/?"
)
_SAFE_ACTIONS = {
    "get_live_categories", "get_live_streams", "get_vod_categories",
    "get_vod_streams", "get_series_categories", "get_series",
    "get_vod_info", "get_series_info", "get_short_epg", "get_simple_data_table",
}
_SAFE_QUERY_NUMBERS = {
    "page", "page_size", "limit", "stream_id", "vod_id", "series_id", "category_id",
}
_SAFE_QUERY_CHOICES = {
    "action": _SAFE_ACTIONS,
    "type": {"m3u", "m3u_plus", "m3u8", "xmltv"},
    "output": {"ts", "m3u8", "mpegts", "hls"},
    "raw": {"true", "false"},
}
_VISIBLE_QUERY_KEYS = _SAFE_QUERY_NUMBERS | _SAFE_QUERY_CHOICES.keys() | {
    "user", "username", "user_name", "password", "passwd", "pwd", "token",
    "access_token", "refresh_token", "key", "api_key", "apikey", "api-key",
    "signature", "sign", "auth", "authorization", "session", "sessionid",
    "session_id", "expires", "exp",
}


def _safe_path(path, host, scheme):
    """Return only paths whose structure is known not to contain credentials."""
    public = _PUBLIC_PATHS.get(host)
    if public and scheme in {"http", "https"} and public.fullmatch(path):
        return path, True, True
    endpoint = _XC_ENDPOINT.search(path)
    if endpoint:
        prefix = f"/{REDACTED}" if endpoint.start() else ""
        return prefix + endpoint.group(), True, False
    for pattern in (_XC_STREAM, _XC_TIMESHIFT):
        stream = pattern.fullmatch(path)
        if stream:
            kind = stream.groupdict().get("kind") or "timeshift"
            return f"/{kind}/{REDACTED}/{REDACTED}/{stream['tail']}", True, False
    if (not host or host in _LOCAL_HOSTS) and _LOCAL_API_PATH.fullmatch(path):
        return path, True, False
    if host in _LOCAL_HOSTS and scheme in {"redis", "rediss"}:
        if re.fullmatch(r"/\d+", path):
            return path, True, False
    if not path or path == "/":
        return path, False, False
    return f"/{REDACTED}", False, False


def _safe_query(query, known_path):
    fields = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        safe = known_path and (
            value in _SAFE_QUERY_CHOICES.get(key.lower(), ())
            or (key.lower() in _SAFE_QUERY_NUMBERS and value.isascii() and value.isdecimal())
        )
        # Unknown names can themselves carry data; do not echo arbitrary text.
        name = key if key.lower() in _VISIBLE_QUERY_KEYS else REDACTED
        shown_value = quote(value, safe="") if safe else REDACTED
        fields.append(f"{quote(name, safe='[]')}={shown_value}")
    return "&".join(fields)


def _redact_url(value):
    # Logs may contain JSON-escaped or entirely percent-encoded URLs. Normalize
    # those representations before parsing; do not decode path segments, where
    # an encoded slash may be part of a credential rather than a separator.
    if len(value) > 16 * 1024:
        return REDACTED
    value = re.sub(r"\\+/", "/", value)
    if re.match(r"[a-z][a-z0-9+.-]*%3a%2f%2f", value, re.IGNORECASE):
        value = unquote(value)
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        if scheme and scheme not in _NETWORK_SCHEMES:
            return REDACTED
        if scheme and (not parts.netloc or not parts.hostname):
            return REDACTED
        host = (parts.hostname or "").lower()
        port = parts.port  # Reject malformed authorities rather than echoing them.
        if parts.netloc.rsplit("@", 1)[-1].startswith("["):
            IPv6Address(host)
        path, known, public = _safe_path(parts.path, host, scheme)
        authority = ""
        if parts.netloc:
            shown_host = host if public or host in _LOCAL_HOSTS else _REDACTED_HOST
            authority = f"[{shown_host}]" if ":" in shown_host else shown_host
            if port is not None:
                authority += f":{port}"
            if "@" in parts.netloc:
                # Bracketed markers in userinfo are rejected by Python 3.13's
                # URL parser. Keep repeated formatter/collector passes stable.
                authority = f"redacted@{authority}"
        fragment = REDACTED if parts.fragment else ""
        return urlunsplit((scheme, authority, path, _safe_query(parts.query, known), fragment))
    except ValueError:
        return REDACTED


def _replace_url(match):
    value = match.group()
    # Exception messages commonly wrap an URL in parentheses. Keep the wrapper
    # rather than treating it as part of an endpoint or safe query value.
    suffix = ""
    while value.endswith((")", ",", ".")):
        suffix = value[-1] + suffix
        value = value[:-1]
    return _redact_url(value) + suffix


def _redact_host(value):
    try:
        parts = urlsplit("//" + value)
        host = (parts.hostname or "").lower()
        port = parts.port
        if not host or parts.path or parts.query or parts.fragment or "@" in value:
            return REDACTED
        if value.startswith("["):
            IPv6Address(host)
        shown = host if host in _LOCAL_HOSTS else _REDACTED_HOST
        shown = f"[{shown}]" if ":" in shown else shown
        return shown + (f":{port}" if port is not None else "")
    except ValueError:
        return REDACTED


def _replace_address(match):
    value = match.group("value")
    quoted = value[:1] in {"\"", "'"}
    quote_mark = value[0] if quoted else ""
    raw = value[1:-1] if quoted else value
    trailer = ""
    if not quoted:
        while raw.endswith((",", ".")):
            trailer = raw[-1] + trailer
            raw = raw[:-1]
    if raw == REDACTED:
        return match.group()
    explicit = quoted or ":" in match.group("prefix") or "=" in match.group("prefix")
    if match.group("key").lower().startswith("host"):
        if not explicit and not any(char in raw for char in ".:[]"):
            return match.group()
        raw = _redact_host(raw)
    elif explicit or raw.startswith("/") or ":" in raw:
        raw = _redact_url(raw)
    else:
        return match.group()
    return match.group("prefix") + quote_mark + raw + quote_mark + trailer


def _replace_value(match):
    value = match.group("value")
    if value[:1] in ('"', "'"):
        quote = value[0]
        value = f"{quote}{REDACTED}{quote}"
    else:
        value = REDACTED
    return match.group("prefix") + value


def redact_log_text(text):
    """Hide addresses/credentials, retaining known safe URL diagnostics.

    Public poster/docs URLs require an exact host and known path. Other hosts
    are replaced; only known endpoint paths and allowlisted query values stay
    visible. Unknown path segments, query values and fragments remain hidden.
    Labels and error/status information remain useful. Unlabelled arbitrary
    text cannot be identified as a secret; callers must not log raw payloads.
    """
    text = _SQL_WRITE.sub("[REDACTED credential SQL statement]", text)
    text = _ADDRESS_FIELD.sub(_replace_address, text)
    text = _URL.sub(_replace_url, text)
    text = _REQUEST_TARGET.sub(
        lambda match: match.group("prefix") + _redact_url(match.group("url")), text,
    )
    text = _COOKIE.sub(_replace_value, text)
    text = _CLI.sub(_replace_value, text)
    text = _FIELD.sub(_replace_value, text)
    text = _AUTH.sub(lambda match: match.group(1) + " " + REDACTED, text)
    return _XC_PATH.sub(
        lambda match: match.group("prefix") + REDACTED + "/" + REDACTED,
        text,
    )


def redact_log_bytes(data):
    # Latin-1 is a reversible byte mapping; leave unrelated bytes untouched.
    return redact_log_text(data.decode("latin-1")).encode("latin-1")


def redact_log_data(value, *, key=None):
    """Copy JSON diagnostics, preserving non-sensitive fields and value types.

    Keep the original payload for application/integration use. Field names
    supply context for bare credentials and relative URLs in event details;
    free-form messages use the same rules as ordinary log lines.
    """
    if isinstance(key, str) and _SENSITIVE_KEY.fullmatch(key):
        return REDACTED
    if isinstance(value, dict):
        return {
            name: redact_log_data(item, key=name)
            for name, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact_log_data(item, key=key) for item in value)
    if not isinstance(value, str) or value == REDACTED:
        return value
    address = _ADDRESS_KEY.fullmatch(key) if isinstance(key, str) else None
    if address:
        if address["kind"].lower().startswith("host"):
            return _redact_host(value)
        return _redact_url(value)
    return redact_log_text(value)


def redacted_log_lines(stream, max_line_bytes=MAX_LINE_BYTES):
    """Yield redacted lines with bounded memory, including a final fragment.

    A record beyond the bound is redacted up to that point; its continuation is
    omitted so a credential split across input chunks can never escape alone.
    Ordinary records (including large tracebacks) are not truncated here.
    """
    skipping = False
    while True:
        chunk = stream.readline(max_line_bytes)
        if not chunk:
            return
        complete = chunk.endswith(b"\n")
        if skipping:
            skipping = not complete
            continue
        oversized = not complete and len(chunk) == max_line_bytes
        redacted = redact_log_bytes(chunk)
        if oversized:
            redacted += _OVERSIZE_NOTICE
            skipping = True
        yield redacted
