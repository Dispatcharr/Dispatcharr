export const getStatRows = (stats) => {
  return [
    ['Video Codec', stats.video_codec],
    [
      'Resolution',
      stats.resolution ||
        (stats.width && stats.height ? `${stats.width}x${stats.height}` : null),
    ],
    ['FPS', stats.source_fps],
    ['Video Bitrate', stats.video_bitrate && `${stats.video_bitrate} kb/s`],
    ['Audio Codec', stats.audio_codec],
    ['Audio Channels', stats.audio_channels],
    ['Sample Rate', stats.sample_rate && `${stats.sample_rate} Hz`],
    ['Audio Bitrate', stats.audio_bitrate && `${stats.audio_bitrate} kb/s`],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');
};

export const getRating = (customProps, program) => {
  return (
    customProps.rating ||
    customProps.rating_value ||
    (program && program.custom_properties && program.custom_properties.rating)
  );
};

const filterByUpcoming = (arr, tvid, titleKey, toUserTime, userNow) => {
  return arr.filter((r) => {
    const cp = r.custom_properties || {};
    const pr = cp.program || {};

    if ((pr.tvg_id || '') !== tvid) return false;
    if ((pr.title || '').toLowerCase() !== titleKey) return false;
    const st = toUserTime(r.start_time);
    return st.isAfter(userNow());
  });
}

const dedupeByProgram = (filtered) => {
  // Deduplicate by program.id if present, else by time+title
  const seen = new Set();
  const deduped = [];

  for (const r of filtered) {
    const cp = r.custom_properties || {};
    const pr = cp.program || {};
    // Prefer season/episode or onscreen code; else fall back to sub_title; else program id/slot
    const season = cp.season ?? pr?.custom_properties?.season;
    const episode = cp.episode ?? pr?.custom_properties?.episode;
    const onscreen =
      cp.onscreen_episode ?? pr?.custom_properties?.onscreen_episode;

    let key = null;
    if (season != null && episode != null) key = `se:${season}:${episode}`;
    else if (onscreen) key = `onscreen:${String(onscreen).toLowerCase()}`;
    else if (pr.sub_title) key = `sub:${(pr.sub_title || '').toLowerCase()}`;
    else if (pr.id != null) key = `id:${pr.id}`;
    else
      key = `slot:${r.channel}|${r.start_time}|${r.end_time}|${pr.title || ''}`;

    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(r);
  }
  return deduped;
}

export const getUpcomingEpisodes = (
  isSeriesGroup,
  allRecordings,
  program,
  toUserTime,
  userNow
) => {
  if (!isSeriesGroup) return [];

  const arr = Array.isArray(allRecordings)
    ? allRecordings
    : Object.values(allRecordings || {});
  const tvid = program.tvg_id || '';
  const titleKey = (program.title || '').toLowerCase();

  const filtered = filterByUpcoming(arr, tvid, titleKey, toUserTime, userNow);

  return dedupeByProgram(filtered).sort(
    (a, b) => toUserTime(a.start_time) - toUserTime(b.start_time)
  );
};
