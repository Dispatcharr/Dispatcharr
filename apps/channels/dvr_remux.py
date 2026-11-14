"""DVR HLS finalize: playlist remux and mid-recording audio repair.

Used by ``run_recording`` and startup recovery after capture writes
``index.m3u8``. The Celery tasks stay in ``apps.channels.tasks``; this module
owns the remux helpers so they can grow without enlarging the task file.

A recording can change audio part way through: an FFmpeg restart, a proxy
stream switch, or a source that drops or adds tracks. FFmpeg writes the
program map once, so after a switch the segments keep the first source's
labels over the new source's bytes (see ``dvr_ts``). Finalize reads what the
segments really carry, splits the recording where that changes, and rebuilds
each section onto the first source's audio tracks: matching audio is copied,
other audio is re-encoded to the original codec and layout, and a track a
section lacks is filled with silence so the file stays usable.
"""
import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass

from apps.channels.dvr_ts import (
    audio_entries,
    build_pmt_payload,
    iter_relabeled,
    label_matches,
    relabeled_entry,
    scan_segment,
    video_entries,
)

logger = logging.getLogger(__name__)

# Shared ceiling for HLS finalize
HLS_REMUX_TIMEOUT_SECONDS = 30 * 60


class RemuxResult(tuple):
    """``(success, via_mp4)`` with ``repaired`` for the section-rebuild path.

    Two-item unpacking stays valid. ``repaired`` is true only when the MKV was
    rebuilt per section. A plain copy and the MP4 fallback leave it false.
    """

    def __new__(cls, success, via_mp4=False, repaired=False):
        result = super().__new__(cls, (bool(success), bool(via_mp4)))
        result.repaired = bool(success) and bool(repaired) and not via_mp4
        return result


def _build_hls_playlist_remux_cmd(m3u8_path, output_path):
    """Build an FFmpeg remux command that reads an HLS playlist as a single input."""
    return [
        "ffmpeg", "-y",
        "-fflags", "+genpts+discardcorrupt",
        "-err_detect", "ignore_err",
        "-i", m3u8_path,
        "-map", "0:v?",
        "-map", "0:a?",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]


def _ensure_hls_endlist(m3u8_path):
    """Append ``#EXT-X-ENDLIST`` if missing so ffmpeg treats the playlist as VOD.

    Capture uses ``omit_endlist`` so clients can watch live. A clean SIGINT
    usually writes the tag; a crash or kill often does not. Without it the
    HLS demuxer waits for new segments and remux never finishes.
    """
    try:
        with open(m3u8_path) as _f:
            text = _f.read()
        if "#EXT-X-ENDLIST" in text:
            return True
        if text and not text.endswith("\n"):
            text += "\n"
        text += "#EXT-X-ENDLIST\n"
        _tmp = f"{m3u8_path}.endlist.tmp"
        with open(_tmp, "w") as _f:
            _f.write(text)
        os.replace(_tmp, m3u8_path)
        return True
    except Exception as _ee:
        logger.warning(f"DVR: failed to ensure EXT-X-ENDLIST on {m3u8_path}: {_ee}")
        try:
            os.remove(f"{m3u8_path}.endlist.tmp")
        except OSError:
            pass
        return False


def _remove_empty_or_partial_output(path):
    """Remove a remux output file if present so a later attempt can rewrite it."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _output_nonempty(path):
    """True when ``path`` exists and has at least one byte."""
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


# FFmpeg always prints this preamble; it is never the reason a run failed.
_FFMPEG_BANNER_PREFIXES = (
    "ffmpeg version",
    "built with",
    "configuration:",
    "libavutil",
    "libavcodec",
    "libavformat",
    "libavdevice",
    "libavfilter",
    "libswscale",
    "libswresample",
)

# One region's ffprobe is capped so a hung probe cannot spend the whole remux budget.
_PROBE_TIMEOUT_SECONDS = 30

# Stable audio encoders in this FFmpeg build, codec name -> encoder name.
# None until a listing succeeds (a failed listing is retried, never cached).
# Experimental encoders are left out.
_audio_encoder_cache = None

# Probed codec names that are re-encoded under a different codec id. LATM AAC
# (common on DVB sources) comes back as plain AAC, so a region in that codec
# can never be copied next to re-encoded regions.
_AUDIO_CODEC_ALIASES = {"aac_latm": "aac"}

# name -> channel count, from ``ffmpeg -layouts``. None until a listing succeeds.
_layout_channel_counts_cache = None
# codec -> declared max channels. None means the encoder help lists no layouts.
_encoder_channel_limit_cache = {}

# Bitrates (kbps) the MP2 encoder accepts. Other values fail to open the encoder.
_MP2_BITRATES_MPEG1 = (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384)
_MP2_BITRATES_MPEG2 = (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)


def _ffmpeg_error_tail(stderr, max_chars=1500):
    """Return the meaningful end of FFmpeg stderr for a log line.

    FFmpeg writes its version banner first and the actual errors last, so
    slicing from the front (``stderr[:300]``) logged nothing but the banner.
    Drop the banner lines and keep the tail, where the failure is explained.
    """
    if not stderr:
        return "<no stderr>"
    lines = [line.rstrip() for line in stderr.splitlines() if line.strip()]
    body = [
        line for line in lines
        if not line.strip().startswith(_FFMPEG_BANNER_PREFIXES)
    ]
    text = "\n".join(body or lines)
    return text[-max_chars:]


def _ffmpeg_failed_adts(result):
    """Recognize an AAC bitstream-filter failure in this attempt's stderr."""
    if result is None or result.returncode == 0:
        return False
    return any(
        "[aac_adtstoasc @" in line and "Error parsing ADTS frame header" in line
        for line in (result.stderr or "").splitlines()
    )


