"""XC lineup reads must never trigger provider refreshes."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.output.views import xc_get, xc_panel_api, xc_player_api


class XcLiveCatalogReadOnlyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            custom_properties={"xc_live_refresh_on_request": True},
            stream_limit=1,
            id=1,
        )
        self.refresh = self.enterContext(
            patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
        )
        self.delay = self.enterContext(
            patch("apps.m3u.tasks.refresh_single_m3u_account.delay")
        )
        self.enterContext(
            patch("apps.output.views._xc_api_user", return_value=(self.user, None))
        )

    def tearDown(self):
        self.refresh.assert_not_called()
        self.delay.assert_not_called()
        super().tearDown()

    def test_streaming_lineup_reads_existing_catalog_with_legacy_opt_in(self):
        for category_id in (None, "42"):
            with self.subTest(category_id=category_id):
                query = {"action": "get_live_streams"}
                if category_id is not None:
                    query["category_id"] = category_id
                request = self.factory.get("/player_api.php", query)
                with patch(
                    "apps.output.views._xc_stream_live_streams",
                    return_value=iter(['[{"stream_id":1}]']),
                ) as catalog:
                    response = xc_player_api(request)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        b"".join(response.streaming_content), b'[{"stream_id":1}]'
                    )
                catalog.assert_called_once_with(request, self.user, category_id)

    def test_categories_read_existing_catalog(self):
        request = self.factory.get(
            "/player_api.php", {"action": "get_live_categories"}
        )
        with patch(
            "apps.output.views.xc_get_live_categories", return_value=[]
        ) as catalog:
            self.assertEqual(xc_player_api(request).content, b"[]")
        catalog.assert_called_once_with(self.user)

    def test_panel_lineup_reads_existing_catalog(self):
        request = self.factory.get("/panel_api.php", {"category_id": "42"})
        with patch(
            "apps.output.views.xc_get_live_categories", return_value=[]
        ), patch(
            "apps.output.views.xc_get_live_streams", return_value=[]
        ) as catalog, patch(
            "apps.output.views.get_user_active_connections", return_value=[]
        ):
            self.assertEqual(xc_panel_api(request).status_code, 200)
        catalog.assert_called_once_with(request, self.user, "42")

    def test_playlist_uses_existing_catalog(self):
        request = self.factory.get("/get.php")
        with patch("apps.output.views.generate_m3u") as catalog:
            self.assertIs(xc_get(request), catalog.return_value)
        catalog.assert_called_once_with(request, None, self.user)
