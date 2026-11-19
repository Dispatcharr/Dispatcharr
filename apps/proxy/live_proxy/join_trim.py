"""Mid-chunk join trim: start near target media, preferring a RAP.

Stream-time join still picks a Redis chunk by end-of-chunk score. This module
refines only the first delivery: drop leading bytes before the target PTS and
prefer a video keyframe (adaptation-field RAP, else codec-aware scan). When
that keyframe lives in a prior Redis chunk (GOP crossing a chunk boundary),
optional prior chunks are walked newest-first and prepended from the RAP.
Cost is paid once per new client or output-profile/HLS writer start.
"""

from apps.proxy.ts_psi import (
    TS_PACKET_SIZE,
    packet_pusi,
    parse_pat,
    parse_pmt,
    parse_pmt_streams,
)

from .psi_scan import index_psi_headers
from .ts_clock import extract_pts, packet_random_access
from .ts_nal import (
    build_parameter_set_packets,
    extract_parameter_sets,
    inspect_avc_hevc_packet,
    packet_continuity_counter,
    packet_has_decoder_init,
    param_types_for,
    starts_keyframe,
)

# RAP / SPS lookback is a media-time window before the join target (join depth
# unchanged). High-bitrate ~1MB chunks are short, so a fixed chunk count can
# miss a 2s GOP; the span covers every chunk after the newest one known to end
# before the window.
KEYFRAME_LOOKBACK_SECONDS = 2.0
# Hard cap on prior payloads fetched once per cold join (one pipeline).
KEYFRAME_LOOKBACK_MAX_CHUNKS = 16


def _is_video_pusi(data, off, video_pid):
    """Header-only test for a video PUSI packet at ``off`` (no packet slice)."""
    return (
        data[off] == 0x47
        and data[off + 1] & 0x40
        and (((data[off + 1] & 0x1F) << 8) | data[off + 2]) == video_pid
    )


def discover_video_layout(data):
    """Return ``(video_pid, stream_type)`` from the first PAT/PMT in ``data``.

    ``(None, None)`` when the chunk carries no usable PSI. That is common:
    muxers often send PAT/PMT only with keyframes, so a chunk shorter than the
    GOP may have none. Callers can then try an older chunk. One header-plane
    index finds both PAT and PMT offsets, so the chunk is not scanned twice.
    """
    if not data:
        return None, None
    index = index_psi_headers(data)
    if index is None:
        return None, None
    pats = index.pat_offsets()
    if not pats:
        return None, None
    pmt_pid = None
    for off in pats:
        pmt_pid = parse_pat(data[off : off + TS_PACKET_SIZE])
        if pmt_pid is not None:
            break
    if pmt_pid is None:
        return None, None
    for off in index.pid_offsets(pmt_pid, require_pusi=False):
        packet = data[off : off + TS_PACKET_SIZE]
        video_pid, stream_type = parse_pmt(packet)
        if video_pid is not None:
            return video_pid, stream_type
        # One PUSI PMT with no video: stop looking.
        if packet_pusi(packet) and parse_pmt_streams(packet) is not None:
            return None, None
    return None, None


def discover_layout_in_chunks(chunks):
    """First ``(video_pid, stream_type)`` found in ``chunks`` (newest first)."""
    for data in chunks:
        layout = discover_video_layout(data)
        if layout[0] is not None:
            return layout
    return None, None


def is_keyframe_at(data, offset, video_pid, stream_type):
    """True when ``data[offset:]`` opens on a video keyframe packet."""
    if (
        not data
        or video_pid is None
        or offset is None
        or offset < 0
        or offset + TS_PACKET_SIZE > len(data)
    ):
        return False
    if not _is_video_pusi(data, offset, video_pid):
        return False
    return starts_keyframe(
        data[offset : offset + TS_PACKET_SIZE], stream_type
    )


def normalize_media_entries(pairs):
    """Normalize stored pairs to ``(offset, media, is_rap)``."""
    out = []
    for item in pairs or ():
        if len(item) >= 3:
            out.append((int(item[0]), float(item[1]), bool(item[2])))
        elif len(item) == 2:
            out.append((int(item[0]), float(item[1]), False))
    return out


