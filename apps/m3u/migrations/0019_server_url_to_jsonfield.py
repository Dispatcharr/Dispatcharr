# Generated migration for server_url field change to JSONField with failover support

from django.db import migrations, models


def convert_url_to_list(apps, schema_editor):
    """Convert existing single URL strings to single-element arrays."""
    M3UAccount = apps.get_model('m3u', 'M3UAccount')
    for account in M3UAccount.objects.all():
        if account.server_url:
            # If it's already a list (shouldn't happen, but be safe), skip
            if isinstance(account.server_url, list):
                continue
            # Convert string URL to single-element list
            account.server_url = [account.server_url]
            account.save(update_fields=['server_url'])
        else:
            # Set empty list for null/empty values
            account.server_url = []
            account.save(update_fields=['server_url'])


def convert_list_to_url(apps, schema_editor):
    """Reverse migration: Convert list back to single URL string."""
    M3UAccount = apps.get_model('m3u', 'M3UAccount')
    for account in M3UAccount.objects.all():
        if account.server_url and isinstance(account.server_url, list):
            # Take the first URL if available
            account.server_url = account.server_url[0] if account.server_url else None
            account.save(update_fields=['server_url'])


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0018_add_profile_custom_properties'),
    ]

    operations = [
        # First, alter the field type to JSONField
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
        # Then run the data migration to convert existing data
        migrations.RunPython(convert_url_to_list, convert_list_to_url),
    ]
