from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backups", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupjob",
            name="celery_task_id",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
