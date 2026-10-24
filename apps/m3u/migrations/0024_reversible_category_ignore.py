from django.db import migrations, models


def pause_legacy_ignore(apps, schema_editor):
    apps.get_model("m3u", "M3UGroupRule").objects.using(
        schema_editor.connection.alias
    ).filter(action="ignore").update(enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ("m3u", "0023_m3ufilter_enabled"),
        ("dispatcharr_channels", "0041_category_ignored"),
        ("vod", "0008_category_ignored"),
    ]
    operations = [
        migrations.RunPython(pause_legacy_ignore, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="m3ugrouprule", name="action",
            field=models.CharField(
                choices=[("keep", "Keep import selection"), ("enable", "Import enabled"),
                         ("disable", "Import disabled"), ("ignore", "Ignore")],
                default="disable", max_length=10,
            ),
        ),
    ]
