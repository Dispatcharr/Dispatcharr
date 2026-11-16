from django.test import TestCase

from apps.channels.models import Channel, ChannelGroup, ChannelOverride


class ChannelEffectiveScalarFieldsTests(TestCase):
    def setUp(self):
        self.group = ChannelGroup.objects.create(name="Effective Fields")
        self.channel = Channel.objects.create(
            channel_number=1.0,
            name="Provider Name",
            tvg_id="provider.tvg",
            channel_group=self.group,
            auto_created=True,
        )

    def test_without_override_uses_channel_fields(self):
        self.assertEqual(self.channel.get_effective_name(), "Provider Name")
        self.assertEqual(self.channel.get_effective_tvg_id(), "provider.tvg")

    def test_override_wins_for_name_and_tvg_id(self):
        ChannelOverride.objects.create(
            channel=self.channel,
            name="Display Name",
            tvg_id="display.tvg",
        )
        channel = Channel.objects.select_related("override").get(pk=self.channel.pk)
        self.assertEqual(channel.get_effective_name(), "Display Name")
        self.assertEqual(channel.get_effective_tvg_id(), "display.tvg")
        self.assertEqual(channel.name, "Provider Name")
        self.assertEqual(channel.tvg_id, "provider.tvg")

    def test_partial_override_falls_back_per_field(self):
        ChannelOverride.objects.create(
            channel=self.channel,
            name="Display Name Only",
        )
        channel = Channel.objects.select_related("override").get(pk=self.channel.pk)
        self.assertEqual(channel.get_effective_name(), "Display Name Only")
        self.assertEqual(channel.get_effective_tvg_id(), "provider.tvg")

    def test_annotation_name_stays_assignable(self):
        from apps.channels.managers import with_effective_values

        ChannelOverride.objects.create(channel=self.channel, name="Display Name")
        row = with_effective_values(
            Channel.objects.filter(pk=self.channel.pk)
        ).get()
        self.assertEqual(row.effective_name, "Display Name")
        self.assertEqual(row.effective_tvg_id, "provider.tvg")
