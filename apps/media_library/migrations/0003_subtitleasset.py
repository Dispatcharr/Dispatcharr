from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("media_library", "0002_mediaitem_is_missing"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubtitleAsset",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("language", models.CharField(max_length=16, blank=True)),
                ("is_forced", models.BooleanField(default=False)),
                ("source", models.CharField(max_length=64, blank=True)),
                ("file_path", models.CharField(max_length=4096, blank=True)),
                ("external_url", models.URLField(blank=True)),
                (
                    "format",
                    models.CharField(
                        max_length=8,
                        choices=[("srt", "SRT"), ("vtt", "WebVTT")],
                        default="srt",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "media_item",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="subtitles",
                        to="media_library.mediaitem",
                    ),
                ),
            ],
            options={
                "ordering": ["media_item", "language", "created_at"],
                "unique_together": {("media_item", "language", "source", "format")},
            },
        ),
    ]
