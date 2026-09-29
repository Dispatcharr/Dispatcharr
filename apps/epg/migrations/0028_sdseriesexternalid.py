from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0027_programdata_epg_start_end_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='SDSeriesExternalID',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('series_key', models.CharField(help_text='SD programID prefix + root, e.g. SH01258333 or MV00123456', max_length=16, unique=True)),
                ('tmdb_id', models.CharField(blank=True, max_length=32, null=True)),
                ('tmdb_type', models.CharField(blank=True, help_text="TMDB media type for tmdb_id: 'tv' or 'movie'", max_length=8, null=True)),
                ('imdb_id', models.CharField(blank=True, max_length=32, null=True)),
                ('tvdb_id', models.CharField(blank=True, max_length=32, null=True)),
                ('attempted_at', models.DateTimeField(help_text='Last TMDB search, used to back off retries for unmatched entries')),
            ],
        ),
    ]
