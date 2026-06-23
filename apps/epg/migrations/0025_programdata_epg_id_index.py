from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class AddIndexConcurrentlyIfPostgres(AddIndexConcurrently):
    """Create the index CONCURRENTLY on PostgreSQL (no table lock on large
    tables), falling back to a normal blocking AddIndex on other backends
    such as the sqlite dev/test fallback."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'postgresql':
            super().database_forwards(app_label, schema_editor, from_state, to_state)
        else:
            migrations.AddIndex.database_forwards(
                self, app_label, schema_editor, from_state, to_state
            )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'postgresql':
            super().database_backwards(app_label, schema_editor, from_state, to_state)
        else:
            migrations.AddIndex.database_backwards(
                self, app_label, schema_editor, from_state, to_state
            )


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ('epg', '0024_remove_epgsource_api_key_epgsource_password_and_more'),
    ]

    operations = [
        AddIndexConcurrentlyIfPostgres(
            model_name='programdata',
            index=models.Index(fields=['epg', 'id'], name='epg_prog_epg_id_idx'),
        ),
    ]
