import os
import gzip
import tempfile
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.epg.models import EPGSource, EPGData
from apps.epg.tasks import (
    find_current_program_for_tvg_id,
    build_programme_index,
    build_programme_index_task,
    _EPG_TVG_PARSE_DEFER_SECONDS,
)

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

    def test_channel_id_entities_and_whitespace_match_tvg_id(self):
        # programme@channel carries an XML entity and surrounding whitespace;
        # EPGData.tvg_id holds the lxml-decoded, stripped form. The index key
        # and lookup must canonicalize to the same value.
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="A&amp;E.us"/>\n'
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel=" A&amp;E.us ">\n'
            "    <title>A and E Now</title>\n"
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
                name="Entities", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()
            self.assertIn("A&E.us", src.programme_index["channels"])

            epg = EPGData.objects.create(
                tvg_id="A&E.us", name="A&E", epg_source=src
            )
            result = find_current_program_for_tvg_id(epg)
            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "A and E Now")
        finally:
            os.unlink(tmp_path)

    def test_offset_lookup_resolves_named_html_entities_in_programme_text(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="entity.channel"/>\n'
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="entity.channel">\n'
            "    <title>Caf&eacute; Live</title>\n"
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
                name="Named Entities", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)

            epg = EPGData.objects.create(
                tvg_id="entity.channel", name="Entity Channel", epg_source=src
            )
            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "Caf\u00e9 Live")
        finally:
            os.unlink(tmp_path)

    def test_epgshare_fr_style_programme_with_channel_first_and_apostrophe_entities(self):
        # Based on epgshare01 FR feeds: channel is the first programme attr,
        # ids/text include non-ASCII plus XML entities, and sub-title is common.
        tvg_id = "France.3.-.C\u00f4te.d'Azur.fr"
        xml = (
            '<?xml version="1.0" encoding="UTF-8" ?>\n'
            '<tv generator-info-name="none" generator-info-url="none">\n'
            '  <channel id="France.3.-.C\u00f4te.d&apos;Azur.fr">\n'
            '    <display-name lang="fr">France 3 - C\u00f4te d&apos;Azur</display-name>\n'
            "  </channel>\n"
            '  <programme channel="France.3.-.C\u00f4te.d&apos;Azur.fr" '
            'start="20000101000000 +0000" stop="20991231235959 +0000">\n'
            "    <title lang=\"fr\">La p&apos;tite librairie</title>\n"
            "    <sub-title lang=\"fr\">Le Lys de Brooklyn, de Betty Smith</sub-title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-8", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="EPGShare FR", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()
            self.assertIn(tvg_id, src.programme_index["channels"])

            epg = EPGData.objects.create(
                tvg_id=tvg_id, name="France 3 Cote d'Azur", epg_source=src
            )
            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "La p'tite librairie")
            self.assertEqual(
                result["sub_title"], "Le Lys de Brooklyn, de Betty Smith"
            )
        finally:
            os.unlink(tmp_path)

    def test_epgshare_fr_style_description_decodes_predefined_entities(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8" ?>\n'
            "<tv>\n"
            '  <channel id="Chasse.et.P\u00eache.fr"/>\n'
            '  <programme channel="Chasse.et.P\u00eache.fr" '
            'start="20000101000000 +0000" stop="20991231235959 +0000">\n'
            "    <title lang=\"fr\">Chasse &amp; p\u00eache, le mag</title>\n"
            "    <desc lang=\"fr\">Au sommaire : &quot;La r\u00e9gion&quot; &lt;HD&gt; &amp; bonus.</desc>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-8", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="EPGShare FR Entities", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)

            epg = EPGData.objects.create(
                tvg_id="Chasse.et.P\u00eache.fr",
                name="Chasse et Peche",
                epg_source=src,
            )
            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "Chasse & p\u00eache, le mag")
            self.assertEqual(
                result["description"],
                'Au sommaire : "La r\u00e9gion" <HD> & bonus.',
            )
        finally:
            os.unlink(tmp_path)

    def test_epgshare_all_sources_style_start_stop_before_channel(self):
        # The all-sources EPG contains both programme attr orders:
        # channel/start/stop and start/stop/channel.
        tvg_id = "Atfal.&.Mawaheb.ae"
        xml = (
            '<?xml version="1.0" encoding="UTF-8" ?>\n'
            "<tv>\n"
            '  <channel id="Atfal.&amp;.Mawaheb.ae"/>\n'
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="Atfal.&amp;.Mawaheb.ae">\n'
            "    <title lang=\"en\">Kids &amp; Talent</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-8", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="EPGShare All Sources", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()
            self.assertIn(tvg_id, src.programme_index["channels"])

            epg = EPGData.objects.create(
                tvg_id=tvg_id, name="Atfal and Mawaheb", epg_source=src
            )
            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "Kids & Talent")
        finally:
            os.unlink(tmp_path)

    def test_jesmann_fullguide_style_numeric_channel_id(self):
        # FullGuide.xml.gz uses numeric channel ids and consistently orders
        # programme attrs as start/stop/channel.
        xml = (
            '<?xml version="1.0" encoding="UTF-8" ?>\n'
            "<tv>\n"
            '  <channel id="123958">\n'
            "    <display-name>Sample Numeric Channel</display-name>\n"
            "  </channel>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="123958">\n'
            "    <title>Breaking Basics</title>\n"
            "    <desc>Tobi visits the &quot;Flying Steps&quot; in Berlin.</desc>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-8", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="Jesmann FullGuide", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()
            self.assertIn("123958", src.programme_index["channels"])

            epg = EPGData.objects.create(
                tvg_id="123958", name="Numeric Channel", epg_source=src
            )
            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "Breaking Basics")
            self.assertEqual(
                result["description"],
                'Tobi visits the "Flying Steps" in Berlin.',
            )
        finally:
            os.unlink(tmp_path)

    def test_offset_lookup_accepts_single_quoted_channel_attribute(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            "  <channel id='single.quote.channel'/>\n"
            "  <programme start='20000101000000 +0000' "
            "stop='20991231235959 +0000' channel='single.quote.channel'>\n"
            "    <title>Single Quote Current</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-8", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="Single Quotes", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()
            self.assertIn("single.quote.channel", src.programme_index["channels"])

            epg = EPGData.objects.create(
                tvg_id="single.quote.channel",
                name="Single Quote Channel",
                epg_source=src,
            )
            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "Single Quote Current")
        finally:
            os.unlink(tmp_path)

    def test_offset_lookup_resolves_html_named_entity_not_predefined_by_xml(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="html.entity.channel"/>\n'
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="html.entity.channel">\n'
            "    <title>Caf&eacute;&nbsp;Society</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-8", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="HTML Entities", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)

            epg = EPGData.objects.create(
                tvg_id="html.entity.channel",
                name="HTML Entity Channel",
                epg_source=src,
            )
            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "Caf\u00e9\u00a0Society")
        finally:
            os.unlink(tmp_path)

    def test_offset_lookup_handles_programme_element_larger_than_read_chunk(self):
        long_desc = "x" * (2 * 1024 * 1024 + 1024)
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="large.programme.channel"/>\n'
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="large.programme.channel">\n'
            "    <title>Large Programme Current</title>\n"
            f"    <desc>{long_desc}</desc>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-8", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="Large Programme", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)

            epg = EPGData.objects.create(
                tvg_id="large.programme.channel",
                name="Large Programme Channel",
                epg_source=src,
            )
            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(result)
            self.assertEqual(result["title"], "Large Programme Current")
            self.assertEqual(len(result["description"]), len(long_desc))
        finally:
            os.unlink(tmp_path)

    @patch("apps.epg.tasks.build_programme_index_task")
    def test_no_index_dispatches_build_and_returns_timeout(self, mock_build_task):
        # Source with no index and file on disk
        src = EPGSource.objects.create(
            name="No Index",
            source_type="xmltv",
            file_path=FIXTURE_XML,
        )
        epg = EPGData.objects.create(
            tvg_id="channel.current",
            name="Current",
            epg_source=src,
        )

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
        # Small fixture has no interleaved channels
        self.assertEqual(index["interleaved_channels"], [])

    def test_builds_index_when_channel_attribute_has_valid_xml_spacing(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="spaced.channel"/>\n'
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel = "spaced.channel">\n'
            "    <title>Spaced Attribute Current</title>\n"
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
                name="Spaced Attribute", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()

            self.assertIn(
                "spaced.channel", src.programme_index["channels"]
            )
        finally:
            os.unlink(tmp_path)

    def test_builds_index_from_extracted_file_path_for_gz_source(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="gz.channel"/>\n'
            '  <programme channel="gz.channel" '
            'start="20000101000000 +0000" stop="20991231235959 +0000">\n'
            "    <title>GZ Current</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        gz_path = None
        xml_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".xml.gz", delete=False
            ) as gz_file:
                gz_path = gz_file.name
                with gzip.GzipFile(fileobj=gz_file, mode="wb") as compressed:
                    compressed.write(b"not the file the index should scan")

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", encoding="utf-8", delete=False
            ) as xml_file:
                xml_file.write(xml)
                xml_path = xml_file.name

            src = EPGSource.objects.create(
                name="Extracted GZ",
                source_type="xmltv",
                file_path=gz_path,
                extracted_file_path=xml_path,
            )
            build_programme_index(src.id)
            src.refresh_from_db()

            self.assertIn("gz.channel", src.programme_index["channels"])
        finally:
            if gz_path:
                os.unlink(gz_path)
            if xml_path:
                os.unlink(xml_path)

    def test_builds_index_ignores_elements_whose_name_only_starts_with_programme(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="real.channel"/>\n'
            '  <programme-extra channel="not.a.programme" '
            'start="20000101000000 +0000" stop="20991231235959 +0000">\n'
            "    <title>Not a Programme</title>\n"
            "  </programme-extra>\n"
            '  <programme channel="real.channel" '
            'start="20000101000000 +0000" stop="20991231235959 +0000">\n'
            "    <title>Real Programme</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-8", delete=False
        ) as f:
            f.write(xml)
            tmp_path = f.name

        try:
            src = EPGSource.objects.create(
                name="Programme Prefix", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()

            self.assertIn("real.channel", src.programme_index["channels"])
            self.assertNotIn("not.a.programme", src.programme_index["channels"])
        finally:
            os.unlink(tmp_path)

    def test_nonexistent_source_does_not_raise(self):
        # Should log error but not raise
        build_programme_index(99999)

    @patch("apps.epg.tasks.build_programme_index")
    @patch("apps.epg.tasks.release_task_lock")
    @patch("apps.epg.tasks.acquire_task_lock", return_value=True)
    def test_task_builds_and_releases_lock_when_free(
        self, mock_acquire, mock_release, mock_build
    ):
        build_programme_index_task(42)

        mock_build.assert_called_once_with(42)
        mock_acquire.assert_called_once_with("epg_source_file", 42)
        mock_release.assert_called_once_with("epg_source_file", 42)

    @patch("apps.epg.tasks.build_programme_index")
    @patch("apps.epg.tasks.acquire_task_lock", return_value=False)
    def test_task_defers_when_lock_held(self, mock_acquire, mock_build):
        with patch("apps.epg.tasks.build_programme_index_task.apply_async") as mock_apply:
            build_programme_index_task(42)

        mock_build.assert_not_called()
        mock_apply.assert_called_once_with(
            args=[42],
            kwargs={'_defer_retry': 1},
            countdown=_EPG_TVG_PARSE_DEFER_SECONDS,
        )

    @patch("apps.epg.tasks.build_programme_index", side_effect=RuntimeError("boom"))
    @patch("apps.epg.tasks.release_task_lock")
    @patch("apps.epg.tasks.acquire_task_lock", return_value=True)
    def test_task_releases_lock_on_failure(
        self, mock_acquire, mock_release, mock_build
    ):
        with self.assertRaises(RuntimeError):
            build_programme_index_task(42)

        mock_release.assert_called_once_with("epg_source_file", 42)

    def test_per_channel_interleaved_marking(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="A"/>\n'
            '  <channel id="B"/>\n'
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="A">\n'
            "    <title>A Current</title>\n"
            "  </programme>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="B">\n'
            "    <title>B Current</title>\n"
            "  </programme>\n"
            '  <programme start="19990101000000 +0000" '
            'stop="19990102000000 +0000" channel="A">\n'
            "    <title>A Old</title>\n"
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
                name="Interleaved", source_type="xmltv", file_path=tmp_path
            )
            with patch("apps.epg.tasks._OFFSET_CAP", 1):
                build_programme_index(src.id)
            src.refresh_from_db()
            index = src.programme_index
            self.assertEqual(index["interleaved_channels"], ["A"])

            epg_b = EPGData.objects.create(
                tvg_id="B", name="B", epg_source=src
            )
            with patch(
                "apps.epg.tasks._scan_from_offset_for_tvg_id"
            ) as mock_scan:
                result_b = find_current_program_for_tvg_id(epg_b)
            self.assertIsNotNone(result_b)
            self.assertEqual(result_b["title"], "B Current")
            mock_scan.assert_not_called()

            epg_a = EPGData.objects.create(
                tvg_id="A", name="A", epg_source=src
            )
            result_a = find_current_program_for_tvg_id(epg_a)
            self.assertIsNotNone(result_a)
            self.assertEqual(result_a["title"], "A Current")
        finally:
            os.unlink(tmp_path)
