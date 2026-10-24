from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dispatcharr_channels", "0040_channel_auto_created_from")]
    operations = [
        migrations.AddField(
            model_name="channelgroupm3uaccount", name="ignored",
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name="channelgroupm3uaccount",
            constraint=models.CheckConstraint(
                condition=models.Q(ignored=False) | models.Q(enabled=False),
                name="live_ignored_category_disabled",
            ),
        ),
    ]