def _run_ffmpeg_with_budget(cmd, log_label, step_label, deadline):
    """Run ffmpeg under a shared remux deadline. Returns a CompletedProcess or None."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        logger.error(
            f"{log_label}: {step_label} skipped, remux budget exhausted "
            f"({HLS_REMUX_TIMEOUT_SECONDS}s)"
        )
        return None
    try:
        # errors="replace": ffmpeg echoes stream metadata (service names, titles)
        # to stderr, and a stray non-UTF-8 byte must not abort a finished remux.
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=remaining,
        )
    except subprocess.TimeoutExpired:
        logger.error(
            f"{log_label}: {step_label} timed out "
            f"(step budget {remaining:.0f}s, remux ceiling "
            f"{HLS_REMUX_TIMEOUT_SECONDS}s)"
        )
        return None


def _run_ffmpeg_fed_with_budget(
    cmd, chunks, log_label, step_label, deadline, side_feeds=(),
):
    """Run ffmpeg reading MPEG-TS from stdin under the shared remux deadline.

    ``chunks`` yields the bytes and is closed before returning. ``side_feeds``
    are further inputs, each ``(read_fd, write_fd, chunks)``: the child
    inherits ``read_fd`` (the command names it as ``pipe:<read_fd>``) and the
    bytes are written to ``write_fd``. Returns a CompletedProcess, or ``None``
    when the budget ran out, the run timed out, or an input could not be read.
    An ffmpeg that stops reading early but reports success is returned as a
    failure, because its output is cut short.
    """
    def release():
        chunks.close()
        for read_fd, write_fd, side_chunks in side_feeds:
            for fd in (read_fd, write_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass
            side_chunks.close()

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        release()
        logger.error(
            f"{log_label}: {step_label} skipped, remux budget exhausted "
            f"({HLS_REMUX_TIMEOUT_SECONDS}s)"
        )
        return None
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            pass_fds=[read_fd for read_fd, _write_fd, _chunks in side_feeds],
        )
    except OSError as exc:
        release()
        logger.error(f"{log_label}: {step_label} could not start ffmpeg: {exc}")
        return None
    for read_fd, _write_fd, _chunks in side_feeds:
        os.close(read_fd)  # the child holds its own copy

    state = {"read_error": None, "stopped_early": False}
    stderr_parts = []

    def feed(sink, source):
        try:
            for chunk in source:
                sink.write(chunk)
        except BrokenPipeError:
            state["stopped_early"] = True
        except OSError as exc:
            state["read_error"] = exc
        finally:
            try:
                sink.close()
            except OSError:
                state["stopped_early"] = True

    feeders = [threading.Thread(target=feed, args=(proc.stdin, chunks), daemon=True)]
    for _read_fd, write_fd, side_chunks in side_feeds:
        feeders.append(threading.Thread(
            target=feed, args=(os.fdopen(write_fd, "wb"), side_chunks), daemon=True,
        ))
    reader = threading.Thread(
        target=lambda: stderr_parts.append(proc.stderr.read()), daemon=True,
    )
    for feeder in feeders:
        feeder.start()
    reader.start()
    timed_out = False
    try:
        proc.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()
    for feeder in feeders:
        feeder.join(10)
    reader.join(10)
    for source in [chunks] + [side_chunks for _r, _w, side_chunks in side_feeds]:
        try:
            source.close()
        except ValueError:
            pass  # a feeder is still inside the generator; the process is gone

    if timed_out:
        logger.error(
            f"{log_label}: {step_label} timed out "
            f"(step budget {remaining:.0f}s, remux ceiling "
            f"{HLS_REMUX_TIMEOUT_SECONDS}s)"
        )
        return None
    if state["read_error"] is not None:
        logger.error(
            f"{log_label}: {step_label} could not read its segments: "
            f"{state['read_error']}"
        )
        return None
    stderr = b"".join(stderr_parts).decode("utf-8", "replace")
    returncode = proc.returncode
    if state["stopped_early"] and returncode == 0:
        returncode = 1
        stderr += "\nffmpeg stopped reading its input before the end"
    return subprocess.CompletedProcess(cmd, returncode, b"", stderr)


def _line_is_discontinuity(line):
    """True for ``#EXT-X-DISCONTINUITY``, not ``#EXT-X-DISCONTINUITY-SEQUENCE``."""
    tag = line.strip()
    return tag == "#EXT-X-DISCONTINUITY" or tag.startswith("#EXT-X-DISCONTINUITY:")


def _split_hls_regions(m3u8_path):
    """Split an HLS playlist where FFmpeg restarted.

    Capture writes a discontinuity tag before the first segment of every
    playlist and one more at each FFmpeg restart. The leading tag does not
    start a region. ``#EXT-X-DISCONTINUITY-SEQUENCE`` is a header value, not a
    boundary. A proxy stream switch inside one FFmpeg process leaves no tag;
    those changes are found from the segments themselves
    (``_plan_sections``).

    Returns ``(header_lines, regions)`` where each region is a list of
    ``(extinf_line, uri_line)`` pairs, or ``None`` on read error.
    """
    try:
        with open(m3u8_path) as f:
            lines = f.read().splitlines()
    except OSError:
        return None

    header = []
    regions = []
    current = []
    for i, line in enumerate(lines):
        if _line_is_discontinuity(line):
            if current:
                regions.append(current)
                current = []
            continue
        if line.startswith("#EXTINF"):
            uri = lines[i + 1] if i + 1 < len(lines) else ""
            if uri and not uri.startswith("#"):
                current.append((line, uri))
            continue
        if line.startswith("#") and not line.startswith("#EXT-X-ENDLIST"):
            # Per-segment tags are not playlist-wide header lines.
            if not any(
                line.startswith(p) for p in (
                    "#EXT-X-BYTERANGE", "#EXT-X-KEY", "#EXT-X-MAP",
                    "#EXT-X-PROGRAM-DATE-TIME", "#EXT-X-DATERANGE", "#EXT-X-GAP",
                )
            ):
                if not regions and not current:
                    header.append(line)
    if current:
        regions.append(current)
    return header, regions


