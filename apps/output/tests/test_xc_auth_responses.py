"""XC API entry points return authorize_xc_client error responses as-is."""

from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.accounts.xc_auth import (
    XC_AUTH_CREDENTIALS,
    XC_AUTH_NETWORK,
    XC_AUTH_RATE_LIMIT,
    xc_auth_error_response,
)
from apps.output.views import xc_get, xc_panel_api, xc_player_api, xc_xmltv


class XcApiAuthStatusTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _assert_endpoint_statuses(self, view, path):
        request = self.factory.get(path, {"username": "u", "password": "p"})
        with patch(
            "apps.output.views.authorize_xc_client",
            return_value=(None, xc_auth_error_response(XC_AUTH_NETWORK)),
        ), patch("apps.output.views.log_system_event"):
            self.assertEqual(view(request).status_code, 403)

        with patch(
            "apps.output.views.authorize_xc_client",
            return_value=(None, xc_auth_error_response(XC_AUTH_CREDENTIALS)),
        ), patch("apps.output.views.log_system_event"):
            self.assertEqual(view(request).status_code, 401)

    def test_player_api(self):
        self._assert_endpoint_statuses(xc_player_api, "/player_api.php")

    def test_panel_api(self):
        self._assert_endpoint_statuses(xc_panel_api, "/panel_api.php")

    def test_get_php(self):
        self._assert_endpoint_statuses(xc_get, "/get.php")

    def test_xmltv_php(self):
        self._assert_endpoint_statuses(xc_xmltv, "/xmltv.php")

    def test_get_logs_network_separately_from_credentials(self):
        request = self.factory.get("/get.php", {"username": "u", "password": "p"})
        with patch(
            "apps.output.views.authorize_xc_client",
            return_value=(None, xc_auth_error_response(XC_AUTH_NETWORK)),
        ), patch("apps.output.views.log_system_event") as log_event:
            xc_get(request)
        self.assertEqual(
            log_event.call_args.kwargs["reason"],
            "Network access denied (XC API)",
        )

        with patch(
            "apps.output.views.authorize_xc_client",
            return_value=(None, xc_auth_error_response(XC_AUTH_CREDENTIALS)),
        ), patch("apps.output.views.log_system_event") as log_event:
            xc_get(request)
        self.assertEqual(
            log_event.call_args.kwargs["reason"],
            "Invalid XC credentials",
        )

        with patch(
            "apps.output.views.authorize_xc_client",
            return_value=(None, xc_auth_error_response(XC_AUTH_RATE_LIMIT)),
        ), patch("apps.output.views.log_system_event") as log_event:
            xc_get(request)
        self.assertEqual(
            log_event.call_args.kwargs["reason"],
            "XC auth rate limited",
        )
