import os
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.test import TestCase

from core.models import CoreSettings, SYSTEM_SETTINGS_KEY


class PublicPortEnvSeedTests(TestCase):
    """
    DISPATCHARR_PUBLIC_PORT pre-fills Settings > System > Public Port at
    startup for Docker deployments that map a non-default host port and
    want it set at deploy time instead of through the admin UI. It must
    only ever seed an *unset* value - once configured (by the env var or
    by hand), the DB value stays the source of truth on every later
    startup, even if the env var is later changed or removed.
    """

    def setUp(self):
        cache.clear()
        CoreSettings.objects.filter(key=SYSTEM_SETTINGS_KEY).delete()
        self.config = apps.get_app_config("core")

    def tearDown(self):
        cache.clear()

    def test_seeds_unset_value_from_env(self):
        with patch.dict(os.environ, {"DISPATCHARR_PUBLIC_PORT": "8080"}):
            self.config._seed_public_port_from_env()
        self.assertEqual(CoreSettings.get_public_port(), "8080")

    def test_does_not_override_an_already_configured_value(self):
        """A UI-set (or previously env-seeded) value must survive even if
        the env var is later changed - the DB is the source of truth once
        anything has been configured."""
        CoreSettings.set_public_port("80")
        with patch.dict(os.environ, {"DISPATCHARR_PUBLIC_PORT": "8080"}):
            self.config._seed_public_port_from_env()
        self.assertEqual(CoreSettings.get_public_port(), "80")

    def test_no_env_var_leaves_setting_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPATCHARR_PUBLIC_PORT", None)
            self.config._seed_public_port_from_env()
        self.assertIsNone(CoreSettings.get_public_port())
