# Document the {streamProfile=Name} placeholder on StreamProfile.parameters.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_limit_default_interleave_delta"),
    ]

    operations = [
        migrations.AlterField(
            model_name="streamprofile",
            name="parameters",
            field=models.TextField(
                blank=True,
                help_text="Command-line parameters. Use {userAgent}, {streamUrl}, {channelId}, "
                "and {streamProfile=Name} as placeholders.",
            ),
        ),
    ]