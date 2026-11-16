import core.redacted_fields
from core.redacted_fields import redact_value
from django.db import migrations


def redact_existing(apps, schema_editor):
    """Mask credentials already stored before the field masked on write."""
    model = apps.get_model("core", "SystemEvent")
    for obj in model.objects.only("id", "details").iterator():
        value = getattr(obj, "details")
        if redact_value(value) != value:
            obj.save(update_fields=["details"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_drop_output_profile_nobuffer"),
    ]

    operations = [
        migrations.AlterField(
            model_name="systemevent",
            name="details",
            field=core.redacted_fields.RedactedJSONField(blank=True, default=dict),
        ),
        migrations.RunPython(redact_existing, migrations.RunPython.noop),
    ]
