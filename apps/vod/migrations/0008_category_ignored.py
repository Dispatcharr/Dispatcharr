from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vod", "0007_source_metadata_and_canonical_identity")]
    operations = [
        migrations.AddField(
            model_name="m3uvodcategoryrelation", name="ignored",
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name="m3uvodcategoryrelation",
            constraint=models.CheckConstraint(
                condition=models.Q(ignored=False) | models.Q(enabled=False),
                name="vod_ignored_category_disabled",
            ),
        ),
    ]
