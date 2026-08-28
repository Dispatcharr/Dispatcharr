"""Shared helpers for DVR access level (none / view / manage)."""

_DVR_ACCESS = "dvr_access"

DVR_ACCESS_NONE = "none"
DVR_ACCESS_VIEW = "view"
DVR_ACCESS_MANAGE = "manage"

_VALID_LEVELS = frozenset(
    {DVR_ACCESS_NONE, DVR_ACCESS_VIEW, DVR_ACCESS_MANAGE}
)


def _is_admin(user):
    return getattr(user, "user_level", 0) >= 10


def _is_standard_or_above(user):
    # Streamers (user_level 0) have no DVR UI and no XC DVR surface, so
    # DVR access does not apply to them even if set in custom_properties.
    return getattr(user, "user_level", 0) >= 1


def get_dvr_access(*, user=None):
    """Return the DVR access level for *user*: ``none``, ``view``, or ``manage``.

    Admins always get ``manage``. Streamers always get ``none``. For standard
    users, reads ``custom_properties.dvr_access``. Absent or unrecognized
    values default to ``view`` so standard users keep watch access
    (channel-scoped). An anonymous *user* (``None``) is ``none``.
    """
    if user is None:
        return DVR_ACCESS_NONE
    if _is_admin(user):
        return DVR_ACCESS_MANAGE
    if not _is_standard_or_above(user):
        return DVR_ACCESS_NONE

    props = getattr(user, "custom_properties", None) or {}
    raw = props.get(_DVR_ACCESS)
    if raw in _VALID_LEVELS:
        return raw
    # Absent or unrecognized: view (opt-out via explicit "none").
    return DVR_ACCESS_VIEW


def is_dvr_manage_enabled(*, user=None):
    """Return whether *user* may manage DVR (create, delete, rules, etc.)."""
    return get_dvr_access(user=user) == DVR_ACCESS_MANAGE


def is_dvr_view_enabled(*, user=None):
    """Return whether *user* may list and play DVR recordings."""
    return get_dvr_access(user=user) in (DVR_ACCESS_VIEW, DVR_ACCESS_MANAGE)


def recordings_queryset_for_user(queryset, user):
    """Scope *queryset* of Recording rows to channels *user* may access.

    Managers and admins see the full catalog. View-only users are limited
    to recordings whose source channel is within their ``user_level`` and,
    when they have channel profiles, enabled in one of those profiles.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()
    if is_dvr_manage_enabled(user=user):
        return queryset

    filters = {
        "channel__user_level__lte": user.user_level,
    }
    try:
        has_profiles = user.channel_profiles.exists()
    except Exception:
        has_profiles = False

    if has_profiles:
        filters["channel__channelprofilemembership__enabled"] = True
        filters["channel__channelprofilemembership__channel_profile__in"] = (
            user.channel_profiles.all()
        )
        return queryset.filter(**filters).distinct()
    return queryset.filter(**filters)