def scan_chunk_media_entries(data, video_pid=None, stream_type=None):
    """Build ``(offset, pts, is_kf)`` entries by walking one chunk once.

    Used when the owner-side sparse map is unavailable (other workers). With a
    known ``video_pid``, only that elementary stream is considered for PTS and
    keyframe markers.
    """
    if not data:
        return []
    if video_pid is None and stream_type is None:
        video_pid, stream_type = discover_video_layout(data)
    n = len(data) // TS_PACKET_SIZE
    entries = []
    for i in range(n):
        off = i * TS_PACKET_SIZE
        b1 = data[off + 1]
        if data[off] != 0x47 or not (b1 & 0x40):
            continue
        if video_pid is not None and (((b1 & 0x1F) << 8) | data[off + 2]) != video_pid:
            continue
        packet = data[off : off + TS_PACKET_SIZE]
        pts = extract_pts(packet)
        if pts is None:
            continue
        # PUSI (and video PID when known) already matched; do not re-gate.
        is_kf = video_pid is not None and starts_keyframe(packet, stream_type)
        entries.append((off, float(pts), is_kf))
    return entries


def resolve_start_offset(entries, target_media):
    """Byte offset of the preferred start packet, or 0.

    Prefers the last keyframe marker at or before ``target_media``. Falls back
    to the last PTS sample at or before the target, then to 0 (start of chunk).
    """
    if not entries or target_media is None:
        return 0
    at_or_before = [e for e in entries if e[1] <= target_media]
    if not at_or_before:
        return 0
    for offset, _media, is_kf in reversed(at_or_before):
        if is_kf:
            return int(offset)
    return int(at_or_before[-1][0])