def _as_int(value):
    """``int(value)``, or 0 when ffprobe reports nothing usable (``N/A``, None)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extinf_seconds(extinf):
    """Duration in seconds from an ``#EXTINF:<seconds>,`` line."""
    try:
        return float(extinf.split(":", 1)[1].split(",", 1)[0])
    except (IndexError, ValueError):
        return 0.0


@dataclass
class _Section:
    """Consecutive segments whose audio is the same, judged by their bytes.

    ``audio`` is the PMT's audio entries; a slot is an index into it. ``head``
    and ``shapes`` are what each slot's frames really are at the start and at
    the end of the section (``None`` where the slot has no frames). They differ
    only for a ``mixed`` section, a single segment in which the source changed.
    ``skewed`` holds the slots whose clock cannot be trusted.
    """

    region: int
    segments: list
    pmt: object
    audio: tuple
    head: tuple
    shapes: tuple
    mixed: bool = False
    skewed: frozenset = frozenset()

    def present(self, slot):
        return slot < len(self.shapes) and self.shapes[slot] is not None

    def duration(self):
        return sum(_extinf_seconds(extinf) for extinf, _uri in self.segments)

    def paths(self, hls_dir):
        return [
            uri if os.path.isabs(uri) else os.path.join(hls_dir, uri)
            for _extinf, uri in self.segments
        ]


def _plan_sections(hls_dir, regions, log_label):
    """Split the regions into sections by what each segment's audio really is.

    Each segment is read at both ends. A segment whose ends differ held a
    source change and becomes its own section; otherwise neighbours with the
    same program map and audio join one section. Boundaries do not depend on
    when a switch happened, only on what the capture wrote.

    Returns the sections in order, or ``None`` when a segment cannot be read.
    """
    sections = []
    for region_index, region in enumerate(regions):
        current = None
        current_key = None
        for extinf, uri in region:
            path = uri if os.path.isabs(uri) else os.path.join(hls_dir, uri)
            scan = scan_segment(path)
            if scan is None:
                logger.warning(f"{log_label}: could not inspect segment {uri}")
                return None
            audio = audio_entries(scan.pmt)
            head = tuple(scan.head.get(entry.pid) for entry in audio)
            tail = tuple(scan.tail.get(entry.pid) for entry in audio)
            skewed = frozenset(
                slot for slot, entry in enumerate(audio) if entry.pid in scan.skewed
            )
            if head != tail:
                sections.append(_Section(
                    region_index, [(extinf, uri)], scan.pmt, audio, head, tail,
                    mixed=True, skewed=skewed,
                ))
                current = None
                continue
            key = (scan.pmt.entries, tail, skewed)
            if current is not None and key == current_key:
                current.segments.append((extinf, uri))
            else:
                current = _Section(
                    region_index, [(extinf, uri)], scan.pmt, audio, tail, tail,
                    skewed=skewed,
                )
                current_key = key
                sections.append(current)
    return sections


def _plan_needs_repair(sections):
    """True when the audio the segments carry cannot be copied as labeled.

    That is a track whose label disagrees with its frames, whose frames change
    codec, layout, or rate, whose clock cannot be trusted, or one the first
    section does not list (a copy only carries the first section's tracks). A
    track that merely has no frames for a while copies fine, as a gap.
    """
    first = {}
    listed = len(sections[0].audio) if sections else 0
    for section in sections:
        if section.skewed:
            return True
        for shapes in (section.head, section.shapes):
            for slot, shape in enumerate(shapes):
                if shape is None:
                    continue
                if slot >= listed:
                    return True
                if not label_matches(section.audio[slot], shape):
                    return True
                if first.setdefault(slot, shape) != shape:
                    return True
    return False


def _section_entries(section, slots=None):
    """PMT entries FFmpeg should see for ``section``, and the slots they carry.

    Video passes through, unless ``slots`` is given: then only those slots are
    listed (a section's skewed tracks go in an input of their own). Each audio
    slot with frames is listed under its true codec; a slot without frames is
    left out.
    """
    carried = [
        slot for slot in range(len(section.audio))
        if section.present(slot) and (slots is None or slot in slots)
    ]
    entries = [] if slots is not None else list(video_entries(section.pmt))
    entries.extend(
        relabeled_entry(section.audio[slot], section.shapes[slot]) for slot in carried
    )
    return entries, carried


# Bytes of a section read to learn its audio shape. ffprobe analyzes about 5 MB.
_PROBE_BYTES = 8 * 1024 * 1024


