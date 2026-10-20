from django.db import migrations


CUSTOM_ACCOUNT_NAME = "custom"


def create_custom_group_relations(apps, schema_editor):
    Channel = apps.get_model("dispatcharr_channels", "Channel")
    ChannelGroup = apps.get_model("dispatcharr_channels", "ChannelGroup")
    ChannelGroupM3UAccount = apps.get_model(
        "dispatcharr_channels", "ChannelGroupM3UAccount"
    )
    M3UAccount = apps.get_model("m3u", "M3UAccount")

    custom_account = M3UAccount.objects.get(
        name=CUSTOM_ACCOUNT_NAME,
        locked=True,
    )
    manual_group_ids = Channel.objects.filter(
        channel_group_id__isnull=False,
        auto_created=False,
    ).values_list("channel_group_id", flat=True)
    provider_only_group_ids = Channel.objects.filter(
        channel_group_id__isnull=False,
        auto_created=True,
    ).exclude(channel_group_id__in=manual_group_ids).values_list(
        "channel_group_id", flat=True
    )
    custom_group_ids = ChannelGroup.objects.exclude(
        id__in=provider_only_group_ids
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
