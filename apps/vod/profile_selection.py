"""Prepared VOD profile selections used by XC output and profile previews."""

import hashlib
import json
import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .catalog_cache import selection_catalog_generation
from .models import (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    VODAccessPolicy,
    VODMovieProfileSelection,
    VODPolicyCategory,
    VODSeriesProfileSelection,
)
from .metadata import normalize_source_metadata
from .policies import (
    _profile_category_enabled,
    _vertical_resolution,
    allowed_category_query,
    content_rules_use_canonical_metadata,
    policy_category_map,
    relation_edition,
    relation_metadata,
    select_relation_ids_for_policy,
)
from .utils import get_vod_source_name, policy_output_name

logger = logging.getLogger(__name__)
BUILD_CHUNK_SIZE = 5000
PROGRESS_SCAN_INTERVAL = 5000
BUILD_STAGE_COUNT = 5
PROFILE_REBUILD_ENQUEUE_KEY = "vod_profile_selection:rebuild-all-enqueued"
# Profile builds can legitimately take longer than the old one-minute debounce
# window.  Keep one global catalog worker authoritative for the whole run so a
# later invalidation cannot publish a duplicate task which races the first one.
PROFILE_REBUILD_LOCK_TIMEOUT = 4 * 60 * 60
SINGLE_PROFILE_TASK_NAME = "apps.vod.tasks.rebuild_vod_profile_selection"
BATCH_PROFILE_TASK_NAME = "apps.vod.tasks.rebuild_all_vod_profile_selections"
PROGRESS_CONTEXT_KEYS = (
    "task_id",
    "task_name",
    "queue",
    "queued_at",
    "batch",
    "batch_position",
    "batch_total",
    "trigger_reason",
    "original_trigger_reason",
    "attempt",
    "restart_reason",
)


class CatalogChangedDuringBuild(RuntimeError):
    pass


class ProfileBuildAlreadyRunning(RuntimeError):
    pass


class ProfileBuildNotPending(RuntimeError):
    pass


def _progress_payload(phase, percent, **details):
    return {
        "phase": phase,
        "percent": max(0, min(int(percent), 100)),
        "updated_at": timezone.now().isoformat(),
        **{key: value for key, value in details.items() if value is not None},
    }


def _progress_context(progress):
    progress = progress if isinstance(progress, dict) else {}
    return {
        key: progress[key]
        for key in PROGRESS_CONTEXT_KEYS
        if progress.get(key) not in (None, "")
    }


def _publish_profile_progress(
    policy_id,
    selection_status,
    selection_progress,
    *,
    active_selection_generation="",
    selection_completed_at=None,
):
    """Push one durable profile heartbeat through the normal UI update bus."""
    from core.utils import send_websocket_update

    send_websocket_update(
        "updates",
        "update",
        {
            "type": "vod_profile_selection",
            "profile_id": policy_id,
            "selection_status": selection_status,
            "selection_progress": selection_progress or {},
            "active_selection_generation": active_selection_generation or "",
            "selection_completed_at": (
                selection_completed_at.isoformat()
                if hasattr(selection_completed_at, "isoformat")
                else selection_completed_at or None
            ),
        },
        collect_garbage=False,
    )


def _set_pending_profiles_progress(
    queryset,
    phase,
    percent,
    *,
    include_batch_position=False,
    **details,
):
    """Update queued profiles without discarding their task provenance."""
    rows = list(
        queryset.filter(
            selection_status=VODAccessPolicy.SelectionStatus.PENDING
        )
        .order_by("id")
        .values("id", "selection_progress")
    )
    total = len(rows)
    updated = 0
    for position, row in enumerate(rows, start=1):
        context = _progress_context(row["selection_progress"])
        clean_details = {
            key: value
            for key, value in details.items()
            if value not in (None, "")
        }
        trigger_reason = clean_details.pop("trigger_reason", None)
        context.update(clean_details)
        if trigger_reason:
            # Debounced invalidations may revisit a profile that is already
            # pending. Keep its original cause instead of replacing it with a
            # later, less specific catalog change.
            context.setdefault("trigger_reason", trigger_reason)
        if include_batch_position:
            context.update(
                batch=True,
                batch_position=position,
                batch_total=total,
            )
        updated += VODAccessPolicy.objects.filter(
            pk=row["id"],
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
        ).update(
            selection_progress=_progress_payload(
                phase,
                percent,
                **context,
            )
        )
    return updated


def mark_profile_selections_outdated(
    *,
    trigger_reason="VOD metadata changed",
    policy_ids=None,
):
    """Keep serving completed catalogs but require an explicit rebuild.

    Manual metadata edits must be visible to administrators without silently
    launching a potentially expensive all-profile catalog build. Provider VOD
    imports and profile saves continue to use the normal automatic enqueue
    paths.
    """
    queryset = VODAccessPolicy.objects.filter(
        is_active=True,
        active_selection_generation__gt="",
        selection_status__in=(
            VODAccessPolicy.SelectionStatus.PENDING,
            VODAccessPolicy.SelectionStatus.BUILDING,
            VODAccessPolicy.SelectionStatus.READY,
            VODAccessPolicy.SelectionStatus.OUTDATED,
        ),
    )
    if policy_ids is not None:
        queryset = queryset.filter(pk__in=policy_ids)
    profile_ids = list(queryset.values_list("id", flat=True))
    if not profile_ids:
        return 0
    progress = _progress_payload(
        "Catalog rebuild required",
        0,
        manual_required=True,
        trigger_reason=trigger_reason,
    )
    updated = VODAccessPolicy.objects.filter(pk__in=profile_ids).update(
        selection_status=VODAccessPolicy.SelectionStatus.OUTDATED,
        selection_error="",
        selection_progress=progress,
    )

    def publish():
        for policy_id in profile_ids:
            _publish_profile_progress(
                policy_id,
                VODAccessPolicy.SelectionStatus.OUTDATED,
                progress,
            )

    transaction.on_commit(publish)
    return updated


