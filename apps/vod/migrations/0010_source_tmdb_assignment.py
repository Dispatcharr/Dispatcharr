from typing import ClassVar

from django.db import migrations, models


def preserve_library_assignments(apps, schema_editor):
    for kind in ("Movie", "Series"):
        canonical = apps.get_model("vod", kind)
        source = apps.get_model("vod", f"M3U{kind}Relation")
        field = kind.lower()
        target = (
            canonical.objects.using(schema_editor.connection.alias)
            .filter(
                pk=models.OuterRef(f"{field}_id"),
            )
            .values("tmdb_match_id")[:1]
        )
        source.objects.using(schema_editor.connection.alias).exclude(
            **{f"{field}__tmdb_match_id": ""},
        ).update(tmdb_override_id=models.Subquery(target))


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("vod", "0009_library_metadata")]
    operations = [
        migrations.AddField(
            model_name=name,
            name="tmdb_override_id",
            field=models.CharField(
                max_length=50, blank=True, default="", db_default="", db_index=True
            ),
        )
        for name in ("m3umovierelation", "m3useriesrelation")
    ] + [migrations.RunPython(preserve_library_assignments, migrations.RunPython.noop)]
