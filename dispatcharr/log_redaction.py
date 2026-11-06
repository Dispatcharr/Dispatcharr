"""Mask IPTV provider credentials in a single line of log text.

The log collector runs this over every line of the container's merged
stdout, so it must import in a bare interpreter: no Django, no app
imports, standard library only.
"""

import re

_KEY_ALT = (
    r"username|password|passwd|passphrase|pass|secret|signature|sig|"
    r"authorization|auth[_-]?token|bearer|"
    r"x[_-]api[_-]key|api[_-]?key|apikey|token|cookie|credentials?"
)

# Compound-key prefix ("xc_password"); the trailing delimiter keeps "compass" out.
# Anchored to the token start, or a long dotted token is rescanned at every dot.
_KEY_PREFIX = r"(?<![\w.-])(?:[\w.-]*[._-])?"

# An XC server may sit under a sub-path; segments hold no ':' so a scan ends there.
_SUB_PATH = r"(?:/[^/\s?#:]++)*?"

# Dispatcharr's own VOD API and proxy routes reuse the type words without credentials.
_OWN_ROUTE = r"(?<!/api/vod)(?<!/proxy/vod)"

_URL_PATH_CREDS = re.compile(
    rf"://(?P<host>[^/\s]+)(?P<sub>{_SUB_PATH}){_OWN_ROUTE}"
    r"(?P<type>/(?:live|movie|series|timeshift)/)"
    r"(?P<user>[^/\s]+)/(?P<pass>[^/\s]+)"
    r"(?P<post>/)",
    re.IGNORECASE,
)

# The XC live shape with no type segment, host/user/pass/<id>, as M3U playlists
# list it; a full URL only, since a bare path is ambiguous with REST routes.
_URL_PLAIN_CREDS = re.compile(
    r"(?i)(?P<pre>://(?:[^/\s@]*+@)?+)(?:\[[0-9a-f:.]++\](?::\d++)?|[^/\s@\[]++)/(?!api/)"
    r"[^/\s?#\[]++/[^/\s?#\[]++(?P<post>/\d++(?:\.\w++)?)"
    # ffmpeg ends a URL with ': <error>' or a full stop.
    r"(?=[\s'\",;:|<>)\]}?#]|\.(?!\w)|$)"
)

_XC_PROVIDER_HOST = re.compile(
    rf"(?i)(?P<pre>://(?:[^/\s]*@)?)[^/\s@]+(?P<path>{_SUB_PATH}/(?:player_api|get|panel_api)\.php)"
)
_XC_EPG_HOST = re.compile(
    rf"(?i)(?P<pre>://(?:[^/\s]*@)?)[^/\s@]+(?P<path>{_SUB_PATH}/xmltv\.php)"
)

# The same path credentials without scheme://host, as request paths appear in logs.
_BARE_PATH_CREDS = re.compile(
    rf"(?i)(?<!:){_OWN_ROUTE}(?P<pre>/(?:live|movie|series|timeshift)/)"
    r"(?P<user>[^/\s]+)/(?P<pass>[^/\s]+)(?P<post>/)"
)

# userinfo before the host: scheme://user:pass@host (greedy to the last '@').
_URL_USERINFO = re.compile(r"(://)[^/\s:]++:(?:[^/\s@]*+@)++")
_URL_USER_ONLY = re.compile(r"(://)[^/\s:@\[]++@")

_QUERY_PARAM = re.compile(
    rf"(?i)({_KEY_PREFIX}(?:{_KEY_ALT}))="
    r"((?:Bearer|Basic|Digest|Token)\s+[^&\s\"']+|[^&\s\"']+)"
)

# A bare "user" also names the app's own users in login lines, so it is
# masked only as a query parameter.
_QUERY_USER = re.compile(r"(?i)(?<=[?&])((?:[\w.-]*[._-])?user)=([^&\s\"']+)")

# Every cookie in a header line, not just the first.
_COOKIE_HEADER = re.compile(
    rf"(?i)({_KEY_PREFIX}cookie)(\s*:\s*)([^\s;,]+(?:;\s*[^\s;,]+)*)"
)

_KV_ASSIGN = re.compile(
    rf"(?i)({_KEY_PREFIX}(?:{_KEY_ALT}))\b(\s*[:=]\s*)"
    # A value already masked as this key is left whole, quote and all.
    r"(?!\[\1\])"
    r"((?:Bearer|Basic|Digest|Token)\s+[^\s,;)}&]+|\"[^\"]*\"|'[^']*'|[^\s,;)}&]+)"
)

# Credentials and url-labelled values in a quoted dict repr; the quote before
# the colon defeats _KV_ASSIGN and _URL_LABEL.
_DICT_KV = re.compile(
    rf"(?ix)(?P<q>['\"])(?P<key>{_KEY_PREFIX}(?:{_KEY_ALT}|url))(?P=q)(?P<sep>\s*:\s*)"
    r"(?P<vq>['\"])(?P<val>(?:\\.|(?!(?P=vq))[^\\])*)(?P=vq)"
)

# A bare provider base URL has no shape; the url label is the only signal.
_URL_LABEL = re.compile(
    rf"(?i)({_KEY_PREFIX}url)(\s*[:=]\s*)([^\s,;)}}&]+)"
)

# The shape requests exception text uses: HTTPSConnectionPool(host='...', port=443).
_HOST_KV = re.compile(r"(?i)\bhost=(['\"])[^'\"\s]+\1")