def profile_ids_using_canonical_content(*, movie_ids=(), series_ids=()):
    """Return prepared profiles whose client output embeds canonical data.

    A canonical metadata edit cannot affect profiles that exclude the title.
    Provider-only variant profiles are likewise independent unless their name
    formatter explicitly references the canonical title.
    """
    movie_ids = {int(value) for value in movie_ids if value is not None}
    series_ids = {int(value) for value in series_ids if value is not None}
    canonical_template_title = (
        Q(policy__naming_mode=VODAccessPolicy.NamingMode.TEMPLATE)
        & ~Q(
            policy__canonical_title_source=(
                VODAccessPolicy.CanonicalTitleSource.PROVIDER
            )
        )
        & (
            Q(policy__name_template__contains="{title}")
            | Q(policy__name_template__contains="{canonical}")
        )
    )
    canonical_output = (
        Q(policy__metadata_source=VODAccessPolicy.MetadataSource.CANONICAL)
        | Q(policy__naming_mode=VODAccessPolicy.NamingMode.CANONICAL)
        | Q(
            policy__export_mode=VODAccessPolicy.ExportMode.COMPACT,
            policy__naming_mode=VODAccessPolicy.NamingMode.MODE_DEFAULT,
        )
        | canonical_template_title
    )
    policy_ids = set()
    for policy_id, constraints in VODAccessPolicy.objects.filter(
        is_active=True
    ).values_list("id", "hard_constraints"):
        rules = (constraints or {}).get("source_rules") or []
        if content_rules_use_canonical_metadata(rules):
            # A canonical metadata change can make a previously excluded title
            # eligible, so prepared selection rows alone cannot identify every
            # affected metadata-filtering profile.
            policy_ids.add(policy_id)
    if movie_ids:
        policy_ids.update(
            VODMovieProfileSelection.objects.filter(
                movie_id__in=movie_ids,
                generation=F("policy__active_selection_generation"),
                policy__is_active=True,
            )
            .filter(canonical_output)
            .values_list("policy_id", flat=True)
            .distinct()
        )
    if series_ids:
        policy_ids.update(
            VODSeriesProfileSelection.objects.filter(
                series_id__in=series_ids,
                generation=F("policy__active_selection_generation"),
                policy__is_active=True,
            )
            .filter(canonical_output)
            .values_list("policy_id", flat=True)
            .distinct()
        )
    return sorted(policy_ids)


def profile_ids_using_source_categories(category_keys=()):
    """Return prepared profiles that can consume any changed source category."""
    keys = {
        (int(account_id), int(category_id))
        for account_id, category_id in category_keys
        if account_id is not None and category_id is not None
    }
    if not keys:
        return []

    account_ids = {account_id for account_id, _category_id in keys}
    category_ids = {category_id for _account_id, category_id in keys}
    targets = [
        relation
        for relation in M3UVODCategoryRelation.objects.filter(
            enabled=True,
            m3u_account__is_active=True,
            m3u_account_id__in=account_ids,
            category_id__in=category_ids,
        ).select_related("category")
        if (relation.m3u_account_id, relation.category_id) in keys
    ]
    if not targets:
        return []

    policies = list(
        VODAccessPolicy.objects.filter(
            is_active=True,
            active_selection_generation__gt="",
        ).only("id", "hard_constraints")
    )
    if not policies:
        return []

    explicit_by_policy = {}
    for policy_id, relation_id, enabled in VODPolicyCategory.objects.filter(
        policy_id__in=[policy.id for policy in policies]
    ).values_list("policy_id", "category_relation_id", "enabled"):
        explicit_by_policy.setdefault(policy_id, {})[relation_id] = enabled

    affected = []
    for policy in policies:
        explicit = explicit_by_policy.get(policy.id, {})
        constraints = policy.hard_constraints or {}
        dynamic_configured = "category_import_rules" in constraints
        if not dynamic_configured:
            if not explicit or any(
                explicit.get(target.id) is True for target in targets
            ):
                affected.append(policy.id)
            continue

        rules = list(constraints.get("category_import_rules") or [])
        for target in targets:
            decision = explicit.get(target.id)
            if decision is None:
                decision = _profile_category_enabled(
                    {
                        "account_id": target.m3u_account_id,
                        "category_name": target.category.name,
                        "category_type": target.category.category_type,
                    },
                    rules,
                )
            if decision:
                affected.append(policy.id)
                break
    return sorted(affected)


def _set_profile_progress(policy_id, phase, percent, **details):
    """Persist coarse build progress without firing policy invalidation signals."""
    # Progress is read and written by background workers while the API polls
    # the same row. Serialize writers so a delayed heartbeat cannot win the
    # read/update race and make one build appear to run backwards.
    progress = None
    with transaction.atomic():
        row = (
            VODAccessPolicy.objects.select_for_update()
            .filter(pk=policy_id)
            .values("selection_status", "selection_progress")
            .first()
        )
        if not row or (
            row["selection_status"]
            != VODAccessPolicy.SelectionStatus.BUILDING
        ):
            return False
        current = row["selection_progress"] or {}
        build_generation = details.get("build_generation")
        active_build_generation = current.get("build_generation")
        if (
            build_generation
            and active_build_generation
            and active_build_generation != build_generation
        ):
            # A watchdog or a newer delivery has superseded this worker. Do not
            # let a late heartbeat replace the authoritative generation token.
            return False
        if build_generation and active_build_generation == build_generation:
            current_stage = int(current.get("stage_index") or 0)
            next_stage = int(details.get("stage_index") or 0)
            current_processed = int(current.get("processed") or 0)
            next_processed = int(details.get("processed") or 0)
            current_percent = int(current.get("percent") or 0)
            next_percent = max(0, min(int(percent), 100))
            if (
                next_percent < current_percent
                or next_stage < current_stage
                or (
                    next_stage == current_stage
                    and current.get("phase") == phase
                    and next_processed < current_processed
                )
            ):
                # A delayed duplicate heartbeat must never make one build
                # appear to run backwards. A genuine Celery retry uses a new
                # generation and is surfaced as a separate attempt instead.
                return False
        persistent = _progress_context(current)
        progress = _progress_payload(
            phase, percent, **persistent, **details
        )
        updated = VODAccessPolicy.objects.filter(
            pk=policy_id,
            selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
        ).update(selection_progress=progress)
    if updated:
        _publish_profile_progress(
            policy_id,
            VODAccessPolicy.SelectionStatus.BUILDING,
            progress,
        )
    return bool(updated)


