from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0026_epgsourceindex'),
    ]

    operations = [
        migrations.AddField(
            model_name='epgdata',
            name='lineup',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
