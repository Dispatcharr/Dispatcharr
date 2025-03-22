# In your app's migrations folder, create a new migration file
# e.g., migrations/000X_migrate_channel_group_to_foreign_key.py

from django.db import migrations

def migrate_channel_group(apps, schema_editor):
    Stream = apps.get_model('dispatcharr_channels', 'Stream')
    ChannelGroup = apps.get_model('dispatcharr_channels', 'ChannelGroup')
    ChannelGroupM3UAccount = apps.get_model('dispatcharr_channels', 'ChannelGroup')
    M3UAccount = apps.get_model('m3u', 'M3UAccount')

    streams_to_update = []
    for stream in Stream.objects.all():
        # If the stream has a 'channel_group' string, try to find or create the ChannelGroup
        if stream.group_name:  # group_name holds the channel group string
            channel_group_name = stream.group_name.strip()

            # Try to find the ChannelGroup by name
            channel_group, created = ChannelGroup.objects.get_or_create(name=channel_group_name)

            # Set the foreign key to the found or newly created ChannelGroup
            stream.channel_group = channel_group

            streams_to_update.append(stream)

            # If the stream has an M3U account, ensure the M3U account is linked
            if stream.m3u_account:
                ChannelGroupM3UAccount.objects.get_or_create(
                    channel_group=channel_group,
                    m3u_account=stream.m3u_account,
                    enabled=True  # Or set it to whatever the default logic is
                )

    Stream.objects.bulk_update(streams_to_update, ['channel_group'])

def reverse_migration(apps, schema_editor):
    # This reverse migration would undo the changes, setting `channel_group` to `None` and clearing any relationships.
    Stream = apps.get_model('yourapp', 'Stream')
    for stream in Stream.objects.all():
        stream.channel_group = None
        stream.save()

class Migration(migrations.Migration):

    dependencies = [
        ('dispatcharr_channels', '0005_stream_channel_group_stream_last_seen_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_channel_group, reverse_code=reverse_migration),
    ]
