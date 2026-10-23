from django.db import migrations


CUSTOM_ACCOUNT_NAME = "custom"
USER_CUSTOM_ACCOUNT_NAME = "custom (user)"


def _free_account_name(M3UAccount, base):
    if not M3UAccount.objects.filter(name=base).exists():
        return base
    suffix = 2
    while M3UAccount.objects.filter(name=f"{base} {suffix}").exists():
        suffix += 1
    return f"{base} {suffix}"


def ensure_custom_account(apps):
    """Return the locked custom account, recreating it if missing.

    Early installs seed this row in m3u.0003. Some databases lose it
    (manual deletes, restores, etc.). This migration needs that row to
    attach custom group relations, so recreate it the same way 0003 did.

    If a user account already occupies the name, rename that row first.
    Lookups require the system account to stay named custom.
    """
    M3UAccount = apps.get_model("m3u", "M3UAccount")
    M3UAccountProfile = apps.get_model("m3u", "M3UAccountProfile")
    UserAgent = apps.get_model("core", "UserAgent")

    custom_account = M3UAccount.objects.filter(
        name=CUSTOM_ACCOUNT_NAME,
        locked=True,
    ).first()
    if custom_account is not None:
        return custom_account

    occupant = M3UAccount.objects.filter(name=CUSTOM_ACCOUNT_NAME).first()
    if occupant is not None:
        occupant.name = _free_account_name(M3UAccount, USER_CUSTOM_ACCOUNT_NAME)
        occupant.save(update_fields=["name"])

    user_agent = UserAgent.objects.order_by("id").first()
    custom_account = M3UAccount.objects.create(
        name=CUSTOM_ACCOUNT_NAME,
        max_streams=0,
        is_active=True,
        locked=True,
        user_agent_id=user_agent.id if user_agent else None,
    )

    M3UAccountProfile.objects.get_or_create(
        m3u_account=custom_account,
        name=f"{CUSTOM_ACCOUNT_NAME} Default",
        defaults={
            "max_streams": custom_account.max_streams,
            "is_default": True,
            "is_active": True,
            "search_pattern": "^(.*)$",
            "replace_pattern": "$1",
        },
    )
    return custom_account


def create_custom_group_relations(apps, schema_editor):
    Channel = apps.get_model("dispatcharr_channels", "Channel")
    ChannelGroup = apps.get_model("dispatcharr_channels", "ChannelGroup")
    ChannelGroupM3UAccount = apps.get_model(
        "dispatcharr_channels", "ChannelGroupM3UAccount"
    )

    custom_account = ensure_custom_account(apps)
    manual_group_ids = Channel.objects.filter(
        channel_group_id__isnull=False,
        auto_created=False,
    ).values_list("channel_group_id", flat=True)
    custom_group_ids = ChannelGroup.objects.filter(
        id__in=manual_group_ids
    ).values_list("id", flat=True)

    ChannelGroupM3UAccount.objects.bulk_create(
        [
            ChannelGroupM3UAccount(
                channel_group_id=group_id,
                m3u_account_id=custom_account.id,
            )
            for group_id in custom_group_ids
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0039_add_radio_fields"),
        ("m3u", "0019_m3uaccountprofile_exp_date"),
    ]

    operations = [
        migrations.RunPython(
            create_custom_group_relations,
            migrations.RunPython.noop,
        ),
    ]
