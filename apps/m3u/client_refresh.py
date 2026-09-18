"""Coalesced Live TV refresh requests triggered by XC clients."""

import hashlib
import logging
import time
import uuid
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import User
from apps.channels.models import Channel
from core.utils import is_task_lock_held, log_system_event
from dispatcharr.utils import get_client_ip

from .models import M3UAccount


logger = logging.getLogger(__name__)

XC_LIVE_REFRESH_USER_PROPERTY = "xc_live_refresh_on_request"
XC_LIVE_REFRESH_USER_INTERVAL_PROPERTY = (
    "xc_live_refresh_request_interval_minutes"
)
XC_LIVE_REFRESH_WAIT_PROPERTY = "xc_live_refresh_wait_for_completion"
XC_LIVE_REFRESH_WAIT_TIMEOUT_PROPERTY = "xc_live_refresh_wait_timeout_seconds"
DEFAULT_USER_REQUEST_INTERVAL_MINUTES = 55
DEFAULT_PROVIDER_MIN_AGE_MINUTES = 55
DEFAULT_CLIENT_WAIT_TIMEOUT_SECONDS = 15
MAX_CLIENT_WAIT_TIMEOUT_SECONDS = 60
MAX_REFRESH_INTERVAL_MINUTES = 7 * 24 * 60
CLIENT_REFRESH_QUEUE_TTL_SECONDS = 15 * 60
CLIENT_REQUEST_EVENT_TTL_SECONDS = 60


def _visible_live_accounts(user):
    """Return active XC accounts contributing Live channels visible to *user*."""
    channels = Channel.objects.filter(
        hidden_from_output=False,
        user_level__lte=user.user_level,
    )

    if user.user_level < User.UserLevel.ADMIN:
        if (user.custom_properties or {}).get("hide_adult_content", False):
            channels = channels.filter(is_adult=False)

        profiles = user.channel_profiles.all()
        if profiles.exists():
            channels = channels.filter(
                channelprofilemembership__enabled=True,
                channelprofilemembership__channel_profile__in=profiles,
            )

    return M3UAccount.objects.filter(
        is_active=True,
        account_type=M3UAccount.Types.XC,
        streams__channels__in=channels,
    ).distinct()


def _bounded_minutes(value, default):
    try:
        if isinstance(value, bool):
            raise ValueError
        return max(0, min(MAX_REFRESH_INTERVAL_MINUTES, int(value)))
    except (TypeError, ValueError):
        return default


