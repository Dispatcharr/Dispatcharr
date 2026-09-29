"""Tests for Schedules Direct external ID resolution and stamping."""
from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import requests
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.channels.models import Channel, ChannelGroup
from apps.epg.models import EPGData, EPGSource, ProgramData, SDSeriesExternalID
from apps.epg.sd_external_ids import (
    _search_profiles,
    clear_program_external_ids,
    resolve_by_search,
    sd_series_key,
    stamp_program_external_ids,
    update_sd_external_ids,
)
from apps.epg.sd_tasks import lookup_sd_tmdb_ids
from apps.epg.tmdb_match import TMDBAuthError
from apps.output.tests.test_views import OutputEndpointTestMixin, _response_text


def _response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


def _entry(series_key, **fields):
    return SDSeriesExternalID.objects.create(
        series_key=series_key, attempted_at=fields.pop("attempted_at", timezone.now()), **fields,
    )


class SDSeriesKeyTests(TestCase):
    def test_episode_and_show_share_key(self):
        self.assertEqual(sd_series_key("EP012583330912"), "SH01258333")
        self.assertEqual(sd_series_key("SH012583330000"), "SH01258333")

    def test_movie_keeps_prefix(self):
        self.assertEqual(sd_series_key("MV012583330000"), "MV01258333")

    def test_short_or_missing_ids(self):
        self.assertIsNone(sd_series_key(None))
        self.assertIsNone(sd_series_key(""))
        self.assertIsNone(sd_series_key("EP0125"))


class StampProgramExternalIdsTests(TestCase):
    def setUp(self):
        source = EPGSource.objects.create(name="SD", source_type="schedules_direct")
        self.epg = EPGData.objects.create(tvg_id="12345", name="BBC One", epg_source=source)
        now = timezone.now()
        self._n = 0

        def make(program_id, cp=None):
            self._n += 1
            return ProgramData.objects.create(
                epg=self.epg, tvg_id="12345", title="T", program_id=program_id,
                start_time=now + timedelta(hours=self._n),
                end_time=now + timedelta(hours=self._n + 1),
                custom_properties=cp,
            )

        self.episode = make("EP012583330912", {"season": 38, "episode": 37})
        self.show = make("SH012583330000")
        self.other = make("EP099999990001", {"season": 1})
        self.movie = make("MV012583330000")
        self.xmltv = make(None, {"imdb.com_id": "tt9"})
        _entry("SH01258333", tmdb_id="1981", tmdb_type="tv", imdb_id="tt0158552", tvdb_id="70626")

    def test_stamps_all_airings_of_series(self):
        self.assertEqual(stamp_program_external_ids([self.epg.id]), 2)

        for prog in (self.episode, self.show):
            prog.refresh_from_db()
            self.assertEqual(prog.custom_properties["themoviedb.org_id"], "1981")
            self.assertEqual(prog.custom_properties["tmdb_type"], "tv")
            self.assertEqual(prog.custom_properties["imdb.com_id"], "tt0158552")
            self.assertEqual(prog.custom_properties["thetvdb.com_id"], "70626")
        self.assertEqual(self.episode.custom_properties["season"], 38)

        for prog in (self.other, self.movie):
            prog.refresh_from_db()
            self.assertNotIn("themoviedb.org_id", prog.custom_properties or {})
        self.xmltv.refresh_from_db()
        self.assertEqual(self.xmltv.custom_properties, {"imdb.com_id": "tt9"})

    def test_is_idempotent(self):
        stamp_program_external_ids([self.epg.id])
        self.assertEqual(stamp_program_external_ids([self.epg.id]), 0)

    def test_cache_changes_are_applied(self):
        stamp_program_external_ids([self.epg.id])
        SDSeriesExternalID.objects.filter(series_key="SH01258333").update(
            tmdb_id=None, tmdb_type=None, imdb_id="tt1",
        )
        self.assertEqual(stamp_program_external_ids([self.epg.id]), 2)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.custom_properties["imdb.com_id"], "tt1")
        self.assertNotIn("themoviedb.org_id", self.episode.custom_properties)
        self.assertNotIn("tmdb_type", self.episode.custom_properties)

    def test_other_epg_rows_untouched(self):
        self.assertEqual(stamp_program_external_ids([]), 0)

    def test_clear_removes_only_stamped_keys(self):
        stamp_program_external_ids([self.epg.id])
        self.assertEqual(clear_program_external_ids([self.epg.id]), 2)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.custom_properties, {"season": 38, "episode": 37})
        self.xmltv.refresh_from_db()
        self.assertEqual(self.xmltv.custom_properties, {"imdb.com_id": "tt9"})
        self.assertEqual(clear_program_external_ids([self.epg.id]), 0)


