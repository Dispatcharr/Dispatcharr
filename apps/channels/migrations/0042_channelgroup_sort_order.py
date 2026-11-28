from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0041_alter_stream_url_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelgroup",
            name="sort_order",
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
    ]
