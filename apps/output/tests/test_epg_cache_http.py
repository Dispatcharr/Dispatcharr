"""Real HTTP XMLTV exports retain integrity across committed EPG updates."""

import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import requests
from django.db import connection, transaction
from django.test import LiveServerTestCase, TestCase
from django.utils import timezone
from django_redis import get_redis_connection

from apps.accounts.models import User
from apps.channels.models import (
    Channel, ChannelGroup, ChannelOverride, ChannelProfile, ChannelProfileMembership,
)
from apps.epg.models import EPGData, ProgramData
from apps.epg.services import ProgrammeUpdate, get_epg_revision, update_programmes
from apps.output import streaming_chunk_cache as chunk_cache


class EPGCacheHTTPTests(LiveServerTestCase):
    """Exercise Django's WSGI server, PostgreSQL, and the configured real Redis."""

    def setUp(self):
        super().setUp()
        if connection.vendor != "postgresql":
            self.skipTest("HTTP concurrency requires separate PostgreSQL connections")
        self.redis = get_redis_connection("default")
        self.redis.ping()
        self.prefix = uuid.uuid4().hex
        self.profile = ChannelProfile.objects.create(name=f"http-{self.prefix}")
        group = ChannelGroup.objects.create(name=f"HTTP {self.prefix}")
        self.epg = EPGData.objects.create(name="Override programme data")
        base_epg = EPGData.objects.create(name="Provider programme data")
        channels = {}
        for number, (name, extra) in enumerate([
            ("visible", {}),
            ("hidden", {"hidden_from_output": True}),
            ("restricted", {"user_level": 10}),
            ("adult", {"is_adult": True}),
            ("outside", {}),
        ], 1):
            channels[name] = Channel.objects.create(
                name=name, tvg_id=name, channel_number=number,
                channel_group=group, epg_data=base_epg, **extra,
            )
        # Profile/channel creation signals may auto-add memberships.
        ChannelProfileMembership.objects.filter(channel_profile=self.profile).delete()
        ChannelProfileMembership.objects.bulk_create([
            ChannelProfileMembership(channel_profile=self.profile, channel=channel, enabled=True)
            for name, channel in channels.items() if name != "outside"
        ])
        ChannelOverride.objects.create(
            channel=channels["visible"], name="Override display name",
            tvg_id="visible.override", channel_number=101, epg_data=self.epg,
        )
        now = timezone.now() + timedelta(minutes=1)
        programmes = ProgramData.objects.bulk_create([
            ProgramData(
                epg=self.epg, title=f"Programme {number}",
                start_time=now + timedelta(minutes=number),
                end_time=now + timedelta(minutes=number + 1),
            )
            for number in range(1001)
        ])
        self.programme = programmes[0]
        ProgramData.objects.create(
            epg=base_epg, title="Restricted schedule", start_time=now, end_time=now + timedelta(hours=1),
        )
        self.admin_key = uuid.uuid4().hex
        User.objects.create_user(username=f"admin-{self.prefix}", user_level=10, api_key=self.admin_key)
        self.xc_password = uuid.uuid4().hex
        self.viewer = User.objects.create_user(
            username=f"viewer-{self.prefix}", user_level=0,
            custom_properties={"xc_password": self.xc_password, "hide_adult_content": True},
        )
        self.viewer.channel_profiles.add(self.profile)
        self.revision = get_epg_revision()

    def tearDown(self):
        # Live server origin is unique to this class; never flush a shared Redis DB.
        if hasattr(self, "redis"):
            keys = [key for key in self.redis.scan_iter(match="epg_content:*")
                    if self.live_server_url.encode() in key]
            if keys:
                self.redis.delete(*keys)
        super().tearDown()

    def _get(self, endpoint):
        params = {"tvg_id_source": "tvg_id", "days": 0, "prev_days": 0}
        if endpoint == "xc":
            path = "/xmltv.php"
            params.update(username=self.viewer.username, password=self.xc_password)
        else:
            path = f"/output/epg/{self.profile.name}"
        return requests.get(
            self.live_server_url + path, params=params,
            headers={"Accept-Encoding": "identity", "Connection": "close"}, timeout=(3, 15),
        )

    def _assert_feed(self, response, endpoint, title="Programme 0"):
        self.assertEqual(response.status_code, 200, response.content[:200])
        root = ET.fromstring(response.content)
        self.assertEqual(root.tag, "tv")
        channels = {element.get("id"): element for element in root.findall("channel")}
        expected_channels = {"visible.override"} if endpoint == "xc" else {"visible.override", "restricted", "adult"}
        self.assertEqual(set(channels), expected_channels)
        self.assertEqual(channels["visible.override"].findtext("display-name"), "Override display name")
        programmes = root.findall("programme")
        self.assertEqual(len(programmes), 1001 if endpoint == "xc" else 1003)
        selected = [item for item in programmes if item.get("channel") == "visible.override"]
        self.assertEqual(len(selected), 1001)
        self.assertEqual(selected[0].findtext("title"), title)
        self.assertEqual(selected[-1].findtext("title"), "Programme 1000")
        if "Content-Length" in response.headers:
            self.assertEqual(int(response.headers["Content-Length"]), len(response.content))
        return response.content

    def _warm(self, endpoint):
        expected = self._assert_feed(self._get(endpoint), endpoint)
        cached = self._get(endpoint)
        self.assertIn("Content-Length", cached.headers)
        self.assertEqual(self._assert_feed(cached, endpoint), expected)
        return expected

    def _service_update(self, title="Updated", **kwargs):
        return update_programmes([
            ProgrammeUpdate(self.programme.pk, {"title": "Programme 0"}, {"title": title})
        ], **kwargs)

    @contextmanager
    def _pause(self, target, *, producer=False):
        """Pause real cache work, retaining original bytes and Redis operations."""
        entered, release = threading.Event(), threading.Event()
        claimed = threading.Lock()
        build_keys = []
        original = getattr(chunk_cache._Build if producer else chunk_cache, target)
        revision = get_epg_revision()

        def barrier(build_key):
            if revision not in build_key or entered.is_set():
                return
            with claimed:
                if entered.is_set():
                    return
                build_keys.append(build_key)
                entered.set()
            if not release.wait(10):
                raise RuntimeError("HTTP cache test barrier timed out")

        if producer:
            def wrapped(build, offset, chunk):
                result = original(build, offset, chunk)
                if b"<programme " in chunk:
                    barrier(build.key)
                return result
            owner = chunk_cache._Build
        else:
            def wrapped(redis, build_key, manifest, offset, retention):
                if offset == 1:
                    barrier(build_key)
                return original(redis, build_key, manifest, offset, retention)
            owner = chunk_cache
        with patch.object(owner, target, wrapped):
            try:
                yield entered, release, build_keys
            finally:
                release.set()

    def test_admin_http_update_refreshes_both_endpoints_and_preserves_visibility(self):
        for endpoint in ("standard", "xc"):
            self._warm(endpoint)
        response = requests.patch(
            f"{self.live_server_url}/api/epg/programs/{self.programme.pk}/",
            json={"title": "Updated & <title>"},
            headers={"X-API-Key": self.admin_key}, timeout=(3, 15),
        )
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertNotEqual(get_epg_revision(), self.revision)
        for endpoint in ("standard", "xc"):
            self._assert_feed(self._get(endpoint), endpoint, title="Updated & <title>")

    def test_admin_http_noop_does_not_advance_revision(self):
        expected = self._warm("xc")
        response = requests.patch(
            f"{self.live_server_url}/api/epg/programs/{self.programme.pk}/",
            json={"title": "Programme 0"}, headers={"X-API-Key": self.admin_key}, timeout=(3, 15),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_epg_revision(), self.revision)
        self.assertEqual(self._assert_feed(self._get("xc"), "xc"), expected)

    def test_admin_http_delete_retires_cached_programme(self):
        self._warm("xc")
        response = requests.delete(
            f"{self.live_server_url}/api/epg/programs/{self.programme.pk}/",
            headers={"X-API-Key": self.admin_key}, timeout=(3, 15),
        )
        self.assertEqual(response.status_code, 204)
        self.assertNotEqual(get_epg_revision(), self.revision)
        feed = self._get("xc")
        self.assertEqual(feed.status_code, 200)
        programmes = ET.fromstring(feed.content).findall("programme")
        self.assertEqual(len(programmes), 1000)
        self.assertEqual(programmes[0].findtext("title"), "Programme 1")

    def test_admin_http_update_does_not_resurrect_row_deleted_after_lookup(self):
        from apps.epg.api_views import ProgramViewSet

        original = ProgramViewSet.perform_update
        programme_id = self.programme.pk

        def delete_before_write(view, serializer):
            ProgramData.objects.filter(pk=programme_id).delete()
            return original(view, serializer)

        with patch.object(ProgramViewSet, "perform_update", delete_before_write):
            response = requests.patch(
                f"{self.live_server_url}/api/epg/programs/{programme_id}/",
                json={"title": "Stale edit"}, headers={"X-API-Key": self.admin_key}, timeout=(3, 15),
            )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ProgramData.objects.filter(pk=programme_id).exists())

    def test_preview_noop_and_rollback_retain_warmed_feeds(self):
        baseline = {endpoint: self._warm(endpoint) for endpoint in ("standard", "xc")}
        self._service_update(preview=True)
        self._service_update(title="Programme 0")
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self._service_update()
                raise RuntimeError("Caller rolls back")
        self.assertEqual(get_epg_revision(), self.revision)
        for endpoint, expected in baseline.items():
            response = self._get(endpoint)
            self.assertIn("Content-Length", response.headers)
            self.assertEqual(self._assert_feed(response, endpoint), expected)

    def test_active_producer_survives_update_and_new_generation(self):
        with self._pause("_cache_chunk", producer=True) as (entered, release, build_keys):
            with ThreadPoolExecutor(max_workers=1) as pool:
                old = pool.submit(self._get, "standard")
                try:
                    self.assertTrue(entered.wait(5))
                    self._service_update()
                    self._assert_feed(self._get("standard"), "standard", title="Updated")
                    self._assert_feed(self._get("xc"), "xc", title="Updated")
                finally:
                    release.set()
                self._assert_feed(old.result(timeout=15), "standard")
        self.assertTrue(self.redis.exists(chunk_cache._chunks_key(build_keys[0])))
        self._assert_feed(self._get("standard"), "standard", title="Updated")

    def test_active_ready_reader_survives_update_and_new_generation(self):
        expected = self._warm("xc")
        with self._pause("_read_chunk") as (entered, release, build_keys):
            with ThreadPoolExecutor(max_workers=1) as pool:
                old = pool.submit(self._get, "xc")
                try:
                    self.assertTrue(entered.wait(5))
                    self._service_update()
                    self._assert_feed(self._get("xc"), "xc", title="Updated")
                    self._assert_feed(self._get("standard"), "standard", title="Updated")
                finally:
                    release.set()
                self.assertEqual(self._assert_feed(old.result(timeout=15), "xc"), expected)
        self.assertTrue(self.redis.exists(chunk_cache._chunks_key(build_keys[0])))

    def test_cached_data_loss_aborts_http_transfer_instead_of_returning_truncated_xml(self):
        for expire in (False, True):
            with self.subTest(expire=expire):
                self._warm("standard")
                with self._pause("_read_chunk") as (entered, release, build_keys):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        response = pool.submit(self._get, "standard")
                        try:
                            self.assertTrue(entered.wait(5))
                            chunks_key = chunk_cache._chunks_key(build_keys[0])
                            if expire:
                                self.redis.pexpire(chunks_key, 1)
                                deadline = time.monotonic() + 2
                                while self.redis.exists(chunks_key) and time.monotonic() < deadline:
                                    time.sleep(0.01)
                                self.assertFalse(self.redis.exists(chunks_key))
                            else:
                                self.redis.delete(chunks_key)
                        finally:
                            release.set()
                        with self.assertRaises(requests.exceptions.ChunkedEncodingError):
                            response.result(timeout=15)
                # A later HTTP request rebuilds a complete feed, without waiting for TTL.
                self._assert_feed(self._get("standard"), "standard")


