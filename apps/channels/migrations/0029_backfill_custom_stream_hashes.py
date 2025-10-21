# Generated migration to backfill stream_hash for existing custom streams

from django.db import migrations
import hashlib


def backfill_custom_stream_hashes(apps, schema_editor):
    """
    Generate stream_hash for all custom streams that don't have one.
    Uses stream ID to create a stable hash that won't change when name/url is edited.
    """
    Stream = apps.get_model('dispatcharr_channels', 'Stream')

    custom_streams_without_hash = Stream.objects.filter(
        is_custom=True,
        stream_hash__isnull=True
    )

    updated_count = 0
    for stream in custom_streams_without_hash:
        # Generate a stable hash using the stream's ID
        # This ensures the hash never changes even if name/url is edited
        unique_string = f"custom_stream_{stream.id}"
        stream.stream_hash = hashlib.sha256(unique_string.encode()).hexdigest()
        stream.save(update_fields=['stream_hash'])
        updated_count += 1

    if updated_count > 0:
        print(f"Backfilled stream_hash for {updated_count} custom streams")
    else:
        print("No custom streams needed stream_hash backfill")


def reverse_backfill(apps, schema_editor):
    """
    Reverse migration - clear stream_hash for custom streams.
    Note: This will break preview functionality for custom streams.
    """
    Stream = apps.get_model('dispatcharr_channels', 'Stream')

    custom_streams = Stream.objects.filter(is_custom=True)
    count = custom_streams.update(stream_hash=None)
    print(f"Cleared stream_hash for {count} custom streams")


class Migration(migrations.Migration):

    dependencies = [
        ('dispatcharr_channels', '0028_channel_created_at_channel_updated_at'),
    ]

    operations = [
        migrations.RunPython(backfill_custom_stream_hashes, reverse_backfill),
    ]
