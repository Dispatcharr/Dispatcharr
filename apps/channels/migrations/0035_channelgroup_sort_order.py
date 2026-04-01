from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0034_remove_stream_dispatcharr_stream_id_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelgroup",
            name="sort_order",
            field=models.IntegerField(blank=True, db_index=True, default=None, null=True),
        ),
    ]
