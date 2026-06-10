from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import Channel, Logo
from apps.channels.utils import (
    apply_logos_from_epg_icon_url,
    apply_logos_from_epg_for_source,
    auto_apply_epg_logos_enabled,
    maybe_auto_apply_epg_logos,
)
from apps.epg.models import EPGData, EPGSource

User = get_user_model()


class AutoApplyEpgLogosEnabledTests(TestCase):
    def test_enabled_when_flag_true(self):
        self.assertTrue(
            auto_apply_epg_logos_enabled({'auto_apply_epg_logos': True})
        )

    def test_disabled_when_flag_false_or_missing(self):
        self.assertFalse(
            auto_apply_epg_logos_enabled({'auto_apply_epg_logos': False})
        )
        self.assertFalse(auto_apply_epg_logos_enabled({}))
        self.assertFalse(auto_apply_epg_logos_enabled(None))


class ApplyLogosFromEpgIconUrlTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name='XML EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
        )
        self.epg_one = EPGData.objects.create(
            tvg_id='ch.one',
            name='Channel One',
            icon_url='https://example.com/one.png',
            epg_source=self.source,
        )
        self.epg_two = EPGData.objects.create(
            tvg_id='ch.two',
            name='Channel Two',
            icon_url='https://example.com/one.png',
            epg_source=self.source,
        )
        self.channel_one = Channel.objects.create(
            channel_number=1,
            name='Channel One',
            tvg_id='ch.one',
            epg_data=self.epg_one,
        )
        self.channel_two = Channel.objects.create(
            channel_number=2,
            name='Channel Two',
            tvg_id='ch.two',
            epg_data=self.epg_two,
        )

    def test_creates_logo_and_updates_channels(self):
        channels = Channel.objects.filter(
            id__in=[self.channel_one.id, self.channel_two.id],
        ).select_related('epg_data', 'logo')

        stats = apply_logos_from_epg_icon_url(channels)

        self.assertEqual(stats['updated_count'], 2)
        self.assertEqual(stats['created_logos_count'], 1)
        self.assertEqual(Logo.objects.count(), 1)

        self.channel_one.refresh_from_db()
        self.channel_two.refresh_from_db()
        self.assertEqual(self.channel_one.logo.url, 'https://example.com/one.png')
        self.assertEqual(self.channel_two.logo_id, self.channel_one.logo_id)

    def test_skips_channels_already_using_icon_url(self):
        existing_logo = Logo.objects.create(
            name='Existing',
            url='https://example.com/one.png',
        )
        self.channel_one.logo = existing_logo
        self.channel_one.save(update_fields=['logo'])

        channels = Channel.objects.filter(
            id__in=[self.channel_one.id, self.channel_two.id],
        ).select_related('epg_data', 'logo')

        stats = apply_logos_from_epg_icon_url(channels)

        self.assertEqual(stats['updated_count'], 1)
        self.assertEqual(stats['created_logos_count'], 0)

    def test_skips_channels_without_icon_url(self):
        self.epg_one.icon_url = None
        self.epg_one.save(update_fields=['icon_url'])

        channels = Channel.objects.filter(
            id__in=[self.channel_one.id, self.channel_two.id],
        ).select_related('epg_data', 'logo')

        stats = apply_logos_from_epg_icon_url(channels)

        self.assertEqual(stats['updated_count'], 1)
        self.channel_one.refresh_from_db()
        self.assertIsNone(self.channel_one.logo_id)


class ApplyLogosForSourceTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name='XML EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
        )
        self.other_source = EPGSource.objects.create(
            name='Other EPG',
            source_type='xmltv',
            url='http://example.com/other.xml',
        )
        self.epg = EPGData.objects.create(
            tvg_id='mapped',
            name='Mapped',
            icon_url='https://example.com/mapped.png',
            epg_source=self.source,
        )
        self.other_epg = EPGData.objects.create(
            tvg_id='other',
            name='Other',
            icon_url='https://example.com/other.png',
            epg_source=self.other_source,
        )
        self.mapped_channel = Channel.objects.create(
            channel_number=1,
            name='Mapped',
            tvg_id='mapped',
            epg_data=self.epg,
        )
        Channel.objects.create(
            channel_number=2,
            name='Other',
            tvg_id='other',
            epg_data=self.other_epg,
        )

    def test_only_updates_channels_mapped_to_source(self):
        stats = apply_logos_from_epg_for_source(self.source)

        self.assertEqual(stats['updated_count'], 1)
        self.mapped_channel.refresh_from_db()
        self.assertEqual(
            self.mapped_channel.logo.url,
            'https://example.com/mapped.png',
        )

    def test_processes_source_in_batches(self):
        stats = apply_logos_from_epg_for_source(self.source, batch_size=1)

        self.assertEqual(stats['updated_count'], 1)
        self.mapped_channel.refresh_from_db()
        self.assertEqual(
            self.mapped_channel.logo.url,
            'https://example.com/mapped.png',
        )


class MaybeAutoApplyEpgLogosTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name='XML EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
            custom_properties={'auto_apply_epg_logos': True},
        )
        self.epg = EPGData.objects.create(
            tvg_id='mapped',
            name='Mapped',
            icon_url='https://example.com/mapped.png',
            epg_source=self.source,
        )
        self.channel = Channel.objects.create(
            channel_number=1,
            name='Mapped',
            tvg_id='mapped',
            epg_data=self.epg,
        )

    def test_runs_when_enabled(self):
        stats = maybe_auto_apply_epg_logos(self.source)
        self.assertEqual(stats['updated_count'], 1)
        self.channel.refresh_from_db()
        self.assertIsNotNone(self.channel.logo_id)

    def test_skips_when_disabled(self):
        self.source.custom_properties = {'auto_apply_epg_logos': False}
        self.source.save(update_fields=['custom_properties'])

        stats = maybe_auto_apply_epg_logos(self.source)
        self.assertIsNone(stats)
        self.channel.refresh_from_db()
        self.assertIsNone(self.channel.logo_id)

class SetLogosFromEpgApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = '/api/channels/channels/set-logos-from-epg/'

        self.source = EPGSource.objects.create(
            name='XML EPG',
            source_type='xmltv',
            url='http://example.com/epg.xml',
        )
        self.epg = EPGData.objects.create(
            tvg_id='mapped',
            name='Mapped',
            icon_url='https://example.com/mapped.png',
            epg_source=self.source,
        )
        self.channel = Channel.objects.create(
            channel_number=1,
            name='Mapped',
            tvg_id='mapped',
            epg_data=self.epg,
        )

    @patch('apps.channels.tasks.set_channels_logos_from_epg.delay')
    def test_accepts_channel_ids(self, mock_delay):
        mock_delay.return_value.id = 'task-1'

        response = self.client.post(
            self.url,
            {'channel_ids': [self.channel.id]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_delay.assert_called_once_with(channel_ids=[self.channel.id])

    @patch('apps.channels.tasks.set_channels_logos_from_epg.delay')
    def test_accepts_epg_source_id(self, mock_delay):
        mock_delay.return_value.id = 'task-2'

        response = self.client.post(
            self.url,
            {'epg_source_id': self.source.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_delay.assert_called_once_with(epg_source_id=self.source.id)
        self.assertEqual(response.data['channel_count'], 1)

    def test_rejects_both_parameters(self):
        response = self.client.post(
            self.url,
            {
                'channel_ids': [self.channel.id],
                'epg_source_id': self.source.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
