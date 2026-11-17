"""Tests for the MPEG-TS inspection DVR remux relies on."""
import json
import struct
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

import unittest

from apps.channels.dvr_ts import (
    PmtEntry,
    Shape,
    TS_PACKET_SIZE,
    UNKNOWN_CODEC,
    audio_entries,
    build_pmt_payload,
    entry_codec,
    entry_kind,
    iter_relabeled,
    label_matches,
    parse_pmt,
    relabeled_entry,
    scan_segment,
    sniff_audio,
    video_entries,
)
from apps.channels.tests.test_dvr_remux_recovery import (
    _capture_joined_clips,
    _ff,
    _freeze_pmt,
    _have_ffmpeg,
    _make_tracks_part,
    _shift_pes_clock,
    _stall_audio_pts,
)
from apps.proxy.live_proxy.tests.test_ts_pmt_watcher import (
    AAC,
    AUDIO_PID,
    H264,
    PMT_PID,
    VIDEO_PID,
    make_filler,
    make_packet,
    make_pat,
    make_pmt,
    pmt_section,
    split_pmt,
    wide_streams,
)


def _mpeg_crc(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def _elementary_stream(root, codec, channels, rate, fmt):
    path = Path(root) / f"{codec}_{channels}_{rate}.{fmt}"
    # A PES payload starts at the first frame, so leave out the MP3 ID3 tag.
    tag = ["-id3v2_version", "0", "-write_xing", "0"] if fmt == "mp3" else []
    result = _ff([
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={rate}",
        "-t", "1", "-ac", str(channels), "-ar", str(rate),
        "-c:a", codec, "-f", fmt, *tag, str(path),
    ])
    if result.returncode != 0:
        raise AssertionError(f"{codec} fixture failed: {result.stderr[-300:]}")
    return path.read_bytes()


def _mpegts(root, codec, channels, name=None):
    path = Path(root) / (name or f"{codec}_{channels}.ts")
    result = _ff([
        "-f", "lavfi", "-i", "testsrc2=rate=25:size=64x64",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
        "-c:a", codec, "-ac", str(channels), "-f", "mpegts", str(path),
    ])
    if result.returncode != 0:
        raise AssertionError(f"{codec} ts fixture failed: {result.stderr[-300:]}")
    return path


def _probe_audio(path_or_bytes):
    """ffprobe audio streams of a file path, or of MPEG-TS bytes on stdin."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,channels,sample_rate", "-of", "json",
    ]
    if isinstance(path_or_bytes, (bytes, bytearray)):
        result = subprocess.run(
            cmd + ["-f", "mpegts", "-i", "pipe:0"],
            input=bytes(path_or_bytes), capture_output=True, timeout=60,
        )
    else:
        result = subprocess.run(cmd + [str(path_or_bytes)], capture_output=True, timeout=60)
    streams = json.loads(result.stdout or b"{}").get("streams") or []
    return [s for s in streams if s["codec_type"] == "audio"]


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
class SniffAudioTests(SimpleTestCase):
    def test_frames_from_ffmpeg_are_identified(self):
        cases = [
            ("aac", 1, 48000, "adts", Shape("aac", 1, 48000)),
            ("aac", 2, 44100, "adts", Shape("aac", 2, 44100)),
            ("aac", 6, 48000, "adts", Shape("aac", 6, 48000)),
            ("ac3", 1, 48000, "ac3", Shape("ac3", 1, 48000)),
            ("ac3", 2, 44100, "ac3", Shape("ac3", 2, 44100)),
            ("ac3", 6, 48000, "ac3", Shape("ac3", 6, 48000)),
            ("eac3", 2, 48000, "eac3", Shape("eac3", 2, 48000)),
            ("eac3", 6, 48000, "eac3", Shape("eac3", 6, 48000)),
            ("mp2", 2, 48000, "mp2", Shape("mp2", 2, 48000)),
            ("mp2", 2, 24000, "mp2", Shape("mp2", 2, 24000)),
            ("libmp3lame", 2, 44100, "mp3", Shape("mp3", 2, 44100)),
            ("libmp3lame", 1, 48000, "mp3", Shape("mp3", 1, 48000)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for codec, channels, rate, fmt, expected in cases:
                data = _elementary_stream(tmp, codec, channels, rate, fmt)
                self.assertEqual(sniff_audio(data[:64]), expected, (codec, channels, rate))

    def test_adts_channel_configurations_map_to_channel_counts(self):
        # FFmpeg will not mux 7.1 into ADTS, but the header format carries it.
        for config, channels in ((1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 8), (0, 0)):
            header = bytes([
                0xFF, 0xF1,
                0x40 | (3 << 2) | (config >> 2),
                ((config & 0x03) << 6) | 0x01,
                0x00, 0x1F, 0xFC, 0x00,
            ])
            self.assertEqual(sniff_audio(header), Shape("aac", channels, 48000), config)

    def test_other_bytes_are_not_audio(self):
        self.assertIsNone(sniff_audio(b""))
        self.assertIsNone(sniff_audio(b"\x00" * 64))
        self.assertIsNone(sniff_audio(b"\x47\x40\x00\x10" * 16))
        # An ADTS sync word with a reserved sampling-frequency index.
        self.assertIsNone(sniff_audio(bytes([0xFF, 0xF1, 0x3C, 0x80]) + b"\x00" * 8))
        # Layer I and reserved MPEG audio headers are not used by DVR sources.
        self.assertIsNone(sniff_audio(bytes([0xFF, 0xFE, 0x90, 0x00]) + b"\x00" * 8))
        self.assertIsNone(sniff_audio(bytes([0xFF, 0xE8, 0x90, 0x00]) + b"\x00" * 8))


class SplitProgramMapTests(SimpleTestCase):
    def test_a_program_map_split_across_packets_is_read_whole(self):
        packets = split_pmt(wide_streams(AAC))
        self.assertGreater(len(packets), 1)
        # The first packet of the section is not a program on its own.
        self.assertIsNone(parse_pmt(make_pat() + packets[0]))
        pmt = parse_pmt(make_pat() + b"".join(packets))
        self.assertIsNotNone(pmt)
        self.assertEqual(pmt.pmt_pid, PMT_PID)
        self.assertEqual(pmt.program, 1)
        self.assertEqual(pmt.version, 0)
        self.assertEqual(pmt.pcr_pid, 0x100)
        self.assertEqual(
            [(entry.stream_type, entry.pid) for entry in pmt.entries],
            [(H264, VIDEO_PID), (AAC, AUDIO_PID)]
            + [(AAC, 0x200 + index) for index in range(32)],
        )
        self.assertTrue(all(entry.descriptors == b"" for entry in pmt.entries))


def _pid_of(packet):
    return ((packet[1] & 0x1F) << 8) | packet[2]


def _relabel_bytes(data, pmt_pid, payload, chunk_packets):
    """``iter_relabeled`` over ``data`` written to a file, joined."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "stream.ts"
        path.write_bytes(data)
        return b"".join(
            iter_relabeled([str(path)], pmt_pid, payload, chunk_packets=chunk_packets)
        )


class RelabelPacketTests(SimpleTestCase):
    """The program map rewrite, on hand-built streams (no FFmpeg needed)."""

    def test_leftover_continuation_packets_become_null_packets(self):
        packets = split_pmt(wide_streams(AAC))
        self.assertGreater(len(packets), 1)
        original = make_pat() + b"".join(packets)
        pmt = parse_pmt(original)
        # One video stream: the rewritten map fits in a single packet. Two
        # packets per chunk puts the continuation in the chunk after its start.
        payload = build_pmt_payload(pmt, list(video_entries(pmt)))
        relabeled = _relabel_bytes(original, pmt.pmt_pid, payload, chunk_packets=2)

        self.assertEqual(len(relabeled), len(original))
        on_pmt_pid = [
            offset for offset in range(0, len(relabeled), TS_PACKET_SIZE)
            if _pid_of(relabeled[offset:offset + TS_PACKET_SIZE]) == PMT_PID
        ]
        self.assertEqual(len(on_pmt_pid), 1)
        for offset in range(0, len(original), TS_PACKET_SIZE):
            if offset in on_pmt_pid:
                continue
            was = _pid_of(original[offset:offset + TS_PACKET_SIZE])
            now = _pid_of(relabeled[offset:offset + TS_PACKET_SIZE])
            # A former PMT continuation is now null; every other packet is as it was.
            self.assertEqual(now, 0x1FFF if was == PMT_PID else was)
        self.assertEqual(parse_pmt(relabeled).entries, tuple(video_entries(pmt)))

    def test_a_program_map_packet_with_an_adaptation_field_becomes_payload_only(self):
        section = pmt_section([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        # Header with adaptation field and payload (0x30), counter 5, then a
        # one byte adaptation field, then pointer_field and the section.
        packet = bytes([0x47, 0x40 | (PMT_PID >> 8), PMT_PID & 0xFF, 0x35, 1, 0x00, 0x00])
        packet += section
        packet += b"\xff" * (TS_PACKET_SIZE - len(packet))
        original = make_pat() + packet
        pmt = parse_pmt(original)
        self.assertEqual(len(pmt.entries), 2)
        payload = build_pmt_payload(pmt, list(video_entries(pmt)))
        relabeled = _relabel_bytes(original, pmt.pmt_pid, payload, chunk_packets=7)

        rewritten = relabeled[TS_PACKET_SIZE:2 * TS_PACKET_SIZE]
        self.assertEqual(rewritten[3] & 0x30, 0x10)  # payload only
        self.assertEqual(rewritten[3] & 0x0F, 5)  # continuity counter kept
        self.assertEqual(rewritten[4:], payload)
        self.assertEqual(parse_pmt(relabeled).entries, tuple(video_entries(pmt)))

    def test_media_and_a_partial_tail_pass_through_untouched(self):
        pmt_packet = make_pmt([(H264, VIDEO_PID), (AAC, AUDIO_PID)])
        # A media payload that looks like a program map header must not be
        # mistaken for one: only each packet's own header counts.
        lookalike = make_packet(VIDEO_PID, bytes([0x47, 0x50, 0x00, 0x10]) * 40)
        media = [make_filler(AUDIO_PID), lookalike, make_filler(VIDEO_PID)] * 3
        tail = b"\x47" + b"\x01" * 49
        original = make_pat() + pmt_packet + b"".join(media) + tail
        pmt = parse_pmt(original)
        payload = build_pmt_payload(pmt, list(video_entries(pmt)))
        relabeled = _relabel_bytes(original, pmt.pmt_pid, payload, chunk_packets=4)

        self.assertEqual(len(relabeled), len(original))
        self.assertNotEqual(relabeled[TS_PACKET_SIZE:2 * TS_PACKET_SIZE], pmt_packet)
        self.assertEqual(relabeled[:TS_PACKET_SIZE], original[:TS_PACKET_SIZE])
        self.assertEqual(relabeled[2 * TS_PACKET_SIZE:], original[2 * TS_PACKET_SIZE:])


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
class ProgramMapTests(SimpleTestCase):
    def test_ffmpeg_program_maps_are_read(self):
        expected = {
            "aac": (0x0F, "aac"),
            "ac3": (0x81, "ac3"),
            "eac3": (0x87, "eac3"),
            "mp2": (0x03, "mpeg"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for codec, (stream_type, claimed) in expected.items():
                pmt = parse_pmt(_mpegts(tmp, codec, 2).read_bytes())
                self.assertIsNotNone(pmt, codec)
                video = video_entries(pmt)
                audio = audio_entries(pmt)
                self.assertEqual([e.stream_type for e in video], [0x1B])
                self.assertEqual([e.stream_type for e in audio], [stream_type])
                self.assertEqual(entry_codec(audio[0]), claimed)
                self.assertEqual(entry_kind(video[0]), "video")
                self.assertEqual(pmt.pcr_pid, video[0].pid)

    def test_unreadable_or_foreign_data_has_no_program_map(self):
        self.assertIsNone(parse_pmt(b""))
        self.assertIsNone(parse_pmt(b"\x00" * 188 * 10))
        with tempfile.TemporaryDirectory() as tmp:
            data = _mpegts(tmp, "aac", 2).read_bytes()
        # Lose sync before any PAT can be found.
        self.assertIsNone(parse_pmt(b"\x00" + data))

    def test_labels_are_compared_with_what_the_frames_are(self):
        ac3 = PmtEntry(0x81, 0x101, b"\x05\x04AC-3")
        aac = PmtEntry(0x0F, 0x102, b"")
        mpeg = PmtEntry(0x03, 0x103, b"")
        other = PmtEntry(0x82, 0x104, b"")
        self.assertTrue(label_matches(ac3, Shape("ac3", 6, 48000)))
        self.assertFalse(label_matches(ac3, Shape("aac", 2, 48000)))
        self.assertTrue(label_matches(aac, Shape("aac", 2, 24000)))
        self.assertTrue(label_matches(mpeg, Shape("mp2", 2, 48000)))
        self.assertTrue(label_matches(mpeg, Shape("mp3", 2, 44100)))
        self.assertFalse(label_matches(mpeg, Shape("aac", 2, 48000)))
        # Neither an unnamed codec nor an unrecognized payload can be wrong.
        self.assertTrue(label_matches(other, Shape("aac", 2, 48000)))
        self.assertTrue(label_matches(ac3, Shape(UNKNOWN_CODEC, 0, 0)))
        self.assertTrue(label_matches(ac3, None))

    def test_private_pes_audio_is_recognized_from_its_descriptor(self):
        dvb_ac3 = PmtEntry(0x06, 0x201, b"\x6a\x01\x00")
        dvb_eac3 = PmtEntry(0x06, 0x202, b"\x7a\x01\x00")
        subtitle = PmtEntry(0x06, 0x203, b"\x59\x08eng\x10\x00\x01\x00\x01")
        self.assertEqual(entry_kind(dvb_ac3), "audio")
        self.assertEqual(entry_codec(dvb_ac3), "ac3")
        self.assertEqual(entry_kind(dvb_eac3), "audio")
        self.assertEqual(entry_codec(dvb_eac3), "eac3")
        self.assertIsNone(entry_kind(subtitle))

    def test_relabeling_keeps_the_language_and_drops_the_old_codec(self):
        lying = PmtEntry(0x81, 0x101, b"\x05\x04AC-3" + b"\x0a\x04eng\x00")
        fixed = relabeled_entry(lying, Shape("aac", 2, 48000))
        self.assertEqual(fixed.stream_type, 0x0F)
        self.assertEqual(fixed.pid, 0x101)
        self.assertEqual(fixed.descriptors, b"\x0a\x04eng\x00")
        # An honest label, and a payload it cannot judge, pass through.
        self.assertIs(relabeled_entry(lying, Shape("ac3", 6, 48000)), lying)
        self.assertIs(relabeled_entry(lying, Shape(UNKNOWN_CODEC, 0, 0)), lying)
        self.assertIs(relabeled_entry(lying, None), lying)
        ac3 = relabeled_entry(PmtEntry(0x0F, 0x102, b""), Shape("ac3", 6, 48000))
        self.assertEqual((ac3.stream_type, ac3.descriptors), (0x81, b"\x05\x04AC-3"))

    def test_rebuilt_program_map_is_a_valid_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _mpegts(tmp, "ac3", 6).read_bytes()
        pmt = parse_pmt(data)
        entries = list(video_entries(pmt)) + [
            PmtEntry(0x0F, 0x101, b"\x0a\x04spa\x00"),
            PmtEntry(0x81, 0x105, b"\x05\x04AC-3"),
        ]
        payload = build_pmt_payload(pmt, entries)
        self.assertEqual(len(payload), 184)
        section = payload[1:1 + 3 + (((payload[2] & 0x0F) << 8) | payload[3])]
        # A section followed by its CRC always checks to zero.
        self.assertEqual(_mpeg_crc(section), 0)
        # And it reads back as what was asked for.
        buf = bytearray(data)
        for i in range(0, len(buf) - 187, 188):
            pid = ((buf[i + 1] & 0x1F) << 8) | buf[i + 2]
            if pid == pmt.pmt_pid and buf[i + 1] & 0x40:
                buf[i + 4:i + 188] = payload
        again = parse_pmt(bytes(buf))
        self.assertEqual(again.entries, tuple(entries))
        self.assertEqual(again.program, pmt.program)

    def test_pcr_falls_back_to_video_when_its_stream_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _mpegts(tmp, "aac", 2).read_bytes()
        pmt = parse_pmt(data)._replace(pcr_pid=0x101)
        payload = build_pmt_payload(pmt, list(video_entries(pmt)))
        section = payload[1:1 + 3 + (((payload[2] & 0x0F) << 8) | payload[3])]
        self.assertEqual(((section[8] & 0x1F) << 8) | section[9], video_entries(pmt)[0].pid)

    def test_too_many_streams_for_one_packet_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _mpegts(tmp, "aac", 2).read_bytes()
        pmt = parse_pmt(data)
        entries = [PmtEntry(0x0F, 0x100 + n, b"\x0a\x04eng\x00") for n in range(30)]
        with self.assertRaises(ValueError):
            build_pmt_payload(pmt, entries)


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
class RelabelTests(SimpleTestCase):
    def test_only_program_map_packets_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _mpegts(tmp, "aac", 2)
            original = path.read_bytes()
            pmt = parse_pmt(original)
            payload = build_pmt_payload(pmt, list(video_entries(pmt)))
            relabeled = b"".join(iter_relabeled([str(path)], pmt.pmt_pid, payload, chunk_packets=7))
        self.assertEqual(len(relabeled), len(original))
        changed = [
            i for i in range(0, len(original), 188)
            if relabeled[i:i + 188] != original[i:i + 188]
        ]
        self.assertTrue(changed)
        for i in changed:
            self.assertEqual(((original[i + 1] & 0x1F) << 8) | original[i + 2], pmt.pmt_pid)
            # Headers, including the continuity counter, are untouched.
            self.assertEqual(relabeled[i:i + 4], original[i:i + 4])

    def test_frames_under_a_wrong_label_decode_once_relabeled(self):
        with tempfile.TemporaryDirectory() as tmp:
            honest_ac3 = _mpegts(tmp, "ac3", 6, "ac3.ts")
            aac = _mpegts(tmp, "aac", 2, "aac.ts")
            _freeze_pmt([aac], honest_ac3)
            self.assertEqual(_probe_audio(aac)[0]["codec_name"], "ac3")
            self.assertNotEqual(int(_probe_audio(aac)[0].get("channels") or 0), 2)
            scan = scan_segment(str(aac))
            entry = audio_entries(scan.pmt)[0]
            shape = scan.tail[entry.pid]
            self.assertEqual(shape, Shape("aac", 2, 48000))
            entries = list(video_entries(scan.pmt)) + [relabeled_entry(entry, shape)]
            payload = build_pmt_payload(scan.pmt, entries)
            fixed = b"".join(iter_relabeled([str(aac)], scan.pmt.pmt_pid, payload))
            audio = _probe_audio(fixed)
            self.assertEqual(
                [(s["codec_name"], int(s["channels"]), int(s["sample_rate"])) for s in audio],
                [("aac", 2, 48000)],
            )


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg/ffprobe not available")
class ScanSegmentTests(SimpleTestCase):
    def test_a_clean_segment_reads_the_same_at_both_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = scan_segment(str(_mpegts(tmp, "ac3", 6)))
        pid = audio_entries(scan.pmt)[0].pid
        self.assertEqual(scan.head, {pid: Shape("ac3", 6, 48000)})
        self.assertEqual(scan.tail, scan.head)
        self.assertEqual(scan.skewed, frozenset())

    def test_a_large_segment_is_read_from_both_ends_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _mpegts(tmp, "ac3", 6)
            size = path.stat().st_size
            # A window well under half the file forces the two-window path.
            scan = scan_segment(str(path), window=188 * 40)
            self.assertGreater(size, 2 * 188 * 40)
        pid = audio_entries(scan.pmt)[0].pid
        self.assertEqual(scan.head[pid], Shape("ac3", 6, 48000))
        self.assertEqual(scan.tail[pid], Shape("ac3", 6, 48000))

    def test_a_splice_inside_a_segment_shows_at_its_two_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            pl = _capture_joined_clips(Path(tmp) / "swap", [("ac3", 6, 10), ("aac", 2, 10)])
            scans = [
                scan_segment(str(p)) for p in sorted(pl.parent.glob("seg_*.ts"))
            ]
        mixed = [s for s in scans if s.head != s.tail]
        self.assertEqual(len(mixed), 1)
        pid = next(iter(mixed[0].head))
        self.assertEqual(mixed[0].head[pid].codec, "ac3")
        self.assertEqual(mixed[0].tail[pid].codec, "aac")
        # Every segment carries the first clip's label.
        self.assertEqual(len({s.pmt.entries for s in scans}), 1)

    def test_a_track_with_no_frames_reads_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _make_tracks_part(root, 0, 8, [("aac", 2)])
            lone = root / entries[0][1]
            template = root / "two.ts"
            two = _ff([
                "-f", "lavfi", "-i", "testsrc2=rate=25:size=64x64",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
                "-t", "2", "-map", "0:v", "-map", "1:a", "-map", "2:a",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a:0", "aac", "-c:a:1", "ac3", "-f", "mpegts", str(template),
            ])
            self.assertEqual(two.returncode, 0, two.stderr[-300:])
            _freeze_pmt([lone], template)
            scan = scan_segment(str(lone))
        first, second = (e.pid for e in audio_entries(scan.pmt))
        self.assertEqual(scan.head[first], Shape("aac", 2, 48000))
        self.assertIsNone(scan.head[second])
        self.assertIsNone(scan.tail[second])

    def test_audio_whose_clock_crawls_is_skewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _make_tracks_part(root, 0, 8, [("ac3", 2)])
            segments = [root / uri for _extinf, uri in entries]
            before = scan_segment(str(segments[0]))
            _stall_audio_pts(segments[0], 0x101)
            after = scan_segment(str(segments[0]))
            other = scan_segment(str(segments[1]))
        self.assertEqual(before.skewed, frozenset())
        self.assertEqual(after.skewed, frozenset({0x101}))
        self.assertEqual(other.skewed, frozenset())

    def test_audio_that_jumps_in_steps_is_skewed_even_when_a_window_straddles_a_jump(self):
        # A crawling clock that jumps now and then still has most steps at 1 tick.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _make_tracks_part(root, 0, 4, [("ac3", 2)])
            segment = root / entries[0][1]
            _stall_audio_pts(segment, 0x101)
            data = bytearray(segment.read_bytes())
            seen = 0
            for i in range(0, len(data) - 187, 188):
                if (((data[i + 1] & 0x1F) << 8) | data[i + 2]) == 0x101 and data[i + 1] & 0x40:
                    seen += 1
                    if seen % 9 == 0:
                        off = i + 4 + (1 + data[i + 4] if (data[i + 3] >> 4) & 3 == 3 else 0)
                        pts = 3_000_000 + seen * 1 + 27_000
                        data[off + 9] = 0x21 | (((pts >> 30) & 0x07) << 1)
                        data[off + 10] = (pts >> 22) & 0xFF
                        data[off + 11] = 0x01 | (((pts >> 15) & 0x7F) << 1)
                        data[off + 12] = (pts >> 7) & 0xFF
                        data[off + 13] = 0x01 | ((pts & 0x7F) << 1)
            segment.write_bytes(data)
            scan = scan_segment(str(segment))
        self.assertEqual(scan.skewed, frozenset({0x101}))

    def test_one_repeated_timestamp_marks_a_track_as_skewed(self):
        # A healthy track advances by a frame or more at every PES. A single PES
        # that stamps the same moment as the one before it is the capture's
        # clock misbehaving, and copying it would keep the repeat.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _make_tracks_part(root, 0, 4, [("ac3", 2)])
            segment = root / entries[0][1]
            self.assertEqual(scan_segment(str(segment)).skewed, frozenset())
            data = bytearray(segment.read_bytes())
            stamps = []
            for i in range(0, len(data) - 187, 188):
                if (((data[i + 1] & 0x1F) << 8) | data[i + 2]) == 0x101 and data[i + 1] & 0x40:
                    off = i + 4 + (1 + data[i + 4] if (data[i + 3] >> 4) & 3 == 3 else 0)
                    stamps.append(off + 9)
            # Give the fifth PES the fourth's timestamp.
            data[stamps[4]:stamps[4] + 5] = data[stamps[3]:stamps[3] + 5]
            segment.write_bytes(data)
            scan = scan_segment(str(segment))
        self.assertEqual(scan.skewed, frozenset({0x101}))

    def test_audio_far_from_the_video_clock_is_skewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _make_tracks_part(root, 0, 8, [("ac3", 2), ("aac", 2)])
            segments = [root / uri for _extinf, uri in entries]
            self.assertEqual(scan_segment(str(segments[0])).skewed, frozenset())
            # The video and one track move to the live clock; the other track
            # keeps a clock 40 s behind, with perfectly regular steps.
            _shift_pes_clock(segments[0], (0x100, 0x101), 40.0)
            near = scan_segment(str(segments[1]))
            far = scan_segment(str(segments[0]))
            # A second off is ordinary muxing delay, not another clock.
            _shift_pes_clock(segments[1], (0x102,), 1.0)
            close = scan_segment(str(segments[1]))
        self.assertEqual(far.skewed, frozenset({0x102}))
        self.assertEqual(near.skewed, frozenset())
        self.assertEqual(close.skewed, frozenset())

    def test_files_that_are_not_capture_segments_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(scan_segment(str(root / "missing.ts")))
            junk = root / "junk.ts"
            junk.write_bytes(b"not a transport stream" * 200)
            self.assertIsNone(scan_segment(str(junk)))
            empty = root / "empty.ts"
            empty.write_bytes(b"")
            self.assertIsNone(scan_segment(str(empty)))
            video_only = _make_tracks_part(root, 0, 4, [("aac", 2)])
            good = root / video_only[0][1]
            # A segment cut off before its program map has nothing to read.
            cut = root / "cut.ts"
            cut.write_bytes(good.read_bytes()[:188 * 2])
            self.assertIsNone(scan_segment(str(cut)))
