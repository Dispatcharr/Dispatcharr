# Generated migration for proxy field
from django.db import migrations, models


def add_proxy_field(apps, schema_editor):
    """Idempotent migration - checks if column exists before adding"""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_name='m3u_m3uaccount' AND column_name='proxy'
        """)
        exists = cursor.fetchone()[0] > 0
    
    if not exists:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("""
                ALTER TABLE m3u_m3uaccount 
                ADD COLUMN proxy VARCHAR(255) DEFAULT '' NULL
            """)


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0019_m3uaccountprofile_exp_date'),
    ]

    operations = [
        migrations.RunPython(add_proxy_field, migrations.RunPython.noop),
    ]
