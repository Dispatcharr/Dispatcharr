"""Shared channel visibility for authenticated users.

Every surface that lists, looks up, schedules, or plays a channel for a
logged-in user goes through these helpers so a new visibility rule only has to
be added here.
"""

from django.db.models import Exists, OuterRef

from apps.channels.models import Channel, ChannelProfileMembership

ADMIN_USER_LEVEL = 10


def is_admin_user(user):
    return getattr(user, "user_level", 0) >= ADMIN_USER_LEVEL


def channels_queryset_for_user(queryset, user, *, profiles=True, level_cap_admins=False):
    """Scope a Channel queryset to what *user* may see.

    Admins get *queryset* unchanged unless *level_cap_admins* is True, in
    which case they are limited to ``user_level__lte`` their own level
    (XC / M3U / EPG output list views have always done this). Everyone else is
    limited by ``user_level`` and the hide-adult-content preference. When
    *profiles* is True and the user has assigned channel profiles, only
    channels with an enabled membership in one of those profiles remain.

    Profile membership is expressed with ``Exists`` subqueries so a filtered
    ``.first()`` / ``.exists()`` stays one SQL round trip (no Python-side
    ``channel_profiles.exists()`` probe).

    Pass ``profiles=False`` only where profile membership is deliberately not
    part of the rule: channel groups, and views that apply one explicit
    profile themselves.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()
    if is_admin_user(user):
        if level_cap_admins:
            return queryset.filter(user_level__lte=user.user_level)
        return queryset

    queryset = queryset.filter(user_level__lte=user.user_level)
    custom_props = getattr(user, "custom_properties", None) or {}
    if custom_props.get("hide_adult_content", False):
        queryset = queryset.filter(is_adult=False)

    if not profiles:
        return queryset

    # No assigned profiles → unrestricted within level/adult. Otherwise the
    # channel needs an enabled membership in one of those profiles.
    through = user.channel_profiles.through
    user_has_profiles = Exists(through.objects.filter(user_id=user.pk))
    channel_in_profile = Exists(
        ChannelProfileMembership.objects.filter(
            channel_id=OuterRef("pk"),
            enabled=True,
            channel_profile__users=user,
        )
    )
    return queryset.filter(~user_has_profiles | channel_in_profile)


def user_can_access_channel(user, channel):
    """Whether *user* may access *channel* under the shared visibility rules."""
    if channel is None:
        return False
    if is_admin_user(user):
        return True
    return channels_queryset_for_user(
        type(channel).objects.filter(pk=channel.pk), user
    ).exists()


def get_channel_for_user(user, **lookup):
    """Return the channel matching *lookup* if *user* may access it, else None.

    None covers both a missing channel and one the user may not see, so
    callers can return 404 for either without leaking existence.
    """
    return channels_queryset_for_user(Channel.objects.all(), user).filter(**lookup).first()


def user_may_use_profile(user, profile_id):
    """Whether *user* may scope a channel view to the given channel profile.

    Admins and users with no assigned profiles may use any profile. Everyone
    else may only use a profile they are assigned to.
    """
    if is_admin_user(user):
        return True
    assigned = user.channel_profiles
    if not assigned.exists():
        return True
    return assigned.filter(pk=profile_id).exists()


def scope_by_channel_access(queryset, user, *, field="channel_id"):
    """Limit rows owned by a channel (recordings, recurring rules) to
    channels *user* may access. Admins see every row."""
    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()
    if is_admin_user(user):
        return queryset
    visible = channels_queryset_for_user(Channel.objects.all(), user)
    return queryset.filter(**{f"{field}__in": visible.values("pk")})