def profile_selection_signature(policy):
    """Return a stable fingerprint of every profile field used for selection.

    ``updated_at`` protects ordinary profile edits, but category rules live in
    their own table and therefore need to be part of the build snapshot too.
    Persisting this signature with the active generation also lets the API
    distinguish the currently served catalog from newly saved settings.
    """
    prefetched = getattr(policy, "_prefetched_objects_cache", {}).get(
        "vodpolicycategory_set"
    )
    if prefetched is None:
        category_rules = list(
            policy.vodpolicycategory_set.order_by(
                "category_relation_id", "id"
            ).values(
                "category_relation_id",
                "enabled",
                "priority",
            )
        )
    else:
        category_rules = [
            {
                "category_relation_id": rule.category_relation_id,
                "enabled": rule.enabled,
                "priority": rule.priority,
            }
            for rule in sorted(
                prefetched,
                key=lambda rule: (rule.category_relation_id, rule.id),
            )
        ]
    payload = {
        "export_mode": policy.export_mode,
        "hard_constraints": policy.hard_constraints or {},
        "ranking": policy.ranking or [],
        "provider_order": policy.provider_order or [],
        "edition_rules": policy.edition_rules or [],
        "naming_mode": policy.naming_mode,
        "name_template": policy.name_template,
        "metadata_source": policy.metadata_source,
        "category_rules": category_rules,
    }
    # Title source now controls the generic {title} token in both modes.
    payload["output_format_schema"] = 4
    payload["canonical_title_source"] = policy.canonical_title_source
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_selection_counts(policy, counts):
    """Refuse to activate an internally inconsistent Compact generation."""
    if policy.export_mode != VODAccessPolicy.ExportMode.COMPACT:
        return
    for content_type in ("movies", "series"):
        content_counts = counts.get(content_type) or {}
        output_entries = int(content_counts.get("output_entries") or 0)
        canonical_titles = int(content_counts.get("canonical_titles") or 0)
        if output_entries < canonical_titles:
            raise RuntimeError(
                f"Compact {content_type} build produced {output_entries} "
                f"output entries for {canonical_titles} titles"
            )


def enqueue_profile_selection_rebuild(
    policy_id,
    *,
    trigger_reason="VOD output profile settings were saved",
):
    """Mark a profile stale and enqueue its build after the transaction."""
    updated = VODAccessPolicy.objects.filter(
        pk=policy_id,
        is_active=True,
    ).exclude(
        selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
    ).update(
        selection_status=VODAccessPolicy.SelectionStatus.PENDING,
        selection_started_at=timezone.now(),
        selection_error="",
        selection_progress=_progress_payload(
            "Publishing background task",
            0,
            queue="celery",
            task_name=SINGLE_PROFILE_TASK_NAME,
            batch=False,
            trigger_reason=trigger_reason,
        ),
    )
    if not updated:
        return False

    def enqueue():
        from .tasks import rebuild_vod_profile_selection

        try:
            result = rebuild_vod_profile_selection.delay(policy_id)
            logger.info(
                "Queued VOD profile selection task %s for profile %s (%s)",
                result.id,
                policy_id,
                trigger_reason,
            )
            queued_at = timezone.now().isoformat()
            VODAccessPolicy.objects.filter(
                pk=policy_id,
                selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            ).update(
                selection_progress=_progress_payload(
                    "Waiting in Celery queue",
                    0,
                    queue="celery",
                    task_id=result.id,
                    task_name=SINGLE_PROFILE_TASK_NAME,
                    queued_at=queued_at,
                    batch=False,
                    trigger_reason=trigger_reason,
                )
            )
        except Exception as exc:
            logger.exception(
                "Could not enqueue VOD profile selection %s", policy_id
            )
            VODAccessPolicy.objects.filter(
                pk=policy_id,
                selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            ).update(
                selection_status=VODAccessPolicy.SelectionStatus.FAILED,
                selection_error=str(exc)[:2000],
                selection_progress=_progress_payload(
                    "Could not publish background task", 100, queue="celery"
                ),
                selection_completed_at=timezone.now(),
            )

    transaction.on_commit(enqueue)
    return True


