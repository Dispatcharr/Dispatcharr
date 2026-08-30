from apps.m3u.models import M3UAccountProfile


ALLOWED_M3U_PROFILE_IDS_KEY = "allowed_m3u_profile_ids"


def get_allowed_m3u_profiles(user):
    """Return active allowed profiles by account, or None when unrestricted."""
    custom_properties = getattr(user, "custom_properties", None)
    if not isinstance(custom_properties, dict):
        return None

    profile_ids = custom_properties.get(ALLOWED_M3U_PROFILE_IDS_KEY)
    if not isinstance(profile_ids, list) or not profile_ids:
        return None

    profiles = (
        M3UAccountProfile.objects.select_related("m3u_account__user_agent")
        .filter(
            id__in=profile_ids,
            is_active=True,
            m3u_account__is_active=True,
        )
        .order_by("m3u_account_id", "-is_default", "id")
    )
    profiles_by_account = {}
    for profile in profiles:
        profiles_by_account.setdefault(profile.m3u_account_id, []).append(profile)
    return profiles_by_account
