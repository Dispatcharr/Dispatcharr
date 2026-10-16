"""In-process HLS playlist-ready waiter registry."""

import time

import gevent
from django.test import SimpleTestCase

from apps.proxy.live_proxy.output.hls import waiters


class PlaylistWaiterTests(SimpleTestCase):
    def setUp(self):
        waiters._waiters.clear()

    def tearDown(self):
        waiters._waiters.clear()

    def test_notify_sets_only_matching_waiters(self):
        a = waiters.register_playlist_waiter("chan-a", "hls")
        b = waiters.register_playlist_waiter("chan-a", "hls:p3")
        c = waiters.register_playlist_waiter("chan-b", "hls")

        waiters.notify_playlist_ready("chan-a", "hls")

        self.assertTrue(a.is_set())
        self.assertFalse(b.is_set())
        self.assertFalse(c.is_set())

    def test_every_waiter_on_the_same_channel_is_woken(self):
        first = waiters.register_playlist_waiter("chan", "hls")
        second = waiters.register_playlist_waiter("chan", "hls")

        waiters.notify_playlist_ready("chan", "hls")

        self.assertTrue(first.is_set())
        self.assertTrue(second.is_set())

    def test_unregister_removes_the_waiter(self):
        event = waiters.register_playlist_waiter("chan", "hls")
        waiters.unregister_playlist_waiter("chan", "hls", event)
        waiters.notify_playlist_ready("chan", "hls")
        self.assertFalse(event.is_set())
        self.assertNotIn(("chan", "hls"), waiters._waiters)

    def test_unregister_of_unknown_waiter_is_a_no_op(self):
        other = waiters.register_playlist_waiter("chan", "hls")
        stranger = waiters.register_playlist_waiter("elsewhere", "hls")
        waiters.unregister_playlist_waiter("chan", "hls", stranger)
        waiters.unregister_playlist_waiter("nobody", "hls", stranger)
        waiters.notify_playlist_ready("chan", "hls")
        self.assertTrue(other.is_set())

    def test_notify_with_no_waiters_is_a_no_op(self):
        waiters.notify_playlist_ready("missing", "hls")

    def test_notify_wakes_a_blocked_waiter_long_before_its_timeout(self):
        event = waiters.register_playlist_waiter("chan", "hls")
        waited = []

        def block():
            started = time.monotonic()
            event.wait(timeout=5)
            waited.append(time.monotonic() - started)

        greenlet = gevent.spawn(block)
        gevent.sleep(0.01)
        waiters.notify_playlist_ready("chan", "hls")
        greenlet.join(timeout=2)

        self.assertEqual(len(waited), 1)
        self.assertLess(waited[0], 1.0)

    def test_notify_before_the_wait_is_not_lost(self):
        event = waiters.register_playlist_waiter("chan", "hls")
        waiters.notify_playlist_ready("chan", "hls")

        started = time.monotonic()
        woke = event.wait(timeout=5)

        self.assertTrue(woke)
        self.assertLess(time.monotonic() - started, 1.0)
