"""Durable post-import work, independent of Lists and output Profiles."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import VODMetadataState

logger = logging.getLogger(__name__)


def publish_pending_enrichment():
    from .tasks import dispatch_pending_library_enrichment

    try:
        dispatch_pending_library_enrichment.apply_async(countdown=5)
    except Exception:  # noqa: BLE001 -- preserve the outbox across broker failures
        # The database outbox survives broker downtime and worker restarts.
        logger.warning("Could not publish pending Library enrichment")


@transaction.atomic
def mark_library_refresh(account_id, *, running):
    state, _ = VODMetadataState.objects.get_or_create(pk=1)
    state = VODMetadataState.objects.select_for_update().get(pk=state.pk)
    ids = set(state.refreshing_accounts)
    if running:
        ids.add(account_id)
    else:
        ids.discard(account_id)
    state.refreshing_accounts = sorted(ids)
    state.save(update_fields=["refreshing_accounts", "updated_at"])
    if not running and state.pending_enrichment:
        transaction.on_commit(publish_pending_enrichment)


@transaction.atomic
def request_automatic_enrichment(refs):
    state, _ = VODMetadataState.objects.get_or_create(pk=1)
    state = VODMetadataState.objects.select_for_update().get(pk=state.pk)
    state.pending_enrichment = [
        list(ref)
        for ref in dict.fromkeys(
            tuple(ref) for ref in [*state.pending_enrichment, *refs]
        )
    ]
    state.save(update_fields=["pending_enrichment", "updated_at"])
    if state.pending_enrichment:
        transaction.on_commit(publish_pending_enrichment)


@transaction.atomic
def dispatch_pending_enrichment():
    from core.utils import is_task_lock_held

    from .library import library_settings, queue_library_job

    state = VODMetadataState.objects.select_for_update().filter(pk=1).first()
    if not state:
        return True
    if state.status in {"queued", "running"}:
        if state.job_heartbeat < timezone.now() - timedelta(hours=6):
            state.status = "failed"
            state.error = (
                "The Library worker stopped responding. Resume the job to continue."
            )
            state.save(update_fields=["status", "error", "updated_at"])
            return True
        return False
    if not state.pending_enrichment:
        return True
    if state.status in {"failed", "cancelled"}:
        return True
    settings = library_settings()
    if not settings["auto_enrich"] or not settings["token_configured"]:
        return True
    try:
        active = [
            pk
            for pk in state.refreshing_accounts
            if is_task_lock_held("refresh_single_m3u_account", pk)
        ]
    except Exception:  # noqa: BLE001 -- defer rather than race an unchecked import
        logger.warning(
            "Could not check active VOD imports; Library enrichment remains pending"
        )
        return False
    state.refreshing_accounts = active
    state.save(update_fields=["refreshing_accounts", "updated_at"])
    if active or state.status in {"queued", "running"}:
        return False
    queue_library_job("enrich", state.pending_enrichment, automatic=True)
    state.pending_enrichment = []
    state.save(update_fields=["pending_enrichment", "updated_at"])
    return True
