import json

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def forwards_copy_app_data(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    UserAppData = apps.get_model("accounts", "UserAppData")
    rows = []
    for user in User.objects.exclude(app_data={}).iterator():
        blob = user.app_data or {}
        if not isinstance(blob, dict):
            continue
        for key, value in blob.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            try:
                byte_size = len(
                    json.dumps(
                        value,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode("utf-8")
                )
            except (TypeError, ValueError):
                continue
            rows.append(
                UserAppData(
                    user_id=user.pk,
                    key=key[:64],
                    value=value,
                    byte_size=byte_size,
                )
            )
        if len(rows) >= 500:
            UserAppData.objects.bulk_create(rows, ignore_conflicts=True)
            rows = []
    if rows:
        UserAppData.objects.bulk_create(rows, ignore_conflicts=True)


def backwards_copy_app_data(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    UserAppData = apps.get_model("accounts", "UserAppData")
    by_user = {}
    for entry in UserAppData.objects.all().iterator():
        by_user.setdefault(entry.user_id, {})[entry.key] = entry.value
    for user_id, blob in by_user.items():
        User.objects.filter(pk=user_id).update(app_data=blob)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_user_app_data"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserAppData",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=64)),
                ("value", models.JSONField(default=dict)),
                ("byte_size", models.PositiveIntegerField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="app_data_entries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["key"],
            },
        ),
        migrations.AddConstraint(
            model_name="userappdata",
            constraint=models.UniqueConstraint(
                fields=("user", "key"),
                name="uniq_accounts_user_app_data_key",
            ),
        ),
        migrations.RunPython(forwards_copy_app_data, backwards_copy_app_data),
        migrations.RemoveField(
            model_name="user",
            name="app_data",
        ),
    ]
