from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("media_library", "0003_mediafile_requires_transcode_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="libraryscan",
            name="artwork_processed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="libraryscan",
            name="artwork_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("completed", "Completed"),
                    ("skipped", "Skipped"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="libraryscan",
            name="artwork_total",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="libraryscan",
            name="discovery_processed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="libraryscan",
            name="discovery_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("completed", "Completed"),
                    ("skipped", "Skipped"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="libraryscan",
            name="discovery_total",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="libraryscan",
            name="metadata_processed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="libraryscan",
            name="metadata_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("completed", "Completed"),
                    ("skipped", "Skipped"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="libraryscan",
            name="metadata_total",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
