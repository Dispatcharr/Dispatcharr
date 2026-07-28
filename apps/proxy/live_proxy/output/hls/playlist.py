"""
HLS playlist rendering and segment-journal parsing.

Playlist generation stays in our code (not ffmpeg's) so the proxy controls
EXT-X-TARGETDURATION, the media sequence, and discontinuity tags, including
when the manager skips ahead in the source ring or a provider switches.
"""


def parse_segment_list_line(line):
    """
    Parse one CSV line of ffmpeg's segment list journal
    (``-segment_list pipe:1 -segment_list_type csv``):

        <filename>,<start_time>,<end_time>

    Returns ``(filename, start, end)`` with the times as floats.
    Raises ValueError on a malformed line. The filename is our own
    ``%d.ts`` pattern in a private scratch directory, so it cannot
    contain commas; rsplit keeps the parse exact regardless.
    """
    name, start, end = line.strip().rsplit(",", 2)
    if not name:
        raise ValueError("empty segment filename")
    return name, float(start), float(end)


def render_media_playlist(window, target_duration, segment_name="{seq}.ts", adv_target=None):
    """
    Render an HLS media playlist (RFC 8216, version 3) from a window of
    segment descriptors: [{"seq": int, "dur": float, "disc": bool}, ...].
    Segment URIs are relative so they resolve against the playlist URL.

    ``adv_target`` is the manager's frozen EXT-X-TARGETDURATION; when supplied it
    is emitted verbatim so the value never changes across reloads (RFC 8216
    6.2.1). Without it (legacy descriptor) the per-window ceil is used.
    """
    # Frozen live-edge offset: ~2.5 config target-durations (~10s at the 4s
    # default) so the value is a session constant and never drifts across
    # reloads as the window slides (unlike a window-max derivation).
    start_offset = 2.5 * target_duration
    if not window:
        return (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            # Ceil to match the populated branch; a fractional target must never
            # round DOWN below a real EXTINF (RFC 8216 4.3.3.1).
            f"#EXT-X-TARGETDURATION:{adv_target if adv_target else int(max(target_duration, 1) + 0.999)}\n"
            "#EXT-X-MEDIA-SEQUENCE:0\n"
        )
    total_duration = sum(entry["dur"] for entry in window)
    # TARGETDURATION: prefer the manager's frozen constant. RFC 8216 6.2.1 forbids
    # it changing across reloads; a per-render ceil(window max) flaps on GOP
    # jitter, and AVPlayer latches the first value and stops advancing on a
    # contradiction. Legacy fallback keeps the ceil.
    advertised_target = adv_target if adv_target else int(max(entry["dur"] for entry in window) + 0.999)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{advertised_target}",
        f"#EXT-X-MEDIA-SEQUENCE:{window[0]['seq']}",
    ]
    # Emit EXT-X-START only once the window is deep enough to honor the frozen
    # offset, so the tag's value is stable across reloads (RFC 8216 6.2.1). It
    # pins the join point deterministically across players; a client that sets
    # its own offset still overrides it.
    if total_duration >= start_offset:
        lines.append(f"#EXT-X-START:TIME-OFFSET=-{start_offset:.3f},PRECISE=YES")
    for entry in window:
        if entry.get("disc"):
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append(f"#EXTINF:{entry['dur']:.3f},")
        lines.append(segment_name.format(seq=entry["seq"]))
    return "\n".join(lines) + "\n"
