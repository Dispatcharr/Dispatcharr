"""Rate-limited Live-only refresh requests from XC clients."""

import logging
import time
import uuid
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import User
from apps.channels.models import Channel
from core.utils import is_task_lock_held

from .models import M3UAccount


logger = logging.getLogger(__name__)
DEFAULT_INTERVAL_MINUTES = 30
MAX_INTERVAL_MINUTES = 10080
QUEUE_RESERVATION_SECONDS = 15 * 60
FAILURE_RETRY_SECONDS = 60
CLIENT_REFRESH_WAIT_SECONDS = 15


def _bounded_minutes(value, default=DEFAULT_INTERVAL_MINUTES):
    try:
        if isinstance(value, bool):
            raise ValueError
        return max(0, min(MAX_INTERVAL_MINUTES, int(value)))
    except (TypeError, ValueError):
        return default


def _visible_live_accounts(user):
    """Only refresh XC providers that contribute channels this user may see."""
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


def _release_reservation(key, token=None):
    if not key:
        return
    try:
        if token is None or cache.get(key) == token:
            cache.delete(key)
    except Exception:
        logger.warning("Could not release XC Live refresh reservation", exc_info=True)


def release_client_refresh_reservation(account_id, token):
    """Release only the queue reservation owned by this task."""
    if token:
        _release_reservation(f"xc_live_refresh_request:{account_id}", token)


def record_client_refresh_failure(account_id):
    """Back off failed attempts once per provider, not once per user."""
    try:
        cache.set(
            f"xc_live_refresh_failure:{account_id}",
            timezone.now().timestamp(),
            timeout=FAILURE_RETRY_SECONDS,
        )
    except Exception:
        logger.warning("Could not record XC Live refresh failure", exc_info=True)


def record_client_refresh_outcome(account_id):
    try:
        status = M3UAccount.objects.filter(pk=account_id).values_list("status", flat=True).first()
        if status == M3UAccount.Status.ERROR:
            record_client_refresh_failure(account_id)
        elif status == M3UAccount.Status.SUCCESS:
            cache.delete(f"xc_live_refresh_failure:{account_id}")
    except Exception:
        logger.warning("Could not record XC Live refresh outcome", exc_info=True)


def handle_xc_live_catalog_request(user):
    """Queue eligible Live-only refreshes and track their completion."""
    completion_keys = []
    properties = user.custom_properties or {}
    if properties.get("xc_live_refresh_on_request") is not True:
        return completion_keys

    try:
        accounts = list(_visible_live_accounts(user))
    except Exception:
        logger.warning("Could not resolve XC Live accounts for user %s", user.id, exc_info=True)
        return completion_keys

    now = timezone.now()
    for account in accounts:
        min_age = _bounded_minutes(account.xc_live_refresh_min_age_minutes)
        if min_age and account.updated_at and now - account.updated_at < timedelta(minutes=min_age):
            continue
        if account.status in (M3UAccount.Status.FETCHING, M3UAccount.Status.PARSING):
            continue

        queue_key = f"xc_live_refresh_request:{account.id}"
        token = uuid.uuid4().hex
        try:
            if is_task_lock_held("refresh_single_m3u_account", account.id):
                continue
            failed_at = cache.get(f"xc_live_refresh_failure:{account.id}")
            if failed_at is not None and (
                not account.updated_at or account.updated_at.timestamp() <= failed_at
            ):
                continue
            if not cache.add(queue_key, token, timeout=QUEUE_RESERVATION_SECONDS):
                continue
        except Exception:
            logger.warning("Could not coordinate XC Live refresh for account %s", account.id, exc_info=True)
            continue

        try:
            from .tasks import refresh_single_m3u_account

            task_kwargs = {
                "account_id": account.id,
                "include_vod": False,
                "minimum_age_seconds": min_age * 60,
                "skip_if_refreshed_after": now.isoformat(),
                "client_request_token": token,
            }
            completion_key = f"xc_live_refresh_complete:{uuid.uuid4().hex}:{account.id}"
            task_kwargs["client_completion_key"] = completion_key
            refresh_single_m3u_account.apply_async(kwargs=task_kwargs)
            completion_keys.append(completion_key)
            logger.info("Queued XC Live-only refresh for account %s from user %s", account.id, user.id)
        except Exception:
            _release_reservation(queue_key, token)
            record_client_refresh_failure(account.id)
            logger.warning("Could not queue XC Live refresh for account %s", account.id, exc_info=True)

    return completion_keys


def mark_client_refresh_complete(completion_key, outcome):
    if not completion_key:
        return
    try:
        cache.set(completion_key, outcome, timeout=QUEUE_RESERVATION_SECONDS)
    except Exception:
        logger.warning("Could not mark XC Live refresh complete", exc_info=True)


def wait_for_xc_live_refresh(completion_keys):
    """Wait up to 15 seconds total using completion markers, not database polls."""
    pending = set(completion_keys or [])
    if not pending:
        return {"completed": True, "pending": 0}

    deadline = time.monotonic() + CLIENT_REFRESH_WAIT_SECONDS
    try:
        while pending:
            pending.difference_update(cache.get_many(pending).keys())
            if not pending:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.25, remaining))
    except Exception:
        logger.warning("Could not wait for XC Live refresh completion", exc_info=True)
    finally:
        completed = set(completion_keys or []) - pending
        if completed:
            try:
                cache.delete_many(completed)
            except Exception:
                logger.warning("Could not clear XC Live completion markers", exc_info=True)

    return {"completed": not pending, "pending": len(pending)}