def _probe_ts_bytes(data, timeout):
    """ffprobe MPEG-TS bytes: ``{"video": codec_or_None, "audio": [dicts]}`` or ``None``.

    Each audio dict has ``codec``, ``channels``, ``sample_rate``, and
    ``bitrate``.
    """
    if timeout <= 0:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-f", "mpegts",
                "-show_entries",
                "stream=codec_type,codec_name,channels,sample_rate,bit_rate",
                "-of", "json", "-i", "pipe:0",
            ],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(f"DVR: ffprobe failed: {exc}")
        return None
    if result.returncode != 0:
        logger.warning(
            f"DVR: ffprobe failed (rc={result.returncode}): "
            f"{_ffmpeg_error_tail(result.stderr.decode('utf-8', 'replace'))}"
        )
        return None
    try:
        info = json.loads(result.stdout or b"{}")
    except ValueError:
        logger.warning("DVR: ffprobe returned invalid JSON")
        return None

    video = None
    audio = []
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video" and video is None:
            video = stream.get("codec_name")
        elif stream.get("codec_type") == "audio":
            audio.append({
                "codec": stream.get("codec_name"),
                "channels": _as_int(stream.get("channels")),
                "sample_rate": _as_int(stream.get("sample_rate")),
                "bitrate": _as_int(stream.get("bit_rate")),
            })
    return {"video": video, "audio": audio}


def _probe_section(hls_dir, section, timeout=_PROBE_TIMEOUT_SECONDS):
    """ffprobe a section's first segment as FFmpeg will read it, labels corrected.

    Returns ``{"video": codec, "audio": {slot: dict}}`` or ``None``.
    """
    entries, slots = _section_entries(section)
    try:
        payload = build_pmt_payload(section.pmt, entries)
    except ValueError as exc:
        logger.warning(f"DVR: could not rewrite the program map for probe: {exc}")
        return None
    data = bytearray()
    chunks = iter_relabeled(section.paths(hls_dir)[:1], section.pmt.pmt_pid, payload)
    try:
        for chunk in chunks:
            data += chunk
            if len(data) >= _PROBE_BYTES:
                break
    except OSError as exc:
        logger.warning(f"DVR: could not read segment for probe: {exc}")
        return None
    finally:
        chunks.close()
    probed = _probe_ts_bytes(bytes(data), timeout)
    if probed is None or len(probed["audio"]) != len(slots):
        return None
    return {"video": probed["video"], "audio": dict(zip(slots, probed["audio"]))}


def _audio_encoders():
    """Map codec names to a stable encoder this FFmpeg build can use.

    A failed listing returns an empty map for this call only, so one slow or
    failed ``ffmpeg -encoders`` cannot disable repair until the next restart.
    """
    global _audio_encoder_cache
    if _audio_encoder_cache is not None:
        return _audio_encoder_cache
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        logger.warning(f"DVR: could not list ffmpeg audio encoders: {exc}")
        return {}
    if result.returncode != 0:
        logger.warning("DVR: ffmpeg -encoders failed while checking audio repair codecs")
        return {}

    encoders = {}
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        flags, name = parts[0], parts[1]
        # flags[3] is the experimental marker. Skip anull and the legend row.
        if len(flags) < 6 or flags[0] != "A" or flags[3] == "X":
            continue
        if name == "anull" or name.startswith("="):
            continue
        match = re.search(r"\(codec ([^)]+)\)\s*$", line)
        codec = match.group(1).strip() if match else name
        # Prefer the encoder whose name is the codec (aac, not libfdk_aac).
        if codec not in encoders or name == codec:
            encoders[codec] = name
    _audio_encoder_cache = encoders
    return encoders


def _audio_encoder_for(codec):
    """Return the encoder name for ``codec``, or ``None`` when this build lacks one."""
    if not codec:
        return None
    return _audio_encoders().get(_AUDIO_CODEC_ALIASES.get(codec, codec))


