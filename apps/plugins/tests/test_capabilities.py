"""apps.plugins.capabilities: manifest capability/version computation."""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.plugins.capabilities import (
    MANIFEST_SCHEMA_POLICIES,
    capability_supported_by_manifest_version,
    compute_effective_capabilities,
    describe_capabilities,
    max_app_version_for_manifest_version,
    manifest_version_enforces_sandbox,
    manifest_schema_policy,
    manifest_version_parses_capabilities,
    manifest_version_supported,
    min_app_version_for_manifest_version,
    parse_manifest_version,
)


class ComputeEffectiveCapabilitiesTests(SimpleTestCase):
    def test_explicit_declaration(self):
        manifest = {"manifest_version": 1, "capabilities": ["background_tasks"]}
        self.assertEqual(compute_effective_capabilities(manifest), ["background_tasks"])

    def test_async_action_implies_background_tasks(self):
        manifest = {"manifest_version": 1, "actions": [{"id": "a", "async": True}]}
        self.assertEqual(compute_effective_capabilities(manifest), ["background_tasks"])

    def test_legacy_manifest_does_not_parse_capabilities(self):
        manifest = {
            "capabilities": ["background_tasks"],
            "actions": [{"id": "a", "async": True}],
        }
        self.assertEqual(compute_effective_capabilities(manifest), [])

    def test_no_capabilities_no_async_actions(self):
        manifest = {"actions": [{"id": "a"}]}
        self.assertEqual(compute_effective_capabilities(manifest), [])

    def test_unknown_capability_passes_through(self):
        manifest = {"manifest_version": 1, "capabilities": ["some_future_capability"]}
        self.assertEqual(compute_effective_capabilities(manifest), ["some_future_capability"])

    def test_malformed_capabilities_ignored(self):
        manifest = {"manifest_version": 1, "capabilities": "background_tasks"}  # not a list
        self.assertEqual(compute_effective_capabilities(manifest), [])

    def test_persistent_service_requires_explicit_declaration(self):
        # Unlike background_tasks, there's no manifest signal (like
        # action.async) that implies persistent_service; it must be
        # declared explicitly for on_leader_acquired to ever run.
        manifest = {"manifest_version": 1, "capabilities": ["persistent_service"]}
        self.assertEqual(compute_effective_capabilities(manifest), ["persistent_service"])

    def test_dedupes_and_sorts(self):
        manifest = {
            "manifest_version": 1,
            "capabilities": ["background_tasks", "background_tasks", "aaa_capability"],
        }
        self.assertEqual(
            compute_effective_capabilities(manifest), ["aaa_capability", "background_tasks"]
        )


class DescribeCapabilitiesTests(SimpleTestCase):
    def test_known_capability(self):
        result = describe_capabilities(["background_tasks"])
        self.assertEqual(result, [{
            "id": "background_tasks",
            "label": "Run background tasks",
            "description": "Runs long-running or scheduled work on Dispatcharr's shared background task queue.",
            "requires_restart": False,
            "impact": "standard",
        }])

    def test_persistent_service_capability_does_not_require_restart(self):
        result = describe_capabilities(["persistent_service"])
        self.assertEqual(result[0]["id"], "persistent_service")
        self.assertFalse(result[0]["requires_restart"])

    def test_unknown_capability_generic_label(self):
        result = describe_capabilities(["mystery_capability"])
        self.assertEqual(result, [{
            "id": "mystery_capability",
            "label": "Custom capability: mystery_capability",
            "description": "",
            "requires_restart": False,
            "impact": "standard",
        }])


class CapabilityManifestVersionTests(SimpleTestCase):
    def test_known_capabilities_are_supported_from_manifest_version_one(self):
        self.assertFalse(capability_supported_by_manifest_version("background_tasks", 0))
        self.assertTrue(capability_supported_by_manifest_version("background_tasks", 1))
        self.assertTrue(capability_supported_by_manifest_version("persistent_service", 2))

    def test_unknown_capabilities_are_not_parsed_by_legacy_manifests(self):
        self.assertFalse(capability_supported_by_manifest_version("future_capability", 0))
        self.assertTrue(capability_supported_by_manifest_version("future_capability", 1))


class ManifestVersionTests(SimpleTestCase):
    def test_absent_defaults_to_zero(self):
        self.assertEqual(parse_manifest_version({}), 0)

    def test_explicit_version(self):
        self.assertEqual(parse_manifest_version({"manifest_version": 1}), 1)
        self.assertEqual(parse_manifest_version({"manifest_version": 2}), 2)

    def test_garbage_falls_back_to_zero(self):
        self.assertEqual(parse_manifest_version({"manifest_version": "not-a-number"}), 0)
        self.assertEqual(parse_manifest_version({"manifest_version": -5}), 0)

    def test_min_app_version_known(self):
        self.assertIsNone(min_app_version_for_manifest_version(0))
        self.assertEqual(min_app_version_for_manifest_version(2), "0.29.0")

    def test_max_app_version_is_unbounded_for_all_current_schemas(self):
        for manifest_version in (0, 1, 2):
            with self.subTest(manifest_version=manifest_version):
                self.assertIsNone(max_app_version_for_manifest_version(manifest_version))

    def test_min_app_version_unknown_falls_back_to_highest_known(self):
        self.assertEqual(
            min_app_version_for_manifest_version(99),
            min_app_version_for_manifest_version(2),
        )

    def test_manifest_version_supported(self):
        self.assertTrue(manifest_version_supported(0, "0.1.0"))
        self.assertTrue(manifest_version_supported(1, "0.29.0"))
        self.assertFalse(manifest_version_supported(1, "0.1.0"))
        self.assertTrue(manifest_version_supported(2, "0.29.0"))
        self.assertFalse(manifest_version_supported(2, "0.28.2"))

    def test_manifest_version_respects_an_upper_compatibility_bound(self):
        with patch.dict(MANIFEST_SCHEMA_POLICIES, {
            3: {
                "min_app_version": "0.30.0",
                "max_app_version": "0.30.99",
                "enforces_sandbox": True,
            },
        }):
            self.assertTrue(manifest_version_supported(3, "0.30.0"))
            self.assertTrue(manifest_version_supported(3, "0.30.99"))
            self.assertFalse(manifest_version_supported(3, "0.29.99"))
            self.assertFalse(manifest_version_supported(3, "0.31.0"))

    def test_only_version_two_and_later_enforce_the_sandbox(self):
        self.assertFalse(manifest_version_enforces_sandbox(0))
        self.assertFalse(manifest_version_enforces_sandbox(1))
        self.assertTrue(manifest_version_enforces_sandbox(2))
        self.assertTrue(manifest_version_enforces_sandbox(99))

    def test_only_version_one_and_later_parse_capabilities(self):
        self.assertFalse(manifest_version_parses_capabilities(0))
        self.assertTrue(manifest_version_parses_capabilities(1))
        self.assertTrue(manifest_version_parses_capabilities(2))

    def test_future_versions_use_the_latest_known_policy(self):
        self.assertIs(
            manifest_schema_policy(99),
            manifest_schema_policy(2),
        )
