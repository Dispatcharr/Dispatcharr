from django.db import migrations, models
import django.db.models.deletion


def backfill_auto_created_from(apps, schema_editor):
    Channel = apps.get_model("dispatcharr_channels", "Channel")
    ChannelStream = apps.get_model("dispatcharr_channels", "ChannelStream")
    Membership = apps.get_model(
        "dispatcharr_channels", "ChannelGroupM3UAccount"
    )

    membership_ids = {
        (account_id, group_id): membership_id
        for membership_id, account_id, group_id in Membership.objects.values_list(
            "id", "m3u_account_id", "channel_group_id"
        )
    }
    pending = []
    last_channel_id = None
    rows = (
        ChannelStream.objects.filter(
            channel__auto_created=True,
            channel__auto_created_by_id__isnull=False,
            stream__channel_group_id__isnull=False,
        )
        .order_by("channel_id", "id")
        .values_list(
            "channel_id",
            "channel__auto_created_by_id",
            "stream__channel_group_id",
        )
        .iterator(chunk_size=2000)
    )
    for channel_id, account_id, group_id in rows:
        if channel_id == last_channel_id:
            continue
        last_channel_id = channel_id
        membership_id = membership_ids.get((account_id, group_id))
        if not membership_id:
            continue
        pending.append(Channel(id=channel_id, auto_created_from_id=membership_id))
        if len(pending) >= 1000:
            Channel.objects.bulk_update(pending, ["auto_created_from"])
            pending = []
    if pending:
        Channel.objects.bulk_update(pending, ["auto_created_from"])


class Migration(migrations.Migration):
    dependencies = [
        ("dispatcharr_channels", "0038_add_catchup_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="auto_created_from",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "The provider group membership that auto-created this channel"
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="auto_created_channels",
                to="dispatcharr_channels.channelgroupm3uaccount",
            ),
        ),
        migrations.RunPython(
            backfill_auto_created_from,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
