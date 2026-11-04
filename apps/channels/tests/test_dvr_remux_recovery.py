"""Real-ffmpeg coverage for DVR remux ADTS and mid-restart audio repair."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.channels.dvr_remux import (
    RemuxResult,
    _Section,
    _audio_bitrate_arg,
    _audio_encoder_for,
    _build_section_remux_cmd,
    _codec_for_layout,
    _copyable_slots,
    _encoder_channel_limit,
    _ffmpeg_error_tail,
    _ffmpeg_failed_adts,
    _max_channels_in_layout_help,
    _plan_needs_repair,
    _plan_sections,
    _probe_section,
    _run_ffmpeg_fed_with_budget,
    _run_ffmpeg_with_budget,
    _section_repair,
    _slot_targets,
    _split_hls_regions,
    remux_hls_to_mkv,
)
from apps.channels.dvr_ts import PmtEntry, PmtInfo, Shape
from apps.proxy.live_proxy.input.ts_discontinuity import stamp_first_packet_per_pid


def _have_ffmpeg():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _ff(args, timeout=120, loglevel="error"):
    return subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", loglevel, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _make_part(root, start_no, dur, acodec, channels, rate=48000, bitrate=None, audio=True):
    """Encode one continuous HLS part starting at ``start_no``.

    ``acodec="aac_latm"`` encodes AAC and muxes it as LATM, as DVB sources do.
    """
    part = root / f"part{start_no}.m3u8"
    if bitrate is None:
        bitrate = "192k" if acodec == "ac3" else "128k"
    latm = acodec == "aac_latm"
    if latm:
        acodec = "aac"
    cmd = [
        "-f", "lavfi", "-i", "testsrc2=rate=25:size=64x64",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={rate}"]
    cmd += [
        "-t", str(dur),
        "-map", "0:v",
    ]
    if audio:
        cmd += [
            "-map", "1:a",
            "-c:a", acodec, "-b:a", str(bitrate),
            "-ac", str(channels), "-ar", str(rate),
        ]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
        "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
        "-hls_flags", "independent_segments",
    ]
    if latm:
        cmd += ["-hls_segment_options", "mpegts_flags=+latm"]
    cmd += [
        "-start_number", str(start_no),
        "-hls_segment_filename", str(root / "seg_%05d.ts"),
        str(part),
    ]
    result = _ff(cmd)
    if result.returncode != 0:
        raise AssertionError(f"fixture part encode failed: {result.stderr[-400:]}")
    lines = part.read_text().splitlines()
    return [
        (line, lines[i + 1])
        for i, line in enumerate(lines)
        if line.startswith("#EXTINF")
    ]


def _make_dual_audio_part(root, start_no, dur, first_channels):
    """One HLS part with two audio tracks: AAC (``first_channels``) and AC-3 stereo."""
    part = root / f"part{start_no}.m3u8"
    result = _ff([
        "-f", "lavfi", "-i", "testsrc2=rate=25:size=64x64",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
        "-t", str(dur),
        "-map", "0:v", "-map", "1:a", "-map", "2:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
        "-c:a:0", "aac", "-b:a:0", "128k", "-ac:a:0", str(first_channels),
        "-c:a:1", "ac3", "-b:a:1", "192k", "-ac:a:1", "2",
        "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
        "-hls_flags", "independent_segments",
        "-start_number", str(start_no),
        "-hls_segment_filename", str(root / "seg_%05d.ts"),
        str(part),
    ])
    if result.returncode != 0:
        raise AssertionError(f"dual-audio part encode failed: {result.stderr[-400:]}")
    lines = part.read_text().splitlines()
    return [
        (line, lines[i + 1])
        for i, line in enumerate(lines)
        if line.startswith("#EXTINF")
    ]


def _build_dual_audio_playlist(root, spec):
    """Capture-like playlist where every region has AAC plus AC-3 tracks.

    ``spec`` is a list of ``(duration, first_track_channels)``.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:4",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    n = 0
    for dur, first_channels in spec:
        ents = _make_dual_audio_part(root, n, dur, first_channels)
        n += len(ents)
        out.append("#EXT-X-DISCONTINUITY")
        for extinf, uri in ents:
            out.extend([extinf, uri])
    out.append("#EXT-X-ENDLIST")
    path = root / "index.m3u8"
    path.write_text("\n".join(out) + "\n")
    return path


def _build_playlist(root, spec):
    """Build a capture-like playlist: leading DISCONTINUITY plus one per part.

    ``spec`` is a list of ``(duration, acodec, channels, sample_rate[, bitrate])``.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:4",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    n = 0
    for entry in spec:
        dur, codec, channels, rate = entry[:4]
        bitrate = entry[4] if len(entry) > 4 else None
        ents = _make_part(root, n, dur, codec, channels, rate, bitrate)
        n += len(ents)
        out.append("#EXT-X-DISCONTINUITY")
        for extinf, uri in ents:
            out.extend([extinf, uri])
    out.append("#EXT-X-ENDLIST")
    path = root / "index.m3u8"
    path.write_text("\n".join(out) + "\n")
    return path


def _build_video_playlist(root, durations):
    """Capture-like playlist of video-only parts, one region per duration."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:4",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    n = 0
    for dur in durations:
        ents = _make_part(root, n, dur, "aac", 2, audio=False)
        n += len(ents)
        out.append("#EXT-X-DISCONTINUITY")
        for extinf, uri in ents:
            out.extend([extinf, uri])
    out.append("#EXT-X-ENDLIST")
    path = root / "index.m3u8"
    path.write_text("\n".join(out) + "\n")
    return path