class ProgrammeViewMutationTests(TestCase):
    """Verify transaction guarantees of the existing DRF persistence hooks."""

    def setUp(self):
        from apps.epg.api_views import ProgramViewSet
        from apps.epg.serializers import ProgramDataSerializer

        self.view = ProgramViewSet()
        self.serializer_class = ProgramDataSerializer
        self.epg = EPGData.objects.create(name="Mutation hook test")
        self.now = timezone.now()
        self.programme = ProgramData.objects.create(
            epg=self.epg, title="Original", start_time=self.now, end_time=self.now + timedelta(hours=1),
            custom_properties={"flag": True, "unrelated": "existing"},
        )
        self.revision = get_epg_revision()

    def _creation_serializer(self):
        serializer = self.serializer_class(data={
            "title": "New programme", "start_time": self.now, "end_time": self.now + timedelta(hours=1),
        })
        serializer.is_valid(raise_exception=True)
        # The existing HTTP serializer does not expose epg. Supply it here to
        # exercise the persistence hook without widening that public schema.
        serializer.validated_data["epg"] = self.epg
        return serializer

    def test_create_advances_revision_in_same_transaction(self):
        serializer = self._creation_serializer()
        self.view.perform_create(serializer)
        self.assertTrue(ProgramData.objects.filter(pk=serializer.instance.pk).exists())
        self.assertNotEqual(get_epg_revision(), self.revision)

    def test_revision_failure_rolls_back_create_update_and_delete(self):
        update = self.serializer_class(self.programme, data={"title": "Changed"}, partial=True)
        update.is_valid(raise_exception=True)
        operations = [
            lambda: self.view.perform_create(self._creation_serializer()),
            lambda: self.view.perform_update(update),
            lambda: self.view.perform_destroy(self.programme),
        ]
        for operation in operations:
            with self.subTest(operation=operation):
                with patch("apps.epg.api_views.advance_epg_revision", side_effect=RuntimeError("revision failed")):
                    with self.assertRaises(RuntimeError):
                        operation()
                self.programme.refresh_from_db()
                self.assertEqual(self.programme.title, "Original")
                self.assertEqual(ProgramData.objects.count(), 1)
                self.assertEqual(get_epg_revision(), self.revision)

    def test_json_replacement_distinguishes_numbers_from_booleans(self):
        class PropertySerializer(self.serializer_class):
            class Meta(self.serializer_class.Meta):
                fields = [*self.serializer_class.Meta.fields, "custom_properties"]

        serializer = PropertySerializer(
            self.programme, data={"custom_properties": {"flag": 1}}, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        self.view.perform_update(serializer)
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.custom_properties, {"flag": 1})
        self.assertIs(type(self.programme.custom_properties["flag"]), int)
        self.assertNotEqual(get_epg_revision(), self.revision)