def _layout_channel_counts():
    """Map standard layout names to channel counts from ``ffmpeg -layouts``."""
    global _layout_channel_counts_cache
    if _layout_channel_counts_cache is not None:
        return _layout_channel_counts_cache
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-layouts"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        logger.warning(f"DVR: could not list ffmpeg channel layouts: {exc}")
        return {}
    if result.returncode != 0:
        logger.warning("DVR: ffmpeg -layouts failed while checking encoder channel limits")
        return {}

    counts = {}
    in_standard = False
    for line in (result.stdout or "").splitlines():
        if line.startswith("Standard channel layouts"):
            in_standard = True
            continue
        if not in_standard or not line.strip() or line.startswith("NAME"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        name, decomposition = parts
        channels = [part for part in decomposition.split("+") if part]
        if channels:
            counts[name] = len(channels)
    _layout_channel_counts_cache = counts
    return counts


def _max_channels_in_layout_help(line, layout_counts):
    """Widest channel count named on one ``Supported channel layouts`` line.

    Layout names come from ``ffmpeg -layouts``. A few entries are unnamed and
    look like ``2 channels (FC+LFE)``; those use the leading number.
    """
    found = [int(match) for match in re.findall(r"(\d+) channels \([^)]*\)", line)]
    remainder = re.sub(r"\d+ channels \([^)]*\)", " ", line)
    if "Supported channel layouts:" in remainder:
        remainder = remainder.split("Supported channel layouts:", 1)[1]
    for token in remainder.split():
        count = layout_counts.get(token)
        if count:
            found.append(count)
    return max(found) if found else None


def _encoder_channel_limit(codec):
    """Max channels this build's encoder declares, or ``None`` if it declares none.

    ``ffmpeg -h encoder=<name>`` prints ``Supported channel layouts`` only when
    the encoder has a fixed set. No line means no declared cap, not that every
    channel count will encode.
    """
    if not codec:
        return None
    if codec in _encoder_channel_limit_cache:
        return _encoder_channel_limit_cache[codec]
    encoder = _audio_encoder_for(codec)
    if not encoder:
        return None
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-h", f"encoder={encoder}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        logger.warning(f"DVR: could not read encoder help for {encoder}: {exc}")
        return None
    if result.returncode != 0:
        logger.warning(f"DVR: ffmpeg -h encoder={encoder} failed while checking channel layouts")
        return None

    line = ""
    for row in (result.stdout or "").splitlines():
        if "Supported channel layouts:" in row:
            line = row
            break
    if not line:
        _encoder_channel_limit_cache[codec] = None
        return None
    layout_counts = _layout_channel_counts()
    if not layout_counts:
        return None
    limit = _max_channels_in_layout_help(line, layout_counts)
    if limit is None:
        logger.warning(f"DVR: could not parse channel layouts for encoder {encoder}")
        return None
    _encoder_channel_limit_cache[codec] = limit
    return limit


def _codec_for_layout(codec, channels):
    """Pick an encode codec that can carry ``channels`` channels.

    Returns the codec name, or ``None`` when every encoder that declares a
    channel list refuses this count. A wider track is encoded as AAC instead
    of folded down. AAC itself usually declares no list, so it is the fallback.
    """
    if not codec:
        return None
    encode_codec = _AUDIO_CODEC_ALIASES.get(codec, codec)
    limit = _encoder_channel_limit(encode_codec)
    if limit is None or channels <= 0 or channels <= limit:
        return encode_codec
    if encode_codec != "aac":
        aac_limit = _encoder_channel_limit("aac")
        if aac_limit is None or channels <= aac_limit:
            return "aac"
    return None


def _audio_bitrate_arg(stream):
    """Pick ``-b:a`` from a probed stream, with a layout-aware fallback.

    MP2 only opens with a standard bitrate, so its value is snapped to the
    nearest one the encoder accepts. AC-3 does that rounding itself.
    """
    bitrate = int(stream.get("bitrate") or 0)
    channels = int(stream.get("channels") or 0)
    if stream.get("codec") == "mp2":
        sample_rate = int(stream.get("sample_rate") or 0)
        table = (
            _MP2_BITRATES_MPEG2
            if 0 < sample_rate < 32000
            else _MP2_BITRATES_MPEG1
        )
        target = bitrate if bitrate > 0 else (320000 if channels > 2 else 192000)
        return str(min(table, key=lambda kbps: abs(kbps * 1000 - target)) * 1000)
    if bitrate > 0:
        return str(bitrate)
    return "320k" if channels > 2 else "192k"


def _slot_targets(hls_dir, sections, deadline, log_label):
    """The audio every section is rebuilt onto, or ``None`` when repair must refuse.

    A slot takes its shape from the first section that has frames for it, so
    the file keeps the original tracks. Returns ``(targets, slots)``:
    ``targets`` maps a slot to its probed ``codec``, ``channels``,
    ``sample_rate`` and ``bitrate`` plus ``source_codec`` (as probed) and
    ``sniff`` (the shape its frames show); ``codec`` is what repair encodes
    with. ``slots`` lists the slots the output has, in order.
    """
    video_layouts = {
        tuple(entry.stream_type for entry in video_entries(section.pmt))
        for section in sections
    }
    if len(video_layouts) > 1:
        logger.error(
            f"{log_label}: section repair refused, the video stream type changed"
        )
        return None

    probed = {}
    targets = {}
    for slot in range(max((len(s.audio) for s in sections), default=0)):
        carrying = [s for s in sections if s.present(slot)]
        if not carrying:
            continue
        # A mixed section holds two sources, so a clean one is the better witness.
        section = next((s for s in carrying if not s.mixed), carrying[0])
        if id(section) not in probed:
            remaining = max(deadline - time.monotonic(), 0)
            probed[id(section)] = _probe_section(
                hls_dir, section,
                timeout=min(remaining, _PROBE_TIMEOUT_SECONDS),
            )
        probe = probed[id(section)]
        if probe is None:
            logger.error(
                f"{log_label}: section repair refused, audio track {slot} "
                "could not be probed"
            )
            return None
        stream = probe["audio"][slot]
        source_codec = stream.get("codec")
        channels = int(stream.get("channels") or 0)
        encode_codec = _codec_for_layout(source_codec, channels)
        if not encode_codec or not _audio_encoder_for(encode_codec):
            logger.error(
                f"{log_label}: section repair refused, no encoder can keep "
                f"{channels} channels of {source_codec!r}"
            )
            return None
        if (
            encode_codec != source_codec
            and source_codec not in _AUDIO_CODEC_ALIASES
        ):
            logger.warning(
                f"{log_label}: {source_codec} with {channels} channels is wider "
                f"than this encoder allows; re-encoding as {encode_codec} "
                f"so the channel count is kept"
            )
        targets[slot] = {
            **stream,
            "codec": encode_codec,
            "source_codec": source_codec,
            "sniff": section.shapes[slot],
        }
    return targets, sorted(targets)


def _copyable_slots(sections, targets, slots, force_reencode):
    """Per section, the slots whose frames can be copied as they are.

    A slot is copied only when its frames already are the target, its clock can
    be trusted, and nothing needs re-encoding for its codec. Encoding rebuilds
    the timeline from the samples. An AAC track is all or nothing: its
    header comes from the first frames written, and frames re-encoded at
    another AAC profile would play at the wrong rate under it.
    """
    copyable = []
    for section in sections:
        copyable.append({
            slot for slot in slots
            if not force_reencode
            and targets[slot]["codec"] == targets[slot]["source_codec"]
            and not section.mixed
            and slot not in section.skewed
            and section.present(slot)
            and section.shapes[slot] == targets[slot]["sniff"]
        })
    for slot in slots:
        if targets[slot]["codec"] == "aac" and any(slot not in ok for ok in copyable):
            for ok in copyable:
                ok.discard(slot)
    return copyable


def _build_section_remux_cmd(
    output_path, kept, slots, targets, copy, seconds, side=(), side_fd=None,
):
    """Remux command for one section, rebuilt onto the output's audio ``slots``.

    Input 0 is the section's relabeled MPEG-TS on stdin, carrying the audio
    slots in ``kept``. The slots in ``side`` have a clock that cannot be
    trusted, so they come in as input 1, from the pipe ``side_fd``: FFmpeg
    corrects a clock jump for a whole input, and kept apart they cannot drag
    the video along. A slot in neither is filled with ``seconds`` of generated
    silence. Slots in ``copy`` keep their frames; the rest are encoded to the
    slot's target codec, layout, rate, and bitrate, and cut at ``seconds``. An
    encoded slot follows its input timestamps (filling gaps), except a ``side``
    slot, whose timeline comes from its sample count.
    """
    rank = {slot: position for position, slot in enumerate(kept)}
    side_rank = {slot: position for position, slot in enumerate(side)}
    silent = [slot for slot in slots if slot not in rank and slot not in side_rank]
    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts+discardcorrupt",
        "-err_detect", "ignore_err",
        "-f", "mpegts", "-i", "pipe:0",
    ]
    next_input = 1
    side_input = None
    if side:
        cmd.extend(["-f", "mpegts", "-i", f"pipe:{side_fd}"])
        side_input = next_input
        next_input += 1
    silent_input = {}
    for slot in silent:
        rate = int(targets[slot].get("sample_rate") or 0) or 48000
        cmd.extend([
            "-f", "lavfi", "-t", f"{seconds:.3f}",
            "-i", f"anullsrc=r={rate}:cl=stereo",
        ])
        silent_input[slot] = next_input
        next_input += 1
    cmd.extend(["-map", "0:v?"])
    for slot in slots:
        if slot in rank:
            cmd.extend(["-map", f"0:a:{rank[slot]}"])
        elif slot in side_rank:
            cmd.extend(["-map", f"{side_input}:a:{side_rank[slot]}"])
        else:
            cmd.extend(["-map", f"{silent_input[slot]}:a:0"])
    cmd.extend(["-c:v", "copy"])
    encoding = False
    for out_index, slot in enumerate(slots):
        if slot in copy:
            cmd.extend([f"-c:a:{out_index}", "copy"])
            continue
        encoding = True
        target = targets[slot]
        codec = target.get("codec") or "aac"
        cmd.extend([f"-c:a:{out_index}", _audio_encoder_for(codec) or codec])
        channels = int(target.get("channels") or 0)
        if channels > 0:
            cmd.extend([f"-ac:a:{out_index}", str(channels)])
        sample_rate = int(target.get("sample_rate") or 0)
        if sample_rate > 0:
            cmd.extend([f"-ar:a:{out_index}", str(sample_rate)])
        cmd.extend([f"-b:a:{out_index}", _audio_bitrate_arg(target)])
        # Never longer than the section's video: a capture flushed at its end,
        # for one, holds more audio than video in its last segment.
        trim = f"atrim=end={seconds:.3f}"
        if slot in side_rank:
            cmd.extend([f"-filter:a:{out_index}", f"asetpts=N/SR/TB,{trim}"])
        elif slot in rank:
            cmd.extend([
                f"-filter:a:{out_index}", f"aresample=async=1:first_pts=0,{trim}",
            ])
    if encoding:
        cmd.extend(["-abort_on", "empty_output+empty_output_stream"])
    cmd.extend(["-avoid_negative_ts", "make_zero", output_path])
    return cmd