def enqueue_all_profile_selection_rebuilds(
    *,
    pending_only=False,
    trigger_reason=None,
):
    """Enqueue one debounced rebuild task for active profiles.

    Normal catalog invalidations mark every ready profile pending. Incremental
    metadata updates use ``pending_only`` so an already-stranded pending
    profile can be republished without invalidating profiles that were updated
    synchronously.
    """
    if trigger_reason is None and not pending_only:
        trigger_reason = "The VOD source catalog or source metadata changed"
    queued_progress = _progress_payload(
        "Waiting for worker",
        0,
        queue="celery",
        task_name=BATCH_PROFILE_TASK_NAME,
        batch=True,
        trigger_reason=trigger_reason,
    )
    newly_pending = 0
    if not pending_only:
        newly_pending = VODAccessPolicy.objects.filter(is_active=True).exclude(
            selection_status__in=(
                VODAccessPolicy.SelectionStatus.PENDING,
                VODAccessPolicy.SelectionStatus.BUILDING,
            ),
        ).update(
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            selection_started_at=timezone.now(),
            selection_error="",
            selection_progress=queued_progress,
        )
    # Repeated catalog invalidations are common when one UI operation updates
    # several related source rows.  A pending worker reads the latest catalog
    # generation when it starts, while an active build detects a changed
    # generation and retries itself.  Resetting either state here would erase
    # its task/progress metadata and could publish duplicate recovery work.
    pending_exists = VODAccessPolicy.objects.filter(
        is_active=True,
        selection_status=VODAccessPolicy.SelectionStatus.PENDING,
    ).exists()
    if not newly_pending and not pending_exists:
        return False

    def enqueue():
        from django.core.cache import cache
        from .tasks import rebuild_all_vod_profile_selections

        try:
            acquired = cache.add(
                PROFILE_REBUILD_ENQUEUE_KEY,
                "1",
                timeout=PROFILE_REBUILD_LOCK_TIMEOUT,
            )
        except Exception:
            acquired = True
        if not acquired:
            try:
                owner = cache.get(PROFILE_REBUILD_ENQUEUE_KEY)
            except Exception:
                owner = None
            _set_pending_profiles_progress(
                VODAccessPolicy.objects.filter(is_active=True),
                "Waiting for the active VOD profile catalog batch",
                0,
                include_batch_position=True,
                queue="celery",
                task_id=(
                    str(owner) if owner not in (None, "", "1") else None
                ),
                task_name=BATCH_PROFILE_TASK_NAME,
                batch=True,
                trigger_reason=trigger_reason,
            )
            return
        try:
            result = rebuild_all_vod_profile_selections.delay()
            logger.info(
                "Queued VOD profile catalog batch %s (%s)",
                result.id,
                trigger_reason,
            )
            try:
                cache.set(
                    PROFILE_REBUILD_ENQUEUE_KEY,
                    result.id,
                    timeout=PROFILE_REBUILD_LOCK_TIMEOUT,
                )
            except Exception:
                pass
            _set_pending_profiles_progress(
                VODAccessPolicy.objects.filter(
                    is_active=True,
                ),
                "Waiting in Celery queue",
                0,
                include_batch_position=True,
                queue="celery",
                task_id=result.id,
                task_name=BATCH_PROFILE_TASK_NAME,
                queued_at=timezone.now().isoformat(),
                batch=True,
                trigger_reason=trigger_reason,
            )
        except Exception as exc:
            try:
                cache.delete(PROFILE_REBUILD_ENQUEUE_KEY)
            except Exception:
                pass
            logger.exception("Could not enqueue all VOD profile selections")
            VODAccessPolicy.objects.filter(
                is_active=True,
                selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            ).update(
                selection_status=VODAccessPolicy.SelectionStatus.FAILED,
                selection_error=str(exc)[:2000],
                selection_progress=_progress_payload(
                    "Could not publish background task", 100, queue="celery"
                ),
                selection_completed_at=timezone.now(),
            )

    transaction.on_commit(enqueue)
    return True


def _selection_rows_for_canonical_ids(
    policy,
    generation,
    relation_model,
    selection_model,
    canonical_field,
    canonical_ids,
):
    """Prepare selected rows for a small set of canonical titles."""
    if not canonical_ids:
        return []
    from core.models import CoreSettings

    category_mapping = policy_category_map(policy)
    canonical_languages = CoreSettings.get_tmdb_languages()
    candidates = (
        relation_model.objects.filter(
            m3u_account__is_active=True,
            **{f"{canonical_field}__in": canonical_ids},
        )
        .filter(allowed_category_query(policy))
        .select_related(
            "m3u_account",
            "category",
            canonical_field.removesuffix("_id"),
        )
        .order_by("pk")
    )
    output_category_ids = {}
    selected_ids = select_relation_ids_for_policy(
        candidates.iterator(chunk_size=500),
        policy,
        canonical_field,
        output_category_ids=output_category_ids,
    )
    relations = relation_model.objects.filter(pk__in=selected_ids).select_related(
        "m3u_account",
        "category",
        canonical_field.removesuffix("_id"),
    )
    rows = []
    for relation in relations:
        metadata = relation_metadata(
            relation,
            category_mapping.get(
                (relation.m3u_account_id, relation.category_id)
            ),
        )
        rows.append(
            selection_model(
                policy=policy,
                generation=generation,
                relation=relation,
                category_id=output_category_ids.get(
                    getattr(relation, canonical_field), relation.category_id
                ),
                **{canonical_field: getattr(relation, canonical_field)},
                **_metadata_columns(metadata, relation),
                **_edition_columns(
                    policy,
                    relation,
                    getattr(relation, canonical_field.removesuffix("_id")),
                    metadata,
                    category_mapping,
                    canonical_languages,
                ),
            )
        )
    return rows


