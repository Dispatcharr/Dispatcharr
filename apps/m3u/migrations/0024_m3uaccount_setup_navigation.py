from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("m3u", "0023_m3uaccount_setup_step"),
    ]

    operations = [
        migrations.AlterField(
            model_name="m3uaccount",
            name="setup_step",
            field=models.CharField(
                blank=True,
                choices=[
                    ("account", "Account"),
                    ("content", "Content"),
                    ("epg", "Optional EPG"),
                    ("categories", "Categories"),
                ],
                default="",
                help_text="Unfinished guided setup step, independent of refresh status.",
                max_length=16,
            ),
        ),
    ]
