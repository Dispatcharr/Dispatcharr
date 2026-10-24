"""Account responses include saved category selections without a catalog fetch."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountSerializer
from apps.vod.models import M3UVODCategoryRelation, VODCategory


class CategorySelectionCountsTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Selection account",
            account_type="XC",
            custom_properties={"enable_vod": True},
        )
        self.other = M3UAccount.objects.create(name="Other account")
        self.client = APIClient()
        self.client.force_authenticate(
            get_user_model().objects.create_user(
                username="selection-admin", user_level=10,
            )
        )
        self.url = f"/api/m3u/accounts/{self.account.pk}/"

    def add_selections(self):
        for enabled in (True, False):
            group = ChannelGroup.objects.create(name=f"Live {enabled}")
            ChannelGroupM3UAccount.objects.create(
                m3u_account=self.account,
                channel_group=group,
                enabled=enabled,
            )
            ChannelGroupM3UAccount.objects.create(
                m3u_account=self.other, channel_group=group, enabled=True,
            )
            for index in range(2):
                Stream.objects.create(
                    name=f"Stream {enabled} {index}",
                    url=f"https://example.invalid/{enabled}/{index}",
                    m3u_account=self.account, channel_group=group,
                )
        selections = (("movie", True), ("movie", False), ("series", False))
        for scope, enabled in selections:
            category = VODCategory.objects.create(
                name=f"{scope} {enabled}", category_type=scope,
            )
            M3UVODCategoryRelation.objects.create(
                m3u_account=self.account, category=category, enabled=enabled,
            )
            M3UVODCategoryRelation.objects.create(
                m3u_account=self.other, category=category, enabled=True,
            )
        unrelated = VODCategory.objects.create(
            name="Other only", category_type="movie",
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.other, category=unrelated, enabled=True,
        )

    def test_empty_account_has_zero_counts_for_every_scope(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["category_selection_counts"], {
            scope: {"selected": 0, "total": 0}
            for scope in ("live", "movie", "series")
        })

    def test_list_and_detail_count_memberships_not_content_or_other_accounts(self):
        self.add_selections()
        expected = {
            "live": {"selected": 1, "total": 2},
            "movie": {"selected": 1, "total": 2},
            "series": {"selected": 0, "total": 1},
        }
        self.assertEqual(
            self.client.get(self.url).data["category_selection_counts"], expected,
        )
        response = self.client.get("/api/m3u/accounts/")
        self.assertEqual(response.status_code, 200)
        rows = (
            response.data.get("results", [])
            if isinstance(response.data, dict) else response.data
        )
        account = next(row for row in rows if row["id"] == self.account.pk)
        self.assertEqual(account["category_selection_counts"], expected)

    def test_saving_live_and_vod_selection_returns_updated_counts_on_account_read(self):
        self.add_selections()
        live = self.account.channel_group.get(enabled=True)
        movie = self.account.category_relations.get(
            category__category_type="movie", enabled=True,
        )
        series = self.account.category_relations.get(
            category__category_type="series",
        )
        response = self.client.patch(
            f"{self.url}group-settings/",
            {
                "group_settings": [{
                    "channel_group": live.channel_group_id, "enabled": False,
                }],
                "category_settings": [
                    {"id": movie.category_id, "enabled": False},
                    {"id": series.category_id, "enabled": True},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        expected = {
            "live": {"selected": 0, "total": 2},
            "movie": {"selected": 0, "total": 2},
            "series": {"selected": 1, "total": 1},
        }
        self.assertEqual(
            self.client.get(self.url).data["category_selection_counts"], expected,
        )
        # Counts are derived again, not persisted as an independently stale cache.
        self.assertEqual(
            self.client.get(self.url).data["category_selection_counts"], expected,
        )
        self.assertEqual(
            self.other.category_relations.filter(enabled=True).count(), 4,
        )

    def test_live_only_save_preserves_every_vod_selection(self):
        self.add_selections()
        vod_before = list(self.account.category_relations.order_by("pk").values())
        live = self.account.channel_group.get(enabled=True)
        response = self.client.patch(
            f"{self.url}group-settings/",
            {"group_settings": [{
                "channel_group": live.channel_group_id, "enabled": False,
            }], "category_settings": []},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        live.refresh_from_db()
        self.assertFalse(live.enabled)
        self.assertEqual(
            list(self.account.category_relations.order_by("pk").values()),
            vod_before,
        )

    def test_vod_only_save_preserves_every_live_selection_and_sync_setting(self):
        self.add_selections()
        live_before = list(self.account.channel_group.order_by("pk").values())
        movie = self.account.category_relations.get(
            category__category_type="movie", enabled=True,
        )
        response = self.client.patch(
            f"{self.url}group-settings/",
            {"group_settings": [], "category_settings": [{
                "id": movie.category_id, "enabled": False,
            }]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        movie.refresh_from_db()
        self.assertFalse(movie.enabled)
        self.assertEqual(
            list(self.account.channel_group.order_by("pk").values()),
            live_before,
        )

    def test_count_field_cannot_be_written_by_clients(self):
        self.add_selections()
        response = self.client.patch(
            self.url,
            {
                "category_selection_counts": {
                    "movie": {"selected": 999, "total": 999},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["category_selection_counts"]["movie"], {
            "selected": 1, "total": 2,
        })

    def test_create_response_includes_counts(self):
        response = self.client.post(
            "/api/m3u/accounts/",
            {
                "name": "New standard account", "account_type": "STD",
                "server_url": "https://example.invalid/playlist.m3u",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["category_selection_counts"]["movie"], {
            "selected": 0, "total": 0,
        })

    def test_direct_serialization_has_a_single_account_fallback(self):
        self.add_selections()
        counts = M3UAccountSerializer(self.account).data["category_selection_counts"]
        self.assertEqual(
            counts["movie"],
            {"selected": 1, "total": 2},
        )

    def test_deleted_memberships_are_not_counted(self):
        self.add_selections()
        self.account.category_relations.filter(
            category__category_type="movie",
        ).delete()
        counts = self.client.get(self.url).data["category_selection_counts"]
        self.assertEqual(counts["movie"], {"selected": 0, "total": 0})

    def test_list_aggregates_vod_counts_once_as_account_count_grows(self):
        self.add_selections()

        def read_list():
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get("/api/m3u/accounts/")
                self.assertEqual(response.status_code, 200)
            table = connection.ops.quote_name(M3UVODCategoryRelation._meta.db_table)
            category_queries = [
                query for query in queries if f"FROM {table}" in query["sql"]
            ]
            self.assertEqual(len(category_queries), 1)
            return len(queries)

        before = read_list()
        for index in range(5):
            account = M3UAccount.objects.create(name=f"More {index}")
            category = VODCategory.objects.create(
                name=f"More {index}", category_type="movie",
            )
            M3UVODCategoryRelation.objects.create(
                m3u_account=account, category=category,
            )
        self.assertEqual(read_list(), before)
