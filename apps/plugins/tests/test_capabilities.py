"""apps.plugins.capabilities: manifest capability/version computation."""

from django.test import SimpleTestCase

from apps.plugins.capabilities import (
    compute_effective_capabilities,
    describe_capabilities,
    manifest_version_supported,
    min_app_version_for_manifest_version,
    parse_manifest_version,
)


class ComputeEffectiveCapabilitiesTests(SimpleTestCase):
    def test_explicit_declaration(self):
        manifest = {"capabilities": ["background_tasks"]}
        self.assertEqual(compute_effective_capabilities(manifest), ["background_tasks"])

    def test_async_action_implies_background_tasks(self):
        manifest = {"actions": [{"id": "a", "async": True}]}
        self.assertEqual(compute_effective_capabilities(manifest), ["background_tasks"])

    def test_no_capabilities_no_async_actions(self):
        manifest = {"actions": [{"id": "a"}]}
        self.assertEqual(compute_effective_capabilities(manifest), [])

    def test_unknown_capability_passes_through(self):
        manifest = {"capabilities": ["some_future_capability"]}
        self.assertEqual(compute_effective_capabilities(manifest), ["some_future_capability"])

    def test_malformed_capabilities_ignored(self):
        manifest = {"capabilities": "background_tasks"}  # not a list
        self.assertEqual(compute_effective_capabilities(manifest), [])

    def test_persistent_service_requires_explicit_declaration(self):
        # Unlike background_tasks, there's no manifest signal (like
        # action.async) that implies persistent_service; it must be
        # declared explicitly for on_leader_acquired to ever run.
        manifest = {"capabilities": ["persistent_service"]}
        self.assertEqual(compute_effective_capabilities(manifest), ["persistent_service"])

    def test_dedupes_and_sorts(self):
        manifest = {
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
        }])


class ManifestVersionTests(SimpleTestCase):
    def test_absent_defaults_to_zero(self):
        self.assertEqual(parse_manifest_version({}), 0)

    def test_explicit_version(self):
        self.assertEqual(parse_manifest_version({"manifest_version": 1}), 1)

    def test_garbage_falls_back_to_zero(self):
        self.assertEqual(parse_manifest_version({"manifest_version": "not-a-number"}), 0)
        self.assertEqual(parse_manifest_version({"manifest_version": -5}), 0)

    def test_min_app_version_known(self):
        self.assertEqual(min_app_version_for_manifest_version(0), "0.0.0")

    def test_min_app_version_unknown_falls_back_to_highest_known(self):
        self.assertEqual(
            min_app_version_for_manifest_version(99),
            min_app_version_for_manifest_version(1),
        )

    def test_manifest_version_supported(self):
        self.assertTrue(manifest_version_supported(0, "0.1.0"))
        self.assertTrue(manifest_version_supported(1, "0.29.0"))
        self.assertFalse(manifest_version_supported(1, "0.1.0"))
