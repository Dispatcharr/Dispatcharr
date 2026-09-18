from django.db import transaction
from django.conf import settings
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_migrate,
    post_save,
    pre_save,
)
from django.dispatch import receiver
from apps.m3u.models import M3UAccount

from .catalog_cache import bump_catalog_generation
from .models import (
    Episode,
    Movie,
    Series,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    VODAccessPolicy,
    VODPolicyCategory,
)


@receiver(post_migrate, dispatch_uid="vod.ensure_default_policy")
def create_default_vod_policy(sender, **kwargs):
    if sender.label != "vod":
        return
    from .defaults import ensure_default_vod_policy

    ensure_default_vod_policy()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def assign_vod_policy_to_new_user(sender, instance, created, **kwargs):
    if not created:
        return
    from .defaults import assign_default_vod_policy

    assign_default_vod_policy(instance)


CANONICAL_METADATA_MODELS = (
    Movie,
    Series,
    Episode,
)

SELECTION_CATALOG_MODELS = (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
)

M3U_SELECTION_SCALAR_FIELDS = {"is_active", "priority"}
M3U_SELECTION_FIELDS = {*M3U_SELECTION_SCALAR_FIELDS, "custom_properties"}
# Live and VOD account state intentionally share one JSON field.  Compare only
# settings which can affect whether VOD is imported/selected; refresh timings,
# live catalog counters and other operational metadata must never invalidate
# every prepared VOD output profile.
M3U_VOD_SELECTION_PROPERTY_KEYS = {
    "enable_vod",
    "auto_enable_new_groups_vod",
    "auto_enable_new_groups_series",
    "use_group_rules_movie",
    "use_group_rules_series",
}
RELATION_SELECTION_FIELDS = {
    M3UMovieRelation: {
        "m3u_account",
        "m3u_account_id",
        "movie",
        "movie_id",
        "category",
        "category_id",
        "stream_id",
        "container_extension",
        "custom_properties",
    },
    M3USeriesRelation: {
        "m3u_account",
        "m3u_account_id",
        "series",
        "series_id",
        "category",
        "category_id",
        "external_series_id",
        "custom_properties",
    },
}

# Technical metadata learned or edited for one concrete source can affect
# constraints, editions and failover. Manual changes mark prepared catalogs as
# outdated; lazy provider inspection bypasses this signal deliberately.
SOURCE_RELATION_METADATA_FIELDS = {
    "declared_metadata",
    "observed_metadata",
    "manual_metadata",
    "locked_fields",
    "last_observed_at",
    "updated_at",
}
RELATION_INCREMENTAL_SELECTION_FIELDS = {
    M3UMovieRelation: {
        "container_extension",
        "custom_properties",
        "last_advanced_refresh",
        "updated_at",
    },
    M3USeriesRelation: {
        "custom_properties",
        "last_episode_refresh",
        "updated_at",
    },
}


def mark_vod_profiles_outdated_for_source_content(instance):
    """Mark prepared catalogs stale without starting background work."""
    def mark_outdated():
        bump_catalog_generation(invalidate_selections=False)
        from .profile_selection import (
            mark_profile_selections_outdated,
            profile_ids_using_source_categories,
        )

        if isinstance(instance, M3UMovieRelation):
            category_keys = [(instance.m3u_account_id, instance.category_id)]
        elif isinstance(instance, M3USeriesRelation):
            category_keys = [(instance.m3u_account_id, instance.category_id)]
        elif isinstance(instance, M3UEpisodeRelation):
            category_keys = [
                (
                    instance.m3u_account_id,
                    instance.series_relation.category_id
                    if instance.series_relation_id
                    else None,
                )
            ]
        else:
            category_keys = []

        mark_profile_selections_outdated(
            trigger_reason="VOD source metadata changed",
            policy_ids=profile_ids_using_source_categories(category_keys),
        )

    transaction.on_commit(mark_outdated)


def invalidate_and_schedule_vod_profiles(trigger_reason=None):
    """Invalidate once, but never publish a profile batch mid-import."""
    bump_catalog_generation()
    if M3UAccount.objects.filter(
        is_active=True,
        status__in=[M3UAccount.Status.FETCHING, M3UAccount.Status.PARSING],
    ).exists():
        from .tasks import _remember_profile_rebuild_after_vod_refresh

        _remember_profile_rebuild_after_vod_refresh()
        return

    from .profile_selection import enqueue_all_profile_selection_rebuilds

    enqueue_all_profile_selection_rebuilds(trigger_reason=trigger_reason)