class SearchPathTests(TestCase):
    def setUp(self):
        source = EPGSource.objects.create(name="SD", source_type="schedules_direct")
        self.epg = EPGData.objects.create(tvg_id="12345", name="BBC One", epg_source=source)
        self._n = 0

    def _program(self, program_id, title, **cp):
        self._n += 1
        now = timezone.now()
        return ProgramData.objects.create(
            epg=self.epg, tvg_id="12345", title=title, program_id=program_id,
            start_time=now + timedelta(hours=self._n), end_time=now + timedelta(hours=self._n + 1),
            custom_properties=cp,
        )

    def _series(self, root="01258333", title="Der Bergdoktor", airings=1):
        for i in range(airings):
            self._program(
                f"EP{root}{i:04d}", title,
                categories=["Episode", "Series", "Drama"], country="DEU, AUT",
                date=f"{2024 + i % 2}-01-01", sd_title_language="de",
                credits={"actor": [{"name": "Hans Sigl"}, {"name": "Guest", "guest": True}]},
            )

    def test_profiles(self):
        self._series(airings=2)
        self._program("MV000000010000", "Casablanca", categories=["Movie"], date="1942",
                      credits={"actor": [{"name": "Humphrey Bogart"}]})
        self._program("SH099999990000", "Premier League", categories=["Sports event", "Soccer"])
        self._program("EP088888880001", "Mystery", categories=["Episode"])

        profiles = _search_profiles([self.epg.id])

        self.assertEqual(set(profiles), {"SH01258333", "MV00000001"})
        series = profiles["SH01258333"]
        self.assertEqual(series["kind"], "tv")
        self.assertEqual(series["language"], "de")
        self.assertEqual(series["countries"], {"DEU", "AUT"})
        self.assertEqual(min(series["years"]), 2024)
        self.assertEqual(dict(series["cast"]), {"Hans Sigl": 2})
        self.assertEqual(profiles["MV00000001"]["kind"], "movie")
        self.assertEqual(profiles["MV00000001"]["years"], [1942])

    def test_no_api_key_does_nothing(self):
        self._series()
        with patch.dict("os.environ", {}, clear=True), \
                patch("apps.epg.sd_external_ids.match_tmdb") as mock_match:
            self.assertEqual(resolve_by_search([self.epg.id]), 0)
        mock_match.assert_not_called()

    @patch.dict("os.environ", {"TMDB_API_KEY": "k"})
    @patch("apps.epg.sd_external_ids.match_tmdb")
    def test_stores_matches_and_misses(self, mock_match):
        self._series()
        self._program("MV000000010000", "Casablanca", categories=["Movie"], date="1942",
                      credits={"actor": [{"name": "Humphrey Bogart"}]})

        def fake_match(client, kind, title, **kwargs):
            if kind == "tv":
                self.assertEqual(kwargs["year"], 2024)
                self.assertEqual(kwargs["language"], "de")
                self.assertEqual(kwargs["cast"], ["Hans Sigl"])
                return {"id": 62957, "external_ids": {"imdb_id": "tt1", "tvdb_id": 81234}}, "match"
            return None, "unconfirmed"

        mock_match.side_effect = fake_match
        self.assertEqual(resolve_by_search([self.epg.id]), 1)

        series = SDSeriesExternalID.objects.get(series_key="SH01258333")
        self.assertEqual(
            (series.tmdb_id, series.tmdb_type, series.imdb_id, series.tvdb_id),
            ("62957", "tv", "tt1", "81234"),
        )
        miss = SDSeriesExternalID.objects.get(series_key="MV00000001")
        self.assertIsNone(miss.tmdb_id)
        self.assertIsNotNone(miss.attempted_at)

    @patch.dict("os.environ", {"TMDB_API_KEY": "k"})
    @patch("apps.epg.sd_external_ids.match_tmdb", return_value=(None, "unconfirmed"))
    def test_due_rules(self, mock_match):
        now = timezone.now()
        cases = {
            "01000001": dict(attempted_at=now - timedelta(days=1)),
            "01000002": dict(attempted_at=now - timedelta(days=60)),
            "01000003": dict(tmdb_id="3", attempted_at=now - timedelta(days=60)),
            "01000004": None,
        }
        for root, fields in cases.items():
            self._series(root=root, title=f"Show {root}")
            if fields is not None:
                _entry(f"SH{root}", **fields)

        resolve_by_search([self.epg.id])

        searched = {c.args[2] for c in mock_match.call_args_list}
        self.assertEqual(searched, {"Show 01000002", "Show 01000004"})

    @patch.dict("os.environ", {"TMDB_API_KEY": "k"})
    @patch("apps.epg.sd_external_ids.match_tmdb")
    def test_searches_all_due_titles_in_one_run(self, mock_match):
        mock_match.side_effect = lambda client, kind, title, **kw: (
            ({"id": int(title.split()[-1])}, "match") if title.endswith("7") else (None, "unconfirmed")
        )
        for i in range(25):
            self._series(root=f"010000{i:02d}", title=f"Show {i}")
        self.assertEqual(resolve_by_search([self.epg.id]), 2)
        self.assertEqual(mock_match.call_count, 25)
        self.assertEqual(SDSeriesExternalID.objects.count(), 25)
        self.assertEqual(
            set(SDSeriesExternalID.objects.exclude(tmdb_id=None).values_list("tmdb_id", flat=True)),
            {"7", "17"},
        )

    @patch.dict("os.environ", {"TMDB_API_KEY": "bad"})
    @patch("apps.epg.sd_external_ids.TMDB_SEARCH_WORKERS", 1)
    @patch("apps.epg.sd_external_ids.match_tmdb", side_effect=TMDBAuthError())
    def test_invalid_key_stops_search(self, mock_match):
        for i in range(10):
            self._series(root=f"010000{i:02d}", title=f"Show {i}")
        self.assertEqual(resolve_by_search([self.epg.id]), 0)
        self.assertEqual(mock_match.call_count, 1)
        self.assertFalse(SDSeriesExternalID.objects.exists())

    @patch.dict("os.environ", {"TMDB_API_KEY": "k"})
    @patch("apps.epg.sd_external_ids.match_tmdb")
    def test_network_error_skips_without_caching(self, mock_match):
        def fake_match(client, kind, title, **kwargs):
            if title == "A":
                raise requests.exceptions.ConnectionError("down")
            return None, "ambiguous"

        mock_match.side_effect = fake_match
        self._series(root="01000001", title="A", airings=2)
        self._series(root="01000002", title="B")
        resolve_by_search([self.epg.id])
        self.assertFalse(SDSeriesExternalID.objects.filter(series_key="SH01000001").exists())
        self.assertTrue(SDSeriesExternalID.objects.filter(series_key="SH01000002").exists())


