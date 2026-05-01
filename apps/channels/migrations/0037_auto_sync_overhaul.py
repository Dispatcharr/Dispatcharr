"""
Auto-sync overhaul (FR #1196): per-field channel overrides, hide-from-output
flag, configurable auto-sync number range, and nullable channel_number for
compact-numbering slot release.

Bundled operations (in forward order; reversed on rollback):
  1. AddField    Channel.user_hidden
  2. CreateModel ChannelOverride (one-to-one Channel)
  3. AddField    ChannelGroupM3UAccount.auto_sync_channel_end
  4. RunPython   backfill_auto_created_by_null  (orphan re-attribution / demotion)
  5. AlterField  Channel.channel_number (nullable)
  6. RunPython   noop / reverse_backfill_channel_number_nulls
                 (rollback-safety hook; runs FIRST on un-apply, fills NULLs
                 so step 5 reverse can re-impose NOT NULL)
"""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Max


def backfill_auto_created_by_null(apps, schema_editor):
    """
    Re-attribute or demote `auto_created=True, auto_created_by=NULL` rows.

    Sync only touches rows where `auto_created_by=account`, so orphans
    accumulate indefinitely. Best-effort re-attribute via the channel's
    streams' single owning account; otherwise demote to manual by clearing
    `auto_created`. The channel and any user customization survive; sync
    will not touch a demoted row again.
    """
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


def reverse_auto_created_by_null(apps, schema_editor):
    # Forward decisions cannot be cleanly reverted (no record of the
    # original NULL state). Leaving the re-attributions and demotions in
    # place is safer than restoring NULLs the schema may not accept.
    pass


def noop(apps, schema_editor):
    pass


def reverse_backfill_channel_number_nulls(apps, schema_editor):
    """
    Rollback-safety hook for the channel_number nullable AlterField.

    Runs FIRST on un-apply (operations reverse in list order) and assigns
    sequential channel numbers above the current max to any NULL rows so
    the AlterField reverse (nullable to NOT NULL) succeeds without a
    constraint violation. The user can re-hide or re-number these
    channels after they have rolled back.
    """
    Channel = apps.get_model("dispatcharr_channels", "Channel")
    null_qs = Channel.objects.filter(channel_number__isnull=True)
    null_count = null_qs.count()
    if null_count == 0:
        return

    max_num = Channel.objects.aggregate(m=Max("channel_number"))["m"] or 0.0
    next_num = float(max_num) + 1.0
    print(
        f"\n  Backfilling channel_number on {null_count} NULL row(s) "
        f"starting at {int(next_num)} so rollback can re-impose NOT NULL"
    )
    for ch in null_qs.order_by("id"):
        ch.channel_number = next_num
        ch.save(update_fields=["channel_number"])
        next_num += 1.0


class Migration(migrations.Migration):

    dependencies = [
        ('core', '022_default_user_limit_settings'),
        ('dispatcharr_channels', '0036_alter_stream_name'),
        ('epg', '0022_alter_epgdata_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='user_hidden',
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text='Exclude this channel from downstream client output (HDHR, M3U, EPG, XC). Auto-sync still updates provider metadata.',
            ),
        ),
        migrations.CreateModel(
            name='ChannelOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=512, null=True)),
                ('channel_number', models.FloatField(blank=True, null=True)),
                ('tvg_id', models.CharField(blank=True, max_length=255, null=True)),
                ('tvc_guide_stationid', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('channel', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='override', to='dispatcharr_channels.channel')),
                ('channel_group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='dispatcharr_channels.channelgroup')),
                ('epg_data', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='epg.epgdata')),
                ('logo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='dispatcharr_channels.logo')),
                ('stream_profile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='core.streamprofile')),
            ],
        ),
        migrations.AddField(
            model_name='channelgroupm3uaccount',
            name='auto_sync_channel_end',
            field=models.FloatField(
                blank=True,
                help_text='Optional upper bound for auto-created channel numbers in this group. Leave blank for unlimited fill. Overflow streams are skipped and reported in the completion notification.',
                null=True,
            ),
        ),
        migrations.RunPython(backfill_auto_created_by_null, reverse_auto_created_by_null),
        migrations.AlterField(
            model_name='channel',
            name='channel_number',
            field=models.FloatField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(noop, reverse_backfill_channel_number_nulls),
    ]