def _bounded_wait_seconds(value):
    try:
        if isinstance(value, bool):
            raise ValueError
        return max(1, min(MAX_CLIENT_WAIT_TIMEOUT_SECONDS, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_CLIENT_WAIT_TIMEOUT_SECONDS


def get_xc_live_refresh_wait_timeout(user):
    """Return the opt-in same-response wait timeout, or None for background mode."""
    properties = getattr(user, "custom_properties", None) or {}
    if (
        properties.get(XC_LIVE_REFRESH_USER_PROPERTY) is not True
        or properties.get(XC_LIVE_REFRESH_WAIT_PROPERTY) is not True
    ):
        return None
    return _bounded_wait_seconds(
        properties.get(
            XC_LIVE_REFRESH_WAIT_TIMEOUT_PROPERTY,
            DEFAULT_CLIENT_WAIT_TIMEOUT_SECONDS,
        )
    )


def _provider_min_age_minutes(account):
    return _bounded_minutes(
        getattr(
            account,
            "xc_live_refresh_min_age_minutes",
            DEFAULT_PROVIDER_MIN_AGE_MINUTES,
        ),
        DEFAULT_PROVIDER_MIN_AGE_MINUTES,
    )


def _recently_refreshed(account, now, minimum_age_minutes):
    if minimum_age_minutes == 0:
        return False
    last_success = account.updated_at
    if not last_success:
        return False
    return now - last_success < timedelta(minutes=minimum_age_minutes)


def _user_request_interval_minutes(properties):
    return _bounded_minutes(
        properties.get(
            XC_LIVE_REFRESH_USER_INTERVAL_PROPERTY,
            DEFAULT_USER_REQUEST_INTERVAL_MINUTES,
        ),
        DEFAULT_USER_REQUEST_INTERVAL_MINUTES,
    )


def _user_request_allowed(user, account_id, interval_minutes):
    if interval_minutes == 0:
        return True, None, None

    key = f"xc_live_refresh_user_request:{user.id}:{account_id}"
    try:
        allowed = cache.add(
            key,
            True,
            timeout=interval_minutes * 60,
        )
    except Exception:
        logger.warning(
            "Could not coordinate XC Live refresh requests for user %s",
            user.id,
            exc_info=True,
        )
        return False, "request coordinator unavailable", None

    if not allowed:
        return False, f"user cooldown active ({interval_minutes}m)", None
    return True, None, key


def _release_user_request_reservation(key):
    if not key:
        return
    try:
        cache.delete(key)
    except Exception:
        logger.warning(
            "Could not release unused XC Live user request reservation",
            exc_info=True,
        )


def _log_catalog_request(request, user, outcome):
    """Log at most one readable XC catalog event per client and minute."""
    client_ip = get_client_ip(request) or "unknown"
    user_agent = request.META.get("HTTP_USER_AGENT", "unknown")
    client_key = hashlib.sha256(
        f"{client_ip}:{user_agent}".encode("utf-8")
    ).hexdigest()[:16]
    event_key = f"xc_live_catalog_event:{user.id}:{client_key}"

    try:
        should_log = cache.add(
            event_key,
            True,
            timeout=CLIENT_REQUEST_EVENT_TTL_SECONDS,
        )
    except Exception:
        logger.warning("Could not deduplicate XC Live catalog event", exc_info=True)
        should_log = True

    if not should_log:
        return

    log_system_event(
        "xc_live_catalog_request",
        user=user.username,
        client_ip=client_ip,
        user_agent=user_agent,
        refresh=outcome,
    )


def handle_xc_live_catalog_request(
    request,
    user,
    *,
    wait_for_completion=False,
    wait_timeout_seconds=None,
):
    """Optionally queue one Live-only provider refresh after serving XC data.

    Every XC Live catalog request is observable in System Events, but only an
    administrator-enabled user can request provider refreshes. Freshness and
    queue keys are per provider, so several users cannot create duplicate jobs.
    """
    properties = user.custom_properties or {}
    if properties.get(XC_LIVE_REFRESH_USER_PROPERTY) is not True:
        _log_catalog_request(request, user, "disabled for user")
        return {"queued": [], "skipped": ["disabled for user"]}

    now = timezone.now()
    user_interval_minutes = _user_request_interval_minutes(properties)
    queued = []
    completion_keys = []
    skipped = []

    try:
        accounts = list(_visible_live_accounts(user))
    except Exception:
        logger.warning(
            "Could not resolve XC Live accounts visible to user %s",
            user.id,
            exc_info=True,
        )
        _log_catalog_request(request, user, "account lookup failed")
        return {"queued": [], "skipped": ["account lookup failed"]}

    for account in accounts:
        minimum_age_minutes = _provider_min_age_minutes(account)
        if _recently_refreshed(account, now, minimum_age_minutes):
            skipped.append(
                f"{account.name}: refreshed within {minimum_age_minutes}m"
            )
            continue

        user_allowed, user_skip_reason, user_reservation_key = (
            _user_request_allowed(
                user,
                account.id,
                user_interval_minutes,
            )
        )
        if not user_allowed:
            skipped.append(f"{account.name}: {user_skip_reason}")
            continue

        if account.status in {
            M3UAccount.Status.FETCHING,
            M3UAccount.Status.PARSING,
        } or is_task_lock_held("refresh_single_m3u_account", account.id):
            _release_user_request_reservation(user_reservation_key)
            skipped.append(f"{account.name}: already running")
            continue

        queue_key = f"xc_live_refresh_request:{account.id}"
        try:
            reserved = cache.add(
                queue_key,
                str(user.id),
                timeout=CLIENT_REFRESH_QUEUE_TTL_SECONDS,
            )
        except Exception:
            logger.warning(
                "Could not reserve XC-triggered Live refresh for account %s",
                account.id,
                exc_info=True,
            )
            _release_user_request_reservation(user_reservation_key)
            skipped.append(f"{account.name}: coordinator unavailable")
            continue

        if not reserved:
            _release_user_request_reservation(user_reservation_key)
            skipped.append(f"{account.name}: already queued")
            continue

        try:
            from .tasks import refresh_single_m3u_account

            completion_key = None
            if wait_for_completion:
                completion_key = (
                    f"xc_live_refresh_complete:{uuid.uuid4().hex}:{account.id}"
                )
            task_kwargs = {
                "account_id": account.id,
                "include_vod": False,
                "minimum_age_seconds": minimum_age_minutes * 60,
                "skip_if_refreshed_after": now.isoformat(),
                "client_triggered": True,
            }
            if completion_key:
                task_kwargs["client_completion_key"] = completion_key
            refresh_single_m3u_account.apply_async(
                kwargs=task_kwargs
            )
            queued.append(account.name)
            if completion_key:
                completion_keys.append(completion_key)
        except Exception:
            try:
                cache.delete(queue_key)
            except Exception:
                pass
            _release_user_request_reservation(user_reservation_key)
            logger.warning(
                "Could not queue XC-triggered Live refresh for account %s",
                account.id,
                exc_info=True,
            )
            skipped.append(f"{account.name}: queue failed")

    if queued:
        if wait_for_completion:
            timeout = _bounded_wait_seconds(wait_timeout_seconds)
            outcome = (
                f"queued Live-only refresh; waiting up to {timeout}s: "
                f"{', '.join(queued)}"
            )
        else:
            outcome = f"queued Live-only refresh: {', '.join(queued)}"
    elif skipped:
        outcome = "; ".join(skipped)
    else:
        outcome = "no visible XC Live providers"
    _log_catalog_request(request, user, outcome)
    return {
        "queued": queued,
        "skipped": skipped,
        "completion_keys": completion_keys,
    }


def wait_for_xc_live_refresh(completion_keys, timeout_seconds):
    """Wait briefly for opt-in client refresh jobs without polling the database."""
    pending = set(completion_keys or [])
    if not pending:
        return {"completed": True, "pending": 0}

    deadline = time.monotonic() + _bounded_wait_seconds(timeout_seconds)
    try:
        while pending:
            completed = cache.get_many(pending)
            pending.difference_update(completed.keys())
            if not pending:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.25, remaining))
    except Exception:
        logger.warning(
            "Could not wait for XC Live provider refresh completion",
            exc_info=True,
        )
    finally:
        completed_keys = set(completion_keys or []) - pending
        if completed_keys:
            try:
                cache.delete_many(completed_keys)
            except Exception:
                pass

    return {"completed": not pending, "pending": len(pending)}