class UpdateSDExternalIdsTests(TestCase):
    def setUp(self):
        source = EPGSource.objects.create(name="SD", source_type="schedules_direct")
        self.epg = EPGData.objects.create(tvg_id="12345", name="BBC One", epg_source=source)

    def _program(self, title, program_id, hours=1, **cp):
        now = timezone.now()
        return ProgramData.objects.create(
            epg=self.epg, tvg_id="12345", title=title, program_id=program_id,
            start_time=now, end_time=now + timedelta(hours=hours), custom_properties=cp,
        )

    @patch.dict("os.environ", {"TMDB_API_KEY": "k"})
    @patch("apps.epg.sd_external_ids._session")
    def test_matches_movie_by_search_and_stamps(self, mock_session):
        prog = self._program(
            "Casablanca", "MV000000010000", hours=2,
            categories=["Movie"], date="1942", country="USA",
            credits={"actor": [{"name": "Humphrey Bogart"}]},
        )

        def fake_get(url, params=None, timeout=None):
            if url.endswith("/search/movie"):
                return _response(payload={"results": [
                    {"id": 289, "title": "Casablanca", "original_title": "Casablanca",
                     "release_date": "1943-01-15"},
                    {"id": 999, "title": "Casablanca", "original_title": "Casablanca",
                     "release_date": "1955-01-01"},
                ]})
            if url.endswith("/movie/289"):
                return _response(payload={
                    "id": 289, "production_countries": [{"iso_3166_1": "US"}],
                    "credits": {"cast": [{"name": "Humphrey Bogart"}]},
                    "external_ids": {"imdb_id": "tt0034583"},
                })
            raise AssertionError(f"unexpected {url}")

        mock_session.return_value.get.side_effect = fake_get

        self.assertEqual(update_sd_external_ids([self.epg.id]), 1)

        prog.refresh_from_db()
        self.assertEqual(prog.custom_properties["themoviedb.org_id"], "289")
        self.assertEqual(prog.custom_properties["tmdb_type"], "movie")
        self.assertEqual(prog.custom_properties["imdb.com_id"], "tt0034583")
        self.assertNotIn("thetvdb.com_id", prog.custom_properties)

    @patch("apps.epg.sd_external_ids.resolve_by_search")
    def test_needs_api_key(self, mock_search):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(update_sd_external_ids([self.epg.id]), 0)
        mock_search.assert_not_called()

    @patch.dict("os.environ", {"TMDB_API_KEY": "k"})
    @patch("apps.epg.sd_external_ids.resolve_by_search", return_value=1)
    def test_no_stamping_when_disabled_during_search(self, _search):
        prog = self._program("Countryfile", "EP012583330912")
        _entry("SH01258333", tmdb_id="1981", tmdb_type="tv")
        self.assertEqual(update_sd_external_ids([self.epg.id], is_enabled=lambda: False), 0)
        prog.refresh_from_db()
        self.assertEqual(prog.custom_properties, {})


