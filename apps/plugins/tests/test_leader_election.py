"""Leader election for persistent plugin services (on_leader_acquired/on_leader_lost).

Covers acquire/renew/release against a mocked Redis client, exactly-once
transition semantics, exception isolation, and synchronous teardown on
disable/reload; see the "Takedown/cleanup hardening" section of the plan
this implements.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.plugins.loader import LoadedPlugin, PluginManager


def _plugin_with_leader_hooks(key="leader_plugin", capabilities=("persistent_service",)):
    instance = MagicMock()
    instance.on_leader_acquired = MagicMock()
    instance.on_leader_lost = MagicMock()
    return (
        LoadedPlugin(key=key, name=key, instance=instance, loaded=True, capabilities=list(capabilities)),
        instance,
    )


def _plugin_without_leader_hooks(key="plain_plugin"):
    instance = MagicMock(spec=[])  # no on_leader_acquired/on_leader_lost attrs
    return LoadedPlugin(key=key, name=key, instance=instance, loaded=True), instance


class LeaderElectionRedisPrimitiveTests(SimpleTestCase):
    def _pm_with_redis(self, client):
        pm = PluginManager()
        pm.worker_id = "host:123"
        pm._leader_redis_client = MagicMock(return_value=client)
        return pm

    def test_acquire_succeeds_when_key_absent(self):
        client = MagicMock()
        client.set.return_value = True
        pm = self._pm_with_redis(client)

        self.assertTrue(pm.try_acquire_leadership("p"))
        client.set.assert_called_once_with("plugin:p:leader", "host:123", nx=True, ex=pm.LEADER_LEASE_TTL)

    def test_acquire_fails_when_held_by_another_worker(self):
        client = MagicMock()
        client.set.return_value = False
        client.get.return_value = "other-host:999"
        pm = self._pm_with_redis(client)

        self.assertFalse(pm.try_acquire_leadership("p"))

    def test_acquire_treats_own_stale_lock_as_success(self):
        client = MagicMock()
        client.set.return_value = False
        client.get.return_value = "host:123"
        pm = self._pm_with_redis(client)

        self.assertTrue(pm.try_acquire_leadership("p"))
        client.expire.assert_called_once()

    def test_acquire_with_no_redis_always_succeeds(self):
        pm = PluginManager()
        pm._leader_redis_client = MagicMock(return_value=None)
        self.assertTrue(pm.try_acquire_leadership("p"))

    def test_extend_succeeds_when_still_owner(self):
        client = MagicMock()
        client.get.return_value = "host:123"
        pm = self._pm_with_redis(client)

        self.assertTrue(pm.extend_leadership("p"))
        client.expire.assert_called_once_with("plugin:p:leader", pm.LEADER_LEASE_TTL)

    def test_extend_fails_when_owned_by_another(self):
        client = MagicMock()
        client.get.return_value = "other-host:999"
        pm = self._pm_with_redis(client)

        self.assertFalse(pm.extend_leadership("p"))

    def test_extend_reacquires_on_outright_expiry(self):
        client = MagicMock()
        client.get.return_value = None
        client.set.return_value = True
        pm = self._pm_with_redis(client)

        self.assertTrue(pm.extend_leadership("p"))

    def test_release_only_deletes_if_still_owner(self):
        client = MagicMock()
        client.get.return_value = "other-host:999"
        pm = self._pm_with_redis(client)

        pm.release_leadership("p")
        client.delete.assert_not_called()

    def test_release_deletes_when_owner(self):
        client = MagicMock()
        client.get.return_value = "host:123"
        pm = self._pm_with_redis(client)

        pm.release_leadership("p")
        client.delete.assert_called_once_with("plugin:p:leader")


class LeaderElectionTransitionTests(SimpleTestCase):
    def test_transition_to_leader_calls_hook_once_and_sets_state(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks()

        pm._transition_to_leader("k", lp)

        instance.on_leader_acquired.assert_called_once()
        self.assertEqual(pm._leadership_state["k"], "leader")

    def test_transition_to_follower_only_fires_hook_if_was_leader(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks()

        # Not currently tracked as leader; must be a no-op.
        pm._transition_to_follower("k", lp)
        instance.on_leader_lost.assert_not_called()

        pm._leadership_state["k"] = "leader"
        pm._transition_to_follower("k", lp)
        instance.on_leader_lost.assert_called_once()
        self.assertEqual(pm._leadership_state["k"], "follower")

        # Calling again while already follower must not double-fire.
        pm._transition_to_follower("k", lp)
        instance.on_leader_lost.assert_called_once()

    def test_exception_in_on_leader_acquired_releases_and_reverts_state(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks()
        instance.on_leader_acquired.side_effect = RuntimeError("boom")
        pm.release_leadership = MagicMock()

        # Must not raise.
        pm._transition_to_leader("k", lp)

        self.assertEqual(pm._leadership_state["k"], "follower")
        pm.release_leadership.assert_called_once_with("k")

    def test_reacquiring_after_lost_calls_acquired_again(self):
        """Failback: losing then re-acquiring must re-run on_leader_acquired,
        not assume the plugin's service is still running."""
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks()

        pm._transition_to_leader("k", lp)
        pm._transition_to_follower("k", lp)
        pm._transition_to_leader("k", lp)

        self.assertEqual(instance.on_leader_acquired.call_count, 2)
        self.assertEqual(instance.on_leader_lost.call_count, 1)