def _adjusted_selection_counts(
    counts,
    type_key,
    old_queryset,
    new_rows,
    canonical_field,
):
    """Apply counters for only the replaced title rows as a small delta."""
    counts = dict(counts or {})
    type_counts = dict(counts.get(type_key) or {})
    old_output = old_queryset.count()
    old_canonical = old_queryset.values(canonical_field).distinct().count()
    old_unknown = old_queryset.filter(
        audio_languages=[],
        subtitle_languages=[],
        resolution_height=0,
    ).count()
    new_output = len(new_rows)
    new_canonical = len(
        {getattr(row, canonical_field) for row in new_rows}
    )
    new_unknown = sum(
        not (
            row.audio_languages
            or row.subtitle_languages
            or row.resolution_height
        )
        for row in new_rows
    )
    for key, old_value, new_value in (
        ("output_entries", old_output, new_output),
        ("canonical_titles", old_canonical, new_canonical),
        ("unknown_metadata", old_unknown, new_unknown),
    ):
        type_counts[key] = max(
            int(type_counts.get(key) or 0) - old_value + new_value,
            0,
        )
    counts[type_key] = type_counts
    counts.update(
        output_entries=sum(
            (counts.get(key) or {}).get("output_entries", 0)
            for key in ("movies", "series")
        ),
        canonical_titles=sum(
            (counts.get(key) or {}).get("canonical_titles", 0)
            for key in ("movies", "series")
        ),
        unknown_metadata=sum(
            (counts.get(key) or {}).get("unknown_metadata", 0)
            for key in ("movies", "series")
        ),
    )
    return counts


def refresh_profile_selections_for_content(*, movie_ids=(), series_ids=()):
    """Synchronously re-evaluate only manually edited canonical titles.

    A single metadata correction normally affects one movie or series and its
    handful of competing provider relations. Rebuilding every prepared VOD
    profile would rescan the complete provider catalog, so replace just those
    prepared rows and advance ready profiles to the new catalog generation.
    Imports and large bulk edits continue to use the background full rebuild;
    small manual bulk edits may reuse this bounded path.
    """
    movie_ids = {int(value) for value in movie_ids if value is not None}
    series_ids = {int(value) for value in series_ids if value is not None}
    if not movie_ids and not series_ids:
        return {"profiles_updated": 0, "queued_full_rebuild": False}

    from .catalog_cache import bump_catalog_generation

    bump_catalog_generation()
    source_generation = str(selection_catalog_generation())
    updated_profiles = 0
    try:
        with transaction.atomic():
            policies = list(
                VODAccessPolicy.objects.select_for_update().filter(
                    is_active=True,
                    selection_status=VODAccessPolicy.SelectionStatus.READY,
                ).exclude(active_selection_generation="")
            )
            for policy in policies:
                generation = policy.active_selection_generation
                movie_rows = _selection_rows_for_canonical_ids(
                    policy,
                    generation,
                    M3UMovieRelation,
                    VODMovieProfileSelection,
                    "movie_id",
                    movie_ids,
                )
                series_rows = _selection_rows_for_canonical_ids(
                    policy,
                    generation,
                    M3USeriesRelation,
                    VODSeriesProfileSelection,
                    "series_id",
                    series_ids,
                )
                if movie_ids:
                    old_rows = VODMovieProfileSelection.objects.filter(
                        policy=policy,
                        generation=generation,
                        movie_id__in=movie_ids,
                    )
                    policy.selection_counts = _adjusted_selection_counts(
                        policy.selection_counts,
                        "movies",
                        old_rows,
                        movie_rows,
                        "movie_id",
                    )
                    old_rows.delete()
                    VODMovieProfileSelection.objects.bulk_create(
                        movie_rows, batch_size=500
                    )
                if series_ids:
                    old_rows = VODSeriesProfileSelection.objects.filter(
                        policy=policy,
                        generation=generation,
                        series_id__in=series_ids,
                    )
                    policy.selection_counts = _adjusted_selection_counts(
                        policy.selection_counts,
                        "series",
                        old_rows,
                        series_rows,
                        "series_id",
                    )
                    old_rows.delete()
                    VODSeriesProfileSelection.objects.bulk_create(
                        series_rows, batch_size=500
                    )
                policy.selection_catalog_generation = source_generation
                policy.selection_status = VODAccessPolicy.SelectionStatus.READY
                policy.selection_error = ""
                policy.selection_completed_at = timezone.now()
                policy.selection_progress = _progress_payload(
                    "Ready after metadata update", 100, incremental=True
                )
                # Avoid the VODAccessPolicy post-save invalidation signal. This
                # updates prepared bookkeeping, not the profile definition.
                VODAccessPolicy.objects.filter(pk=policy.pk).update(
                    selection_counts=policy.selection_counts,
                    selection_catalog_generation=source_generation,
                    selection_status=VODAccessPolicy.SelectionStatus.READY,
                    selection_error="",
                    selection_completed_at=policy.selection_completed_at,
                    selection_progress=policy.selection_progress,
                )
                updated_profiles += 1
    except Exception:
        logger.exception(
            "Incremental VOD profile refresh failed for movies=%s series=%s",
            sorted(movie_ids),
            sorted(series_ids),
        )
        enqueue_all_profile_selection_rebuilds()
        return {"profiles_updated": 0, "queued_full_rebuild": True}

    # Profiles already pending/building will consume the new generation in
    # their active task. This also repairs any unpublished pending state.
    queued_full_rebuild = enqueue_all_profile_selection_rebuilds(
        pending_only=True
    )
    return {
        "profiles_updated": updated_profiles,
        "queued_full_rebuild": queued_full_rebuild,
    }


def _metadata_list(metadata, *fields):
    for field in fields:
        value = metadata.get(field)
        if isinstance(value, (list, tuple, set)):
            return list(value)
        if value:
            return [str(value)]
    return []


def _metadata_columns(metadata, relation):
    metadata = normalize_source_metadata(metadata)
    audio_languages = _metadata_list(
        metadata,
        "audio_languages",
        "languages",
    )
    subtitle_languages = _metadata_list(metadata, "subtitle_languages")
    container_extension = str(
        metadata.get("container_extension")
        or getattr(relation, "container_extension", "")
        or ""
    ).lower()
    return {
        "effective_metadata": metadata,
        "audio_languages": audio_languages,
        "subtitle_languages": subtitle_languages,
        "resolution_height": _vertical_resolution(metadata),
        "container_extension": container_extension,
    }