@patch("apps.epg.sd_tasks.release_task_lock")
@patch("apps.epg.sd_tasks.TaskLockRenewer")
class LookupSDTmdbIdsTaskTests(TestCase):
    def setUp(self):
        self.source = EPGSource.objects.create(
            name="SD", source_type="schedules_direct",
            custom_properties={"fetch_external_ids": True},
        )
        self.epg = EPGData.objects.create(tvg_id="12345", name="BBC One", epg_source=self.source)
        Channel.objects.create(name="BBC One", epg_data=self.epg)

    @patch("apps.output.streaming_chunk_cache.invalidate_epg_chunk_cache")
    @patch("apps.epg.sd_external_ids.update_sd_external_ids", return_value=3)
    @patch("apps.epg.sd_tasks.acquire_task_lock", return_value=True)
    def test_runs_for_enabled_source(self, _lock, mock_update, mock_invalidate, _renewer, mock_release):
        lookup_sd_tmdb_ids(self.source.id)
        mapped, = mock_update.call_args.args
        self.assertEqual(set(mapped), {self.epg.id})
        self.assertTrue(mock_update.call_args.kwargs["is_enabled"]())
        mock_invalidate.assert_called_once()
        mock_release.assert_called_once_with("lookup_sd_tmdb_ids", self.source.id)

    @patch("apps.epg.sd_external_ids.update_sd_external_ids")
    @patch("apps.epg.sd_tasks.acquire_task_lock", return_value=True)
    def test_skips_disabled_source(self, _lock, mock_update, _renewer, mock_release):
        self.source.custom_properties = {}
        self.source.save()
        lookup_sd_tmdb_ids(self.source.id)
        mock_update.assert_not_called()
        mock_release.assert_called_once_with("lookup_sd_tmdb_ids", self.source.id)

    @patch("apps.epg.sd_external_ids.update_sd_external_ids")
    @patch("apps.epg.sd_tasks.acquire_task_lock", return_value=False)
    def test_skips_when_already_running(self, _lock, mock_update, _renewer, mock_release):
        lookup_sd_tmdb_ids(self.source.id)
        mock_update.assert_not_called()
        mock_release.assert_not_called()


class SDExternalIdsXmltvOutputTests(OutputEndpointTestMixin, TestCase):
    def test_stamped_ids_emitted_as_episode_num(self):
        source = EPGSource.objects.create(name="SD", source_type="schedules_direct")
        epg = EPGData.objects.create(tvg_id="12345", name="BBC One", epg_source=source)
        profile = self._create_isolated_profile("sd-ext-ids")
        group = ChannelGroup.objects.create(name=f"SD {uuid4().hex[:8]}")
        self._add_channel_to_profile(profile, group, channel_number=1.0, name="BBC One", epg_data=epg)
        now = timezone.now()
        ProgramData.objects.create(
            epg=epg, tvg_id="12345", title="Countryfile", program_id="EP012583330912",
            start_time=now, end_time=now + timedelta(hours=1), custom_properties={},
        )
        _entry("SH01258333", tmdb_id="1981", tmdb_type="tv", imdb_id="tt0158552", tvdb_id="70626")
        stamp_program_external_ids([epg.id])

        url = reverse("output:epg_endpoint", kwargs={"profile_name": profile.name})
        response = Client().get(f"{url}?days=1&prev_days=0")
        self.assertEqual(response.status_code, 200)
        content = _response_text(response)
        self.assertIn('<episode-num system="themoviedb.org">1981</episode-num>', content)
        self.assertIn('<episode-num system="imdb.com">tt0158552</episode-num>', content)
        self.assertIn('<episode-num system="thetvdb.com">70626</episode-num>', content)
        self.assertNotIn("tmdb_type", content)