def snap_back_to_keyframe(data, offset, video_pid, stream_type):
    """Move ``offset`` back to the last video keyframe at or before it, if any.

    Walks backward and stops at the first keyframe, so the cost is the distance
    to the nearest keyframe behind ``offset`` (at most one GOP), not the whole
    chunk. Returns ``offset`` unchanged when no keyframe is found.
    """
    if not data or offset is None or video_pid is None:
        return 0 if offset is None else int(offset)
    offset = (int(offset) // TS_PACKET_SIZE) * TS_PACKET_SIZE
    if offset <= 0:
        return 0
    last_full = (len(data) // TS_PACKET_SIZE - 1) * TS_PACKET_SIZE
    if last_full < 0:
        return 0
    offset = min(offset, last_full)
    for off in range(offset, -1, -TS_PACKET_SIZE):
        if not _is_video_pusi(data, off, video_pid):
            continue
        if starts_keyframe(data[off : off + TS_PACKET_SIZE], stream_type):
            return off
    return offset


def find_last_keyframe_offset(data, video_pid, stream_type, target_media=None):
    """Last video keyframe offset in ``data``, or None.

    Walks backward from the end and stops at the first hit. When
    ``target_media`` is set, keyframes whose PTS is strictly after the target
    are skipped (undated RAP packets are kept).
    """
    if not data or video_pid is None:
        return None
    last_full = (len(data) // TS_PACKET_SIZE - 1) * TS_PACKET_SIZE
    for off in range(last_full, -1, -TS_PACKET_SIZE):
        if not _is_video_pusi(data, off, video_pid):
            continue
        packet = data[off : off + TS_PACKET_SIZE]
        if not starts_keyframe(packet, stream_type):
            continue
        if target_media is not None:
            pts = extract_pts(packet)
            if pts is not None and float(pts) > float(target_media):
                continue
        return off
    return None


def psi_prefix_from_head(head):
    """Last PAT and its PMT section (PUSI start plus continuations) from the head."""
    if not head:
        return b""
    index = index_psi_headers(head)
    if index is None:
        return b""
    pats = index.pat_offsets()
    if not pats:
        return b""
    pmt_pid = None
    for off in reversed(pats):
        pmt_pid = parse_pat(head[off : off + TS_PACKET_SIZE])
        if pmt_pid is not None:
            break
    located = index.locate(pmt_pid, pats=pats)
    if not located:
        return b""
    last_pat = None
    pmt_run = []
    for offset, is_pat in located:
        packet = head[offset : offset + TS_PACKET_SIZE]
        if is_pat:
            last_pat = packet
            pmt_run = []
        elif last_pat is not None:
            # A PUSI packet starts a new PMT section; later packets on the
            # PMT PID without PUSI are continuations of that section.
            if packet_pusi(packet):
                pmt_run = [packet]
            elif pmt_run:
                pmt_run.append(packet)
    if last_pat is None:
        return b""
    if pmt_run:
        return last_pat + b"".join(pmt_run)
    return last_pat


def parameter_sets_complete(param_sets, stream_type):
    """True when ``param_sets`` has every NAL type needed to start decoding."""
    wanted = param_types_for(stream_type)
    return bool(wanted) and bool(param_sets) and all(t in param_sets for t in wanted)


def collect_parameter_sets(data, video_pid, stream_type, end_offset=None):
    """Gather H.264/HEVC parameter-set NALs closest to ``end_offset``.

    Walks packets newest-first so a later SPS/PPS (closer to the join cut)
    wins over an older one from earlier in the same chunk.
    """
    if not data or video_pid is None or stream_type not in (0x1B, 0x24):
        return {}
    if end_offset is None:
        end_offset = len(data)
    end_offset = min(int(end_offset), len(data))
    end_offset = (end_offset // TS_PACKET_SIZE) * TS_PACKET_SIZE
    params = {}
    for off in range(end_offset - TS_PACKET_SIZE, -1, -TS_PACKET_SIZE):
        if not _is_video_pusi(data, off, video_pid):
            continue
        found = extract_parameter_sets(data[off : off + TS_PACKET_SIZE], stream_type)
        if not found:
            continue
        # First hit for each NAL type is the newest (closest to the cut).
        for ntype, nal in found.items():
            if ntype not in params:
                params[ntype] = nal
        if parameter_sets_complete(params, stream_type):
            break
    return params


def merge_parameter_sets_from_chunks(chunks, video_pid, stream_type):
    """Newest-first complete-preferring merge of parameter sets from chunk bytes."""
    params = {}
    for data in chunks:
        if not data:
            continue
        found = collect_parameter_sets(data, video_pid, stream_type)
        for ntype, nal in found.items():
            if ntype not in params:
                params[ntype] = nal
        if parameter_sets_complete(params, stream_type):
            break
    return params


def find_opening_video_packet(data, video_pid):
    """``(offset, packet)`` of the first video PUSI packet in ``data``, or ``(None, None)``."""
    if not data or video_pid is None:
        return None, None
    for off in range(0, len(data) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE):
        if _is_video_pusi(data, off, video_pid):
            return off, data[off : off + TS_PACKET_SIZE]
    return None, None


def inject_decoder_init(
    body,
    video_pid,
    stream_type,
    param_sets,
    opening_off=None,
    opening=None,
):
    """Prepend SPS/PPS (VPS) TS packets when the opening keyframe lacks them.

    Continuity counters are stamped to sit immediately before the opening
    video packet's CC, matching the HLS segmenter splice. Pass ``opening_off``
    / ``opening`` when the caller already found the first video PUSI (and
    already knows it lacks decoder init) so this path does not search again.
    """
    if (
        not body
        or video_pid is None
        or stream_type not in (0x1B, 0x24)
        or not param_sets
        or len(body) < TS_PACKET_SIZE
    ):
        return body
    if opening is None:
        # Opening keyframe is the first video PUSI packet in the body (after
        # any PAT/PMT we already prepended).
        opening_off, opening = find_opening_video_packet(body, video_pid)
        if opening is None:
            return body
        if packet_has_decoder_init(opening, stream_type):
            return body
    packets = build_parameter_set_packets(video_pid, param_sets, stream_type)
    if not packets:
        return body
    first_cc = (packet_continuity_counter(opening) - len(packets)) & 0x0F
    stamped = bytearray()
    for i, pkt in enumerate(packets):
        buf = bytearray(pkt)
        buf[3] = (buf[3] & 0xF0) | ((first_cc + i) & 0x0F)
        stamped.extend(buf)
    return body[:opening_off] + bytes(stamped) + body[opening_off:]


def trim_chunk_at_offset(
    data, offset, video_pid=None, stream_type=None, extra_param_sets=None
):
    """Return ``data[offset:]`` with PAT/PMT and decoder-init when needed.

    ``offset`` is aligned down to a packet boundary. Empty or no-op trims return
    ``data`` unchanged. Parameter sets are collected from the discarded head
    (and the opening keyframe packet), merged with ``extra_param_sets`` from
    earlier chunks, and injected only when that keyframe does not already
    carry them.
    """
    if not data or offset is None or offset <= 0:
        body = data
        head = b""
        offset = 0
    else:
        offset = (int(offset) // TS_PACKET_SIZE) * TS_PACKET_SIZE
        if offset <= 0:
            body = data
            head = b""
            offset = 0
        elif offset >= len(data):
            return data
        else:
            head = data[:offset]
            body = data[offset:]
    if not body:
        return data
    prefix = psi_prefix_from_head(head) if head else b""
    out = prefix + body if prefix else body
    if video_pid is not None and stream_type in (0x1B, 0x24):
        opening_off, opening = find_opening_video_packet(out, video_pid)
        if opening is None or packet_has_decoder_init(opening, stream_type):
            return out
        # Prefer a complete set closest to the cut. Do not mix a newer SPS from
        # the head with an older PPS from lookback (or the reverse).
        head_params = collect_parameter_sets(
            data, video_pid, stream_type, end_offset=offset + TS_PACKET_SIZE
        )
        extra = extra_param_sets or {}
        if parameter_sets_complete(head_params, stream_type):
            params = head_params
        elif parameter_sets_complete(extra, stream_type):
            params = extra
        else:
            params = dict(extra)
            params.update(head_params)
        out = inject_decoder_init(
            out,
            video_pid,
            stream_type,
            params,
            opening_off=opening_off,
            opening=opening,
        )
    return out


def resolve_join_cut(
    chunk_data,
    target_media,
    media_map=None,
    video_pid=None,
    stream_type=None,
):
    """Resolve join-chunk layout, snap offset, and whether Redis priors are needed.

    Returns a dict used by ``prepare_join_chunk`` and ``StreamBuffer`` so the
    join chunk is not scanned twice. Pass ``video_pid`` / ``stream_type`` when
    the caller already has them (for example learned from an older chunk when
    this one carries no PAT/PMT).
    """
    if not chunk_data or target_media is None:
        return None
    if video_pid is None or stream_type is None:
        video_pid, stream_type = discover_video_layout(chunk_data)
    entries = normalize_media_entries(media_map)
    if not entries:
        entries = scan_chunk_media_entries(
            chunk_data, video_pid=video_pid, stream_type=stream_type
        )
    offset = resolve_start_offset(entries, target_media)
    offset = snap_back_to_keyframe(chunk_data, offset, video_pid, stream_type)
    needs_param_sets = stream_type in (0x1B, 0x24)
    has_kf = False
    has_init = False
    if (
        video_pid is not None
        and offset + TS_PACKET_SIZE <= len(chunk_data)
        and _is_video_pusi(chunk_data, offset, video_pid)
    ):
        opening = chunk_data[offset : offset + TS_PACKET_SIZE]
        # One RAP check and at most one NAL inspect for both keyframe and
        # decoder-init (starts_keyframe + packet_has_decoder_init would
        # inspect twice on a non-RAP H.264/HEVC keyframe).
        rai = packet_random_access(opening)
        if needs_param_sets:
            nal_kf, found = inspect_avc_hevc_packet(opening, stream_type)
            has_kf = rai or bool(nal_kf)
            if has_kf:
                wanted = param_types_for(stream_type)
                has_init = bool(wanted) and all(t in found for t in wanted)
        else:
            has_kf = rai or starts_keyframe(opening, stream_type)
    return {
        "video_pid": video_pid,
        "stream_type": stream_type,
        "offset": offset,
        "has_kf": has_kf,
        "needs_prior_for_kf": not has_kf,
        "needs_prior_for_params": needs_param_sets and not has_init,
        # Without a layout nothing in an older chunk can be recognized, so a
        # fetch would be wasted.
        "skip_prior_fetch": video_pid is None
        or (has_kf and (not needs_param_sets or has_init)),
    }


def prepare_join_chunk(
    chunk_data,
    target_media,
    media_map=None,
    extra_param_sets=None,
    prior_chunks=None,
    cut=None,
):
    """Trim first-delivery bytes to ``target_media`` (video keyframe when possible).

    ``prior_chunks`` is an optional sequence of chunk bytes for older Redis
    chunks, newest first and contiguous with the join chunk (typically the ~2s
    media window before ``target_media``). When the join chunk has no keyframe
    at or before the cut, those priors are searched backward and the delivery
    becomes ``prior[kf:] + ... + join_chunk``.

    Pass ``cut`` from ``resolve_join_cut`` when the join chunk was already
    analyzed (e.g. on the buffer owner path) to avoid repeating that work.
    """
    if not chunk_data or target_media is None:
        return chunk_data
    if cut is None:
        cut = resolve_join_cut(chunk_data, target_media, media_map=media_map)
    video_pid = cut["video_pid"]
    stream_type = cut["stream_type"]
    offset = cut["offset"]

    if cut["has_kf"] or not prior_chunks:
        return trim_chunk_at_offset(
            chunk_data,
            offset,
            video_pid=video_pid,
            stream_type=stream_type,
            extra_param_sets=extra_param_sets,
        )

    # No in-chunk keyframe at the cut: walk older chunks newest-first. Chunks
    # skipped without a keyframe stay between the eventual RAP and the join
    # chunk so the timeline stays contiguous.
    following = [chunk_data]
    for prior_data in prior_chunks:
        if not prior_data:
            continue
        kf_off = find_last_keyframe_offset(
            prior_data, video_pid, stream_type, target_media=target_media
        )
        if kf_off is not None:
            return trim_chunk_at_offset(
                prior_data + b"".join(following),
                kf_off,
                video_pid=video_pid,
                stream_type=stream_type,
                extra_param_sets=extra_param_sets,
            )
        following.insert(0, prior_data)

    # No prior keyframe either: keep the single-chunk mid-GOP cut.
    return trim_chunk_at_offset(
        chunk_data,
        offset,
        video_pid=video_pid,
        stream_type=stream_type,
        extra_param_sets=extra_param_sets,
    )