def _remux_section(
    hls_dir, section, dest, slots, targets, copy, log_label, step_label, deadline,
):
    """Run one section through ffmpeg with its program map rewritten to the truth.

    The section's skewed tracks are fed to ffmpeg as a second input.
    """
    paths = section.paths(hls_dir)
    main_entries, kept = _section_entries(
        section, [s for s in range(len(section.audio)) if s not in section.skewed],
    )
    main_entries = list(video_entries(section.pmt)) + main_entries
    side_entries, side = _section_entries(section, section.skewed)
    try:
        main_payload = build_pmt_payload(section.pmt, main_entries)
        side_payload = build_pmt_payload(section.pmt, side_entries) if side_entries else None
    except ValueError as exc:
        logger.error(f"{log_label}: section repair refused, {exc}")
        return None
    chunks = iter_relabeled(
        paths, section.pmt.pmt_pid, main_payload,
    )
    if not side:
        cmd = _build_section_remux_cmd(
            dest, kept, slots, targets, copy, section.duration(),
        )
        return _run_ffmpeg_fed_with_budget(cmd, chunks, log_label, step_label, deadline)

    read_fd, write_fd = os.pipe()
    try:
        cmd = _build_section_remux_cmd(
            dest, kept, slots, targets, copy, section.duration(),
            side=side, side_fd=read_fd,
        )
        side_chunks = iter_relabeled(
            paths, section.pmt.pmt_pid, side_payload,
        )
    except BaseException:
        os.close(read_fd)
        os.close(write_fd)
        chunks.close()
        raise
    return _run_ffmpeg_fed_with_budget(
        cmd, chunks, log_label, step_label, deadline,
        side_feeds=[(read_fd, write_fd, side_chunks)],
    )


