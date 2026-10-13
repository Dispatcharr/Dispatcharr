"""Plugin logo endpoint must accept native image-loader Accept headers."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase


class PluginLogoAcceptHeaderTests(TestCase):
    def test_logo_serves_image_for_image_accept_header(self):
        """Native image loaders send Accept: image/*; that must not 406."""
        with tempfile.TemporaryDirectory() as plugins_dir:
            key = "accept_logo_plugin"
            plugin_dir = Path(plugins_dir) / key
            plugin_dir.mkdir()
            logo_path = plugin_dir / "logo.png"
            logo_bytes = b"\x89PNG\r\n\x1a\n" + b"plugin-logo"
            logo_path.write_bytes(logo_bytes)

            with patch.dict(os.environ, {"DISPATCHARR_PLUGINS_DIR": plugins_dir}):
                # PluginManager is a singleton; reset so it picks up the env path.
                from apps.plugins.loader import PluginManager

                PluginManager._instance = None
                try:
                    response = self.client.get(
                        f"/api/plugins/plugins/{key}/logo/",
                        HTTP_ACCEPT="image/*",
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get("Content-Type"), "image/png")
                    self.assertEqual(b"".join(response.streaming_content), logo_bytes)
                finally:
                    PluginManager._instance = None
