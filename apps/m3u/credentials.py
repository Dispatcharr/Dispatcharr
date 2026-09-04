"""
Resolve per-profile XC credentials and build playback URLs.

Live, VOD, and catchup all go through get_transformed_credentials() so a single
search/replace on the profile yields one login. When patterns are configured but
do not match or cannot be parsed, callers receive (None, None, None).
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Optional, Tuple

import regex

logger = logging.getLogger(__name__)

# Bounds catastrophic backtracking on user-authored profile patterns.
CREDENTIAL_TRANSFORM_REGEX_TIMEOUT = 0.1

TransformedCredentials = Tuple[Optional[str], Optional[str], Optional[str]]


def _js_replace_to_python(replace_pattern: str) -> str:
    """Convert JS-style $<name> / $1 backreferences to Python regex form."""
    safe = regex.sub(r"\$<([^>]+)>", r"\\g<\1>", replace_pattern)
    return regex.sub(r"\$(\d+)", r"\\\1", safe)


def get_transformed_credentials(account, profile=None) -> TransformedCredentials:
    """
    Resolve server URL and login for an M3U account profile (XC).

    When *profile* has search_pattern and replace_pattern, they are applied to a
    synthetic live URL and the resulting username/password are extracted. Default
    identity patterns (``^(.*)$`` / ``$1``) keep base credentials.

    Returns:
        (server_url, username, password) on success.
        (None, None, None) when patterns are set but the transform fails, or when
        the account is missing base URL/credentials.
    """
    if profile is None:
        try:
            from apps.m3u.models import M3UAccountProfile

            profile = M3UAccountProfile.objects.filter(
                m3u_account=account,
                is_active=True,
            ).first()
            if profile:
                logger.debug(
                    "Using primary profile '%s' for URL transformation",
                    profile.name,
                )
            else:
                logger.debug(
                    "No active profiles found for account %s, using base credentials",
                    account.name,
                )
        except Exception as exc:
            logger.warning(
                "Could not get primary profile for account %s: %s",
                account.name,
                exc,
            )
            profile = None

    from core.xtream_codes import normalize_server_url

    base_url = normalize_server_url(account.server_url)
    base_username = account.username
    base_password = account.password

    if not (base_url and base_username and base_password):
        logger.warning(
            "Missing credentials for account %s; cannot resolve profile login",
            getattr(account, "name", account.pk),
        )
        return None, None, None

    clean_server_url = base_url.rstrip("/")
    # Synthetic XC live URL used only to apply search/replace and extract login.
    complete_url = f"{clean_server_url}/live/{base_username}/{base_password}/1234.ts"
    logger.debug("Built complete URL for credential transform: %s", complete_url)

    has_patterns = bool(
        profile and profile.search_pattern and profile.replace_pattern
    )
    if not has_patterns:
        return base_url, base_username, base_password

    profile_label = getattr(profile, "name", None) or getattr(profile, "pk", "unknown")

    try:
        safe_replace_pattern = _js_replace_to_python(profile.replace_pattern)
        transformed_complete_url, match_count = regex.subn(
            profile.search_pattern,
            safe_replace_pattern,
            complete_url,
            timeout=CREDENTIAL_TRANSFORM_REGEX_TIMEOUT,
        )
    except TimeoutError:
        logger.error(
            "Profile '%s' search_pattern timed out during credential transform",
            profile_label,
        )
        return None, None, None
    except Exception as exc:
        logger.error(
            "Error transforming credentials for profile '%s': %s",
            profile_label,
            exc,
        )
        return None, None, None

    if match_count == 0:
        logger.warning(
            "Profile '%s' search_pattern did not match (pattern=%r)",
            profile_label,
            profile.search_pattern,
        )
        return None, None, None

    logger.info(
        "Transformed complete URL: %s -> %s",
        complete_url,
        transformed_complete_url,
    )

    parsed_url = urllib.parse.urlparse(transformed_complete_url)
    path_parts = [part for part in parsed_url.path.split("/") if part]

    if len(path_parts) < 4 or path_parts[-1] != "1234.ts":
        logger.warning(
            "Could not extract credentials from transformed URL for profile '%s': %s",
            profile_label,
            transformed_complete_url,
        )
        return None, None, None

    # .../{live}/{username}/{password}/1234.ts (negative indices ignore server sub-paths)
    transformed_username = path_parts[-3]
    transformed_password = path_parts[-2]
    base_path_parts = path_parts[:-4]
    base_path = ("/" + "/".join(base_path_parts)) if base_path_parts else ""
    transformed_url = f"{parsed_url.scheme}://{parsed_url.netloc}{base_path}"

    logger.debug(
        "Extracted transformed credentials for profile '%s': server=%s user=%s",
        profile_label,
        transformed_url,
        transformed_username,
    )
    return transformed_url, transformed_username, transformed_password


def build_xc_playback_url(
    server_url: str,
    username: str,
    password: str,
    *,
    content_path: str,
    stream_id: str,
    extension: str,
) -> str:
    """
    Build an XC-style playback URL from already-resolved credentials.

    content_path is one of: live, movie, series (timeshift builds its own paths).
    """
    base = server_url.rstrip("/")
    return f"{base}/{content_path}/{username}/{password}/{stream_id}.{extension}"
