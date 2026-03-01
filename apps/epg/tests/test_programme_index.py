import os
import tempfile
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from apps.epg.models import EPGSource, EPGData
from apps.epg.tasks import find_current_program_for_tvg_id, build_programme_index

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
FIXTURE_XML = os.path.join(FIXTURE_DIR, "test_epg.xml")


class FindCurrentProgramTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.source = EPGSource.objects.create(
            name="Test Source",
            source_type="xmltv",
            url="http://example.com/epg.xml",
            file_path=FIXTURE_XML,
        )
        self.epg = EPGData.objects.create(
            tvg_id="channel.current",
            name="Current Channel",
            epg_source=self.source,
        )

    def test_returns_none_for_dummy_source(self):
        dummy = EPGSource.objects.create(name="Dummy", source_type="dummy")
        epg = EPGData.objects.create(
            tvg_id="x", name="X", epg_source=dummy
        )
        self.assertIsNone(find_current_program_for_tvg_id(epg))

    def test_returns_none_for_schedules_direct_source(self):
        sd = EPGSource.objects.create(
            name="SD", source_type="schedules_direct"
        )
        epg = EPGData.objects.create(
            tvg_id="x", name="X", epg_source=sd
        )
        self.assertIsNone(find_current_program_for_tvg_id(epg))

    def test_returns_none_when_tvg_id_empty(self):
        epg = EPGData.objects.create(
            tvg_id="", name="Empty", epg_source=self.source
        )
        self.assertIsNone(find_current_program_for_tvg_id(epg))

    def test_returns_none_when_tvg_id_none(self):
        epg = EPGData.objects.create(
            tvg_id=None, name="None", epg_source=self.source
        )
        self.assertIsNone(find_current_program_for_tvg_id(epg))

    def test_byte_offset_index_hit(self):
        # Build the index from the fixture
        build_programme_index(self.source.id)
        self.source.refresh_from_db()
        self.assertIsNotNone(self.source.programme_index)

        # "Always On Show" spans 2000-2099, so should always be current
        result = find_current_program_for_tvg_id(self.epg)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Always On Show")
        self.assertEqual(result["sub_title"], "The eternal broadcast")
        self.assertEqual(
            result["description"],
            "This programme spans a very long time for testing",
        )
        self.assertIn("start_time", result)
        self.assertIn("end_time", result)

    def test_byte_offset_index_miss(self):
        # Build index, then query for a tvg_id that exists in the index
        # but has no programme airing now
        build_programme_index(self.source.id)
        self.source.refresh_from_db()

        epg_past = EPGData.objects.create(
            tvg_id="channel.past",
            name="Past Channel",
            epg_source=self.source,
        )
        result = find_current_program_for_tvg_id(epg_past)
        self.assertIsNone(result)

    def test_index_miss_tvg_id_not_in_index(self):
        # tvg_id not in index at all
        build_programme_index(self.source.id)
        self.source.refresh_from_db()

        epg_unknown = EPGData.objects.create(
            tvg_id="channel.nonexistent",
            name="Nonexistent",
            epg_source=self.source,
        )
        result = find_current_program_for_tvg_id(epg_unknown)
        self.assertIsNone(result)

    def test_accepts_integer_id(self):
        # find_current_program_for_tvg_id accepts an int (EPGData PK)
        build_programme_index(self.source.id)
        result = find_current_program_for_tvg_id(self.epg.id)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Always On Show")

    def test_returns_none_for_nonexistent_id(self):
        result = find_current_program_for_tvg_id(99999)
        self.assertIsNone(result)

    def test_multi_block_file(self):
        # Create an XML where programmes for the same channel appear in
        # multiple non-contiguous blocks (A, B, A, B pattern).
        # The index records multiple offsets per channel so the lookup
        # scans all blocks.
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="A"/>\n'
            '  <channel id="B"/>\n'
            '  <programme start="20000101000000 +0000" stop="20000101060000 +0000" channel="A">\n'
            "    <title>A Morning</title>\n"
            "  </programme>\n"
            '  <programme start="20000101000000 +0000" stop="20000101060000 +0000" channel="B">\n'
            "    <title>B Morning</title>\n"
            "  </programme>\n"
            # Second block for A — current programme lives here
            '  <programme start="20000101060000 +0000" stop="20991231235959 +0000" channel="A">\n'
            "    <title>A Current</title>\n"
            "  </programme>\n"
            '  <programme start="20000101060000 +0000" stop="20991231235959 +0000" channel="B">\n'
            "    <title>B Current</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="MultiBlock",
                source_type="xmltv",
                file_path=tmp_path,
            )
            build_programme_index(src.id)
            src.refresh_from_db()
            self.assertIsNotNone(src.programme_index)

            epg_a = EPGData.objects.create(
                tvg_id="A", name="A", epg_source=src
            )
            result = find_current_program_for_tvg_id(epg_a)
            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "A Current")
        finally:
            os.unlink(tmp_path)

    @patch("apps.epg.tasks._sequential_scan_for_tvg_id", return_value="timeout")
    @patch("apps.epg.tasks.build_programme_index_task")
    def test_returns_timeout_when_no_index_and_scan_times_out(
        self, mock_build_task, mock_scan
    ):
        # Source with no index and file on disk
        src = EPGSource.objects.create(
            name="No Index",
            source_type="xmltv",
            file_path=FIXTURE_XML,
            programme_index=None,
        )
        epg = EPGData.objects.create(
            tvg_id="channel.current",
            name="Current",
            epg_source=src,
        )

        mock_redis = MagicMock()
        mock_redis.set.return_value = True
        with patch(
            "core.utils.RedisClient.get_client",
            return_value=mock_redis,
        ):
            result = find_current_program_for_tvg_id(epg)

        self.assertEqual(result, "timeout")
        mock_build_task.delay.assert_called_once_with(src.id)


class BuildProgrammeIndexTests(TestCase):
    def test_builds_index_from_fixture(self):
        source = EPGSource.objects.create(
            name="Index Test",
            source_type="xmltv",
            file_path=FIXTURE_XML,
        )
        build_programme_index(source.id)
        source.refresh_from_db()

        index = source.programme_index
        self.assertIsNotNone(index)
        channels = index["channels"]
        self.assertIn("channel.current", channels)
        self.assertIn("channel.past", channels)
        # channel.empty has no programmes
        self.assertNotIn("channel.empty", channels)

    def test_nonexistent_source_does_not_raise(self):
        # Should log error but not raise
        build_programme_index(99999)
