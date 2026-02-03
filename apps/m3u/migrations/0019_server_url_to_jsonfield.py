# Migration for server_url field change to JSONField with failover support
#
# This migration converts the server_url field from URLField (VARCHAR) to JSONField
# to support multiple failover URLs stored as a JSON array.
#
# IMPORTANT: The order of operations is critical:
# 1. First convert data to valid JSON format (while still VARCHAR)
# 2. Then change the column type to JSONB
#
# Rollback preserves only the first URL if multiple were stored.

from django.db import migrations, models, connection


def convert_url_to_json_string(apps, schema_editor):
    """
    Convert existing single URL strings to JSON array strings.

    This runs BEFORE the field type change, so the column is still VARCHAR.
    We store the data as JSON-formatted strings that will be valid when
    the column type changes to JSONB.
    """
    M3UAccount = apps.get_model('m3u', 'M3UAccount')

    accounts_to_update = []
    for account in M3UAccount.objects.all():
        if account.server_url:
            # Skip if already looks like a JSON array (idempotency)
            if isinstance(account.server_url, list):
                continue
            if isinstance(account.server_url, str) and account.server_url.startswith('['):
                continue
            # Convert string URL to JSON array string: "url" -> '["url"]'
            import json
            account.server_url = json.dumps([account.server_url])
            accounts_to_update.append(account)
        else:
            # Set empty JSON array for null/empty values
            account.server_url = '[]'
            accounts_to_update.append(account)

    # Bulk update for better performance
    if accounts_to_update:
        M3UAccount.objects.bulk_update(accounts_to_update, ['server_url'], batch_size=500)


def convert_json_to_url_string(apps, schema_editor):
    """
    Reverse migration: Convert JSON array back to single URL string.

    NOTE: This only preserves the first URL if multiple were stored.
    Data loss will occur if the account had multiple failover URLs.
    """
    M3UAccount = apps.get_model('m3u', 'M3UAccount')

    accounts_to_update = []
    for account in M3UAccount.objects.all():
        if account.server_url:
            import json
            # Handle both list (after JSONB) and string (during rollback) formats
            if isinstance(account.server_url, list):
                urls = account.server_url
            elif isinstance(account.server_url, str):
                try:
                    urls = json.loads(account.server_url)
                except json.JSONDecodeError:
                    # Already a plain URL string
                    continue
            else:
                continue

            # Take the first URL, or None if empty
            account.server_url = urls[0] if urls else None
            accounts_to_update.append(account)

    # Bulk update for better performance
    if accounts_to_update:
        M3UAccount.objects.bulk_update(accounts_to_update, ['server_url'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0018_add_profile_custom_properties'),
    ]

    operations = [
        # Step 1: Convert existing data to JSON format (while still VARCHAR)
        # This ensures the data is valid JSON before the type change
        migrations.RunPython(
            convert_url_to_json_string,
            convert_json_to_url_string,
        ),

        # Step 2: Change the field type to JSONField
        # PostgreSQL will cast the JSON-formatted strings to JSONB
        migrations.AlterField(
            model_name='m3uaccount',
            name='server_url',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='List of server URLs with failover support. Enter as pipe-separated URLs.',
                null=True,
            ),
        ),
    ]
