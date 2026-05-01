"""
Data migration: re-attribute `auto_created=True, auto_created_by=NULL` channels
or demote them to manual.

Sync logic only touches rows where `auto_created_by=account`, so orphaned
rows accumulate indefinitely and clutter the admin table.

Strategy:
1. Best-effort re-attribute: if the channel's streams all live under a
   single M3U account, set `auto_created_by` to that account.
2. Otherwise (zero streams or multiple accounts), demote to manual by
   clearing `auto_created`. The channel and any user customization survive;
   sync will not touch it again.

Each decision is logged so operators can see the outcome at migrate time.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Channel = apps.get_model("dispatcharr_channels", "Channel")
    ChannelStream = apps.get_model("dispatcharr_channels", "ChannelStream")

    orphans = Channel.objects.filter(auto_created=True, auto_created_by__isnull=True)
    total = orphans.count()
    if total == 0:
        return

    print(f"\n  Found {total} auto_created channels with NULL auto_created_by")
    reattributed = 0
    demoted = 0

    for channel in orphans.iterator(chunk_size=200):
        account_ids = set(
            ChannelStream.objects.filter(channel=channel)
            .values_list("stream__m3u_account_id", flat=True)
        )
        account_ids.discard(None)

        if len(account_ids) == 1:
            channel.auto_created_by_id = next(iter(account_ids))
            channel.save(update_fields=["auto_created_by"])
            reattributed += 1
        else:
            channel.auto_created = False
            channel.save(update_fields=["auto_created"])
            demoted += 1

    print(
        f"  Re-attributed: {reattributed}, demoted to manual "
        f"(ambiguous/no streams): {demoted}"
    )


def reverse(apps, schema_editor):
    # Irreversible data fix - leaving the forward decisions in place is
    # safer than trying to re-null the auto_created_by field (we cannot
    # recreate the deleted rows).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0037_channeloverride_and_user_hidden"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
