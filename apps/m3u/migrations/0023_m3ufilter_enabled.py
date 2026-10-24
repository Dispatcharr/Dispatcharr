from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("m3u", "0022_group_rule_metadata_defaults")]

    operations = [
        migrations.AddField(
            model_name="m3ufilter",
            name="enabled",
            field=models.BooleanField(default=True),
        ),
    ]
