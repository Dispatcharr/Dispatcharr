"""Mask IPTV provider credentials in user-visible output.

redact_text() sweeps free-form strings (log lines, tracebacks),
redact_url() reduces a single URL to scheme://host/..., and
redact_mapping() recurses structured payloads. RedactingFormatter
applies redact_text() to every rendered log line. Masked values are
replaced with a bracketed name of what was removed ([password],
[xc_password], [provider_host]).
"""

import re

from dispatcharr.display_timezone import DisplayTimezoneFormatter

# Keys whose values are masked in a mapping, matched as whole delimiter-bounded words.
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:passphrase|password|passwd|pass|secret|token|api_?key|apikey|"
    r"authorization|auth_?token|bearer|creds|credential|url)s?(?:$|_)"
    r"|(?:^|_)(?:signature|sig)s?$",
    re.IGNORECASE,
)
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Credential-bearing key names shared by the query, free-text, and dict-repr patterns.
_KEY_ALT = (
    r"username|user|password|passwd|pass|secret|signature|sig|"
    r"authorization|auth[_-]?token|bearer|"
    r"x[_-]api[_-]key|api[_-]?key|apikey|token"
)

# Optional compound-key prefix ("xc_password", "access_token"); must end in a delimiter.
_KEY_PREFIX = r"(?:[\w.-]*[._-])?"

# Xtream-style path credentials and their provider host: http://host/live/<user>/<pass>/123.ts
_URL_PATH_CREDS = re.compile(
    r"://(?P<host>[^/\s]+)(?P<type>/(?:live|movie|series|timeshift)/)"
    r"(?P<user>[^/\s]+)/(?P<pass>[^/\s]+)"
    r"(?P<post>/)",
    re.IGNORECASE,
)

# Hosts of XC API URLs; the endpoint names the role (xmltv.php serves the EPG guide).
_XC_PROVIDER_HOST = re.compile(
    r"(?i)(?P<pre>://(?:[^/\s]*@)?)[^/\s@]+(?P<path>/(?:player_api|get|panel_api)\.php)"
)
_XC_EPG_HOST = re.compile(
    r"(?i)(?P<pre>://(?:[^/\s]*@)?)[^/\s@]+(?P<path>/xmltv\.php)"
)

# The same path credentials without scheme://host, as request paths appear in logs.
_BARE_PATH_CREDS = re.compile(
    r"(?i)(?<![\w:])(?P<pre>/(?:live|movie|series|timeshift)/)"
    r"(?P<user>[^/\s]+)/(?P<pass>[^/\s]+)(?P<post>/)"
)

# userinfo before the host: scheme://user:pass@host (greedy to the last '@').
_URL_USERINFO = re.compile(r"(://)[^/\s]+:[^/\s]+@")

# Sensitive query / form parameters: ?username=x&password=y, token=..., etc.
_QUERY_PARAM = re.compile(
    rf"(?i)\b({_KEY_PREFIX}(?:{_KEY_ALT}))="
    r"((?:Bearer|Basic|Digest|Token)\s+[^&\s\"']+|[^&\s\"']+)"
)

# Bare "password: value" / "password=value" assignments in free text.
_KV_ASSIGN = re.compile(
    rf"(?i)\b({_KEY_PREFIX}(?:{_KEY_ALT}))\b(\s*[:=]\s*)"
    r"((?:Bearer|Basic|Digest|Token)\s+[^\s,;)}&]+|\"[^\"]*\"|'[^']*'|[^\s,;)}&]+)"
)

# Credentials inside a quoted dict repr: 'password': 'x'.
_DICT_KV = re.compile(
    rf"(?ix)(?P<q>['\"])(?P<key>{_KEY_PREFIX}(?:{_KEY_ALT}))(?P=q)(?P<sep>\s*:\s*)"
    r"(?P<vq>['\"])(?:\\.|[^'\"\\])*(?P=vq)"
)

# URL-labeled values: "URL: https://portal.example" / server_url=... (a bare
# provider base URL has no shape the patterns above can classify).
_URL_LABEL = re.compile(
    rf"(?i)\b({_KEY_PREFIX}url)(\s*[:=]\s*)([^\s,;)}}&]+)"
)

