"""MacPanelClient tests. No real HTTP is ever made — every requests.Session
call is patched. These panels must never be hit by the automated suite."""
import json
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

from apps.mac_panel.client import MacPanelClient, MacPanelError


def _mock_response(status_code=200, json_data=None, text=None, content=b"x"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.content = content
    if text is not None:
        resp.text = text
        resp.json.side_effect = ValueError("no json")
    else:
        resp.text = json.dumps(json_data or {})
        resp.json.return_value = json_data or {}
    return resp


class MacPanelClientTests(SimpleTestCase):
    def setUp(self):
        self.client = MacPanelClient("https://panel.example.com")

    @patch("requests.Session.request")
    def test_successful_login(self, mock_request):
        mock_request.return_value = _mock_response(
            200,
            {"token": "jwt-abc", "device": {"_id": "dev1"}, "message": "ok"},
        )
        data = self.client.device_login("AA:BB:CC:DD:EE:FF", "key", "ABCD", "captcha-token")
        self.assertEqual(data["token"], "jwt-abc")
        # captcha uppercased before sending
        sent_body = mock_request.call_args.kwargs["json"]
        self.assertEqual(sent_body["captcha"], "ABCD")

    @patch("requests.Session.request")
    def test_successful_save_playlist(self, mock_request):
        mock_request.return_value = _mock_response(
            200, {"message": "Playlist saved", "playlist": {"_id": "pl1"}}
        )
        data = self.client.save_playlist("jwt-abc", "dev1", {"playlist_type": "xc"})
        self.assertEqual(data["message"], "Playlist saved")

    @patch("requests.Session.request")
    def test_wrong_captcha_raises_with_panel_message(self, mock_request):
        mock_request.return_value = _mock_response(
            400, {"success": False, "message": "Invalid captcha"}
        )
        with self.assertRaises(MacPanelError) as ctx:
            self.client.device_login("AA:BB:CC:DD:EE:FF", "key", "WRONG", "captcha-token")
        self.assertIn("Invalid captcha", str(ctx.exception))

    @patch("requests.Session.request")
    def test_html_error_page_instead_of_json(self, mock_request):
        mock_request.return_value = _mock_response(
            200, text="<html><body>502 Bad Gateway</body></html>"
        )
        with self.assertRaises(MacPanelError) as ctx:
            self.client.get_captcha()
        self.assertIn("HTML", str(ctx.exception))

    @patch("requests.Session.request")
    def test_connection_timeout(self, mock_request):
        mock_request.side_effect = requests.Timeout("timed out")
        with self.assertRaises(MacPanelError) as ctx:
            self.client.get_captcha()
        self.assertIn("Timed out", str(ctx.exception))

    def test_missing_base_url_raises(self):
        with self.assertRaises(MacPanelError):
            MacPanelClient("")
