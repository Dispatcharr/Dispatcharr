from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.output.views import _xc_stream_live_streams_then_refresh


class XcLiveRefreshTriggerTests(SimpleTestCase):
    def test_refresh_is_requested_only_after_current_catalog_is_served(self):
        request = RequestFactory().get(
            "/player_api.php?action=get_live_streams"
        )
        user = SimpleNamespace(id=4)

        with patch(
            "apps.output.views._xc_stream_live_streams",
            return_value=iter(["[", "]"]),
        ), patch(
            "apps.m3u.client_refresh.handle_xc_live_catalog_request"
        ) as handle:
            response = _xc_stream_live_streams_then_refresh(request, user)
            self.assertEqual(next(response), "[")
            handle.assert_not_called()
            self.assertEqual(next(response), "]")
            handle.assert_not_called()
            with self.assertRaises(StopIteration):
                next(response)

        handle.assert_called_once_with(request, user)

    def test_failed_catalog_response_does_not_trigger_refresh(self):
        request = RequestFactory().get(
            "/player_api.php?action=get_live_streams"
        )
        user = SimpleNamespace(id=4)

        def broken_stream():
            yield "["
            raise RuntimeError("catalog failed")

        with patch(
            "apps.output.views._xc_stream_live_streams",
            return_value=broken_stream(),
        ), patch(
            "apps.m3u.client_refresh.handle_xc_live_catalog_request"
        ) as handle:
            response = _xc_stream_live_streams_then_refresh(request, user)
            self.assertEqual(next(response), "[")
            with self.assertRaises(RuntimeError):
                next(response)

        handle.assert_not_called()

    def test_experimental_wait_mode_refreshes_before_catalog_is_built(self):
        request = RequestFactory().get(
            "/player_api.php?action=get_live_streams"
        )
        user = SimpleNamespace(
            id=4,
            custom_properties={
                "xc_live_refresh_on_request": True,
                "xc_live_refresh_wait_for_completion": True,
                "xc_live_refresh_wait_timeout_seconds": 8,
            },
        )
        order = []

        def catalog(*args, **kwargs):
            order.append("catalog")
            return iter(["[]"])

        def request_refresh(*args, **kwargs):
            order.append("request")
            return {"completion_keys": ["complete:1"]}

        def wait(*args, **kwargs):
            order.append("wait")
            return {"completed": True, "pending": 0}

        with patch(
            "apps.output.views._xc_stream_live_streams",
            side_effect=catalog,
        ), patch(
            "apps.m3u.client_refresh.handle_xc_live_catalog_request",
            side_effect=request_refresh,
        ) as handle, patch(
            "apps.m3u.client_refresh.wait_for_xc_live_refresh",
            side_effect=wait,
        ):
            response = list(
                _xc_stream_live_streams_then_refresh(request, user)
            )

        self.assertEqual(response, ["[]"])
        self.assertEqual(order, ["request", "wait", "catalog"])
        handle.assert_called_once_with(
            request,
            user,
            wait_for_completion=True,
            wait_timeout_seconds=8,
        )
