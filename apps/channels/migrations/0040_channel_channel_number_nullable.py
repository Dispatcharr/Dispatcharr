# Generated for compact-numbering support.
# Allowing NULL on Channel.channel_number is required so the compact
# numbering pass can release a hidden channel's slot back to the pool.
# Existing rows are unaffected (NOT NULL -> NULL is a column-only ALTER).
#
# Rollback safety: reverting nullable -> NOT NULL would fail with a
# constraint violation on any row with NULL channel_number. A pre-revert
# RunPython step backfills those NULLs with sequential numbers above the
# current max so the schema can shrink back to NOT NULL cleanly. The
# operation list is ordered so that on REVERSE, the RunPython runs
# BEFORE the AlterField (operations reverse in list order on un-apply).

from django.db import migrations, models
from django.db.models import Max


def forward_noop(apps, schema_editor):
    pass


def reverse_backfill_nulls(apps, schema_editor):
    """
    Assign sequential channel numbers to rows whose channel_number is NULL,
    so the subsequent reverse AlterField can re-impose NOT NULL.

    Numbers are placed above the current max to avoid collision with any
    other channel's existing assignment. The user can re-hide or re-number
    these channels after they have rolled back.
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
        ("dispatcharr_channels", "0039_channelgroupm3uaccount_auto_sync_channel_end"),
    ]

    operations = [
        migrations.AlterField(
            model_name="channel",
            name="channel_number",
            field=models.FloatField(blank=True, db_index=True, null=True),
        ),
        # Forward: no-op (no NULL rows exist before AlterField runs).
        # Reverse: runs FIRST on un-apply (list-reversed) and clears NULLs
        # so the AlterField reverse (nullable -> NOT NULL) succeeds.
        migrations.RunPython(forward_noop, reverse_backfill_nulls),
    ]
