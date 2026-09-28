from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, ChannelOverride
from apps.epg.models import EPGData, EPGSource
from apps.epg.utils import (
    DEFAULT_EPG_RETENTION_DAYS,
    MAX_EPG_RETENTION_DAYS,
    epg_retention_cutoffs,
)


class EpgRetentionCutoffsTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name='Retention Cutoff Test',
            source_type='xmltv',
        )
        self.now = timezone.now().replace(microsecond=0)

    def _epg(self, tvg_id):
        return EPGData.objects.create(
            epg_source=self.source,
            tvg_id=tvg_id,
            name=tvg_id,
        )

    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(epg_retention_cutoffs([]), {})

    def test_defaults_to_the_floor_with_no_catchup_channel(self):
        epg = self._epg('plain')
        Channel.objects.create(channel_number=1, name='Plain', epg_data=epg)

        cutoffs = epg_retention_cutoffs([epg.id], now=self.now)

        self.assertEqual(
            cutoffs[epg.id], self.now - timedelta(days=DEFAULT_EPG_RETENTION_DAYS)
        )

    def test_defaults_to_the_floor_with_no_channel_at_all(self):
        epg = self._epg('orphaned')

        cutoffs = epg_retention_cutoffs([epg.id], now=self.now)

        self.assertEqual(
            cutoffs[epg.id], self.now - timedelta(days=DEFAULT_EPG_RETENTION_DAYS)
        )

    def test_uses_channel_catchup_days(self):
        epg = self._epg('catchup')
        Channel.objects.create(
            channel_number=1,
            name='Catchup',
            epg_data=epg,
            is_catchup=True,
            catchup_days=7,
        )

        cutoffs = epg_retention_cutoffs([epg.id], now=self.now)

        self.assertEqual(cutoffs[epg.id], self.now - timedelta(days=7))

    def test_zero_catchup_days_still_gets_the_floor(self):
        epg = self._epg('zero-days')
        Channel.objects.create(
            channel_number=1,
            name='Zero Days',
            epg_data=epg,
            is_catchup=True,
            catchup_days=0,
        )

        cutoffs = epg_retention_cutoffs([epg.id], now=self.now)

        self.assertEqual(
            cutoffs[epg.id], self.now - timedelta(days=DEFAULT_EPG_RETENTION_DAYS)
        )

    def test_caps_at_the_maximum(self):
        epg = self._epg('long-catchup')
        Channel.objects.create(
            channel_number=1,
            name='Long Catchup',
            epg_data=epg,
            is_catchup=True,
            catchup_days=365,
        )

        cutoffs = epg_retention_cutoffs([epg.id], now=self.now)

        self.assertEqual(
            cutoffs[epg.id], self.now - timedelta(days=MAX_EPG_RETENTION_DAYS)
        )

    def test_uses_the_largest_catchup_days_among_channels_sharing_an_epg(self):
        epg = self._epg('shared')
        Channel.objects.create(
            channel_number=1,
            name='Short Catchup',
            epg_data=epg,
            is_catchup=True,
            catchup_days=2,
        )
        Channel.objects.create(
            channel_number=2,
            name='Long Catchup',
            epg_data=epg,
            is_catchup=True,
            catchup_days=10,
        )

        cutoffs = epg_retention_cutoffs([epg.id], now=self.now)

        self.assertEqual(cutoffs[epg.id], self.now - timedelta(days=10))

    def test_disabled_catchup_channel_does_not_extend_the_floor(self):
        epg = self._epg('disabled')
        Channel.objects.create(
            channel_number=1,
            name='Disabled',
            epg_data=epg,
            is_catchup=False,
            catchup_days=30,
        )

        cutoffs = epg_retention_cutoffs([epg.id], now=self.now)

        self.assertEqual(
            cutoffs[epg.id], self.now - timedelta(days=DEFAULT_EPG_RETENTION_DAYS)
        )

    def test_computes_cutoffs_independently_per_epg(self):
        plain = self._epg('plain-2')
        Channel.objects.create(channel_number=1, name='Plain 2', epg_data=plain)
        catchup = self._epg('catchup-2')
        Channel.objects.create(
            channel_number=2,
            name='Catchup 2',
            epg_data=catchup,
            is_catchup=True,
            catchup_days=5,
        )

        cutoffs = epg_retention_cutoffs([plain.id, catchup.id], now=self.now)

        self.assertEqual(
            cutoffs[plain.id], self.now - timedelta(days=DEFAULT_EPG_RETENTION_DAYS)
        )
        self.assertEqual(cutoffs[catchup.id], self.now - timedelta(days=5))

    def test_uses_catchup_days_from_an_override_only_mapping(self):
        """A channel reaching this epg only through ChannelOverride still counts."""
        own_epg = self._epg('own')
        override_epg = self._epg('override-target')
        channel = Channel.objects.create(
            channel_number=1,
            name='Override Redirected',
            epg_data=own_epg,
            is_catchup=True,
            catchup_days=9,
        )
        ChannelOverride.objects.create(channel=channel, epg_data=override_epg)

        cutoffs = epg_retention_cutoffs([own_epg.id, override_epg.id], now=self.now)

        self.assertEqual(cutoffs[override_epg.id], self.now - timedelta(days=9))
        # The channel's own epg_data is no longer its effective epg once the
        # override redirects it, so it must not also inflate own_epg's window.
        self.assertEqual(
            cutoffs[own_epg.id], self.now - timedelta(days=DEFAULT_EPG_RETENTION_DAYS)
        )
