import uuid

from django.db import migrations, models


def initialize_revision(apps, schema_editor):
    revision = apps.get_model("epg", "EPGRevision")
    revision.objects.using(schema_editor.connection.alias).get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [
        ("epg", "0027_programdata_epg_start_end_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="EPGRevision",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("revision", models.UUIDField(default=uuid.uuid4, editable=False)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=models.Q(id=1), name="epg_revision_singleton"),
                ],
            },
        ),
        migrations.RunPython(initialize_revision, migrations.RunPython.noop),
    ]
