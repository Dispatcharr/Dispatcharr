# Generated by Django 5.1.6 on 2025-05-18 15:47

from django.db import migrations, models


def set_user_level_to_10(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.update(user_level=10)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("dispatcharr_channels", "0021_channel_user_level"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="channel_groups",
        ),
        migrations.AddField(
            model_name="user",
            name="channel_profiles",
            field=models.ManyToManyField(
                blank=True,
                related_name="users",
                to="dispatcharr_channels.channelprofile",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="user_level",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="user",
            name="custom_properties",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunPython(set_user_level_to_10),
    ]
