# Generated migration to remove HLS Output fields from Channel model

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dispatcharr_channels', '0030_alter_stream_url'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE dispatcharr_channels_channel 
                DROP COLUMN IF EXISTS hls_output_enabled CASCADE;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE dispatcharr_channels_channel 
                DROP COLUMN IF EXISTS hls_output_profile_id CASCADE;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

