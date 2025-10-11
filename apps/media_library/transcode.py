import contextlib
import hashlib
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Iterable, Tuple

from django.conf import settings
from django.utils import timezone

from .models import MediaFile

logger = logging.getLogger(__name__)

CHUNK_SIZE = 128 * 1024  # 128KB chunks for streaming


def _as_path(value) -> Path:
    if isinstance(value, Path):
        return value
    return Path(str(value))


def _int_setting(name: str, default: int) -> int:
    value = getattr(settings, name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


TRANSCODE_ROOT = _as_path(
    getattr(settings, "MEDIA_LIBRARY_TRANSCODE_DIR", settings.MEDIA_ROOT / "transcoded")
)
TRANSCODE_ROOT.mkdir(parents=True, exist_ok=True)

FFMPEG_PATH = getattr(settings, "MEDIA_LIBRARY_FFMPEG_PATH", "ffmpeg")
VIDEO_BITRATE = _int_setting("MEDIA_LIBRARY_TRANSCODE_VIDEO_BITRATE", 4500)
AUDIO_BITRATE = _int_setting("MEDIA_LIBRARY_TRANSCODE_AUDIO_BITRATE", 192)
PRESET = getattr(settings, "MEDIA_LIBRARY_TRANSCODE_PRESET", "veryfast")
TARGET_VIDEO_CODEC = getattr(settings, "MEDIA_LIBRARY_TRANSCODE_VIDEO_CODEC", "libx264")
TARGET_AUDIO_CODEC = getattr(settings, "MEDIA_LIBRARY_TRANSCODE_AUDIO_CODEC", "aac")
AUDIO_CHANNELS = _int_setting("MEDIA_LIBRARY_TRANSCODE_AUDIO_CHANNELS", 2)


def _build_target_path(media_file: MediaFile) -> Path:
    identifier = media_file.checksum or f"{media_file.absolute_path}:{media_file.size_bytes}"
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
    filename = f"{media_file.id}_{digest}.mp4"
    return TRANSCODE_ROOT / filename


def _normalize_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "video/mp4"


def _build_ffmpeg_command(
    source_path: Path, *, output: str, fragmented: bool, start_seconds: float = 0.0
) -> list[str]:
    command = [FFMPEG_PATH, "-y"]
    if start_seconds and start_seconds > 0:
        command.extend(["-ss", f"{start_seconds:.3f}"])

    command.extend(
        [
            "-i",
            str(source_path),
        ]
    )

    command.extend(
        [
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        TARGET_VIDEO_CODEC,
        "-preset",
        PRESET,
        "-profile:v",
        "high",
        "-level",
        "4.0",
        "-pix_fmt",
        "yuv420p",
        "-max_muxing_queue_size",
        "1024",
        "-c:a",
        TARGET_AUDIO_CODEC,
        "-b:a",
        f"{AUDIO_BITRATE}k",
        "-ac",
        str(max(1, AUDIO_CHANNELS)),
        "-sn",
        ]
    )

    if VIDEO_BITRATE > 0:
        command.extend(["-b:v", f"{VIDEO_BITRATE}k"])

    if fragmented:
        command.extend(["-movflags", "frag_keyframe+empty_moov+faststart", "-f", "mp4", output])
    else:
        command.extend(["-movflags", "+faststart", output])

    return command


def ensure_browser_ready_source(
    media_file: MediaFile, *, force: bool = False
) -> Tuple[str, str]:
    """
    Ensure the provided media file is playable by major browsers (Chromium, Firefox, Safari).
    Returns a tuple of (absolute_path, mime_type) pointing at either the original file (if compatible)
    or a transcoded MP4 fallback.
    """
    if media_file.is_browser_playable() and not force:
        path = _as_path(media_file.absolute_path)
        mime_type, _ = mimetypes.guess_type(path.name)
        return str(path), mime_type or "video/mp4"

    target_path = _ensure_transcode_to_file(media_file, force=force)
    return str(target_path), "video/mp4"


def _ensure_transcode_to_file(media_file: MediaFile, *, force: bool = False) -> Path:
    source_path = _as_path(media_file.absolute_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Media source missing at {source_path}")

    target_path = _build_target_path(media_file)

    # Re-use existing artifact when it is up-to-date unless force=True.
    if (
        not force
        and media_file.transcode_status == MediaFile.TRANSCODE_STATUS_READY
        and media_file.transcoded_path
    ):
        cached_path = Path(media_file.transcoded_path)
        if cached_path.exists():
            source_mtime = source_path.stat().st_mtime
            if cached_path.stat().st_mtime >= source_mtime:
                return cached_path
        # Cached metadata is stale; clear below.

    # Remove stale artifact if a new digest produced a different path.
    if media_file.transcoded_path and media_file.transcoded_path != str(target_path):
        old_path = Path(media_file.transcoded_path)
        if old_path.exists():
            try:
                old_path.unlink()
            except OSError:
                logger.debug("Unable to remove old transcode %s", old_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)

    media_file.transcode_status = MediaFile.TRANSCODE_STATUS_PROCESSING
    media_file.transcode_error = ""
    media_file.requires_transcode = True
    media_file.transcoded_path = ""
    media_file.transcoded_mime_type = ""
    media_file.transcoded_at = None
    media_file.save(
        update_fields=[
            "transcode_status",
            "transcode_error",
            "requires_transcode",
            "transcoded_path",
            "transcoded_mime_type",
            "transcoded_at",
            "updated_at",
        ]
    )

    fd, temp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".mp4")
    os.close(fd)

    command = _build_ffmpeg_command(source_path, output=str(temp_path), fragmented=False)

    logger.info(
        "Transcoding media file %s (%s) to %s for browser playback",
        media_file.id,
        source_path,
        target_path,
    )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr_tail = (result.stderr or "").strip()[-4000:]
            raise RuntimeError(
                f"ffmpeg exited with status {result.returncode}: {stderr_tail}"
            )
        shutil.move(temp_path, target_path)
    except Exception as exc:  # noqa: BLE001
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        media_file.transcode_status = MediaFile.TRANSCODE_STATUS_FAILED
        media_file.transcode_error = str(exc)
        media_file.save(
            update_fields=["transcode_status", "transcode_error", "updated_at"]
        )
        logger.error("Transcoding failed for %s: %s", media_file.id, exc)
        raise

    media_file.transcode_status = MediaFile.TRANSCODE_STATUS_READY
    media_file.transcoded_path = str(target_path)
    media_file.transcoded_mime_type = _normalize_mime(target_path)
    media_file.transcoded_at = timezone.now()
    media_file.transcode_error = ""
    media_file.requires_transcode = True
    media_file.save(
        update_fields=[
            "transcode_status",
            "transcoded_path",
            "transcoded_mime_type",
            "transcoded_at",
            "transcode_error",
            "requires_transcode",
            "updated_at",
        ]
    )

    logger.info("Finished transcoding media file %s", media_file.id)
    return target_path


class LiveTranscodeSession:
    """Manage a live ffmpeg transcoding process and stream the output while writing to disk."""

    mime_type = "video/mp4"

    def __init__(self, media_file: MediaFile, *, start_seconds: float = 0.0):
        self.media_file = media_file
        self.source_path = _as_path(media_file.absolute_path)
        if not self.source_path.exists():
            raise FileNotFoundError(f"Media source missing at {self.source_path}")

        self.target_path = _build_target_path(media_file)
        self.target_path.parent.mkdir(parents=True, exist_ok=True)

        self.start_seconds = max(0.0, float(start_seconds))
        self.cache_enabled = self.start_seconds == 0.0

        if self.cache_enabled:
            fd, temp_path = tempfile.mkstemp(dir=str(self.target_path.parent), suffix=".mp4")
            os.close(fd)
            self.temp_path = Path(temp_path)
        else:
            self.temp_path = None

        self.process: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: deque[str] = deque(maxlen=200)
        self._aborted = False
        self._finalized = False

        # Prepare media file state
        media_file.requires_transcode = True
        media_file.transcode_status = MediaFile.TRANSCODE_STATUS_PROCESSING
        media_file.transcode_error = ""
        update_fields = [
            "requires_transcode",
            "transcode_status",
            "transcode_error",
            "updated_at",
        ]

        if self.cache_enabled:
            media_file.transcoded_path = ""
            media_file.transcoded_mime_type = ""
            media_file.transcoded_at = None
            update_fields.extend(
                [
                    "transcoded_path",
                    "transcoded_mime_type",
                    "transcoded_at",
                ]
            )

        media_file.save(update_fields=update_fields)

    def start(self) -> "LiveTranscodeSession":
        command = _build_ffmpeg_command(
            self.source_path,
            output="pipe:1",
            fragmented=True,
            start_seconds=self.start_seconds,
        )

        logger.info(
            "Starting live transcode for media file %s (%s) [start=%.3fs]",
            self.media_file.id,
            self.source_path,
            self.start_seconds,
        )

        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=CHUNK_SIZE,
        )

        if self.process.stdout is None or self.process.stderr is None:
            raise RuntimeError("Failed to capture ffmpeg output streams")

        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name=f"ffmpeg-stderr-{self.media_file.id}", daemon=True
        )
        self._stderr_thread.start()
        return self

    def stream(self) -> Iterable[bytes]:
        if not self.process or not self.process.stdout:
            raise RuntimeError("Live transcode session is not started")

        try:
            cache_ctx = (
                open(self.temp_path, "wb")
                if self.cache_enabled and self.temp_path
                else contextlib.nullcontext()
            )
            with cache_ctx as cache_fp:
                while True:
                    chunk = self.process.stdout.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    if cache_fp:
                        cache_fp.write(chunk)
                        cache_fp.flush()
                    yield chunk
        except GeneratorExit:
            self._aborted = True
            logger.debug("Live transcode aborted by client for media file %s", self.media_file.id)
            self._terminate_process()
            raise
        except Exception as exc:  # noqa: BLE001
            self._aborted = True
            logger.warning(
                "Live transcode streaming error for media file %s: %s",
                self.media_file.id,
                exc,
            )
            self._terminate_process()
            raise
        finally:
            self._finalize()

    def _terminate_process(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception:  # noqa: BLE001
                self.process.kill()

    def _drain_stderr(self):
        assert self.process and self.process.stderr
        for line in iter(self.process.stderr.readline, b""):
            text = line.decode("utf-8", errors="ignore").strip()
            if text:
                self._stderr_lines.append(text)
                logger.debug("ffmpeg[%s]: %s", self.media_file.id, text)

    def _stderr_tail(self) -> str:
        return "\n".join(self._stderr_lines)

    def _finalize(self):
        if self._finalized:
            return
        self._finalized = True

        return_code = None
        if self.process:
            try:
                return_code = self.process.poll()
                if return_code is None:
                    return_code = self.process.wait()
            except Exception:  # noqa: BLE001
                return_code = -1

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2)

        if (
            return_code == 0
            and not self._aborted
            and self.cache_enabled
            and self.temp_path
            and os.path.exists(self.temp_path)
        ):
            try:
                shutil.move(self.temp_path, self.target_path)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to finalize live transcode output for media file %s: %s",
                    self.media_file.id,
                    exc,
                )
                return_code = -1

        if return_code == 0 and not self._aborted:
            if not self.cache_enabled:
                self.media_file.transcode_status = MediaFile.TRANSCODE_STATUS_PENDING
                self.media_file.save(update_fields=["transcode_status", "updated_at"])
                return
            logger.info("Finished live transcode for media file %s", self.media_file.id)
            self.media_file.transcode_status = MediaFile.TRANSCODE_STATUS_READY
            self.media_file.transcoded_path = str(self.target_path)
            self.media_file.transcoded_mime_type = self.mime_type
            self.media_file.transcoded_at = timezone.now()
            self.media_file.transcode_error = ""
            self.media_file.requires_transcode = True
            self.media_file.save(
                update_fields=[
                    "transcode_status",
                    "transcoded_path",
                    "transcoded_mime_type",
                    "transcoded_at",
                    "transcode_error",
                    "requires_transcode",
                    "updated_at",
                ]
            )
        else:
            if self.temp_path and os.path.exists(self.temp_path):
                try:
                    os.remove(self.temp_path)
                except OSError:
                    pass

            if self._aborted:
                # Mark as pending so a future request can retry.
                self.media_file.transcode_status = MediaFile.TRANSCODE_STATUS_PENDING
                self.media_file.save(update_fields=["transcode_status", "updated_at"])
            else:
                msg = self._stderr_tail() or "Unknown ffmpeg failure"
                self.media_file.transcode_status = MediaFile.TRANSCODE_STATUS_FAILED
                self.media_file.transcode_error = msg[-4000:]
                self.media_file.save(
                    update_fields=["transcode_status", "transcode_error", "updated_at"]
                )
                logger.error(
                    "Live transcode failed for media file %s: %s",
                    self.media_file.id,
                    self.media_file.transcode_error,
                )


def start_streaming_transcode(
    media_file: MediaFile, *, start_seconds: float = 0.0
) -> LiveTranscodeSession:
    """Start a live transcoding session for the given media file."""
    session = LiveTranscodeSession(media_file, start_seconds=start_seconds)
    return session.start()
