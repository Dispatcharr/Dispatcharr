import core.redacted_fields
from core.redacted_fields import redact_value
from django.db import migrations


def redact_existing(apps, schema_editor):
    """Mask credentials already stored before the field masked on write."""
    model = apps.get_model("epg", "EPGSource")
    for obj in model.objects.exclude(last_message=None).only("id", "last_message").iterator():
        value = getattr(obj, "last_message")
        if redact_value(value) != value:
            obj.save(update_fields=["last_message"])


class Migration(migrations.Migration):

    dependencies = [
        ("epg", "0028_programdata_epg_end_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="epgsource",
            name="last_message",
            field=core.redacted_fields.RedactedTextField(
                blank=True,
                help_text="Last status message, including success results or error information",
                null=True,
            ),
        ),
        migrations.RunPython(redact_existing, migrations.RunPython.noop),
    ]
