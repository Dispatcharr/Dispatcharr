from apps.m3u.models import M3UAccountProfile


REDIRECT_MODE_PROFILE_IDS_KEY = "redirect_mode_profile_ids"


def get_redirect_profiles(user):
    """Return selected active profiles, or None when Redirect is unrestricted."""
    custom_properties = getattr(user, "custom_properties", None)
    if not isinstance(custom_properties, dict):
        return None

    profile_ids = custom_properties.get(REDIRECT_MODE_PROFILE_IDS_KEY)
    if not isinstance(profile_ids, list) or not profile_ids:
        return None

    return list(
        M3UAccountProfile.objects.select_related("m3u_account__user_agent")
        .filter(
            id__in=profile_ids,
            is_active=True,
            m3u_account__is_active=True,
        )
        .order_by("id")
    )