def _make_tracks_part(root, start_no, dur, tracks, freq=440, audio_seconds=None):
    """One HLS part with several audio tracks: ``tracks`` is ``[(codec, channels), ...]``.

    Track ``n`` carries a tone of ``freq * (n + 1)`` Hz. With ``audio_seconds``
    the audio runs that long while the video stops at ``dur``, like a capture
    flushed at its end.
    """
    part = root / f"part{start_no}.m3u8"
    cmd = ["-f", "lavfi", "-i", f"testsrc2=rate=25:size=64x64:duration={dur}"]
    for index in range(len(tracks)):
        cmd += [
            "-f", "lavfi", "-i",
            f"sine=frequency={freq * (index + 1)}:sample_rate=48000"
            f":duration={audio_seconds or dur}",
        ]
    cmd += ["-map", "0:v"]
    for index in range(len(tracks)):
        cmd += ["-map", f"{index + 1}:a"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-g", "25"]
    for index, (codec, channels) in enumerate(tracks):
        bitrate = "192k" if codec == "ac3" else "128k"
        cmd += [
            f"-c:a:{index}", codec, f"-b:a:{index}", bitrate,
            f"-ac:a:{index}", str(channels), f"-ar:a:{index}", "48000",
        ]
    cmd += [
        "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
        "-hls_flags", "independent_segments",
        "-start_number", str(start_no),
        "-hls_segment_filename", str(root / "seg_%05d.ts"),
        str(part),
    ]
    result = _ff(cmd)
    if result.returncode != 0:
        raise AssertionError(f"tracks part encode failed: {result.stderr[-400:]}")
    lines = part.read_text().splitlines()
    return [
        (line, lines[i + 1])
        for i, line in enumerate(lines)
        if line.startswith("#EXTINF")
    ]


def _pmt_payload(path):
    """The 184-byte payload of the first PMT packet in ``path`` (ffmpeg uses PID 0x1000)."""
    data = Path(path).read_bytes()
    for i in range(0, len(data) - 187, 188):
        pid = ((data[i + 1] & 0x1F) << 8) | data[i + 2]
        if data[i] == 0x47 and pid == 0x1000 and data[i + 1] & 0x40:
            return data[i + 4:i + 188]
    raise AssertionError(f"no PMT in {path}")


def _freeze_pmt(paths, template):
    """Give ``paths`` the program map of ``template``.

    That is what capture leaves behind after a source change: the new
    source's frames under the first source's labels.
    """
    payload = _pmt_payload(template)
    for path in paths:
        buf = bytearray(Path(path).read_bytes())
        for i in range(0, len(buf) - 187, 188):
            pid = ((buf[i + 1] & 0x1F) << 8) | buf[i + 2]
            if buf[i] == 0x47 and pid == 0x1000 and buf[i + 1] & 0x40:
                buf[i + 4:i + 188] = payload
        Path(path).write_bytes(buf)


def _build_frozen_playlist(root, spec):
    """One-region capture playlist whose parts differ in audio but share one PMT.

    ``spec`` is ``[(duration, tracks[, audio_seconds]), ...]`` as for
    ``_make_tracks_part``. Every segment carries the program map of the first
    part, as FFmpeg's muxer leaves it across a source change.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = [
        "#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:4",
        "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-DISCONTINUITY",
    ]
    n = 0
    entries = []
    for dur, tracks, *audio in spec:
        ents = _make_tracks_part(root, n, dur, tracks, audio_seconds=audio[0] if audio else None)
        n += len(ents)
        entries.extend(ents)
    template = root / entries[0][1]
    _freeze_pmt([root / uri for _extinf, uri in entries], template)
    for extinf, uri in entries:
        out.extend([extinf, uri])
    out.append("#EXT-X-ENDLIST")
    path = root / "index.m3u8"
    path.write_text("\n".join(out) + "\n")
    return path


def _read_stamp(buf, pos):
    return (
        ((buf[pos] >> 1) & 0x07) << 30 | buf[pos + 1] << 22
        | (buf[pos + 2] >> 1) << 15 | buf[pos + 3] << 7 | (buf[pos + 4] >> 1)
    )


def _write_stamp(buf, pos, value, prefix):
    value %= 1 << 33
    buf[pos] = prefix | (((value >> 30) & 0x07) << 1) | 0x01
    buf[pos + 1] = (value >> 22) & 0xFF
    buf[pos + 2] = (((value >> 15) & 0x7F) << 1) | 0x01
    buf[pos + 3] = (value >> 7) & 0xFF
    buf[pos + 4] = ((value & 0x7F) << 1) | 0x01


def _rewrite_pes_clock(path, pid, start=None, step=None, shift=0):
    """Rewrite the PTS (and DTS, when present) of every PES on ``pid``.

    With ``step`` the PTS become ``start + n * step`` (a crawling clock when the
    step is tiny). Without it every stamp moves by ``shift`` ticks.
    """
    buf = bytearray(Path(path).read_bytes())
    count = 0
    for i in range(0, len(buf) - 187, 188):
        if buf[i] != 0x47 or (((buf[i + 1] & 0x1F) << 8) | buf[i + 2]) != pid:
            continue
        if not buf[i + 1] & 0x40:
            continue
        adaptation = (buf[i + 3] >> 4) & 3
        off = i + 4 + (1 + buf[i + 4] if adaptation == 3 else 0)
        flags = buf[off + 7] >> 6
        if buf[off:off + 3] != b"\x00\x00\x01" or not flags & 0x02:
            continue
        old = _read_stamp(buf, off + 9)
        if step is not None:
            count += 1
            new = start + count * step
        else:
            new = old + shift
        _write_stamp(buf, off + 9, new, 0x30 if flags == 3 else 0x20)
        if flags == 3:
            old_dts = _read_stamp(buf, off + 14)
            _write_stamp(buf, off + 14, old_dts + (new - old), 0x10)
    Path(path).write_bytes(buf)


def _stall_audio_pts(path, pid, ticks=1):
    """Make the PTS of every PES on ``pid`` crawl by ``ticks`` per packet."""
    _rewrite_pes_clock(path, pid, start=3_000_000, step=ticks)


def _shift_pes_clock(path, pids, seconds):
    """Move the clock of each PID in ``pids`` by ``seconds``."""
    for pid in pids:
        _rewrite_pes_clock(path, pid, shift=int(seconds * 90000))


def _hand_section(shapes, codecs=None, head=None, mixed=False, skewed=(), video_type=0x1B):
    """A ``_Section`` for planning tests, without any file behind it.

    ``shapes`` holds one ``Shape`` or ``None`` per audio slot. Each slot is
    labeled with its shape's codec unless ``codecs`` says otherwise.
    """
    labels = {
        "aac": (0x0F, b""),
        "ac3": (0x81, bytes([0x05, 4]) + b"AC-3"),
        "eac3": (0x87, bytes([0x05, 4]) + b"EAC3"),
        "mp2": (0x03, b""),
    }
    audio = []
    for slot, shape in enumerate(shapes):
        codec = codecs[slot] if codecs else (shape.codec if shape else "aac")
        stream_type, descriptors = labels[codec]
        audio.append(PmtEntry(stream_type, 0x101 + slot, descriptors))
    audio = tuple(audio)
    pmt = PmtInfo(1, 0x1000, 0x100, 0, (PmtEntry(video_type, 0x100, b""),) + audio)
    return _Section(
        0, [("#EXTINF:4.0,", "seg_00000.ts")], pmt, audio,
        tuple(shapes if head is None else head), tuple(shapes),
        mixed, frozenset(skewed),
    )


def _build_tracks_playlist(root, spec):
    """Capture-like playlist with one honest region per ``(duration, tracks)`` entry.

    Every region is a separate FFmpeg run, so each carries its own program map.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = [
        "#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:4",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    n = 0
    for dur, tracks in spec:
        ents = _make_tracks_part(root, n, dur, tracks)
        n += len(ents)
        out.append("#EXT-X-DISCONTINUITY")
        for extinf, uri in ents:
            out.extend([extinf, uri])
    out.append("#EXT-X-ENDLIST")
    path = root / "index.m3u8"
    path.write_text("\n".join(out) + "\n")
    return path


def _tracking_fed(seen):
    """A stand-in for the stdin-fed runner that records each command it runs."""
    def tracking(cmd, chunks, log_label, step_label, deadline):
        seen.append(list(cmd))
        return _run_ffmpeg_fed_with_budget(cmd, chunks, log_label, step_label, deadline)
    return tracking


def _capture_joined_clips(root, clips):
    """Capture clips joined as the proxy joins sources, as ``run_recording`` does.

    ``clips`` is ``[(codec, channels, seconds), ...]``. Their bytes are joined
    with the discontinuity bit set on every clip after the first, then copied
    into HLS segments with ``-c copy``. FFmpeg smooths each splice and keeps
    the first clip's program map, so a later clip's audio lands under the first
    clip's label, and a splice inside a segment makes that segment mixed.
    Returns the playlist path.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    joined = bytearray()
    for index, (codec, channels, seconds) in enumerate(clips):
        clip = root / f"clip{index}.ts"
        result = _ff([
            "-f", "lavfi", "-i", "testsrc2=rate=25:size=64x64",
            "-f", "lavfi", "-i", f"sine=frequency={440 * (index + 1)}:sample_rate=48000",
            "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
            "-c:a", codec, "-ac", str(channels), "-b:a", "192k",
            "-f", "mpegts", str(clip),
        ])
        if result.returncode != 0:
            raise AssertionError(f"clip encode failed: {result.stderr[-400:]}")
        data = clip.read_bytes()
        joined += data if index == 0 else stamp_first_packet_per_pid(data)[0]
    joined_path = root / "joined.ts"
    joined_path.write_bytes(joined)
    hls = root / "hls"
    hls.mkdir()
    result = _ff([
        "-fflags", "+genpts", "-i", str(joined_path),
        "-map", "0:v?", "-map", "0:a?", "-c", "copy",
        "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
        "-hls_playlist_type", "event",
        "-hls_flags", "append_list+omit_endlist+independent_segments",
        "-hls_segment_filename", str(hls / "seg_%05d.ts"),
        str(hls / "index.m3u8"),
    ])
    if result.returncode != 0:
        raise AssertionError(f"capture failed: {result.stderr[-400:]}")
    return hls / "index.m3u8"


def _corrupt_adts(seg_path):
    """Zero out a few mid-file TS packets on PID 257 (typical AAC PID)."""
    data = bytearray(Path(seg_path).read_bytes())
    hits = [
        i for i in range(0, len(data) - 187, 188)
        if data[i] == 0x47 and (((data[i + 1] & 0x1F) << 8) | data[i + 2]) == 257
    ]
    mid = len(hits) // 2
    for i in hits[mid:mid + 3]:
        data[i + 4:i + 188] = b"\x00" * 184
    Path(seg_path).write_bytes(data)


def _mean_volume(path, start, duration, audio_index=0):
    result = _ff(
        [
            "-ss", str(start), "-t", str(duration),
            "-i", str(path),
            "-map", f"0:a:{audio_index}",
            "-af", "volumedetect",
            "-f", "null", "-",
        ],
        loglevel="info",
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    return float(match.group(1)) if match else None


def _is_audible(path, start, audio_index=0, duration=2.0):
    """True when the track plays real audio in ``[start, start + duration)``."""
    value = _mean_volume(path, start, duration, audio_index)
    return value is not None and value > -60.0


def _packet_pts(path, stream_spec):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", stream_spec,
            "-show_entries", "packet=pts_time",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return [
        float(x.strip(","))
        for x in result.stdout.split()
        if x.strip(",") not in ("", "N/A")
    ]


def _probe_format(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-count_packets",
            "-show_entries",
            "stream=codec_type,codec_name,channels,sample_rate,bit_rate,"
            "nb_read_packets:format=duration",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout or "{}")


def _video_packets(path):
    info = _probe_format(path)
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video":
            return int(stream.get("nb_read_packets") or 0)
    return 0


def _source_fingerprint(root):
    """Hash source playlists and segments, ignoring remux temps and the output."""
    digest = hashlib.sha256()
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "out.mkv" or path.name.startswith(".dvr_"):
            continue
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _leftover_temps(hls_dir):
    names = []
    for pattern in (
        ".dvr_*_section_*",
        ".dvr_*_sections.txt",
        ".dvr_*_intermediate.mp4",
    ):
        names.extend(p.name for p in Path(hls_dir).glob(pattern))
    return names


def _assert_audible_windows(testcase, out_path, audio_index=0):
    info = _probe_format(out_path)
    duration = float(info["format"]["duration"])
    windows = []
    t = 0.5
    while t + 1.0 <= duration - 0.3:
        windows.append(_mean_volume(out_path, t, 1.0, audio_index))
        t += 3.0
    testcase.assertTrue(windows, "expected at least one volume window")
    for value in windows:
        testcase.assertIsNotNone(value, f"silent/missing window in {windows}")
        # lavfi sine is loud; a truly silent window is around -91 dB.
        testcase.assertLess(value, -1.0)
        testcase.assertGreater(value, -60.0)
    return windows


def _assert_clean_decode(testcase, out_path):
    result = _ff(["-xerror", "-i", str(out_path), "-map", "0", "-f", "null", "-"])
    testcase.assertEqual(result.returncode, 0, result.stderr[-400:])


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
class DvrFfmpegErrorTailTests(SimpleTestCase):
    def test_tail_skips_banner_and_keeps_error(self):
        stderr = (
            "ffmpeg version 9.0.2-Dispatcharr Copyright (c) 2000-2026\n"
            "built with gcc 13\n"
            "configuration: --enable-gpl\n"
            "libavutil      60.  8.100 / 60.  8.100\n"
            "[aac_adtstoasc @ 0x1] Error parsing ADTS frame header\n"
            "[aost#0:1/copy] Error submitting packet to muxer: Invalid data\n"
        )
        tail = _ffmpeg_error_tail(stderr)
        self.assertNotIn("ffmpeg version", tail)
        self.assertIn("Error parsing ADTS frame header", tail)
        self.assertIn("Error submitting packet to muxer", tail)

    def test_empty_stderr(self):
        self.assertEqual(_ffmpeg_error_tail(""), "<no stderr>")
        self.assertEqual(_ffmpeg_error_tail(None), "<no stderr>")

    def test_non_utf8_stderr_does_not_abort_the_run(self):
        """A stray byte in echoed stream metadata must not raise out of the runner."""
        cmd = [
            sys.executable, "-c",
            "import sys; sys.stderr.buffer.write(b'Metadata: title: caf\\xe9 \\xff')",
        ]
        result = _run_ffmpeg_with_budget(
            cmd, "test-decode", "decode check", time.monotonic() + 30,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Metadata: title: caf", result.stderr)


class DvrRegionHelperTests(SimpleTestCase):
    def test_remux_result_unpacks_and_names_section_repair(self):
        copied = RemuxResult(True, False)
        repaired = RemuxResult(True, False, True)
        fallback = RemuxResult(True, True, True)
        failed = RemuxResult(False, False, True)
        ok, via_mp4 = repaired
        self.assertEqual((ok, via_mp4), (True, False))
        self.assertFalse(copied.repaired)
        self.assertTrue(repaired.repaired)
        # MP4 and failure never count as a section rebuild.
        self.assertFalse(fallback.repaired)
        self.assertFalse(failed.repaired)
        self.assertEqual(repaired, (True, False))

    def test_split_ignores_leading_discontinuity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.m3u8"
            path.write_text(
                "#EXTM3U\n"
                "#EXT-X-TARGETDURATION:4\n"
                "#EXT-X-DISCONTINUITY\n"
                "#EXTINF:4.0,\nseg_00000.ts\n"
                "#EXTINF:4.0,\nseg_00001.ts\n"
                "#EXT-X-DISCONTINUITY\n"
                "#EXTINF:4.0,\nseg_00002.ts\n"
                "#EXT-X-ENDLIST\n"
            )
            header, regions = _split_hls_regions(str(path))
            self.assertIn("#EXTM3U", header)
            self.assertEqual(len(regions), 2)
            self.assertEqual([u for _, u in regions[0]], ["seg_00000.ts", "seg_00001.ts"])
            self.assertEqual([u for _, u in regions[1]], ["seg_00002.ts"])

    def test_discontinuity_sequence_is_not_a_region_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.m3u8"
            path.write_text(
                "#EXTM3U\n"
                "#EXT-X-VERSION:3\n"
                "#EXT-X-TARGETDURATION:4\n"
                "#EXT-X-MEDIA-SEQUENCE:0\n"
                "#EXT-X-DISCONTINUITY-SEQUENCE:2\n"
                "#EXT-X-DISCONTINUITY\n"
                "#EXTINF:4.0,\nseg_00000.ts\n"
                "#EXT-X-DISCONTINUITY-SEQUENCE:3\n"
                "#EXTINF:4.0,\nseg_00001.ts\n"
                "#EXT-X-DISCONTINUITY\n"
                "#EXTINF:4.0,\nseg_00002.ts\n"
                "#EXT-X-ENDLIST\n"
            )
            header, regions = _split_hls_regions(str(path))
            self.assertIn("#EXT-X-DISCONTINUITY-SEQUENCE:2", header)
            self.assertEqual(len(regions), 2)
            self.assertEqual(
                [u for _, u in regions[0]],
                ["seg_00000.ts", "seg_00001.ts"],
            )
            self.assertEqual([u for _, u in regions[1]], ["seg_00002.ts"])

    def test_audio_bitrate_fallback_by_channels(self):
        self.assertEqual(_audio_bitrate_arg({"bitrate": 96000, "channels": 2}), "96000")
        self.assertEqual(_audio_bitrate_arg({"bitrate": 0, "channels": 2}), "192k")
        self.assertEqual(_audio_bitrate_arg({"bitrate": 0, "channels": 6}), "320k")

    def test_mp2_bitrate_snaps_to_a_value_the_encoder_accepts(self):
        def mp2(bitrate, rate=48000, channels=2):
            return {
                "codec": "mp2",
                "bitrate": bitrate,
                "sample_rate": rate,
                "channels": channels,
            }

        self.assertEqual(_audio_bitrate_arg(mp2(98736)), "96000")
        self.assertEqual(_audio_bitrate_arg(mp2(128000)), "128000")
        self.assertEqual(_audio_bitrate_arg(mp2(0)), "192000")
        self.assertEqual(_audio_bitrate_arg(mp2(500000)), "384000")
        # MPEG-2 (below 32 kHz) tops out at 160 kbps and has no 192 kbps.
        self.assertEqual(_audio_bitrate_arg(mp2(0, rate=24000)), "160000")
        self.assertEqual(_audio_bitrate_arg(mp2(70000, rate=22050)), "64000")

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
    def test_snapped_mp2_bitrate_opens_the_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "mp2.mkv"
            bitrate = _audio_bitrate_arg({
                "codec": "mp2", "bitrate": 98736,
                "sample_rate": 48000, "channels": 2,
            })
            result = _ff([
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-t", "1", "-c:a", "mp2", "-b:a", bitrate, str(out),
            ])
            self.assertEqual(result.returncode, 0, result.stderr[-400:])

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
    def test_audio_encoder_map_matches_this_build(self):
        self.assertEqual(_audio_encoder_for("aac"), "aac")
        self.assertEqual(_audio_encoder_for("mp2"), "mp2")
        self.assertEqual(_audio_encoder_for("mp3"), "libmp3lame")
        self.assertEqual(_audio_encoder_for("ac3"), "ac3")
        self.assertEqual(_audio_encoder_for("eac3"), "eac3")
        self.assertEqual(_audio_encoder_for("opus"), "libopus")
        self.assertIsNone(_audio_encoder_for("speex"))
        self.assertIsNone(_audio_encoder_for("dts"))
        # LATM AAC is re-encoded as plain AAC.
        self.assertEqual(_audio_encoder_for("aac_latm"), "aac")

    def test_layout_help_uses_the_widest_declared_layout(self):
        counts = {
            "mono": 1,
            "stereo": 2,
            "5.1": 6,
            "5.1(side)": 6,
            "2.1": 3,
        }
        line = (
            "    Supported channel layouts: mono stereo 5.1(side) 5.1 "
            "2 channels (FC+LFE) 4 channels (FL+FR+LFE+BC)"
        )
        self.assertEqual(_max_channels_in_layout_help(line, counts), 6)
        self.assertEqual(
            _max_channels_in_layout_help(
                "    Supported channel layouts: mono stereo", counts,
            ),
            2,
        )
        self.assertIsNone(_max_channels_in_layout_help("no layouts here", counts))

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
    def test_encoder_channel_limits_come_from_ffmpeg(self):
        self.assertEqual(_encoder_channel_limit("eac3"), 6)
        self.assertEqual(_encoder_channel_limit("ac3"), 6)
        self.assertEqual(_encoder_channel_limit("mp2"), 2)
        self.assertEqual(_encoder_channel_limit("mp3"), 2)
        # AAC does not declare a layout list, so there is no cap to apply.
        self.assertIsNone(_encoder_channel_limit("aac"))

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
    def test_wide_layout_switches_to_aac_instead_of_dropping_channels(self):
        self.assertEqual(_codec_for_layout("eac3", 6), "eac3")
        self.assertEqual(_codec_for_layout("eac3", 8), "aac")
        self.assertEqual(_codec_for_layout("ac3", 8), "aac")
        self.assertEqual(_codec_for_layout("mp2", 2), "mp2")
        self.assertEqual(_codec_for_layout("mp2", 6), "aac")
        self.assertEqual(_codec_for_layout("aac", 8), "aac")
        self.assertEqual(_codec_for_layout("aac_latm", 2), "aac")
        # AAC declares no maximum, so a still wider track tries AAC too.
        self.assertEqual(_codec_for_layout("eac3", 16), "aac")

    def test_failed_encoder_listing_is_not_cached(self):
        listing = (
            "Encoders:\n"
            " A....D aac                  AAC (Advanced Audio Coding)\n"
        )
        failing = MagicMock(returncode=1, stdout="")
        working = MagicMock(returncode=0, stdout=listing)
        with patch("apps.channels.dvr_remux._audio_encoder_cache", None), patch(
            "apps.channels.dvr_remux.subprocess.run",
            side_effect=[failing, working],
        ) as run:
            self.assertIsNone(_audio_encoder_for("aac"))
            # The first listing failed. The next call must ask again.
            self.assertEqual(_audio_encoder_for("aac"), "aac")
            self.assertEqual(run.call_count, 2)
            # A successful listing is cached, so there is no third call.
            self.assertEqual(_audio_encoder_for("aac"), "aac")
            self.assertEqual(run.call_count, 2)

    def test_adts_signature_requires_both_markers(self):
        ok = MagicMock(returncode=0, stderr="[aac_adtstoasc @ 0x1] Error parsing ADTS frame header")
        self.assertFalse(_ffmpeg_failed_adts(ok))
        bad = MagicMock(
            returncode=183,
            stderr="[aac_adtstoasc @ 0x1] Error parsing ADTS frame header\n",
        )
        self.assertTrue(_ffmpeg_failed_adts(bad))
        other = MagicMock(returncode=1, stderr="Invalid data found when processing input\n")
        self.assertFalse(_ffmpeg_failed_adts(other))


    def test_plan_needs_no_repair_when_nothing_changes(self):
        aac = Shape("aac", 2, 48000)
        self.assertFalse(_plan_needs_repair([_hand_section([aac]), _hand_section([aac])]))

    def test_plan_needs_repair_when_a_track_changes_codec_layout_or_rate(self):
        aac2 = Shape("aac", 2, 48000)
        for other in (
            Shape("ac3", 2, 48000),
            Shape("aac", 6, 48000),
            Shape("aac", 2, 44100),
        ):
            self.assertTrue(
                _plan_needs_repair([_hand_section([aac2]), _hand_section([other])]),
                other,
            )

    def test_plan_needs_repair_when_a_label_disagrees_with_the_frames(self):
        # AAC frames under an AC-3 label decode as silence.
        lying = _hand_section([Shape("aac", 2, 48000)], codecs=["ac3"])
        self.assertTrue(_plan_needs_repair([lying]))

    def test_a_track_that_only_goes_missing_needs_no_repair(self):
        eng = Shape("aac", 2, 48000)
        spa = Shape("ac3", 2, 48000)
        self.assertFalse(_plan_needs_repair([
            _hand_section([eng, spa]),
            _hand_section([eng, None]),
            _hand_section([eng, spa]),
        ]))

    def test_a_track_the_first_section_does_not_list_needs_repair(self):
        eng = Shape("aac", 2, 48000)
        spa = Shape("ac3", 2, 48000)
        # A copy would carry only the first section's single track.
        self.assertTrue(_plan_needs_repair([
            _hand_section([eng]), _hand_section([eng, spa]),
        ]))

    def test_a_track_on_a_broken_clock_needs_repair(self):
        aac = Shape("aac", 2, 48000)
        self.assertTrue(_plan_needs_repair([_hand_section([aac], skewed=[0])]))

    def test_a_source_change_inside_one_segment_is_noticed(self):
        ac3 = Shape("ac3", 6, 48000)
        aac = Shape("aac", 2, 48000)
        # Head is honest AC-3; the tail is AAC under the same AC-3 label.
        section = _hand_section([aac], codecs=["ac3"], head=[ac3], mixed=True)
        self.assertTrue(_plan_needs_repair([section]))

    def _targets(self, **overrides):
        base = {
            "codec": "ac3", "source_codec": "ac3",
            "sniff": Shape("ac3", 6, 48000),
        }
        return {**base, **overrides}

    def test_only_matching_slots_are_copied(self):
        ac3 = Shape("ac3", 6, 48000)
        aac = Shape("aac", 2, 48000)
        sections = [_hand_section([ac3]), _hand_section([aac], codecs=["ac3"])]
        copyable = _copyable_slots(sections, {0: self._targets()}, [0], False)
        self.assertEqual(copyable, [{0}, set()])

    def test_an_aac_track_is_copied_all_or_nothing(self):
        aac = Shape("aac", 2, 48000)
        silent = Shape("aac", 2, 48000)
        targets = {0: self._targets(codec="aac", source_codec="aac", sniff=aac)}
        sections = [_hand_section([aac]), _hand_section([None]), _hand_section([silent])]
        self.assertEqual(_copyable_slots(sections, targets, [0], False), [set(), set(), set()])
        # With every section matching, the track keeps its frames.
        sections = [_hand_section([aac]), _hand_section([silent])]
        self.assertEqual(_copyable_slots(sections, targets, [0], False), [{0}, {0}])

    def test_skewed_mixed_forced_and_converted_slots_are_not_copied(self):
        ac3 = Shape("ac3", 6, 48000)
        targets = {0: self._targets()}
        self.assertEqual(
            _copyable_slots([_hand_section([ac3], skewed=[0])], targets, [0], False),
            [set()],
        )
        self.assertEqual(
            _copyable_slots([_hand_section([ac3], mixed=True)], targets, [0], False),
            [set()],
        )
        self.assertEqual(
            _copyable_slots([_hand_section([ac3])], targets, [0], True), [set()],
        )
        converted = {0: self._targets(source_codec="aac_latm")}
        self.assertEqual(
            _copyable_slots([_hand_section([ac3])], converted, [0], False), [set()],
        )

    def test_slot_targets_refuse_a_video_stream_type_change(self):
        aac = Shape("aac", 2, 48000)
        sections = [_hand_section([aac]), _hand_section([aac], video_type=0x24)]
        with patch("apps.channels.dvr_remux._probe_section") as probe:
            self.assertIsNone(
                _slot_targets("/tmp", sections, time.monotonic() + 60, "test-video")
            )
        probe.assert_not_called()

    def test_slot_targets_refuse_an_unprobeable_track(self):
        sections = [_hand_section([Shape("aac", 2, 48000)])]
        with patch("apps.channels.dvr_remux._probe_section", return_value=None):
            self.assertIsNone(
                _slot_targets("/tmp", sections, time.monotonic() + 60, "test-probe")
            )

    def test_slot_targets_do_not_probe_past_the_remux_budget(self):
        sections = [_hand_section([Shape("aac", 2, 48000)])]
        with patch("apps.channels.dvr_remux._probe_section", return_value=None) as probe:
            _slot_targets("/tmp", sections, time.monotonic() - 1, "test-budget")
        self.assertEqual(probe.call_args.kwargs["timeout"], 0)

    def test_section_cmd_encodes_to_the_target_shape(self):
        targets = {0: {"codec": "aac", "channels": 2, "sample_rate": 48000, "bitrate": 128000}}
        cmd = _build_section_remux_cmd("/tmp/o.mkv", [0], [0], targets, set(), 8.0)
        self.assertEqual(cmd[cmd.index("-f") + 1], "mpegts")
        self.assertEqual(cmd[cmd.index("-i") + 1], "pipe:0")
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        self.assertEqual(cmd[cmd.index("-c:a:0") + 1], "aac")
        self.assertEqual(cmd[cmd.index("-ac:a:0") + 1], "2")
        self.assertEqual(cmd[cmd.index("-ar:a:0") + 1], "48000")
        self.assertEqual(cmd[cmd.index("-b:a:0") + 1], "128000")
        # Timestamps are followed (gaps filled), and the audio is cut at the
        # section's length.
        self.assertEqual(
            cmd[cmd.index("-filter:a:0") + 1],
            "aresample=async=1:first_pts=0,atrim=end=8.000",
        )
        self.assertIn("empty_output+empty_output_stream", cmd)

    def test_section_cmd_copies_matching_slots(self):
        targets = {0: {"codec": "ac3", "channels": 6, "sample_rate": 48000, "bitrate": 384000}}
        cmd = _build_section_remux_cmd("/tmp/o.mkv", [0], [0], targets, {0}, 8.0)
        self.assertEqual(cmd[cmd.index("-c:a:0") + 1], "copy")
        self.assertNotIn("-filter:a:0", cmd)
        self.assertNotIn("-abort_on", cmd)

    def test_section_cmd_fills_a_missing_slot_with_silence_in_slot_order(self):
        targets = {
            0: {"codec": "aac", "channels": 2, "sample_rate": 48000, "bitrate": 128000},
            1: {"codec": "ac3", "channels": 6, "sample_rate": 44100, "bitrate": 384000},
        }
        # This section only carries slot 0, so slot 1 is generated.
        cmd = _build_section_remux_cmd("/tmp/o.mkv", [0], [0, 1], targets, {0}, 12.5)
        lavfi = cmd.index("lavfi")
        self.assertEqual(cmd[lavfi - 1], "-f")
        self.assertEqual(cmd[lavfi + 1:lavfi + 3], ["-t", "12.500"])
        self.assertEqual(cmd[lavfi + 3], "-i")
        self.assertEqual(cmd[lavfi + 4], "anullsrc=r=44100:cl=stereo")
        maps = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-map"]
        self.assertEqual(maps, ["0:v?", "0:a:0", "1:a:0"])
        # The silence is encoded to the slot's own layout, with no timestamp filter.
        self.assertEqual(cmd[cmd.index("-c:a:1") + 1], "ac3")
        self.assertEqual(cmd[cmd.index("-ac:a:1") + 1], "6")
        self.assertNotIn("-filter:a:1", cmd)

    def test_section_cmd_maps_by_rank_among_the_slots_it_carries(self):
        targets = {
            1: {"codec": "aac", "channels": 2, "sample_rate": 48000, "bitrate": 128000},
            3: {"codec": "aac", "channels": 2, "sample_rate": 48000, "bitrate": 128000},
        }
        # The section carries slots 1 and 3, so they are its audio tracks 0 and 1.
        cmd = _build_section_remux_cmd("/tmp/o.mkv", [1, 3], [1, 3], targets, set(), 4.0)
        maps = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-map"]
        self.assertEqual(maps, ["0:v?", "0:a:0", "0:a:1"])

    def test_section_cmd_reads_a_skewed_slot_from_its_own_input(self):
        targets = {
            0: {"codec": "aac", "channels": 2, "sample_rate": 48000, "bitrate": 128000},
            1: {"codec": "ac3", "channels": 2, "sample_rate": 48000, "bitrate": 192000},
            2: {"codec": "aac", "channels": 2, "sample_rate": 48000, "bitrate": 128000},
        }
        # Slot 0 is read from stdin, slot 1 is on a bad clock and comes from a
        # second pipe, and slot 2 is generated.
        cmd = _build_section_remux_cmd(
            "/tmp/o.mkv", [0], [0, 1, 2], targets, set(), 4.0, side=[1], side_fd=9,
        )
        inputs = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-i"]
        self.assertEqual(inputs[:2], ["pipe:0", "pipe:9"])
        self.assertTrue(inputs[2].startswith("anullsrc"))
        maps = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-map"]
        self.assertEqual(maps, ["0:v?", "0:a:0", "1:a:0", "2:a:0"])
        # The skewed slot's timeline comes from its samples. The others do not.
        self.assertEqual(
            cmd[cmd.index("-filter:a:1") + 1], "asetpts=N/SR/TB,atrim=end=4.000",
        )
        self.assertEqual(
            cmd[cmd.index("-filter:a:0") + 1],
            "aresample=async=1:first_pts=0,atrim=end=4.000",
        )
        self.assertNotIn("-filter:a:2", cmd)

    def test_section_cmd_has_no_second_input_without_a_skewed_slot(self):
        targets = {0: {"codec": "aac", "channels": 2, "sample_rate": 48000, "bitrate": 128000}}
        cmd = _build_section_remux_cmd("/tmp/o.mkv", [0], [0], targets, set(), 4.0)
        self.assertEqual([cmd[i + 1] for i, v in enumerate(cmd) if v == "-i"], ["pipe:0"])

    @unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
    def test_section_cmd_uses_mp3_encoder(self):
        targets = {0: {"codec": "mp3", "channels": 2, "sample_rate": 48000, "bitrate": 128000}}
        cmd = _build_section_remux_cmd("/tmp/o.mkv", [0], [0], targets, set(), 4.0)
        self.assertEqual(cmd[cmd.index("-c:a:0") + 1], "libmp3lame")

    def test_fed_runner_gives_ffmpeg_its_stdin(self):
        result = _run_ffmpeg_fed_with_budget(
            ["sh", "-c", "cat > /dev/null; echo done >&2"],
            (chunk for chunk in [b"x" * 1000] * 50), "test-fed", "step", time.monotonic() + 30,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("done", result.stderr)

    def test_fed_runner_feeds_a_second_input(self):
        import os
        read_fd, write_fd = os.pipe()
        with tempfile.TemporaryDirectory() as tmp:
            side_copy = Path(tmp) / "side.bin"
            main_copy = Path(tmp) / "main.bin"
            result = _run_ffmpeg_fed_with_budget(
                ["sh", "-c", f"cat /proc/self/fd/{read_fd} > {side_copy}; cat > {main_copy}"],
                (chunk for chunk in [b"main" * 1000]), "test-fed", "step",
                time.monotonic() + 30,
                side_feeds=[(read_fd, write_fd, (c for c in [b"side" * 500]))],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(side_copy.read_bytes(), b"side" * 500)
            self.assertEqual(main_copy.read_bytes(), b"main" * 1000)

    def test_fed_runner_closes_a_second_input_it_never_started(self):
        import os
        read_fd, write_fd = os.pipe()
        with patch("apps.channels.dvr_remux.subprocess.Popen") as popen:
            result = _run_ffmpeg_fed_with_budget(
                ["ffmpeg"], (chunk for chunk in [b"x"]), "test-fed", "step",
                time.monotonic() - 1,
                side_feeds=[(read_fd, write_fd, (c for c in [b"y"]))],
            )
        self.assertIsNone(result)
        popen.assert_not_called()
        for fd in (read_fd, write_fd):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_fed_runner_refuses_when_the_budget_is_gone(self):
        chunks = (chunk for chunk in [b"x"])
        with patch("apps.channels.dvr_remux.subprocess.Popen") as popen:
            result = _run_ffmpeg_fed_with_budget(
                ["ffmpeg"], chunks, "test-fed", "step", time.monotonic() - 1,
            )
        self.assertIsNone(result)
        popen.assert_not_called()

    def test_fed_runner_times_out_and_stops_the_process(self):
        started = time.monotonic()
        result = _run_ffmpeg_fed_with_budget(
            ["sleep", "30"], (chunk for chunk in []), "test-fed", "step",
            time.monotonic() + 0.5,
        )
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - started, 10)

    def test_fed_runner_fails_when_the_input_cannot_be_read(self):
        def broken():
            yield b"x"
            raise OSError(5, "Input/output error")

        result = _run_ffmpeg_fed_with_budget(
            ["sh", "-c", "cat > /dev/null"], broken(), "test-fed", "step",
            time.monotonic() + 30,
        )
        self.assertIsNone(result)

    def test_fed_runner_does_not_pass_off_a_truncated_run_as_success(self):
        # The process exits cleanly without reading its input.
        result = _run_ffmpeg_fed_with_budget(
            ["sh", "-c", "exit 0"], (chunk for chunk in [b"x" * 65536] * 400),
            "test-fed", "step", time.monotonic() + 30,
        )
        self.assertIsNotNone(result)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stopped reading", result.stderr)


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
class DvrCaptureChangeIntegrationTests(SimpleTestCase):
    """Audio that changes under the program map capture wrote once.

    These are the recordings a proxy stream switch, or a source that changes
    its own audio, leaves behind.
    """

    def test_sections_follow_the_content_not_the_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plan"
            pl = _build_frozen_playlist(root, [
                (8, [("ac3", 6)]), (8, [("aac", 2)]), (8, [("ac3", 6)]),
            ])
            _header, regions = _split_hls_regions(str(pl))
            self.assertEqual(len(regions), 1)
            sections = _plan_sections(str(root), regions, "test-plan")
            self.assertEqual([len(s.segments) for s in sections], [2, 2, 2])
            self.assertEqual(
                [s.shapes[0].codec for s in sections], ["ac3", "aac", "ac3"],
            )
            self.assertFalse(any(s.mixed for s in sections))
            self.assertTrue(_plan_needs_repair(sections))

    def test_codec_change_under_a_frozen_label_is_recovered(self):
        """AC-3 5.1, then AAC stereo, then AC-3 5.1 again, all labeled AC-3."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "codec"
            pl = _build_frozen_playlist(root, [
                (8, [("ac3", 6)]), (8, [("aac", 2)]), (8, [("ac3", 6)]),
            ])
            out = root / "out.mkv"
            outcome = remux_hls_to_mkv(str(pl), str(out), "test-codec", 4242)
            ok, via_mp4 = outcome
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            self.assertTrue(outcome.repaired)
            audio = [
                s for s in _probe_format(out)["streams"] if s["codec_type"] == "audio"
            ]
            # The file keeps the first source's track, codec, and layout.
            self.assertEqual([(s["codec_name"], int(s["channels"])) for s in audio], [("ac3", 6)])
            for start in (1.0, 9.0, 17.0):
                self.assertTrue(_is_audible(out, start), start)
            self.assertEqual(_video_packets(out), 600)
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(root), [])

    def test_a_source_with_fewer_tracks_keeps_the_original_tracks(self):
        """Two tracks, then one with a new codec, then the two return."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fewer"
            both = [("ac3", 6), ("aac", 2)]
            pl = _build_frozen_playlist(root, [
                (8, both), (8, [("aac", 2)]), (8, both),
            ])
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-fewer", 4242)
            self.assertTrue(ok)
            audio = [
                s for s in _probe_format(out)["streams"] if s["codec_type"] == "audio"
            ]
            self.assertEqual([s["codec_name"] for s in audio], ["ac3", "aac"])
            # The first track plays throughout, even where the source had only one.
            for start in (1.0, 9.0, 17.0):
                self.assertTrue(_is_audible(out, start, 0), start)
            # The second plays while the source has it. Its section is silent,
            # and its audio is back when the source returns.
            self.assertTrue(_is_audible(out, 1.0, 1))
            self.assertFalse(_is_audible(out, 10.0, 1))
            self.assertTrue(_is_audible(out, 18.0, 1))
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(root), [])

    def test_a_track_that_only_goes_missing_is_copied_with_a_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "missing"
            both = [("aac", 2), ("ac3", 2)]
            pl = _build_frozen_playlist(root, [
                (8, both), (8, [("aac", 2)]), (8, both),
            ])
            out = root / "out.mkv"
            with patch(
                "apps.channels.dvr_remux._section_repair",
                side_effect=AssertionError("repair should not run"),
            ):
                ok, via_mp4 = remux_hls_to_mkv(str(pl), str(out), "test-gap", 4242)
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            self.assertTrue(_is_audible(out, 1.0, 1))
            self.assertFalse(_is_audible(out, 10.0, 1))
            self.assertTrue(_is_audible(out, 18.0, 1))

    def test_a_switch_to_a_source_of_the_same_shape_is_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "same"
            pl = _build_frozen_playlist(root, [
                (8, [("aac", 2)]), (8, [("aac", 2)]),
            ])
            out = root / "out.mkv"
            with patch(
                "apps.channels.dvr_remux._section_repair",
                side_effect=AssertionError("repair should not run"),
            ):
                outcome = remux_hls_to_mkv(str(pl), str(out), "test-same", 4242)
            ok, via_mp4 = outcome
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            self.assertFalse(outcome.repaired)
            _assert_audible_windows(self, out)

    def test_a_track_with_a_crawling_clock_is_rebuilt_from_its_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stuck"
            pl = _build_frozen_playlist(root, [
                (8, [("ac3", 2)]), (8, [("ac3", 2)]),
            ])
            _header, regions = _split_hls_regions(str(pl))
            segments = [uri for _extinf, uri in regions[0]]
            for uri in segments[2:]:
                _stall_audio_pts(root / uri, 0x101)
            sections = _plan_sections(str(root), regions, "test-stuck")
            self.assertEqual([sorted(s.skewed) for s in sections], [[], [0]])
            self.assertTrue(_plan_needs_repair(sections))
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-stuck", 4242)
            self.assertTrue(ok)
            pts = _packet_pts(out, "a:0")
            self.assertTrue(all(b > a for a, b in zip(pts, pts[1:])))
            self.assertGreater(pts[-1], 14.0)
            # The crawling clock must not stretch or squeeze the video's own.
            video = _packet_pts(out, "v:0")
            self.assertEqual(len(video), 400)
            self.assertAlmostEqual(video[-1] - video[0], 16.0, delta=0.3)
            for start in (1.0, 9.0, 13.0):
                self.assertTrue(_is_audible(out, start), start)
            _assert_clean_decode(self, out)

    def test_audio_longer_than_the_video_is_cut_at_the_section_end(self):
        """A capture flushed at its end holds more audio than video in its last segment."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "flush"
            pl = _build_frozen_playlist(root, [
                (8, [("ac3", 6)]), (8, [("aac", 2)], 12),
            ])
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-flush", 4242)
            self.assertTrue(ok)
            video = _packet_pts(out, "v:0")
            audio = _packet_pts(out, "a:0")
            self.assertGreater(video[-1], 15.0)
            self.assertLess(audio[-1], video[-1] + 0.2)
            _assert_clean_decode(self, out)

    def test_a_track_on_another_clock_does_not_drag_the_video(self):
        """After a source returns, some tracks keep a clock tens of seconds off.

        FFmpeg corrects a clock jump for a whole input, so left in with the
        video such a track squeezed the video's timeline. It is read apart.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "offset"
            both = [("ac3", 2), ("aac", 2)]
            pl = _build_frozen_playlist(root, [(8, both), (8, both)])
            _header, regions = _split_hls_regions(str(pl))
            segments = [uri for _extinf, uri in regions[0]]
            # After the source returns, the video and one track are on the live
            # clock while the other track kept a clock 40 s behind.
            for uri in segments[2:]:
                _shift_pes_clock(root / uri, (0x100, 0x101), 40.0)
            sections = _plan_sections(str(root), regions, "test-offset")
            self.assertEqual([sorted(s.skewed) for s in sections], [[], [1]])
            self.assertTrue(_plan_needs_repair(sections))
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-offset", 4242)
            self.assertTrue(ok)
            video = _packet_pts(out, "v:0")
            # The video keeps its own 16 seconds; none of it is squeezed.
            self.assertAlmostEqual(video[-1] - video[0], 16.0, delta=0.3)
            self.assertEqual(len(video), 400)
            for index in (0, 1):
                pts = _packet_pts(out, f"a:{index}")
                self.assertGreater(pts[-1] - pts[0], 15.0, index)
                for start in (1.0, 9.0, 13.0):
                    self.assertTrue(_is_audible(out, start, index), (index, start))
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(root), [])

    def test_a_real_capture_that_swaps_codecs_mid_stream_is_recovered(self):
        """FFmpeg itself writes AAC under an AC-3 label, with a mixed segment at the splice."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "swap"
            pl = _capture_joined_clips(root, [
                ("ac3", 6, 10), ("aac", 2, 10), ("ac3", 6, 10),
            ])
            hls = pl.parent
            _header, regions = _split_hls_regions(str(pl))
            sections = _plan_sections(str(hls), regions, "test-swap")
            # The fixture really reproduces the failure: one label, changing frames.
            self.assertEqual(len({s.pmt.entries for s in sections}), 1)
            self.assertIn("aac", [s.shapes[0].codec for s in sections])
            self.assertTrue(any(s.mixed for s in sections))
            self.assertTrue(_plan_needs_repair(sections))
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-swap", 4242)
            self.assertTrue(ok)
            audio = [
                s for s in _probe_format(out)["streams"] if s["codec_type"] == "audio"
            ]
            self.assertEqual([(s["codec_name"], int(s["channels"])) for s in audio], [("ac3", 6)])
            for start in (2.0, 14.0, 26.0):
                self.assertTrue(_is_audible(out, start), start)
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(hls), [])

    def test_in_process_channel_change_is_repaired_from_the_segments(self):
        """AAC stereo, then AAC 5.1, under one label and one codec.

        Only the frames' own headers show the change; FFmpeg writes no
        playlist tag for it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "inproc"
            pl = _capture_joined_clips(root, [("aac", 2, 10), ("aac", 6, 10)])
            hls = pl.parent
            self.assertEqual(pl.read_text().count("#EXT-X-DISCONTINUITY\n"), 1)
            out = root / "out.mkv"
            with patch(
                "apps.channels.dvr_remux._section_repair",
                wraps=_section_repair,
            ) as repair:
                ok, via_mp4 = remux_hls_to_mkv(str(pl), str(out), "test-inproc", 4242)
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            repair.assert_called_once()
            audio = [
                s for s in _probe_format(out)["streams"] if s["codec_type"] == "audio"
            ]
            self.assertEqual(len(audio), 1)
            self.assertEqual(audio[0]["channels"], 2)
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(hls), [])


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
class DvrRemuxRecoveryIntegrationTests(SimpleTestCase):
    """End-to-end remux against synthetic capture playlists."""

    def test_single_region_corrupt_aac_repairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "single"
            pl = _build_playlist(root, [(12, "aac", 2, 48000)])
            source_video = sum(
                _video_packets(path) for path in sorted(root.glob("seg_*.ts"))
            )
            self.assertGreater(source_video, 0)
            _corrupt_adts(root / "seg_00001.ts")
            out = root / "out.mkv"
            ok, via_mp4 = remux_hls_to_mkv(str(pl), str(out), "test-single", 4242)
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            self.assertTrue(out.exists() and out.stat().st_size > 0)
            self.assertEqual(_video_packets(out), source_video)
            _assert_clean_decode(self, out)
            audio_pts = _packet_pts(out, "a:0")
            self.assertGreater(len(audio_pts), 10)
            max_gap = max(
                audio_pts[i + 1] - audio_pts[i] for i in range(len(audio_pts) - 1)
            )
            # One AAC frame at 48 kHz is ~21 ms; async fill should keep gaps small.
            self.assertLess(max_gap, 0.1)
            self.assertEqual(_leftover_temps(root), [])

    def test_stereo_then_surround_routes_to_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "layout"
            pl = _build_playlist(root, [
                (8, "aac", 2, 48000),
                (8, "aac", 6, 48000),
            ])
            out = root / "out.mkv"
            ok, via_mp4 = remux_hls_to_mkv(str(pl), str(out), "test-layout", 4242)
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
            self.assertEqual(audio["codec_name"], "aac")
            self.assertEqual(int(audio["channels"]), 2)
            video = [s for s in info["streams"] if s["codec_type"] == "video"][0]
            self.assertEqual(int(video["nb_read_packets"]), 400)
            _assert_audible_windows(self, out)
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(root), [])

    def test_sample_rate_change_repairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rate"
            pl = _build_playlist(root, [
                (8, "aac", 2, 44100),
                (8, "aac", 2, 48000),
            ])
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-rate", 4242)
            self.assertTrue(ok)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
            self.assertEqual(int(audio["sample_rate"]), 44100)
            _assert_audible_windows(self, out)
            _assert_clean_decode(self, out)

    def test_codec_switch_aac_ac3_aac(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "codec"
            pl = _build_playlist(root, [
                (8, "aac", 2, 48000),
                (8, "ac3", 2, 48000),
                (8, "aac", 2, 48000),
            ])
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-codec", 4242)
            self.assertTrue(ok)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
            self.assertEqual(audio["codec_name"], "aac")
            video = [s for s in info["streams"] if s["codec_type"] == "video"][0]
            self.assertEqual(int(video["nb_read_packets"]), 600)
            _assert_audible_windows(self, out)
            _assert_clean_decode(self, out)

    def test_codec_switch_plus_corrupt_retries_matching_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "codec_corrupt"
            pl = _build_playlist(root, [
                (8, "aac", 2, 48000),
                (8, "ac3", 2, 48000),
                (8, "aac", 2, 48000),
            ])
            # Corrupt a segment in region 0 (matching AAC) so copy-audio retries.
            _corrupt_adts(root / "seg_00001.ts")
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-codec-corrupt", 4242)
            self.assertTrue(ok)
            _assert_audible_windows(self, out)
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(root), [])

    def test_same_shape_regions_with_corrupt_reencodes_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "same_shape"
            pl = _build_playlist(root, [
                (8, "aac", 2, 48000),
                (8, "aac", 2, 48000),
            ])
            _corrupt_adts(root / "seg_00001.ts")
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-same-shape", 4242)
            self.assertTrue(ok)
            _assert_audible_windows(self, out)
            _assert_clean_decode(self, out)

    def test_stable_aac_plus_ac3_tracks_preserved(self):
        """Dual-audio fixture: AAC and AC-3 must both survive repair."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dual"
            root.mkdir()
            # Build a short dual-audio segment playlist (single region).
            part = root / "part.m3u8"
            result = _ff([
                "-f", "lavfi", "-i", "testsrc2=rate=25:size=64x64",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
                "-t", "8",
                "-map", "0:v", "-map", "1:a", "-map", "2:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
                "-c:a:0", "aac", "-b:a:0", "128k", "-ac:a:0", "2",
                "-c:a:1", "ac3", "-b:a:1", "192k", "-ac:a:1", "2",
                "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
                "-hls_flags", "independent_segments",
                "-hls_segment_filename", str(root / "seg_%05d.ts"),
                str(part),
            ])
            self.assertEqual(result.returncode, 0, result.stderr[-400:])
            lines = part.read_text().splitlines()
            ents = [
                (line, lines[i + 1])
                for i, line in enumerate(lines)
                if line.startswith("#EXTINF")
            ]
            body = [
                "#EXTM3U",
                "#EXT-X-VERSION:3",
                "#EXT-X-TARGETDURATION:4",
                "#EXT-X-MEDIA-SEQUENCE:0",
                "#EXT-X-DISCONTINUITY",
            ]
            for e in ents:
                body.extend(e)
            body.append("#EXT-X-ENDLIST")
            pl = root / "index.m3u8"
            pl.write_text("\n".join(body) + "\n")
            _corrupt_adts(root / "seg_00000.ts")
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-dual", 4242)
            self.assertTrue(ok)
            info = _probe_format(out)
            codecs = sorted(
                s["codec_name"] for s in info["streams"] if s["codec_type"] == "audio"
            )
            self.assertEqual(codecs, ["aac", "ac3"])
            # Both tracks should have measurable energy.
            for index in (0, 1):
                result = _ff(
                    [
                        "-ss", "1", "-t", "1",
                        "-i", str(out),
                        "-map", f"0:a:{index}",
                        "-af", "volumedetect",
                        "-f", "null", "-",
                    ],
                    loglevel="info",
                )
                match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
                self.assertIsNotNone(match)
                self.assertGreater(float(match.group(1)), -60.0)

    def test_reencode_uses_probed_bitrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bitrate"
            pl = _build_playlist(root, [
                (6, "aac", 2, 48000, "96000"),
                (6, "aac", 6, 48000, "192000"),
            ])
            _header, regions = _split_hls_regions(str(pl))
            sections = _plan_sections(str(root), regions, "test-bitrate")
            targets, _slots = _slot_targets(
                str(root), sections, time.monotonic() + 60, "test-bitrate",
            )
            probed = int(targets[0]["bitrate"] or 0)
            self.assertGreater(probed, 0)
            seen_cmds = []
            out = root / "out.mkv"
            with patch(
                "apps.channels.dvr_remux._run_ffmpeg_fed_with_budget",
                side_effect=_tracking_fed(seen_cmds),
            ):
                ok, _ = remux_hls_to_mkv(
                    str(pl), str(out), "test-bitrate", 4242,
                )
            self.assertTrue(ok)
            # Matroska often omits bit_rate in ffprobe; assert the encode target
            # used the first section's probed bitrate (not the 192k/320k fallback).
            reencode_cmds = [
                cmd for cmd in seen_cmds
                if "-c:a:0" in cmd and "-b:a:0" in cmd
            ]
            self.assertTrue(reencode_cmds, f"no re-encode cmds in {seen_cmds}")
            for cmd in reencode_cmds:
                self.assertEqual(cmd[cmd.index("-b:a:0") + 1], str(probed))
                self.assertNotIn(cmd[cmd.index("-b:a:0") + 1], ("192k", "320k"))

    def test_unchanged_audio_is_copied_without_an_ffprobe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "norestart"
            # Single region still has a leading DISCONTINUITY in capture playlists.
            pl = _build_playlist(root, [(8, "aac", 2, 48000)])
            out = root / "out.mkv"
            with patch(
                "apps.channels.dvr_remux._probe_ts_bytes",
                side_effect=AssertionError("probe should not run"),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-norestart", 4242,
                )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)

    def test_restarts_identical_shape_uses_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "identical"
            pl = _build_playlist(root, [
                (6, "aac", 2, 48000),
                (6, "aac", 2, 48000),
            ])
            out = root / "out.mkv"
            with patch(
                "apps.channels.dvr_remux._section_repair",
                side_effect=AssertionError("repair should not run"),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-identical", 4242,
                )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)

    def test_track_count_change_across_a_restart_keeps_the_first_tracks(self):
        """Two tracks, then one, then two again: the file keeps both tracks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "count"
            both = [("aac", 2), ("ac3", 2)]
            pl = _build_tracks_playlist(root, [
                (8, both), (8, [("aac", 2)]), (8, both),
            ])
            out = root / "out.mkv"
            ok, via_mp4 = remux_hls_to_mkv(str(pl), str(out), "test-count", 4242)
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
            self.assertEqual([s["codec_name"] for s in audio], ["aac", "ac3"])
            # A copy across restarts can lose a frame at each, as it always has.
            self.assertGreaterEqual(_video_packets(out), 590)
            # The first track plays throughout. The second is silent only while
            # the source lacks it, and its audio returns afterwards.
            for start in (1.0, 9.0, 17.0):
                self.assertTrue(_is_audible(out, start, 0), start)
            self.assertTrue(_is_audible(out, 1.0, 1))
            self.assertFalse(_is_audible(out, 10.0, 1))
            self.assertTrue(_is_audible(out, 18.0, 1))
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(root), [])

    def test_a_track_that_first_appears_later_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "later"
            pl = _build_tracks_playlist(root, [
                (8, [("aac", 2)]),
                (8, [("aac", 2), ("ac3", 2)]),
            ])
            out = root / "out.mkv"
            ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-later", 4242)
            self.assertTrue(ok)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
            self.assertEqual([s["codec_name"] for s in audio], ["aac", "ac3"])
            self.assertFalse(_is_audible(out, 2.0, 1))
            self.assertTrue(_is_audible(out, 10.0, 1))
            self.assertTrue(_is_audible(out, 2.0, 0))
            self.assertTrue(_is_audible(out, 10.0, 0))
            _assert_clean_decode(self, out)

    def test_unreadable_segments_still_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "unprobe"
            pl = _build_playlist(root, [
                (4, "aac", 2, 48000),
                (4, "aac", 6, 48000),
            ])
            out = root / "out.mkv"
            before = _source_fingerprint(root)
            with patch(
                "apps.channels.dvr_remux._plan_sections",
                return_value=None,
            ), patch(
                "apps.channels.dvr_remux._section_repair",
                side_effect=AssertionError("repair must not run"),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-unprobe", 4242,
                )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            self.assertEqual(_source_fingerprint(root), before)
            self.assertEqual(_leftover_temps(root), [])

    def test_unreadable_segments_do_not_strand_an_adts_failure(self):
        """Segments that cannot be inspected must still reach the MP4 fallback."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "unprobe-adts"
            pl = _build_playlist(root, [
                (4, "aac", 2, 48000),
                (4, "aac", 6, 48000),
            ])
            out = root / "out.mkv"
            intermediate = root / ".dvr_77_intermediate.mp4"
            steps = []

            def fake_budget(cmd, log_label, step_label, deadline):
                steps.append(step_label)
                result = MagicMock()
                dest = cmd[-1]
                if "playlist remux" in step_label and dest == str(out):
                    result.returncode = 1
                    result.stderr = (
                        "[aac_adtstoasc @ 0x1] Error parsing ADTS frame header\n"
                    )
                    return result
                if dest == str(intermediate):
                    open(dest, "wb").write(b"fake-mp4")
                    result.returncode = 0
                    result.stderr = ""
                    return result
                if dest == str(out):
                    open(dest, "wb").write(b"fake-mkv")
                    result.returncode = 0
                    result.stderr = ""
                    return result
                result.returncode = 1
                result.stderr = "unexpected step\n"
                return result

            with patch(
                "apps.channels.dvr_remux._plan_sections",
                return_value=None,
            ), patch(
                "apps.channels.dvr_remux._run_ffmpeg_with_budget",
                side_effect=fake_budget,
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-unprobe-adts", 77,
                )
            self.assertTrue(ok)
            self.assertTrue(via_mp4)
            # Repair has no sections to work from, so it never reaches ffmpeg.
            self.assertFalse(any(s.startswith("section ") for s in steps))
            self.assertTrue(any("MP4" in s for s in steps))
            self.assertFalse(intermediate.exists())
            self.assertEqual(_leftover_temps(root), [])

    def test_refuse_missing_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "encoder"
            pl = _build_playlist(root, [
                (4, "aac", 2, 48000),
                (4, "aac", 6, 48000),
            ])

            def fake_probe(hls_dir, section, timeout=30):
                probe = _probe_section(hls_dir, section, timeout=timeout)
                if probe is not None:
                    probe = {**probe, "audio": {
                        slot: dict(stream, codec="speex")
                        for slot, stream in probe["audio"].items()
                    }}
                return probe

            out = root / "out.mkv"
            before = _source_fingerprint(root)
            with patch(
                "apps.channels.dvr_remux._probe_section",
                side_effect=fake_probe,
            ):
                ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-encoder", 4242)
            self.assertFalse(ok)
            self.assertEqual(_source_fingerprint(root), before)

    def test_video_only_restarts_still_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "video"
            pl = _build_video_playlist(root, [4, 4])
            _header, regions = _split_hls_regions(str(pl))
            sections = _plan_sections(str(root), regions, "test-video")
            self.assertTrue(sections)
            for section in sections:
                self.assertEqual(section.audio, ())
            self.assertFalse(_plan_needs_repair(sections))
            out = root / "out.mkv"
            with patch(
                "apps.channels.dvr_remux._section_repair",
                side_effect=AssertionError("repair should not run"),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-video", 4242,
                )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            self.assertGreater(_video_packets(out), 0)

    def test_mp3_target_reencodes_with_lame(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mp3"
            pl = _build_playlist(root, [
                (4, "libmp3lame", 2, 48000, "128k"),
                (4, "aac", 2, 48000),
            ])
            out = root / "out.mkv"
            seen = []
            with patch(
                "apps.channels.dvr_remux._run_ffmpeg_fed_with_budget",
                side_effect=_tracking_fed(seen),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-mp3", 4242,
                )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
            self.assertEqual(audio["codec_name"], "mp3")
            self.assertTrue(
                any("libmp3lame" in cmd for cmd in seen),
                f"libmp3lame not used in {seen}",
            )

    def test_mp2_target_reencodes_and_stays_audible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mp2"
            pl = _build_playlist(root, [
                (8, "mp2", 2, 48000, "128k"),
                (8, "aac", 2, 48000),
            ])
            out = root / "out.mkv"
            ok, via_mp4 = remux_hls_to_mkv(
                str(pl), str(out), "test-mp2", 4242,
            )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
            self.assertEqual(audio["codec_name"], "mp2")
            _assert_audible_windows(self, out)
            _assert_clean_decode(self, out)

    def test_latm_target_is_reencoded_as_aac_everywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "latm"
            pl = _build_playlist(root, [
                (8, "aac_latm", 2, 48000),
                (8, "aac", 6, 48000),
            ])
            _header, regions = _split_hls_regions(str(pl))
            sections = _plan_sections(str(root), regions, "test-latm")
            targets, _slots = _slot_targets(
                str(root), sections, time.monotonic() + 60, "test-latm",
            )
            self.assertEqual(targets[0]["source_codec"], "aac_latm")
            self.assertEqual(targets[0]["codec"], "aac")
            out = root / "out.mkv"
            seen = []
            with patch(
                "apps.channels.dvr_remux._run_ffmpeg_fed_with_budget",
                side_effect=_tracking_fed(seen),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-latm", 4242,
                )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            # Section 0 matches itself but is LATM, so it must be re-encoded
            # too. Otherwise copied LATM and re-encoded AAC would not join.
            section_cmds = [cmd for cmd in seen if "-c:v" in cmd]
            self.assertEqual(len(section_cmds), 2)
            for cmd in section_cmds:
                self.assertEqual(cmd[cmd.index("-c:a:0") + 1], "aac")
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
            self.assertEqual([s["codec_name"] for s in audio], ["aac"])
            _assert_audible_windows(self, out)
            _assert_clean_decode(self, out)

    def test_multi_audio_survives_the_region_join(self):
        """Extra audio tracks must not be dropped when regions are concatenated."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "multi"
            # Track 0 changes layout at the restart, which forces repair.
            pl = _build_dual_audio_playlist(root, [(8, 2), (8, 6)])
            out = root / "out.mkv"
            ok, via_mp4 = remux_hls_to_mkv(
                str(pl), str(out), "test-multi", 4242,
            )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
            self.assertEqual([s["codec_name"] for s in audio], ["aac", "ac3"])
            self.assertEqual(int(audio[0]["channels"]), 2)
            for index in (0, 1):
                _assert_audible_windows(self, out, audio_index=index)
            self.assertEqual(_video_packets(out), 400)
            _assert_clean_decode(self, out)
            self.assertEqual(_leftover_temps(root), [])

    def test_eac3_71_repairs_as_aac_and_keeps_the_channels(self):
        """This build cannot encode E-AC-3 7.1, so repair stores it as AAC 7.1."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "eac3_71"
            pl = _build_playlist(root, [
                (4, "aac_latm", 8, 48000, "384k"),
                (4, "aac", 2, 48000),
            ])

            def fake_probe(hls_dir, section, timeout=30):
                probe = _probe_section(hls_dir, section, timeout=timeout)
                if probe is not None and section.segments[0][1] == "seg_00000.ts":
                    probe = {**probe, "audio": {
                        slot: dict(stream, codec="eac3", channels=8)
                        for slot, stream in probe["audio"].items()
                    }}
                return probe

            out = root / "out.mkv"
            seen = []
            with patch(
                "apps.channels.dvr_remux._probe_section",
                side_effect=fake_probe,
            ), patch(
                "apps.channels.dvr_remux._run_ffmpeg_fed_with_budget",
                side_effect=_tracking_fed(seen),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-eac3-71", 4242,
                )
            self.assertTrue(ok)
            self.assertFalse(via_mp4)
            section_cmds = [cmd for cmd in seen if "-c:v" in cmd]
            self.assertEqual(len(section_cmds), 2)
            for cmd in section_cmds:
                self.assertEqual(cmd[cmd.index("-c:a:0") + 1], "aac")
                self.assertEqual(cmd[cmd.index("-ac:a:0") + 1], "8")
                self.assertNotIn("eac3", cmd)
            info = _probe_format(out)
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
            self.assertEqual(audio["codec_name"], "aac")
            self.assertEqual(int(audio["channels"]), 8)
            _assert_audible_windows(self, out)
            _assert_clean_decode(self, out)

    def test_filesystem_error_during_repair_keeps_sources_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "oserror"
            pl = _build_playlist(root, [
                (4, "aac", 2, 48000),
                (4, "aac", 6, 48000),
            ])
            out = root / "out.mkv"
            before = _source_fingerprint(root)
            with patch(
                "apps.channels.dvr_remux._remux_section",
                side_effect=OSError(28, "No space left on device"),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-enospc", 4242,
                )
            self.assertFalse(ok)
            self.assertFalse(via_mp4)
            self.assertFalse(out.exists())
            self.assertEqual(_source_fingerprint(root), before)
            self.assertEqual(_leftover_temps(root), [])

    def test_non_adts_failure_does_not_start_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "nonadts"
            pl = _build_playlist(root, [(4, "aac", 2, 48000)])
            out = root / "out.mkv"
            steps = []

            def fake_budget(cmd, log_label, step_label, deadline):
                steps.append(step_label)
                result = MagicMock()
                result.returncode = 1
                result.stderr = "Something else went wrong\n"
                return result

            with patch(
                "apps.channels.dvr_remux._run_ffmpeg_with_budget",
                side_effect=fake_budget,
            ), patch(
                "apps.channels.dvr_remux._section_repair",
                side_effect=AssertionError("repair must not run"),
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-nonadts", 4242,
                )
            self.assertFalse(ok)
            self.assertFalse(via_mp4)
            self.assertTrue(any("MP4" in s for s in steps))
            self.assertFalse(any("section" in s for s in steps))

    def test_exhausted_deadline_cleans_temps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "deadline"
            pl = _build_playlist(root, [
                (4, "aac", 2, 48000),
                (4, "aac", 6, 48000),
            ])
            out = root / "out.mkv"
            with patch(
                "apps.channels.dvr_remux._run_ffmpeg_with_budget",
                return_value=None,
            ), patch(
                "apps.channels.dvr_remux._run_ffmpeg_fed_with_budget",
                side_effect=lambda cmd, chunks, *a: chunks.close(),
            ):
                ok, _ = remux_hls_to_mkv(str(pl), str(out), "test-deadline", 4242)
            self.assertFalse(ok)
            self.assertFalse(out.exists())
            self.assertEqual(_leftover_temps(root), [])

    def test_mp4_fallback_has_no_blanket_bsf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mp4bsf"
            # AC-3-only single region: copy to MKV usually works, so force
            # copy failure then observe the MP4 command.
            pl = _build_playlist(root, [(4, "ac3", 2, 48000)])
            out = root / "out.mkv"
            seen = []

            def fake_budget(cmd, log_label, step_label, deadline):
                seen.append(list(cmd))
                result = MagicMock()
                result.stderr = "generic remux failure\n"
                # Fail the first (MKV copy) attempt; succeed MP4 then MKV.
                if len(seen) == 1:
                    result.returncode = 1
                    return result
                dest = cmd[-1]
                open(dest, "wb").write(b"\x00" * 64)
                result.returncode = 0
                return result

            with patch(
                "apps.channels.dvr_remux._run_ffmpeg_with_budget",
                side_effect=fake_budget,
            ):
                ok, via_mp4 = remux_hls_to_mkv(
                    str(pl), str(out), "test-mp4bsf", 4242,
                )
            self.assertTrue(ok)
            self.assertTrue(via_mp4)
            for cmd in seen:
                self.assertNotIn("aac_adtstoasc", cmd)
