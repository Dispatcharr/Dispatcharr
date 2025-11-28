# Generated migration for HLS Output

import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('channels', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='HLSOutputProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, help_text='Profile name')),
                ('description', models.TextField(blank=True, help_text='Profile description')),
                ('segment_duration', models.IntegerField(default=4, help_text='Segment duration in seconds (2-10)')),
                ('max_playlist_segments', models.IntegerField(default=10, help_text='Maximum segments in playlist')),
                ('segment_format', models.CharField(
                    max_length=10,
                    choices=[('mpegts', 'MPEG-TS'), ('fmp4', 'Fragmented MP4')],
                    default='mpegts',
                    help_text='Segment container format'
                )),
                ('playlist_type', models.CharField(
                    max_length=10,
                    choices=[('live', 'Live'), ('event', 'Event (DVR)'), ('vod', 'VOD')],
                    default='event',
                    help_text='Playlist type'
                )),
                ('dvr_window_seconds', models.IntegerField(default=7200, help_text='DVR window in seconds (0 = disabled)')),
                ('enable_abr', models.BooleanField(default=True, help_text='Enable adaptive bitrate streaming')),
                ('qualities', models.JSONField(default=list, help_text='Quality ladder configuration')),
                ('enable_ll_hls', models.BooleanField(default=False, help_text='Enable Low-Latency HLS')),
                ('partial_segment_duration', models.FloatField(default=0.33, help_text='Partial segment duration for LL-HLS')),
                ('storage_path', models.CharField(max_length=255, default='/var/www/hls', help_text='Base storage path')),
                ('use_memory_storage', models.BooleanField(default=False, help_text='Use memory storage (/dev/shm)')),
                ('auto_cleanup', models.BooleanField(default=True, help_text='Automatically cleanup old segments')),
                ('cleanup_interval_seconds', models.IntegerField(default=60, help_text='Cleanup interval in seconds')),
                ('enable_auto_restart', models.BooleanField(default=True, help_text='Auto-restart on errors')),
                ('playlist_cache_ttl', models.IntegerField(default=2, help_text='Playlist cache TTL in seconds')),
                ('segment_cache_ttl', models.IntegerField(default=86400, help_text='Segment cache TTL in seconds')),
                ('enable_cdn', models.BooleanField(default=False, help_text='Enable CDN integration')),
                ('cdn_base_url', models.URLField(blank=True, help_text='CDN base URL')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'HLS Output Profile',
                'verbose_name_plural': 'HLS Output Profiles',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='HLSStream',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stream_id', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
                ('channel', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hls_streams', to='channels.channel')),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='streams', to='hls_output.hlsoutputprofile')),
                ('status', models.CharField(
                    max_length=20,
                    choices=[
                        ('starting', 'Starting'),
                        ('running', 'Running'),
                        ('stopping', 'Stopping'),
                        ('stopped', 'Stopped'),
                        ('error', 'Error'),
                        ('cleaned', 'Cleaned')
                    ],
                    default='starting'
                )),
                ('ffmpeg_pid', models.IntegerField(null=True, blank=True)),
                ('ffmpeg_command', models.TextField(blank=True)),
                ('current_sequence', models.IntegerField(default=0)),
                ('total_segments_generated', models.BigIntegerField(default=0)),
                ('viewer_count', models.IntegerField(default=0)),
                ('total_bytes_generated', models.BigIntegerField(default=0)),
                ('start_time', models.DateTimeField(auto_now_add=True)),
                ('last_segment_time', models.DateTimeField(null=True, blank=True)),
                ('restart_count', models.IntegerField(default=0)),
                ('error_message', models.TextField(blank=True)),
                ('dvr_start_sequence', models.IntegerField(default=0)),
                ('dvr_end_sequence', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'HLS Stream',
                'verbose_name_plural': 'HLS Streams',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='HLSSegment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stream', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='segments', to='hls_output.hlsstream')),
                ('sequence_number', models.IntegerField()),
                ('quality_level', models.CharField(max_length=20)),
                ('filename', models.CharField(max_length=255)),
                ('file_path', models.CharField(max_length=512)),
                ('file_size', models.BigIntegerField(default=0)),
                ('duration', models.FloatField()),
                ('program_date_time', models.DateTimeField()),
                ('marked_for_deletion', models.BooleanField(default=False)),
                ('deleted_at', models.DateTimeField(null=True, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'HLS Segment',
                'verbose_name_plural': 'HLS Segments',
                'ordering': ['stream', 'quality_level', 'sequence_number'],
                'indexes': [
                    models.Index(fields=['stream', 'quality_level', 'sequence_number'], name='hls_segment_idx'),
                    models.Index(fields=['stream', 'marked_for_deletion'], name='hls_cleanup_idx'),
                ],
            },
        ),
    ]

