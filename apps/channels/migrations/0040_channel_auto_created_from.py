import json

from django.db import migrations, models
import django.db.models.deletion


def properties(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return dict(value) if isinstance(value, dict) else {}


def backfill_group_cleanup(apps, schema_editor):
    Channel = apps.get_model("dispatcharr_channels", "Channel")
    ChannelStream = apps.get_model("dispatcharr_channels", "ChannelStream")
    Membership = apps.get_model("dispatcharr_channels", "ChannelGroupM3UAccount")
    database = schema_editor.connection.alias
    memberships = Membership.objects.using(database)
    membership_ids = {}
    pending = []
    for membership in memberships.select_related("m3u_account").iterator(
        chunk_size=1000
    ):
        membership_ids[(membership.m3u_account_id, membership.channel_group_id)] = (
            membership.pk
        )
        custom = properties(membership.custom_properties)
        if not custom.get("orphan_channel_cleanup"):
            custom["orphan_channel_cleanup"] = properties(
                membership.m3u_account.custom_properties
            ).get("orphan_channel_cleanup", "always")
            membership.custom_properties = custom
            pending.append(membership)
        if len(pending) >= 1000:
            memberships.bulk_update(pending, ["custom_properties"])
            pending = []
    if pending:
        memberships.bulk_update(pending, ["custom_properties"])

    # A manually attached backup stream must not change the creating group.
    # Only backfill an unambiguous source group from the owning provider.
    rows = (
        ChannelStream.objects.using(database)
        .filter(
            channel__auto_created=True,
            channel__auto_created_by_id=models.F("stream__m3u_account_id"),
            stream__channel_group_id__isnull=False,
        )
        .values("channel_id", "channel__auto_created_by_id")
        .annotate(
            groups=models.Count("stream__channel_group_id", distinct=True),
            group_id=models.Min("stream__channel_group_id"),
        )
        .filter(groups=1)
        .order_by("channel_id")
    )
    pending = []
    for row in rows.iterator(chunk_size=1000):
        membership_id = membership_ids.get(
            (row["channel__auto_created_by_id"], row["group_id"])
        )
        if membership_id:
            pending.append(
                Channel(id=row["channel_id"], auto_created_from_id=membership_id)
            )
        if len(pending) >= 1000:
            Channel.objects.using(database).bulk_update(pending, ["auto_created_from"])
            pending = []
    if pending:
        Channel.objects.using(database).bulk_update(pending, ["auto_created_from"])


class Migration(migrations.Migration):
    dependencies = [("dispatcharr_channels", "0039_add_radio_fields")]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="auto_created_from",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="auto_created_channels",
                help_text="The provider group membership that auto-created this channel",
                to="dispatcharr_channels.channelgroupm3uaccount",
            ),
        ),
        migrations.RunPython(backfill_group_cleanup, migrations.RunPython.noop),
    ]