@receiver(pre_save, sender=M3UAccount)
def remember_m3u_selection_changes(sender, instance, **kwargs):
    """Detect relevant changes even when callers use a full model save."""
    if not instance.pk:
        instance._vod_selection_changed = True
        return
    previous = sender.objects.filter(pk=instance.pk).values(
        *M3U_SELECTION_FIELDS
    ).first()
    if previous is None:
        instance._vod_selection_changed = True
        return

    scalar_changed = any(
        previous[field] != getattr(instance, field)
        for field in M3U_SELECTION_SCALAR_FIELDS
    )
    previous_properties = previous.get("custom_properties") or {}
    current_properties = instance.custom_properties or {}
    vod_properties_changed = any(
        previous_properties.get(key) != current_properties.get(key)
        for key in M3U_VOD_SELECTION_PROPERTY_KEYS
    )
    instance._vod_selection_changed = scalar_changed or vod_properties_changed


@receiver(post_save)
@receiver(post_delete)
def invalidate_vod_catalog(
    sender,
    instance=None,
    created=False,
    update_fields=None,
    signal=None,
    **kwargs,
):
    if sender in (M3UMovieRelation, M3USeriesRelation, M3UEpisodeRelation):
        changed_fields = set(update_fields or [])
        if (
            signal is post_save
            and changed_fields
            and changed_fields.issubset(SOURCE_RELATION_METADATA_FIELDS)
        ):
            mark_vod_profiles_outdated_for_source_content(instance)
            return
    if sender in CANONICAL_METADATA_MODELS:
        # Names, artwork and provider detail enrichment affect the normal XC
        # response cache, but never which source edition a profile selects.
        # Keeping the prepared generation valid avoids an opened VOD detail
        # dialog needlessly returning every profile to Pending.
        bump_catalog_generation(invalidate_selections=False)
        return
    if sender is M3UAccount:
        if signal is post_delete:
            invalidate_and_schedule_vod_profiles(
                "An M3U account containing VOD sources was deleted"
            )
            return
        changed_fields = set(update_fields or [])
        if changed_fields and changed_fields.isdisjoint(M3U_SELECTION_FIELDS):
            # Playback counters and refresh status/last_message updates are
            # frequent and do not change VOD visibility or ranking.
            return
        if not getattr(instance, "_vod_selection_changed", True):
            return
        invalidate_and_schedule_vod_profiles(
            "M3U account VOD selection settings changed"
        )
        return
    if sender is M3UEpisodeRelation:
        # Episode inventory and playback metadata change the normal XC response,
        # but profile selection is based on movie/series source relations only.
        bump_catalog_generation(invalidate_selections=False)
        return
    if sender is VODAccessPolicy:
        # Policy semantics only invalidate this profile. User-output caches are
        # still globally versioned, but other prepared profiles remain valid.
        if instance and instance.pk:
            VODAccessPolicy.objects.filter(pk=instance.pk).exclude(
                selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            ).update(
                selection_status=VODAccessPolicy.SelectionStatus.PENDING,
                selection_error="",
            )
        bump_catalog_generation(invalidate_selections=False)
        return
    if sender is VODPolicyCategory:
        policy_id = getattr(instance, "policy_id", None)
        if policy_id:
            VODAccessPolicy.objects.filter(pk=policy_id).exclude(
                selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            ).update(
                selection_status=VODAccessPolicy.SelectionStatus.PENDING,
                selection_error="",
            )
        bump_catalog_generation(invalidate_selections=False)
        return
    if sender in SELECTION_CATALOG_MODELS:
        if getattr(instance, "_skip_vod_profile_invalidation", False):
            return
        relevant_fields = RELATION_SELECTION_FIELDS.get(sender)
        if relevant_fields and update_fields and set(update_fields).isdisjoint(
            relevant_fields
        ):
            return
        incremental_fields = RELATION_INCREMENTAL_SELECTION_FIELDS.get(sender)
        if (
            signal is post_save
            and not created
            and incremental_fields
            and update_fields
            and set(update_fields).issubset(incremental_fields)
        ):
            mark_vod_profiles_outdated_for_source_content(instance)
            return
        invalidate_and_schedule_vod_profiles(
            "The selectable VOD source catalog changed"
        )


@receiver(m2m_changed, sender=VODAccessPolicy.users.through)
def invalidate_vod_policy_users(**kwargs):
    # Assignment changes which prepared profile a user consumes, not the
    # contents of any prepared profile.
    bump_catalog_generation(invalidate_selections=False)
