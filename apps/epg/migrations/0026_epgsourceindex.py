import django.db.models.deletion
from django.db import migrations, models


def copy_index_forward(apps, schema_editor):
    EPGSource = apps.get_model('epg', 'EPGSource')
    EPGSourceIndex = apps.get_model('epg', 'EPGSourceIndex')
    rows = list(
        EPGSource.objects.exclude(programme_index__isnull=True).values_list(
            'id', 'programme_index'
        )
    )
    for source_id, data in rows:
        EPGSourceIndex.objects.update_or_create(
            source_id=source_id, defaults={'data': data}
        )


def copy_index_backward(apps, schema_editor):
    EPGSource = apps.get_model('epg', 'EPGSource')
    EPGSourceIndex = apps.get_model('epg', 'EPGSourceIndex')
    for source_id, data in EPGSourceIndex.objects.values_list('source_id', 'data'):
        EPGSource.objects.filter(id=source_id).update(programme_index=data)


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0025_programdata_epg_id_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='EPGSourceIndex',
            fields=[
                ('source', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,
                    related_name='index_record',
                    serialize=False,
                    to='epg.epgsource',
                )),
                ('data', models.JSONField(blank=True, default=None, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.RunPython(copy_index_forward, copy_index_backward),
        migrations.RemoveField(
            model_name='epgsource',
            name='programme_index',
        ),
    ]
