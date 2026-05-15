# connect/handlers/script.py
import os
import select as _select
import signal as _signal
import stat
import time
from django.conf import settings
from .base import IntegrationHandler


def _waitpid_nonblocking(pid, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return -1
        if wpid == pid:
            return os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status)
        time.sleep(0.01)
    return -1


def _posix_run(path, env, timeout):
    stdout_r, stdout_w = os.pipe()
    stderr_r, stderr_w = os.pipe()
    devnull_r = os.open(os.devnull, os.O_RDONLY)
    file_actions = [
        (os.POSIX_SPAWN_DUP2, devnull_r, 0),
        (os.POSIX_SPAWN_DUP2, stdout_w, 1),
        (os.POSIX_SPAWN_DUP2, stderr_w, 2),
        (os.POSIX_SPAWN_CLOSE, devnull_r),
        (os.POSIX_SPAWN_CLOSE, stdout_w),
        (os.POSIX_SPAWN_CLOSE, stderr_w),
        (os.POSIX_SPAWN_CLOSE, stdout_r),
        (os.POSIX_SPAWN_CLOSE, stderr_r),
    ]
    try:
        pid = os.posix_spawn(path, [path], env, file_actions=file_actions)
    except Exception:
        for fd in (stdout_r, stdout_w, stderr_r, stderr_w, devnull_r):
            try:
                os.close(fd)
            except OSError:
                pass
        raise
    for fd in (devnull_r, stdout_w, stderr_w):
        os.close(fd)

    out, err = [], []
    done = set()
    deadline = time.monotonic() + timeout
    timed_out = False

    try:
        while len(done) < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                try:
                    os.kill(pid, _signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break

            fds = [fd for fd in (stdout_r, stderr_r) if fd not in done]
            readable, _, _ = _select.select(fds, [], [], min(remaining, 0.5))
            for fd in readable:
                data = os.read(fd, 8192)
                if data:
                    (out if fd == stdout_r else err).append(data)
                else:
                    done.add(fd)
    finally:
        for fd in (stdout_r, stderr_r):
            try:
                os.close(fd)
            except OSError:
                pass

    rc = _waitpid_nonblocking(pid)
    if timed_out:
        raise TimeoutError(f"Script exceeded {timeout}s")
    return rc, b"".join(out).decode("utf-8", errors="replace"), b"".join(err).decode("utf-8", errors="replace")


def _is_path_allowed(real_path: str) -> bool:
    # Ensure path is within one of the allowed directories
    for base in getattr(settings, "CONNECT_ALLOWED_SCRIPT_DIRS", []):
        base_abs = os.path.abspath(base) + os.sep
        if real_path.startswith(base_abs):
            return True
    return False


class ScriptHandler(IntegrationHandler):
    def execute(self):
        raw_path = self.integration.config.get("path")
        if not raw_path:
            raise ValueError("Missing 'path' in integration config")

        # Resolve and validate path
        real_path = os.path.abspath(os.path.realpath(raw_path))

        if not os.path.exists(real_path):
            raise FileNotFoundError(f"Script not found: {real_path}")

        if not _is_path_allowed(real_path):
            raise PermissionError(
                f"Script path '{real_path}' not within allowed directories: "
                f"{getattr(settings, 'CONNECT_ALLOWED_SCRIPT_DIRS', [])}"
            )

        if getattr(settings, "CONNECT_SCRIPT_REQUIRE_EXECUTABLE", True):
            if not os.access(real_path, os.X_OK):
                raise PermissionError(f"Script is not executable: {real_path}")

        if getattr(settings, "CONNECT_SCRIPT_DISALLOW_WORLD_WRITABLE", True):
            st = os.stat(real_path)
            if st.st_mode & stat.S_IWOTH:
                raise PermissionError(
                    f"Refusing to execute world-writable script: {real_path}"
                )

        # Build a sanitized minimal environment; avoid inheriting secrets
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
        for key, value in (self.payload or {}).items():
            env_key = f"DISPATCHARR_{str(key).upper()}"
            env[env_key] = "" if value is None else str(value)

        # Run with a timeout to prevent hanging scripts
        timeout = getattr(settings, "CONNECT_SCRIPT_TIMEOUT", 10)
        max_out = getattr(settings, "CONNECT_SCRIPT_MAX_OUTPUT", 65536)

        rc, stdout, stderr = _posix_run(real_path, env, timeout)

        # Truncate outputs to avoid excessive memory/logging
        if len(stdout) > max_out:
            stdout = stdout[:max_out] + "... [truncated]"
        if len(stderr) > max_out:
            stderr = stderr[:max_out] + "... [truncated]"

        return {
            "exit_code": rc,
            "stdout": stdout,
            "stderr": stderr,
            "success": rc == 0,
        }