# Quoted host= assignments, the shape requests exception text uses:
#   HTTPSConnectionPool(host='portal.example', port=443)
_HOST_KV = re.compile(r"(?i)\bhost=(['\"])[^'\"\s]+\1")


def _redact_dict_kv(match):
    q, vq = match.group("q"), match.group("vq")
    key = match.group("key")
    return f"{q}{key}{q}{match.group('sep')}{vq}[{key.lower()}]{vq}"


def _redact_url_label(match):
    # A '[' in the value means the URL battery already masked it (or an IPv6
    # literal); leave those, mask only values that survived unshaped.
    if "[" in match.group(3):
        return match.group(0)
    return f"{match.group(1)}{match.group(2)}[{match.group(1).lower()}]"


def _redact_url_path_creds(match):
    return (
        f"://[provider_host]{match.group('type')}"
        f"[username]/[password]{match.group('post')}"
    )


def _redact_path_creds(match):
    return f"{match.group('pre')}[username]/[password]{match.group('post')}"


def redact_text(value):
    """Mask credential patterns anywhere in *value*; non-strings pass through."""
    if not isinstance(value, str) or not value:
        return value
    # Fast path: most log lines carry none of the trigger substrings.
    if (
        "://" not in value
        and "=" not in value
        and ":" not in value
        and "/live/" not in value
        and "/movie/" not in value
        and "/series/" not in value
        and "/timeshift/" not in value
    ):
        return value
    result = _URL_USERINFO.sub(r"\1[username]:[password]@", value)
    result = _URL_PATH_CREDS.sub(_redact_url_path_creds, result)
    result = _BARE_PATH_CREDS.sub(_redact_path_creds, result)
    result = _XC_PROVIDER_HOST.sub(r"\g<pre>[provider_host]\g<path>", result)
    result = _XC_EPG_HOST.sub(r"\g<pre>[epg_host]\g<path>", result)
    result = _QUERY_PARAM.sub(
        lambda m: f"{m.group(1)}=[{m.group(1).lower()}]", result
    )
    result = _DICT_KV.sub(_redact_dict_kv, result)
    result = _KV_ASSIGN.sub(
        lambda m: f"{m.group(1)}{m.group(2)}[{m.group(1).lower()}]", result
    )
    result = _URL_LABEL.sub(_redact_url_label, result)
    result = _HOST_KV.sub(lambda m: f"host={m.group(1)}[host]{m.group(1)}", result)
    return result


def redact_url(url):
    """Reduce *url* to scheme://host/...; non-URL input passes through."""
    if not isinstance(url, str) or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    authority = rest.split("/", 1)[0]
    # Split on the last '@' so an email-shaped username doesn't leak the password.
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    return f"{scheme}://{authority}/..."


def _key_is_sensitive(key):
    if not isinstance(key, str):
        return False
    # Normalise camelCase and hyphens to underscores so whole-word matching applies.
    normalized = _CAMEL_BOUNDARY_RE.sub("_", key).replace("-", "_")
    return bool(_SENSITIVE_KEY_RE.search(normalized))


def _mask_sensitive_value(key, val):
    """Mask a value under a sensitive key, preserving structure and scalar types."""
    if isinstance(val, str):
        return redact_url(val) if "://" in val else f"[{key.lower()}]"
    if isinstance(val, (list, tuple)):
        return type(val)(_mask_sensitive_value(key, v) for v in val)
    if isinstance(val, dict):
        return redact_mapping(val)
    return val


def redact_mapping(value):
    """Recursively mask sensitive keys and sweep string values; returns a copy."""
    if isinstance(value, dict):
        redacted = {}
        for key, val in value.items():
            if _key_is_sensitive(key):
                redacted[key] = _mask_sensitive_value(key, val)
            else:
                redacted[key] = redact_mapping(val)
        return redacted
    if isinstance(value, (list, tuple)):
        return type(value)(redact_mapping(v) for v in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFormatter(DisplayTimezoneFormatter):
    """Mask credentials in the fully rendered line, including tracebacks.

    Subclasses DisplayTimezoneFormatter so the rendered timestamp follows
    the system display timezone.
    """

    def format(self, record):
        return redact_text(super().format(record))
