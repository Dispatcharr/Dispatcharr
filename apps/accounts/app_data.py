"""Limits and validation for per-app user storage (User.app_data)."""

import json
import re

# App-supplied namespace: 8 to 64 chars, reverse-DNS style is fine.
APP_DATA_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
APP_DATA_KEY_MIN_LEN = 8
APP_DATA_KEY_MAX_LEN = 64

APP_DATA_MAX_VALUE_BYTES = 32 * 1024  # 32 KiB per app
APP_DATA_MAX_TOTAL_BYTES = 128 * 1024  # 128 KiB per user
APP_DATA_MAX_APPS = 25
APP_DATA_MAX_DEPTH = 8
# Allow a little whitespace beyond the compact stored size before we refuse to parse.
APP_DATA_MAX_CONTENT_LENGTH = APP_DATA_MAX_VALUE_BYTES + 1024

# Stable machine-readable identifiers for app-data API errors.
CODE_KEY_INVALID = "key_invalid"
CODE_VALUE_NOT_OBJECT = "value_not_object"
CODE_VALUE_HAS_NUL = "value_has_nul"
CODE_VALUE_TOO_DEEP = "value_too_deep"
CODE_VALUE_NOT_SERIALIZABLE = "value_not_serializable"
CODE_VALUE_TOO_LARGE = "value_too_large"
CODE_TOTAL_TOO_LARGE = "total_too_large"
CODE_MAX_APPS = "max_apps"
CODE_BODY_TOO_LARGE = "body_too_large"
CODE_INVALID_CONTENT_LENGTH = "invalid_content_length"
CODE_KEY_NOT_FOUND = "key_not_found"
CODE_FORBIDDEN = "forbidden"
CODE_USER_NOT_FOUND = "user_not_found"


class AppDataError(Exception):
    """Validation or size failure for app_data requests."""

    def __init__(self, detail, status_code=400, code="app_data_error"):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code

    def as_response_data(self):
        return {"detail": self.detail, "code": self.code}


def app_data_error_body(detail, code):
    """Build the standard ``{detail, code}`` error payload."""
    return {"detail": detail, "code": code}


def app_data_limits_payload():
    return {
        "max_value_bytes": APP_DATA_MAX_VALUE_BYTES,
        "max_total_bytes": APP_DATA_MAX_TOTAL_BYTES,
        "max_apps": APP_DATA_MAX_APPS,
        "max_depth": APP_DATA_MAX_DEPTH,
        "key_min_length": APP_DATA_KEY_MIN_LEN,
        "key_max_length": APP_DATA_KEY_MAX_LEN,
    }


def validate_app_data_key(key):
    if not isinstance(key, str) or not APP_DATA_KEY_RE.fullmatch(key):
        raise AppDataError(
            "App data key must be 8 to 64 characters and match "
            "[A-Za-z0-9][A-Za-z0-9._-]* (must start with a letter or digit).",
            code=CODE_KEY_INVALID,
        )


def json_byte_size(value):
    """Compact UTF-8 JSON size used for per-app and total caps.

    ``allow_nan=False`` matters: a literal like ``1e999`` parses to infinity,
    which would otherwise serialize as ``Infinity`` and be rejected by Postgres
    jsonb at save time. Lone surrogates fail the UTF-8 encode for the same reason.
    """
    try:
        return len(
            json.dumps(
                value,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise AppDataError(
            "App data value contains non-serializable data",
            code=CODE_VALUE_NOT_SERIALIZABLE,
        ) from exc


def _check_structure(value):
    """Reject NUL characters and over-deep nesting.

    Iterative on purpose: a recursive walk could exhaust the Python stack on
    hostile input. Depth counts object/array levels, so ``{"a": 1}`` is 1.
    Stops as soon as the depth cap is exceeded.
    """
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, str):
            if "\x00" in node:
                raise AppDataError(
                    "App data value must not contain null characters",
                    code=CODE_VALUE_HAS_NUL,
                )
        elif isinstance(node, dict):
            depth += 1
            if depth > APP_DATA_MAX_DEPTH:
                raise AppDataError(
                    f"App data value exceeds maximum nesting depth of {APP_DATA_MAX_DEPTH}",
                    code=CODE_VALUE_TOO_DEEP,
                )
            for child_key, child in node.items():
                if isinstance(child_key, str) and "\x00" in child_key:
                    raise AppDataError(
                        "App data value must not contain null characters",
                        code=CODE_VALUE_HAS_NUL,
                    )
                stack.append((child, depth))
        elif isinstance(node, list):
            depth += 1
            if depth > APP_DATA_MAX_DEPTH:
                raise AppDataError(
                    f"App data value exceeds maximum nesting depth of {APP_DATA_MAX_DEPTH}",
                    code=CODE_VALUE_TOO_DEEP,
                )
            stack.extend((child, depth) for child in node)


def validate_app_data_value(value):
    """Return compact byte size of a valid app value, or raise AppDataError."""
    if not isinstance(value, dict):
        raise AppDataError(
            "App data value must be a JSON object",
            code=CODE_VALUE_NOT_OBJECT,
        )
    _check_structure(value)
    size = json_byte_size(value)
    if size > APP_DATA_MAX_VALUE_BYTES:
        raise AppDataError(
            f"App data value exceeds maximum size of {APP_DATA_MAX_VALUE_BYTES} bytes",
            status_code=413,
            code=CODE_VALUE_TOO_LARGE,
        )
    return size


def summarize_app_data(app_data):
    """Build the list response: limits, total size, and per-app key/bytes only."""
    apps = []
    total_bytes = 0
    for key, value in (app_data or {}).items():
        size = json_byte_size(value)
        apps.append({"key": key, "bytes": size})
        total_bytes += size
    apps.sort(key=lambda item: item["key"])
    return {
        "limits": app_data_limits_payload(),
        "total_bytes": total_bytes,
        "apps": apps,
    }


def check_put_fits(app_data, key, new_size):
    """Ensure replacing or inserting key keeps the user under total and app caps."""
    current = app_data or {}
    total = sum(json_byte_size(v) for v in current.values())
    if key in current:
        total -= json_byte_size(current[key])
    else:
        if len(current) >= APP_DATA_MAX_APPS:
            raise AppDataError(
                f"User already has the maximum of {APP_DATA_MAX_APPS} apps stored",
                status_code=409,
                code=CODE_MAX_APPS,
            )
    if total + new_size > APP_DATA_MAX_TOTAL_BYTES:
        raise AppDataError(
            f"App data would exceed maximum total size of {APP_DATA_MAX_TOTAL_BYTES} bytes",
            status_code=413,
            code=CODE_TOTAL_TOO_LARGE,
        )
