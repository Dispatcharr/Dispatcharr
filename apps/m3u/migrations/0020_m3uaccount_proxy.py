# Generated migration for adding proxy field to M3UAccount

from django.db import migrations


def add_proxy_field_if_not_exists(apps, schema_editor):
    """Add proxy field only if it doesn't exist (idempotent)"""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='m3u_m3uaccount' AND column_name='proxy'
        """)
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE m3u_m3uaccount
                ADD COLUMN proxy varchar(255) NULL
            """)


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0019_m3uaccountprofile_exp_date'),
    ]

    operations = [
        migrations.RunPython(add_proxy_field_if_not_exists, migrations.RunPython.noop),
    ]
