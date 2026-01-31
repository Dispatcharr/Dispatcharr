# Generated manually for plugin navigation and pages support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plugins', '0002_add_plugin_data'),
    ]

    operations = [
        migrations.AddField(
            model_name='pluginconfig',
            name='navigation',
            field=models.JSONField(
                blank=True,
                help_text="Navigation item config: {label, icon, path, badge, position}",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pluginconfig',
            name='pages',
            field=models.JSONField(
                blank=True,
                help_text='Page definitions for plugin UI',
                null=True,
            ),
        ),
    ]
