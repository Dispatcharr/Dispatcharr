# Generated manually for plugin storage infrastructure

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plugins', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PluginDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plugin_key', models.CharField(db_index=True, help_text='Plugin key that owns this document', max_length=128)),
                ('collection', models.CharField(db_index=True, help_text='Collection name (like a table name)', max_length=128)),
                ('doc_id', models.CharField(help_text='Document ID within the collection', max_length=255)),
                ('data', models.JSONField(default=dict, help_text='Document data as JSON')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Plugin Document',
                'verbose_name_plural': 'Plugin Documents',
            },
        ),
        migrations.AddIndex(
            model_name='plugindocument',
            index=models.Index(fields=['plugin_key', 'collection'], name='plugins_plu_plugin__a1b2c3_idx'),
        ),
        migrations.AddConstraint(
            model_name='plugindocument',
            constraint=models.UniqueConstraint(fields=['plugin_key', 'collection', 'doc_id'], name='unique_plugin_document'),
        ),
    ]