def _edition_columns(
    policy,
    relation,
    content,
    metadata,
    category_mapping,
    canonical_languages=None,
):
    if policy.export_mode == VODAccessPolicy.ExportMode.VARIANTS:
        edition = {
            "key": "default",
            "name": "",
            "suffix": "",
        }
        return {
            "edition_key": edition["key"],
            "edition_name": edition["name"],
            "edition_suffix": edition["suffix"],
            "output_name": policy_output_name(
                content,
                relation,
                policy,
                edition=edition,
                metadata=metadata,
                canonical_languages=canonical_languages,
            )[:500],
        }
    edition = relation_edition(
        relation,
        policy,
        category_mapping=category_mapping,
        metadata=metadata,
    )
    return {
        "edition_key": edition["key"],
        "edition_name": edition["name"],
        "edition_suffix": edition["suffix"],
        "output_name": policy_output_name(
            content,
            relation,
            policy,
            edition=edition,
            metadata=metadata,
            canonical_languages=canonical_languages,
        )[:500],
    }


def _build_type(
    policy,
    generation,
    relation_model,
    selection_model,
    canonical,
    *,
    scan_progress_range,
    store_progress_range,
    content_label,
    build_generation,
    scan_stage_index,
    store_stage_index,
):
    from core.models import CoreSettings

    category_mapping = policy_category_map(policy)
    canonical_languages = CoreSettings.get_tmdb_languages()
    candidates = (
        relation_model.objects.filter(
            m3u_account__is_active=True,
        )
        .filter(allowed_category_query(policy))
        .select_related(
            "m3u_account",
            "category",
            canonical.removesuffix("_id"),
        )
        .order_by("pk")
    )
    candidate_total = candidates.count()
    scan_start, scan_end = scan_progress_range
    scan_started_at = timezone.now().isoformat()

    def report_scan(processed):
        ratio = processed / candidate_total if candidate_total else 1
        _set_profile_progress(
            policy.pk,
            f"Selecting {content_label} sources",
            scan_start + ((scan_end - scan_start) * ratio),
            processed=processed,
            total=candidate_total,
            content_type=content_label,
            item_type="sources",
            stage_index=scan_stage_index,
            stage_count=BUILD_STAGE_COUNT,
            stage_percent=round(ratio * 100),
            phase_started_at=scan_started_at,
            target_export_mode=policy.export_mode,
            build_generation=build_generation,
        )

    report_scan(0)
    stats = {}
    output_category_ids = {}
    selected_ids = select_relation_ids_for_policy(
        candidates.iterator(chunk_size=BUILD_CHUNK_SIZE),
        policy,
        canonical,
        stats=stats,
        progress_callback=report_scan,
        progress_interval=PROGRESS_SCAN_INTERVAL,
        output_category_ids=output_category_ids,
    )
    report_scan(candidate_total)
    canonical_ids = set()
    unknown_metadata = 0
    created = 0

    store_start, store_end = store_progress_range
    selected_total = len(selected_ids)
    store_started_at = timezone.now().isoformat()
    _set_profile_progress(
        policy.pk,
        f"Building {content_label} output",
        store_start,
        processed=0,
        total=selected_total,
        content_type=content_label,
        item_type="output entries",
        stage_index=store_stage_index,
        stage_count=BUILD_STAGE_COUNT,
        stage_percent=0,
        phase_started_at=store_started_at,
        target_export_mode=policy.export_mode,
        build_generation=build_generation,
    )
    for offset in range(0, selected_total, BUILD_CHUNK_SIZE):
        relation_chunk = list(
            relation_model.objects.filter(
                pk__in=selected_ids[offset : offset + BUILD_CHUNK_SIZE]
            ).select_related(
                "m3u_account",
                "category",
                canonical.removesuffix("_id"),
            )
        )
        rows = []
        for relation in relation_chunk:
            metadata = relation_metadata(
                relation,
                category_mapping.get(
                    (relation.m3u_account_id, relation.category_id)
                ),
            )
            metadata_columns = _metadata_columns(metadata, relation)
            if not (
                metadata_columns["audio_languages"]
                or metadata_columns["subtitle_languages"]
                or metadata_columns["resolution_height"]
            ):
                unknown_metadata += 1
            canonical_id = getattr(relation, canonical)
            canonical_ids.add(canonical_id)
            values = {
                "policy": policy,
                "generation": generation,
                "relation": relation,
                "category_id": output_category_ids.get(
                    canonical_id, relation.category_id
                ),
                canonical: canonical_id,
                **metadata_columns,
                **_edition_columns(
                    policy,
                    relation,
                    getattr(relation, canonical.removesuffix("_id")),
                    metadata,
                    category_mapping,
                    canonical_languages,
                ),
            }
            rows.append(selection_model(**values))
        selection_model.objects.bulk_create(rows, batch_size=1000)
        created += len(rows)
        processed = min(offset + BUILD_CHUNK_SIZE, selected_total)
        ratio = processed / selected_total if selected_total else 1
        _set_profile_progress(
            policy.pk,
            f"Building {content_label} output",
            store_start + ((store_end - store_start) * ratio),
            processed=processed,
            total=selected_total,
            content_type=content_label,
            item_type="output entries",
            stage_index=store_stage_index,
            stage_count=BUILD_STAGE_COUNT,
            stage_percent=round(ratio * 100),
            phase_started_at=store_started_at,
            target_export_mode=policy.export_mode,
            build_generation=build_generation,
        )

    if not selected_total:
        _set_profile_progress(
            policy.pk,
            f"Building {content_label} output",
            store_end,
            processed=0,
            total=0,
            content_type=content_label,
            item_type="output entries",
            stage_index=store_stage_index,
            stage_count=BUILD_STAGE_COUNT,
            stage_percent=100,
            phase_started_at=store_started_at,
            target_export_mode=policy.export_mode,
            build_generation=build_generation,
        )

    return {
        "candidate_sources": stats.get("candidates", 0),
        "eligible_sources": stats.get("eligible", 0),
        "output_entries": created,
        "canonical_titles": len(canonical_ids),
        "unknown_metadata": unknown_metadata,
    }


