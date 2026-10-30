from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("m3u", "0022_m3ugrouprule")]

    operations = [
        migrations.AddField(
            model_name="m3uaccount",
            name="setup_step",
            field=models.CharField(
                blank=True,
                choices=[("epg", "Optional EPG"), ("categories", "Categories")],
                default="",
                help_text=(
                    "Unfinished guided setup step, independent of refresh status."
                ),
                max_length=16,
            ),
        ),
    ]