class LeadershipTickTests(SimpleTestCase):
    def test_plugin_without_hook_is_never_touched(self):
        pm = PluginManager()
        lp, _instance = _plugin_without_leader_hooks("plain")
        pm._registry = {"plain": lp}
        pm.try_acquire_leadership = MagicMock()

        pm._leadership_tick()

        pm.try_acquire_leadership.assert_not_called()
        self.assertNotIn("plain", pm._leadership_state)

    def test_new_leader_hook_plugin_attempts_acquire_then_calls_hook(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks("svc")
        pm._registry = {"svc": lp}
        pm.try_acquire_leadership = MagicMock(return_value=True)

        pm._leadership_tick()

        instance.on_leader_acquired.assert_called_once()
        self.assertEqual(pm._leadership_state["svc"], "leader")

    def test_current_leader_extends_without_recalling_hook(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks("svc")
        pm._registry = {"svc": lp}
        pm._leadership_state["svc"] = "leader"
        pm.extend_leadership = MagicMock(return_value=True)

        pm._leadership_tick()

        pm.extend_leadership.assert_called_once_with("svc")
        instance.on_leader_acquired.assert_not_called()

    def test_renewal_failure_triggers_lost_then_next_tick_reacquires(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks("svc")
        pm._registry = {"svc": lp}
        pm._leadership_state["svc"] = "leader"
        pm.extend_leadership = MagicMock(return_value=False)
        pm.try_acquire_leadership = MagicMock(return_value=True)

        pm._leadership_tick()  # loses leadership
        instance.on_leader_lost.assert_called_once()
        self.assertEqual(pm._leadership_state["svc"], "follower")

        pm._leadership_tick()  # reacquires
        instance.on_leader_acquired.assert_called_once()
        self.assertEqual(pm._leadership_state["svc"], "leader")

    def test_hook_without_persistent_service_capability_is_skipped(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks("svc", capabilities=())
        pm._registry = {"svc": lp}
        pm.try_acquire_leadership = MagicMock()

        pm._leadership_tick()

        pm.try_acquire_leadership.assert_not_called()
        instance.on_leader_acquired.assert_not_called()
        self.assertNotIn("svc", pm._leadership_state)

    def test_hook_with_persistent_service_capability_runs(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks("svc", capabilities=("persistent_service",))
        pm._registry = {"svc": lp}
        pm.try_acquire_leadership = MagicMock(return_value=True)

        pm._leadership_tick()

        instance.on_leader_acquired.assert_called_once()
        self.assertEqual(pm._leadership_state["svc"], "leader")

    def test_one_plugin_exception_does_not_stop_others(self):
        pm = PluginManager()
        broken_lp, broken_instance = _plugin_with_leader_hooks("broken")
        ok_lp, ok_instance = _plugin_with_leader_hooks("ok")
        pm._registry = {"broken": broken_lp, "ok": ok_lp}

        def acquire(key, ttl=None):
            if key == "broken":
                raise RuntimeError("redis exploded")
            return True

        pm.try_acquire_leadership = MagicMock(side_effect=acquire)

        # Must not raise, and must still process "ok".
        pm._leadership_tick()

        ok_instance.on_leader_acquired.assert_called_once()
        self.assertEqual(pm._leadership_state.get("ok"), "leader")
        self.assertNotIn("broken", pm._leadership_state)


class ReleasePluginLeadershipTests(SimpleTestCase):
    def test_release_plugin_leadership_calls_lost_hook_and_redis_release(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks("svc")
        pm._registry = {"svc": lp}
        pm._leadership_state["svc"] = "leader"
        pm.release_leadership = MagicMock()

        pm._release_plugin_leadership("svc")

        instance.on_leader_lost.assert_called_once()
        pm.release_leadership.assert_called_once_with("svc")

    def test_release_plugin_leadership_safe_for_non_leader(self):
        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks("svc")
        pm._registry = {"svc": lp}
        pm.release_leadership = MagicMock()

        # Never was leader; must not raise, must not call the hook.
        pm._release_plugin_leadership("svc")

        instance.on_leader_lost.assert_not_called()
        pm.release_leadership.assert_called_once_with("svc")

    def test_release_plugin_leadership_safe_for_unknown_key(self):
        pm = PluginManager()
        pm._registry = {}
        pm.release_leadership = MagicMock()

        # get_plugin("missing") returns None; must not raise.
        pm._release_plugin_leadership("missing")
        pm.release_leadership.assert_called_once_with("missing")


class ReleaseAllLeadershipsTests(SimpleTestCase):
    def test_releases_only_currently_held_leaderships(self):
        pm = PluginManager()
        led_lp, led_instance = _plugin_with_leader_hooks("led")
        other_lp, other_instance = _plugin_with_leader_hooks("other")
        pm._registry = {"led": led_lp, "other": other_lp}
        pm._leadership_state = {"led": "leader", "other": "follower"}
        pm.release_leadership = MagicMock()

        pm.release_all_leaderships()

        led_instance.on_leader_lost.assert_called_once()
        other_instance.on_leader_lost.assert_not_called()
        pm.release_leadership.assert_called_once_with("led")

    def test_one_plugin_failure_does_not_stop_release_of_others(self):
        pm = PluginManager()
        broken_lp, broken_instance = _plugin_with_leader_hooks("broken")
        ok_lp, ok_instance = _plugin_with_leader_hooks("ok")
        pm._registry = {"broken": broken_lp, "ok": ok_lp}
        pm._leadership_state = {"broken": "leader", "ok": "leader"}
        broken_instance.on_leader_lost.side_effect = RuntimeError("boom")
        pm.release_leadership = MagicMock()

        # Must not raise.
        pm.release_all_leaderships()

        ok_instance.on_leader_lost.assert_called_once()


class StopPluginReleasesLeadershipTests(SimpleTestCase):
    def test_stop_plugin_releases_leadership_before_calling_stop(self):
        from apps.plugins.models import PluginConfig

        pm = PluginManager()
        lp, instance = _plugin_with_leader_hooks("svc")
        instance.stop = MagicMock()
        pm._registry = {"svc": lp}
        pm._leadership_state["svc"] = "leader"

        cfg = MagicMock(enabled=True, settings={})
        with patch.object(pm, "get_plugin", return_value=lp), patch.object(
            pm, "release_leadership"
        ), patch(
            "apps.plugins.loader.PluginConfig.objects.get", return_value=cfg
        ), patch("apps.plugins.loader.close_old_connections"):
            pm.stop_plugin("svc", reason="disable")

        instance.on_leader_lost.assert_called_once()
        self.assertEqual(pm._leadership_state["svc"], "follower")
        instance.stop.assert_called_once()


class LeadershipLoopStartupTests(SimpleTestCase):
    def test_thread_not_started_under_testing_settings(self):
        # settings_test.py sets TESTING = True; this is the default here.
        with patch("threading.Thread") as mock_thread:
            PluginManager()
            mock_thread.assert_not_called()

    @override_settings(TESTING=False)
    def test_thread_started_once_when_not_testing(self):
        with patch("threading.Thread") as mock_thread:
            pm = PluginManager()  # __init__ calls _ensure_leadership_loop_started once
            pm._ensure_leadership_loop_started()  # second call must be a no-op

            mock_thread.assert_called_once()
            _args, kwargs = mock_thread.call_args
            self.assertEqual(kwargs.get("target"), pm._leadership_loop)
            self.assertTrue(kwargs.get("daemon"))