def _section_repair(
    m3u8_path, output_path, log_label, recording_id, deadline,
    sections, force_reencode,
):
    """Rebuild each section onto the first source's audio tracks, then join them.

    Returns True on success. ``force_reencode`` encodes all audio, for a copy
    that failed on a bad AAC frame at an unknown place. Temp files are always
    removed.
    """
    hls_dir = os.path.dirname(m3u8_path)
    plan = _slot_targets(hls_dir, sections, deadline, log_label)
    if plan is None:
        return False
    targets, slots = plan
    copyable = _copyable_slots(sections, targets, slots, force_reencode)
    logger.info(
        f"{log_label}: rebuilding {len(sections)} sections onto "
        f"{len(slots)} audio track(s)"
    )

    temp_paths = []
    section_outputs = []
    try:
        for index, section in enumerate(sections):
            if len(sections) == 1:
                dest = output_path
            else:
                dest = os.path.join(
                    hls_dir, f".dvr_{recording_id}_section_{index}.mkv"
                )
                temp_paths.append(dest)
                section_outputs.append(dest)

            copy = copyable[index]
            silent = [slot for slot in slots if not section.present(slot)]
            logger.debug(
                f"{log_label}: section {index}: {len(section.segments)} segment(s), "
                f"copy {sorted(copy)}, "
                f"encode {sorted(set(slots) - copy - set(silent))}, "
                f"silent {silent}"
            )
            attempts = [copy] + ([set()] if copy else [])
            for attempt, attempt_copy in enumerate(attempts):
                result = _remux_section(
                    hls_dir, section, dest, slots, targets, attempt_copy,
                    log_label,
                    f"section {index} remux "
                    f"({'copy' if attempt_copy else 're-encode'})",
                    deadline,
                )
                if (
                    result is not None
                    and result.returncode == 0
                    and _output_nonempty(dest)
                ):
                    break
                _remove_empty_or_partial_output(dest)
                if (
                    attempt == 0
                    and attempt_copy
                    and _ffmpeg_failed_adts(result)
                ):
                    logger.warning(
                        f"{log_label}: section {index} copy hit ADTS error; "
                        "retrying with audio re-encoded"
                    )
                    continue
                # Without a result, the step already logged why nothing ran (a
                # program map that cannot be rewritten, an unreadable segment,
                # or the budget).
                outcome = (
                    "did not finish" if result is None
                    else f"failed (rc={result.returncode}). "
                         f"stderr: {_ffmpeg_error_tail(result.stderr)}"
                )
                logger.error(f"{log_label}: section {index} remux {outcome}")
                return False

        if len(sections) == 1:
            return True

        concat_list = os.path.join(hls_dir, f".dvr_{recording_id}_sections.txt")
        temp_paths.append(concat_list)
        with open(concat_list, "w") as f:
            for path in section_outputs:
                # Absolute paths; quoting is safe for spaces.
                escaped = path.replace("'", r"'\''")
                f.write(f"file '{escaped}'\n")

        # Without an explicit map ffmpeg keeps one audio stream and drops
        # the rest, which would turn a multi-audio recording into stereo.
        concat_result = _run_ffmpeg_with_budget(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-map", "0:v?",
                "-map", "0:a?",
                "-c", "copy",
                output_path,
            ],
            log_label,
            "section concat",
            deadline,
        )
        if (
            concat_result is not None
            and concat_result.returncode == 0
            and _output_nonempty(output_path)
        ):
            return True

        _rc = getattr(concat_result, "returncode", "timeout")
        _stderr = _ffmpeg_error_tail(getattr(concat_result, "stderr", None))
        logger.error(
            f"{log_label}: section concat failed (rc={_rc}). stderr: {_stderr}"
        )
        _remove_empty_or_partial_output(output_path)
        return False
    except OSError as exc:
        logger.error(f"{log_label}: section repair failed on a filesystem error: {exc}")
        _remove_empty_or_partial_output(output_path)
        return False
    finally:
        for path in temp_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def _try_mp4_intermediate(
    m3u8_path, output_path, log_label, recording_id, deadline,
):
    """Remux via an MP4 intermediate file.

    Returns ``(success, via_mp4, result)``. ``result`` is the attempt that
    failed when success is false, so the caller can recognize an ADTS error.
    """
    hls_dir = os.path.dirname(m3u8_path)
    intermediate_mp4 = os.path.join(
        hls_dir, f".dvr_{recording_id}_intermediate.mp4"
    )
    try:
        if os.path.exists(intermediate_mp4):
            os.remove(intermediate_mp4)
    except OSError:
        pass

    try:
        # No explicit ``-bsf:a aac_adtstoasc``: the MP4 muxer adds it on its
        # own for AAC streams, and forcing it makes every non-AAC source
        # (AC-3, E-AC-3, MP2) fail with EINVAL before a single packet is copied.
        mp4_result = _run_ffmpeg_with_budget(
            _build_hls_playlist_remux_cmd(m3u8_path, intermediate_mp4),
            log_label,
            "HLS\u2192MP4 remux fallback",
            deadline,
        )
        if not (
            mp4_result is not None
            and mp4_result.returncode == 0
            and _output_nonempty(intermediate_mp4)
        ):
            _rc = getattr(mp4_result, "returncode", "timeout")
            _stderr = _ffmpeg_error_tail(getattr(mp4_result, "stderr", None))
            logger.error(
                f"{log_label}: HLS\u2192MP4 remux fallback failed "
                f"(rc={_rc}). stderr: {_stderr}"
            )
            return False, False, mp4_result

        mkv_result = _run_ffmpeg_with_budget(
            [
                "ffmpeg", "-y",
                "-err_detect", "ignore_err",
                "-i", intermediate_mp4,
                "-map", "0:v?",
                "-map", "0:a?",
                "-c", "copy",
                output_path,
            ],
            log_label,
            "MP4\u2192MKV remux step",
            deadline,
        )
        if (
            mkv_result is not None
            and mkv_result.returncode == 0
            and _output_nonempty(output_path)
        ):
            return True, True, mkv_result

        _rc = getattr(mkv_result, "returncode", "timeout")
        _stderr = _ffmpeg_error_tail(getattr(mkv_result, "stderr", None))
        logger.error(
            f"{log_label}: MP4\u2192MKV remux step failed "
            f"(rc={_rc}). stderr: {_stderr}"
        )
        _remove_empty_or_partial_output(output_path)
        return False, False, mkv_result
    finally:
        try:
            if os.path.exists(intermediate_mp4):
                os.remove(intermediate_mp4)
        except OSError:
            pass


