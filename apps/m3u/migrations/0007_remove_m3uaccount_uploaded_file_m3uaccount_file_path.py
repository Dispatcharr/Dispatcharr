# Generated by Django 5.1.6 on 2025-04-06 19:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0006_populate_periodic_tasks'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='m3uaccount',
            name='uploaded_file',
        ),
        migrations.AddField(
            model_name='m3uaccount',
            name='file_path',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
