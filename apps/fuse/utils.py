import json
import logging
from typing import Mapping, Optional

from core.models import CoreSettings, FUSE_SETTINGS_KEY

from .serializers import FUSE_SETTINGS_DEFAULTS

logger = logging.getLogger(__name__)

FUSE_CLIENT_USER_AGENT_MARKER = "dispatcharr-fuse/"
FUSE_CLIENT_HEADER_KEY = "HTTP_X_DISPATCHARR_CLIENT"
FUSE_CLIENT_HEADER_VALUE = "fuse"


def is_fuse_client_request(
    client_user_agent: Optional[str] = None,
    request_meta: Optional[Mapping[str, str]] = None,
) -> bool:
    """Detect if a request originated from the Dispatcharr FUSE client."""
    user_agent = (client_user_agent or "").lower()
    if FUSE_CLIENT_USER_AGENT_MARKER in user_agent:
        return True

    if request_meta:
        header_value = str(request_meta.get(FUSE_CLIENT_HEADER_KEY, "")).strip().lower()
        if header_value == FUSE_CLIENT_HEADER_VALUE:
            return True

    return False


def get_fuse_settings() -> dict:
    """Load FUSE settings and merge them over serializer defaults."""
    raw_value = {}
    try:
        raw_value = CoreSettings.objects.values_list("value", flat=True).get(
            key=FUSE_SETTINGS_KEY
        )
    except CoreSettings.DoesNotExist:
        raw_value = {}
    except Exception as exc:
        logger.warning("Error loading FUSE settings: %s", exc)
        raw_value = {}

    if isinstance(raw_value, str):
        try:
            raw_value = json.loads(raw_value)
        except json.JSONDecodeError:
            raw_value = {}

    if not isinstance(raw_value, dict):
        raw_value = {}

    merged = FUSE_SETTINGS_DEFAULTS.copy()
    merged.update(raw_value)
    return merged


def get_fuse_stats_grace_seconds() -> int:
    """Get the configured grace period for recently active FUSE stats rows."""
    configured = get_fuse_settings().get(
        "fuse_stats_grace_seconds",
        FUSE_SETTINGS_DEFAULTS["fuse_stats_grace_seconds"],
    )
    try:
        return max(0, int(configured))
    except (TypeError, ValueError):
        return FUSE_SETTINGS_DEFAULTS["fuse_stats_grace_seconds"]
