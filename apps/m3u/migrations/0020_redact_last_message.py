import core.redacted_fields
from core.redacted_fields import redact_value
from django.db import migrations


def redact_existing(apps, schema_editor):
    """Mask credentials already stored before the field masked on write."""
    model = apps.get_model("m3u", "M3UAccount")
    for obj in model.objects.exclude(last_message=None).only("id", "last_message").iterator():
        value = getattr(obj, "last_message")
        if redact_value(value) != value:
            obj.save(update_fields=["last_message"])


class Migration(migrations.Migration):

    dependencies = [
        ("m3u", "0019_m3uaccountprofile_exp_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="m3uaccount",
            name="last_message",
            field=core.redacted_fields.RedactedTextField(
                blank=True,
                help_text="Last status message, including success results or error information",
                null=True,
            ),
        ),
        migrations.RunPython(redact_existing, migrations.RunPython.noop),
    ]
