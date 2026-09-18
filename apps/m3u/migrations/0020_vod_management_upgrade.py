import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('django_celery_beat', '0019_alter_periodictasks_options'),
        ('m3u', '0019_m3uaccountprofile_exp_date'),
    ]

    operations = [
        migrations.CreateModel(
            name='M3UGroupRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scope', models.CharField(choices=[('live', 'Live TV'), ('movie', 'VOD Movies'), ('series', 'VOD Series')], max_length=10)),
                ('match_field', models.CharField(choices=[('group_name', 'Group name'), ('item_name', 'Contained item name')], default='group_name', max_length=20)),
                ('match_mode', models.CharField(choices=[('any', 'Any item'), ('all', 'All items')], default='any', help_text='Used only when matching contained item names.', max_length=10)),
                ('regex_pattern', models.CharField(max_length=500)),
                ('action', models.CharField(choices=[('enable', 'Enable'), ('disable', 'Import disabled'), ('ignore', 'Ignore')], default='disable', max_length=10)),
                ('case_sensitive', models.BooleanField(default=False)),
                ('enabled', models.BooleanField(default=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('m3u_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='group_rules', to='m3u.m3uaccount')),
                ('exclude_regex_pattern', models.CharField(blank=True, default='', help_text='Optional regular expression which vetoes an otherwise matching rule.', max_length=500)),
                ('metadata_defaults', models.JSONField(blank=True, default=dict, help_text='Default VOD source metadata assigned to newly discovered matching categories.')),
            ],
            options={
                'ordering': ('scope', 'order', 'id'),
                'indexes': [models.Index(fields=['m3u_account', 'scope', 'enabled', 'order'], name='m3u_group_rule_lookup_idx')],
            },
        ),
        migrations.CreateModel(
            name='M3UAccountTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('description', models.TextField(blank=True, default='')),
                ('account_type', models.CharField(choices=[('STD', 'Standard'), ('XC', 'Xtream Codes')], default='XC', max_length=3)),
                ('account_settings', models.JSONField(blank=True, default=dict)),
                ('filters', models.JSONField(blank=True, default=list)),
                ('group_rules', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ('name', 'id'),
            },
        ),
        migrations.AddField(
            model_name='m3uaccount',
            name='vod_refresh_after_live',
            field=models.BooleanField(default=True, help_text='Refresh VOD after every successful Live TV refresh instead of using the separate VOD schedule.'),
        ),
        migrations.AddField(
            model_name='m3uaccount',
            name='vod_refresh_interval',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='m3uaccount',
            name='vod_refresh_task',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='django_celery_beat.periodictask'),
        ),
        migrations.AddField(
            model_name='m3uaccount',
            name='xc_live_refresh_min_age_minutes',
            field=models.PositiveIntegerField(default=55, help_text='Minimum age of the last successful Live TV refresh before an XC client request may queue another one. Use 0 to always allow it.', validators=[django.core.validators.MaxValueValidator(10080)]),
        ),
    ]