def remux_hls_to_mkv(m3u8_path, output_path, log_label, recording_id):
    """Remux ``index.m3u8`` to MKV, repairing audio that changes mid-recording.

    Happy path is a single playlist ``-c copy``. Every segment is first read
    at both ends to see what its audio really is. When a track's label
    disagrees with its frames, or its frames change codec, layout, or rate
    (an FFmpeg restart, a proxy stream switch, a source changing its own
    audio), each stretch is remuxed onto the first source's audio tracks and
    the stretches are joined: video is copied, matching audio is copied, other
    audio is re-encoded to the original codec and layout, and a track a stretch
    lacks is filled with silence. The same rebuild runs when copy fails on an
    AAC ADTS error, with all audio re-encoded.

    Segments that cannot be read leave the copy unrepaired. Repair refuses
    only when a track cannot be probed, the video stream type changed, no
    encoder can keep the channel count, or the corrected program map does not
    fit in one TS packet. A refused repair fails the remux and the caller
    keeps the HLS directory, except that a copy which failed on an AAC error
    still tries the MP4 fallback first. A track wider than the layouts its
    encoder lists is re-encoded as AAC so the channels are kept.

    Returns ``RemuxResult``: ``(success, via_mp4_fallback)``, and ``repaired``
    when the file was rebuilt per section rather than copied.
    """
    if not m3u8_path or not os.path.exists(m3u8_path):
        logger.warning(f"{log_label}: no HLS playlist to remux")
        return RemuxResult(False, False)
    if not _ensure_hls_endlist(m3u8_path):
        logger.error(
            f"{log_label}: playlist is missing EXT-X-ENDLIST and could not be updated"
        )
        return RemuxResult(False, False)

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    deadline = time.monotonic() + HLS_REMUX_TIMEOUT_SECONDS
    hls_dir = os.path.dirname(m3u8_path)

    split = _split_hls_regions(m3u8_path)
    if split is None:
        logger.error(f"{log_label}: could not read HLS playlist for remux")
        return RemuxResult(False, False)
    _header, regions = split
    if not regions:
        logger.error(f"{log_label}: HLS playlist has no segments to remux")
        return RemuxResult(False, False)

    sections = _plan_sections(hls_dir, regions, log_label)
    if sections is None:
        logger.warning(
            f"{log_label}: could not inspect every segment; copying the "
            "playlist without audio repair"
        )

    def repair(force_reencode):
        if not sections:
            return False
        repaired = _section_repair(
            m3u8_path, output_path, log_label, recording_id, deadline,
            sections, force_reencode,
        )
        if repaired:
            # Section count lives here. Callers also see RemuxResult.repaired.
            logger.info(
                f"{log_label}: section repair succeeded "
                f"({len(sections)} section(s))"
            )
        return repaired

    if sections and _plan_needs_repair(sections):
        logger.warning(
            f"{log_label}: the audio changes inside this recording (an FFmpeg "
            "restart or a stream switch); rebuilding it per section"
        )
        repaired = repair(False)
        return RemuxResult(repaired, False, repaired)

    playlist_result = _run_ffmpeg_with_budget(
        _build_hls_playlist_remux_cmd(m3u8_path, output_path),
        log_label,
        "HLS\u2192MKV playlist remux",
        deadline,
    )
    if (
        playlist_result is not None
        and playlist_result.returncode == 0
        and _output_nonempty(output_path)
    ):
        return RemuxResult(True, False)

    _rc = getattr(playlist_result, "returncode", "timeout")
    _stderr_text = getattr(playlist_result, "stderr", None) or ""
    adts_failed = _ffmpeg_failed_adts(playlist_result)
    next_step = "section repair" if adts_failed else "MP4-intermediate fallback"
    logger.warning(
        f"{log_label}: HLS\u2192MKV playlist remux failed (rc={_rc}); "
        f"attempting {next_step}. stderr: {_ffmpeg_error_tail(_stderr_text)}"
    )
    _remove_empty_or_partial_output(output_path)

    if adts_failed and repair(True):
        return RemuxResult(True, False, True)
    if adts_failed:
        # Repair could not run (segments unreadable) or failed. MP4 may still
        # succeed for some sources; for AAC ADTS it often fails the same way.
        logger.warning(
            f"{log_label}: section repair after ADTS failed; "
            "attempting MP4-intermediate fallback"
        )

    mp4_ok, via_mp4, mp4_or_mkv_result = _try_mp4_intermediate(
        m3u8_path, output_path, log_label, recording_id, deadline,
    )
    if mp4_ok:
        return RemuxResult(True, via_mp4)

    if _ffmpeg_failed_adts(mp4_or_mkv_result):
        logger.warning(
            f"{log_label}: MP4 path hit ADTS error; attempting section repair"
        )
        repaired = repair(True)
        return RemuxResult(repaired, False, repaired)

    return RemuxResult(False, False)