# The same sensitive keys with a LIST value ('token': ['x']), the dict(QueryDict) shape.
_DICT_LIST_KV = re.compile(
    rf"(?ix)(?P<q>['\"])(?P<key>{_KEY_PREFIX}(?:{_KEY_ALT}))(?P=q)(?P<sep>\s*:\s*)"
    r"\[(?P<body>(?:[^\[\]]|\[[^\[\]]*\])*)\]"
)

# Bare hostnames in DNS/timeout failure prose, which no key or URL shape catches.
_RESOLVE_PROSE = re.compile(
    r"(?i)\b((?:failed to resolve|could not resolve hostname)\s+')[^'\s]+(')"
)
_TIMEOUT_PROSE = re.compile(r"(?i)\b(connection to )[^\s']+( timed out)")

# Every pattern needs a scheme, a stream path, host=, a credential-shaped key
# name or the failure prose, so one scan gates the battery: a shape missing
# here never reaches it.
_TRIGGER = re.compile(
    rf"(?i)://|/(?:live|movie|series|timeshift)/|\bhost="
    rf"|{_KEY_PREFIX}(?:{_KEY_ALT}|url)\b|[?&](?:[\w.-]*[._-])?user="
    rf"|resolve|timed out"
)

# Every _TRIGGER alternative holds one of these once lowercased.
_TRIGGER_WORDS = (
    "://", "/live/", "/movie/", "/series/", "/timeshift/", "host=", "resolve",
    "timed out", "user", "pass", "secret", "sig", "auth", "bearer", "apikey",
    "api_key", "api-key", "token", "cookie", "credential", "url",
)
# The non-ASCII letters IGNORECASE matches to ASCII ones, which lower() misses.
_FOLD = {0x130: "i", 0x131: "i", 0x17F: "s", 0x212A: "k"}


# A bracketed value or host means the URL battery already masked it, or the
# host is an IPv6 literal; masked userinfo alone still leaves the host to hide.
_MASKED_URL = re.compile(r"\[|[^\s/]*://(?:[^/\s@]*+@)?+\[")


def _redact_dict_kv(match):
    q, vq = match.group("q"), match.group("vq")
    key = match.group("key")
    if key.lower().endswith("url") and _MASKED_URL.match(match.group("val")):
        return match.group(0)
    return f"{q}{key}{q}{match.group('sep')}{vq}[{key.lower()}]{vq}"


def _redact_dict_list_kv(match):
    # A '[' in the body means it was already masked; leave it (idempotency).
    if "[" in match.group("body"):
        return match.group(0)
    q = match.group("q")
    key = match.group("key")
    return f"{q}{key}{q}{match.group('sep')}[{q}[{key.lower()}]{q}]"


def _redact_url_label(match):
    if _MASKED_URL.match(match.group(3)):
        return match.group(0)
    return f"{match.group(1)}{match.group(2)}[{match.group(1).lower()}]"


def _redact_url_path_creds(match):
    return (
        f"://[provider_host]{match.group('sub')}{match.group('type')}"
        f"[username]/[password]{match.group('post')}"
    )


def _redact_path_creds(match):
    return f"{match.group('pre')}[username]/[password]{match.group('post')}"


def _apply(value):
    """Run the whole battery; redact_text() gates this on the trigger scan."""
    result = _URL_USERINFO.sub(r"\1[username]:[password]@", value)
    result = _URL_USER_ONLY.sub(r"\1[username]@", result)
    result = _URL_PATH_CREDS.sub(_redact_url_path_creds, result)
    result = _URL_PLAIN_CREDS.sub(
        r"\g<pre>[provider_host]/[username]/[password]\g<post>", result
    )
    result = _BARE_PATH_CREDS.sub(_redact_path_creds, result)
    result = _XC_PROVIDER_HOST.sub(r"\g<pre>[provider_host]\g<path>", result)
    result = _XC_EPG_HOST.sub(r"\g<pre>[epg_host]\g<path>", result)
    result = _COOKIE_HEADER.sub(
        lambda m: f"{m.group(1)}{m.group(2)}[{m.group(1).lower()}]", result
    )
    result = _QUERY_PARAM.sub(
        lambda m: f"{m.group(1)}=[{m.group(1).lower()}]", result
    )
    result = _QUERY_USER.sub(
        lambda m: f"{m.group(1)}=[{m.group(1).lower()}]", result
    )
    result = _DICT_KV.sub(_redact_dict_kv, result)
    result = _KV_ASSIGN.sub(
        lambda m: f"{m.group(1)}{m.group(2)}[{m.group(1).lower()}]", result
    )
    result = _DICT_LIST_KV.sub(_redact_dict_list_kv, result)
    result = _URL_LABEL.sub(_redact_url_label, result)
    result = _HOST_KV.sub(lambda m: f"host={m.group(1)}[host]{m.group(1)}", result)
    result = _RESOLVE_PROSE.sub(r"\1[host]\2", result)
    result = _TIMEOUT_PROSE.sub(r"\1[host]\2", result)
    return result


def redact_text(value):
    """Mask credential patterns anywhere in *value*; non-strings pass through.

    Idempotent: every substitution rewrites its match into a bracketed token
    that the same pattern maps back onto itself, so masking an already-masked
    line is a no-op.
    """
    if not isinstance(value, str) or not value:
        return value
    # Cheapest first: a line with none of the trigger words cannot match.
    lowered = (value if value.isascii() else value.translate(_FOLD)).lower()
    if not any(word in lowered for word in _TRIGGER_WORDS):
        return value
    if not _TRIGGER.search(value):
        return value
    return _apply(value)
