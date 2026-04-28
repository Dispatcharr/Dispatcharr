from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_user_stream_limit'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='xc_allowed_ips',
            field=models.TextField(blank=True, default=''),
        ),
    ]
