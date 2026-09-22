from django.contrib.auth import get_user_model

from .models import VODAccessPolicy


DEFAULT_VOD_POLICY_NAME = "All"


def ensure_default_vod_policy():
    defaults = {
        "export_mode": VODAccessPolicy.ExportMode.COMPACT,
        "is_default": True,
        "is_active": True,
        "hard_constraints": {},
        "ranking": [],
        "naming_mode": VODAccessPolicy.NamingMode.TEMPLATE,
        "name_template": "{title}",
        "metadata_source": VODAccessPolicy.MetadataSource.CANONICAL,
        "canonical_title_source": VODAccessPolicy.CanonicalTitleSource.PRIMARY,
    }
    policy, created = VODAccessPolicy.objects.get_or_create(
        name=DEFAULT_VOD_POLICY_NAME,
        defaults=defaults,
    )
    if created:
        VODAccessPolicy.objects.exclude(pk=policy.pk).filter(
            is_default=True
        ).update(is_default=False)
    user_model = get_user_model()
    assigned_user_ids = VODAccessPolicy.users.through.objects.values_list(
        "user_id", flat=True
    )
    unassigned_user_ids = user_model.objects.exclude(
        pk__in=assigned_user_ids
    ).values_list("pk", flat=True)
    VODAccessPolicy.users.through.objects.bulk_create(
        [
            VODAccessPolicy.users.through(
                vodaccesspolicy_id=policy.pk,
                user_id=user_id,
            )
            for user_id in unassigned_user_ids
        ],
        ignore_conflicts=True,
    )
    return policy


def assign_default_vod_policy(user):
    if user.vod_access_policies.exists():
        return
    policy = VODAccessPolicy.objects.filter(
        name=DEFAULT_VOD_POLICY_NAME,
        is_active=True,
    ).first()
    if policy is None:
        policy = ensure_default_vod_policy()
    VODAccessPolicy.users.through.objects.get_or_create(
        vodaccesspolicy_id=policy.pk,
        user_id=user.pk,
    )
