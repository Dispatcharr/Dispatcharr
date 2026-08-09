from django.db import migrations, models


def backfill_movie_is_adult(apps, schema_editor):
    """Set Movie.is_adult from provider flags stored on relation basic_data."""
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            # ->> yields text for both JSON number 1 and string "1".
            cursor.execute(
                """
                UPDATE vod_movie AS m
                SET is_adult = TRUE
                WHERE EXISTS (
                    SELECT 1
                    FROM vod_m3umovierelation AS r
                    WHERE r.movie_id = m.id
                      AND (r.custom_properties->'basic_data'->>'is_adult') = '1'
                )
                """
            )
        return

    Movie = apps.get_model('vod', 'Movie')
    M3UMovieRelation = apps.get_model('vod', 'M3UMovieRelation')

    adult_movie_ids = set()
    for rel in (
        M3UMovieRelation.objects.exclude(custom_properties=None)
        .only('movie_id', 'custom_properties')
        .iterator(chunk_size=2000)
    ):
        basic = (rel.custom_properties or {}).get('basic_data') or {}
        try:
            if int(basic.get('is_adult', 0)) == 1:
                adult_movie_ids.add(rel.movie_id)
        except (TypeError, ValueError):
            continue

    if adult_movie_ids:
        Movie.objects.filter(id__in=adult_movie_ids).update(is_adult=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vod', '0004_m3uepisoderelation_series_relation'),
    ]

    operations = [
        migrations.AddField(
            model_name='movie',
            name='is_adult',
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text='Whether this movie contains adult content',
            ),
        ),
        migrations.RunPython(backfill_movie_is_adult, noop_reverse),
    ]
