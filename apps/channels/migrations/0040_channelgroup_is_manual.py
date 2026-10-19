from django.db import migrations, models


def classify_group_sources(apps, schema_editor):
    Channel = apps.get_model("dispatcharr_channels", "Channel")
    ChannelGroup = apps.get_model("dispatcharr_channels", "ChannelGroup")

    manual_group_ids = Channel.objects.filter(
        channel_group_id__isnull=False,
        auto_created=False,
    ).values_list("channel_group_id", flat=True)
    provider_group_ids = Channel.objects.filter(
        channel_group_id__isnull=False,
        auto_created=True,
    ).exclude(channel_group_id__in=manual_group_ids).values_list(
        "channel_group_id", flat=True
    )

    # Empty groups are manual. A user-created channel also makes its group
    # manual, even when it contains provider-created channels.
    ChannelGroup.objects.update(is_manual=True)
    ChannelGroup.objects.filter(id__in=provider_group_ids).update(
        is_manual=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0039_add_radio_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelgroup",
            name="is_manual",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(classify_group_sources, migrations.RunPython.noop),
    ]
