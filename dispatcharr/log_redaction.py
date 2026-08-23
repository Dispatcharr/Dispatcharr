"""Mask IPTV provider credentials in a single line of log text.

The log collector runs this over every line of the container's merged
stdout, so it must import in a bare interpreter: no Django, no app
imports, standard library only. core.redaction re-exports redact_text()
for the application-side masking of structured payloads.
"""

import re

_KEY_ALT = (
    r"username|user|password|passwd|pass|secret|signature|sig|"
    r"authorization|auth[_-]?token|bearer|"
    r"x[_-]api[_-]key|api[_-]?key|apikey|token"
)

# Compound-key prefix ("xc_password"); the trailing delimiter keeps "compass" out.
_KEY_PREFIX = r"(?:[\w.-]*[._-])?"

_URL_PATH_CREDS = re.compile(
    r"://(?P<host>[^/\s]+)(?P<type>/(?:live|movie|series|timeshift)/)"
    r"(?P<user>[^/\s]+)/(?P<pass>[^/\s]+)"
    r"(?P<post>/)",
    re.IGNORECASE,
)

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

_QUERY_PARAM = re.compile(
    rf"(?i)\b({_KEY_PREFIX}(?:{_KEY_ALT}))="
    r"((?:Bearer|Basic|Digest|Token)\s+[^&\s\"']+|[^&\s\"']+)"
)

_KV_ASSIGN = re.compile(
    rf"(?i)\b({_KEY_PREFIX}(?:{_KEY_ALT}))\b(\s*[:=]\s*)"
    r"((?:Bearer|Basic|Digest|Token)\s+[^\s,;)}&]+|\"[^\"]*\"|'[^']*'|[^\s,;)}&]+)"
)

# Credentials in a quoted dict repr; the quote before the colon defeats _KV_ASSIGN.
_DICT_KV = re.compile(
    rf"(?ix)(?P<q>['\"])(?P<key>{_KEY_PREFIX}(?:{_KEY_ALT}))(?P=q)(?P<sep>\s*:\s*)"
    r"(?P<vq>['\"])(?:\\.|[^'\"\\])*(?P=vq)"
)

# A bare provider base URL has no shape; the url label is the only signal.
_URL_LABEL = re.compile(
    rf"(?i)\b({_KEY_PREFIX}url)(\s*[:=]\s*)([^\s,;)}}&]+)"
)

# The shape requests exception text uses: HTTPSConnectionPool(host='...', port=443).
_HOST_KV = re.compile(r"(?i)\bhost=(['\"])[^'\"\s]+\1")

# Every pattern needs a scheme, a stream path, host=, or a credential-shaped key
# name, so one scan gates the battery: a shape missing here never reaches it.
_TRIGGER = re.compile(
    rf"(?i)://|/(?:live|movie|series|timeshift)/|\bhost="
    rf"|\b{_KEY_PREFIX}(?:{_KEY_ALT}|url)\b"
)


def _redact_dict_kv(match):
    q, vq = match.group("q"), match.group("vq")
    key = match.group("key")
    return f"{q}{key}{q}{match.group('sep')}{vq}[{key.lower()}]{vq}"


def _redact_url_label(match):
    # A '[' means the URL battery already masked the value, or it is an IPv6 literal.
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


def _apply(value):
    """Run the whole battery; redact_text() gates this on the trigger scan."""
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


def redact_text(value):
    """Mask credential patterns anywhere in *value*; non-strings pass through.

    Idempotent: every substitution rewrites its match into a bracketed token
    that the same pattern maps back onto itself, so masking an already-masked
    line is a no-op.
    """
    if not isinstance(value, str) or not value:
        return value
    # Cheapest first: a line with none of this punctuation cannot match.
    if (
        "://" not in value
        and "=" not in value
        and ":" not in value
        and "/live/" not in value
        and "/movie/" not in value
        and "/series/" not in value
        and "/timeshift/" not in value
        and "resolve" not in value
        and " timed out" not in value
    ):
        return value
    if not _TRIGGER.search(value):
        return value
    return _apply(value)