def build_vod_profile_selection(policy_id, *, require_pending=False):
    """Build a new generation and switch to it only when fully complete."""
    generation = uuid.uuid4().hex
    source_generation = str(selection_catalog_generation())
    now = timezone.now()
    stale_build = now - timedelta(hours=1)
    candidates = VODAccessPolicy.objects.filter(
        pk=policy_id,
        is_active=True,
    )
    if require_pending:
        # Celery deliveries are at-least-once. A delayed duplicate must not
        # rebuild a profile which another delivery has already made Ready.
        candidates = candidates.filter(
            Q(selection_status=VODAccessPolicy.SelectionStatus.PENDING)
            | Q(
                selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
                selection_started_at__isnull=True,
            )
            | Q(
                selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
                selection_started_at__lt=stale_build,
            )
        )
    else:
        candidates = candidates.filter(
            ~Q(selection_status=VODAccessPolicy.SelectionStatus.BUILDING)
            | Q(selection_started_at__isnull=True)
            | Q(selection_started_at__lt=stale_build)
        )
    previous_progress = (
        candidates.values_list("selection_progress", flat=True).first() or {}
    )
    task_details = _progress_context(previous_progress)
    acquired = candidates.update(
        selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
        selection_started_at=now,
        selection_completed_at=None,
        selection_error="",
        selection_progress=_progress_payload(
            "Starting", 1, build_generation=generation, **task_details
        ),
    )
    if not acquired:
        current = VODAccessPolicy.objects.filter(
            pk=policy_id, is_active=True
        ).values("selection_status").first()
        if current and (
            current["selection_status"]
            == VODAccessPolicy.SelectionStatus.BUILDING
        ):
            raise ProfileBuildAlreadyRunning(
                f"VOD profile {policy_id} is already being prepared"
            )
        if current and require_pending:
            raise ProfileBuildNotPending(
                f"VOD profile {policy_id} no longer needs preparation"
            )
        raise VODAccessPolicy.DoesNotExist
    policy = VODAccessPolicy.objects.get(pk=policy_id, is_active=True)
    policy_updated_at = policy.updated_at
    policy_signature = profile_selection_signature(policy)
    _set_profile_progress(
        policy.pk,
        "Starting catalog build",
        1,
        stage_index=0,
        stage_count=BUILD_STAGE_COUNT,
        stage_percent=0,
        phase_started_at=now.isoformat(),
        target_export_mode=policy.export_mode,
        build_generation=generation,
    )

    try:
        movie_counts = _build_type(
            policy,
            generation,
            M3UMovieRelation,
            VODMovieProfileSelection,
            "movie_id",
            scan_progress_range=(2, 36),
            store_progress_range=(36, 50),
            content_label="movies",
            build_generation=generation,
            scan_stage_index=1,
            store_stage_index=2,
        )
        series_counts = _build_type(
            policy,
            generation,
            M3USeriesRelation,
            VODSeriesProfileSelection,
            "series_id",
            scan_progress_range=(50, 84),
            store_progress_range=(84, 98),
            content_label="series",
            build_generation=generation,
            scan_stage_index=3,
            store_stage_index=4,
        )
        activating_started_at = timezone.now().isoformat()
        _set_profile_progress(
            policy.pk,
            "Activating catalog",
            99,
            stage_index=5,
            stage_count=BUILD_STAGE_COUNT,
            stage_percent=0,
            phase_started_at=activating_started_at,
            target_export_mode=policy.export_mode,
            build_generation=generation,
        )
        if str(selection_catalog_generation()) != source_generation:
            raise CatalogChangedDuringBuild(
                "The VOD catalog changed while the profile was being built"
            )

        counts = {
            "movies": movie_counts,
            "series": series_counts,
            "output_entries": (
                movie_counts["output_entries"]
                + series_counts["output_entries"]
            ),
            "canonical_titles": (
                movie_counts["canonical_titles"]
                + series_counts["canonical_titles"]
            ),
            "eligible_sources": (
                movie_counts["eligible_sources"]
                + series_counts["eligible_sources"]
            ),
            "unknown_metadata": (
                movie_counts["unknown_metadata"]
                + series_counts["unknown_metadata"]
            ),
            "export_mode": policy.export_mode,
            "profile_signature": policy_signature,
            "generation": generation,
        }
        _validate_selection_counts(policy, counts)
        with transaction.atomic():
            locked_policy = VODAccessPolicy.objects.select_for_update().get(
                pk=policy.pk
            )
            if str(selection_catalog_generation()) != source_generation:
                raise CatalogChangedDuringBuild(
                    "The VOD catalog changed before profile activation"
                )
            if locked_policy.updated_at != policy_updated_at:
                raise CatalogChangedDuringBuild(
                    "The VOD profile changed while it was being prepared"
                )
            if profile_selection_signature(locked_policy) != policy_signature:
                raise CatalogChangedDuringBuild(
                    "The VOD profile rules changed while it was being prepared"
                )
            active_build_generation = (
                locked_policy.selection_progress or {}
            ).get("build_generation")
            if (
                locked_policy.selection_status
                != VODAccessPolicy.SelectionStatus.BUILDING
                or active_build_generation != generation
            ):
                raise CatalogChangedDuringBuild(
                    "This catalog build was superseded by recovery work"
                )
            completed_at = timezone.now()
            prepared_seconds = max((completed_at - now).total_seconds(), 0)
            counts["prepared_seconds"] = prepared_seconds
            counts["completed_at"] = completed_at.isoformat()
            # QuerySet.update deliberately avoids the catalog-invalidating
            # policy signal: selection bookkeeping does not change policy
            # semantics or source data.
            ready_progress = _progress_payload(
                "Ready",
                100,
                **task_details,
                stage_index=BUILD_STAGE_COUNT,
                stage_count=BUILD_STAGE_COUNT,
                stage_percent=100,
                target_export_mode=policy.export_mode,
                build_generation=generation,
                prepared_seconds=prepared_seconds,
            )
            VODAccessPolicy.objects.filter(pk=policy.pk).update(
                active_selection_generation=generation,
                selection_catalog_generation=source_generation,
                selection_counts=counts,
                selection_status=VODAccessPolicy.SelectionStatus.READY,
                selection_completed_at=completed_at,
                selection_error="",
                selection_progress=ready_progress,
            )
            transaction.on_commit(
                lambda: _publish_profile_progress(
                    policy.pk,
                    VODAccessPolicy.SelectionStatus.READY,
                    ready_progress,
                    active_selection_generation=generation,
                    selection_completed_at=completed_at,
                )
            )
        VODMovieProfileSelection.objects.filter(policy=policy).exclude(
            generation=generation
        ).delete()
        VODSeriesProfileSelection.objects.filter(policy=policy).exclude(
            generation=generation
        ).delete()
        # A client may have requested the previous active generation while
        # this build was running. Publish the newly activated snapshots under
        # a fresh XC cache generation without invalidating this selection.
        from .catalog_cache import bump_catalog_generation

        bump_catalog_generation(invalidate_selections=False)
        return counts
    except CatalogChangedDuringBuild as exc:
        VODMovieProfileSelection.objects.filter(
            policy=policy, generation=generation
        ).delete()
        VODSeriesProfileSelection.objects.filter(
            policy=policy, generation=generation
        ).delete()
        current_state = VODAccessPolicy.objects.filter(pk=policy.pk).values(
            "selection_status", "selection_progress"
        ).first()
        if current_state and (
            current_state["selection_status"]
            == VODAccessPolicy.SelectionStatus.BUILDING
            and (current_state["selection_progress"] or {}).get(
                "build_generation"
            )
            == generation
        ):
            context = _progress_context(current_state["selection_progress"])
            VODAccessPolicy.objects.filter(pk=policy.pk).update(
                selection_status=VODAccessPolicy.SelectionStatus.PENDING,
                selection_error=str(exc),
                selection_progress=_progress_payload(
                    "Catalog changed; restarting",
                    0,
                    **context,
                    stage_index=0,
                    stage_count=BUILD_STAGE_COUNT,
                    stage_percent=0,
                    target_export_mode=policy.export_mode,
                    build_generation=generation,
                    restart_reason=str(exc),
                ),
            )
        raise
    except Exception as exc:
        logger.exception("Failed to build VOD profile selection %s", policy.pk)
        VODMovieProfileSelection.objects.filter(
            policy=policy, generation=generation
        ).delete()
        VODSeriesProfileSelection.objects.filter(
            policy=policy, generation=generation
        ).delete()
        current_state = VODAccessPolicy.objects.filter(pk=policy.pk).values(
            "selection_status", "selection_progress"
        ).first()
        if current_state and (
            current_state["selection_status"]
            == VODAccessPolicy.SelectionStatus.BUILDING
            and (current_state["selection_progress"] or {}).get(
                "build_generation"
            )
            == generation
        ):
            context = _progress_context(current_state["selection_progress"])
            VODAccessPolicy.objects.filter(pk=policy.pk).update(
                selection_status=VODAccessPolicy.SelectionStatus.FAILED,
                selection_error=str(exc)[:2000],
                selection_completed_at=timezone.now(),
                selection_progress=_progress_payload(
                    "Failed",
                    100,
                    **context,
                ),
            )
        raise


