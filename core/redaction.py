"""Mask IPTV provider credentials in user-visible output.

redact_text() (re-exported from dispatcharr.log_redaction, which the
Django-free log collector also imports) sweeps free-form strings,
redact_url() reduces a single URL to scheme://host/..., and
redact_mapping() recurses structured payloads. RedactingFormatter applies
redact_text() to every rendered log line. Masked values are replaced with
a bracketed name of what was removed ([password], [xc_password],
[provider_host]).
"""

import re

from dispatcharr.display_timezone import DisplayTimezoneFormatter
from dispatcharr.log_redaction import redact_text

# Keys whose values are masked in a mapping, matched as whole delimiter-bounded words.
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:passphrase|password|passwd|pass|secret|token|api_?key|apikey|"
    r"authorization|auth_?token|bearer|creds|credential|url)s?(?:$|_)"
    r"|(?:^|_)(?:signature|sig)s?$",
    re.IGNORECASE,
)
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


_ANY_URL = re.compile(r"(?i)https?://[^\s'\"]+")


def redact_provider_url(url, token="[provider_host]"):
    """Mask the host of a URL known to belong to a provider; the rest is swept as text."""
    if not isinstance(url, str) or "://" not in url:
        return redact_text(url)
    scheme, rest = url.split("://", 1)
    authority, sep, tail = rest.partition("/")
    if "@" in authority:
        authority = authority.rsplit("@", 1)[0] + "@" + token
    else:
        authority = token
    return redact_text(f"{scheme}://{authority}{sep}{tail}")


def redact_provider_text(text, token="[provider_host]"):
    """Sweep text whose URLs are all provider material; unshaped URLs reduce to the token host."""
    result = redact_text(text)
    if not isinstance(result, str):
        return result
    # A '[' means the pattern battery already masked it; reduce only unshaped URLs.
    return _ANY_URL.sub(
        lambda m: m.group(0)
        if "[" in m.group(0)
        else f"{m.group(0).split('://', 1)[0]}://{token}/...",
        result,
    )


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
    the system display timezone. Kept alongside the collector's own
    masking: modular mode runs no collector, so this is the only masking
    those deployments get.
    """

    def format(self, record):
        return redact_text(super().format(record))
