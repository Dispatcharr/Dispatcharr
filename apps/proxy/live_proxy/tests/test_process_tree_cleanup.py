"""Process-group isolation for live-proxy posix_spawn helpers."""

import os
import pathlib
import signal
import time
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.utils import posix_spawn_proc, signal_process_tree


def _direct_children(pid):
    children = []
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            parts = (entry / "stat").read_text().split()
            if int(parts[3]) == pid:
                children.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
            continue
    return children


def _pid_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class SignalProcessTreeTests(SimpleTestCase):
    def test_group_leader_signals_process_group(self):
        with patch("os.getpgid", return_value=1234), patch("os.killpg") as killpg, patch(
            "os.kill"
        ) as kill:
            signal_process_tree(1234, signal.SIGTERM)
        killpg.assert_called_once_with(1234, signal.SIGTERM)
        kill.assert_not_called()

    def test_non_leader_signals_only_pid(self):
        """Never broadcast into another process group (e.g. the worker itself)."""
        with patch("os.getpgid", return_value=1), patch("os.killpg") as killpg, patch(
            "os.kill"
        ) as kill:
            signal_process_tree(1234, signal.SIGKILL)
        kill.assert_called_once_with(1234, signal.SIGKILL)
        killpg.assert_not_called()

    def test_missing_process_is_ignored(self):
        with patch("os.getpgid", side_effect=ProcessLookupError):
            signal_process_tree(999999, signal.SIGKILL)


class PosixSpawnProcProcessGroupTests(SimpleTestCase):
    def test_spawn_is_session_leader(self):
        proc = posix_spawn_proc(["/bin/sleep", "30"])
        try:
            self.assertEqual(os.getpgid(proc.pid), proc.pid)
            self.assertIsNone(proc.poll())
        finally:
            proc.kill()
            proc.wait(timeout=2)

    def test_kill_terminates_shell_children(self):
        """
        Stream profiles often launch a shell that starts ffmpeg/vlc children.
        Stopping the stream must not leave those children orphaned under PID 1.
        """
        proc = posix_spawn_proc(
            ["/bin/sh", "-c", "sleep 60 & sleep 60 & wait"]
        )
        try:
            deadline = time.monotonic() + 2.0
            children = []
            while time.monotonic() < deadline:
                children = _direct_children(proc.pid)
                if len(children) >= 2:
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(
                len(children),
                2,
                f"expected shell children before kill, got {children}",
            )
            self.assertEqual(os.getpgid(proc.pid), proc.pid)

            proc.kill()
            proc.wait(timeout=2)

            # Direct child is gone; former grandchildren must not survive as orphans.
            time.sleep(0.1)
            survivors = [pid for pid in children if _pid_exists(pid)]
            self.assertEqual(
                survivors,
                [],
                f"orphaned child processes survived kill: {survivors}",
            )
        finally:
            if proc.poll() is None:
                try:
                    os.kill(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
            for pid in _direct_children(proc.pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
