# Generated manually for plugin data storage

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('plugins', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PluginData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('collection', models.CharField(db_index=True, help_text="Collection name (e.g., 'calendars', 'events')", max_length=128)),
                ('data', models.JSONField(default=dict, help_text='Arbitrary JSON data for this record')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('plugin', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='data_records', to='plugins.pluginconfig')),
            ],
            options={
                'verbose_name': 'Plugin Data',
                'verbose_name_plural': 'Plugin Data',
            },
        ),
        migrations.AddIndex(
            model_name='plugindata',
            index=models.Index(fields=['plugin', 'collection'], name='plugins_plu_plugin__a3e2c1_idx'),
        ),
    ]