def prepared_relation_rows(
    policy,
    relation_model,
    relation_filters,
    selection_filters=None,
):
    """Return prepared output snapshots keyed by relation ID.

    ``None`` means there is no activated generation and callers must use the
    cold selector. An empty mapping is a valid prepared result.
    """
    state = VODAccessPolicy.objects.filter(pk=policy.pk).values(
        "selection_status",
        "active_selection_generation",
        "selection_catalog_generation",
    ).first()
    if not state:
        return None
    # Keep serving the last atomically activated generation while a newer
    # generation is queued or building. Deleted source relations disappear via
    # FK cascades, and the new generation replaces this one only when complete.
    if not state["active_selection_generation"]:
        return None

    if relation_model is M3UMovieRelation:
        selection_model = VODMovieProfileSelection
    elif relation_model is M3USeriesRelation:
        selection_model = VODSeriesProfileSelection
    else:
        return None
    prefixed_filters = {
        f"relation__{key}": value for key, value in relation_filters.items()
    }
    prefixed_filters.update(selection_filters or {})
    rows = selection_model.objects.filter(
        policy_id=policy.pk,
        generation=state["active_selection_generation"],
        **prefixed_filters,
    ).values(
        "relation_id",
        "edition_key",
        "edition_name",
        "edition_suffix",
        "output_name",
    )
    return {row["relation_id"]: row for row in rows}


def prepared_relation_ids(
    policy,
    relation_model,
    relation_filters,
    selection_filters=None,
):
    """Return prepared relation IDs or ``None`` for a stale/missing build."""
    rows = prepared_relation_rows(
        policy,
        relation_model,
        relation_filters,
        selection_filters=selection_filters,
    )
    if rows is None:
        return None
    return list(rows)


def prepared_relation_snapshot(policy, relation_model, relation_id):
    """Return one activated output snapshot for detail responses."""
    rows = prepared_relation_rows(
        policy,
        relation_model,
        {"pk": relation_id},
    )
    if rows is None:
        return None
    return rows.get(relation_id)
