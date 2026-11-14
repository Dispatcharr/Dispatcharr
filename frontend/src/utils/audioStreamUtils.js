// Pure formatting helpers for the per-track `audio_streams` list reported by
// the live proxy. Kept free of API/store imports so cards and tables can share
// them without pulling in the app's data layer.

const upper = (value) => String(value).toUpperCase();
const hasValue = (value) => value != null && value !== '';

/** FFmpeg stream selector: 0:N from Stream #0:N, or i:PID from a VLC TS pid. */
export const formatAudioStreamSelector = (track) => {
  if (!track || typeof track !== 'object') return '';
  if (typeof track.index === 'number') return `0:${track.index}`;
  if (typeof track.pid === 'number') return `i:${track.pid}`;
  return '';
};

/** Labeled fields for one track, in display order. */
export const getAudioTrackFields = (track, { omitLanguage = false } = {}) => {
  if (!track || typeof track !== 'object') return [];
  const fields = [];
  if (!omitLanguage && track.audio_language) {
    fields.push({
      key: 'language',
      label: 'Language',
      value: upper(track.audio_language),
    });
  }
  if (track.audio_channels) {
    fields.push({
      key: 'channels',
      label: 'Channels',
      value: String(track.audio_channels),
    });
  }
  if (track.audio_codec) {
    fields.push({
      key: 'codec',
      label: 'Codec',
      value: upper(track.audio_codec),
    });
  }
  if (hasValue(track.audio_bitrate)) {
    fields.push({
      key: 'bitrate',
      label: 'Bitrate',
      value: `${track.audio_bitrate} kbps`,
    });
  }
  if (hasValue(track.sample_rate)) {
    fields.push({
      key: 'sample_rate',
      label: 'Sample Rate',
      value: `${track.sample_rate} Hz`,
    });
  }
  const streamSelector = formatAudioStreamSelector(track);
  if (streamSelector) {
    fields.push({
      key: 'stream',
      label: 'Stream',
      value: streamSelector,
    });
  }
  return fields;
};

/** Group tracks by language, keeping first-seen order. */
export const groupAudioStreamsByLanguage = (streams) => {
  if (!Array.isArray(streams) || streams.length === 0) return [];

  const groups = [];
  const indexByLanguage = new Map();

  streams.forEach((track) => {
    const language = track?.audio_language
      ? upper(track.audio_language)
      : 'No language';
    if (indexByLanguage.has(language)) {
      groups[indexByLanguage.get(language)].tracks.push(track);
      return;
    }
    indexByLanguage.set(language, groups.length);
    groups.push({ language, tracks: [track] });
  });

  return groups;
};

/** Compact track summary for tooltips: "5.1 AC3 384 kbps". */
export const formatAudioTrackCompact = (track) => {
  if (!track || typeof track !== 'object') return '';
  const parts = [];
  if (track.audio_channels) parts.push(String(track.audio_channels));
  if (track.audio_codec) parts.push(upper(track.audio_codec));
  if (hasValue(track.audio_bitrate)) parts.push(`${track.audio_bitrate} kbps`);
  return parts.join(' ');
};

/** Summary badge text: "ENG 5.1 AC3 +3" (+N is the number of other tracks). */
export const formatBestAudioBadge = (stats) => {
  if (!stats) return '';
  const parts = [];
  if (stats.audio_language) parts.push(upper(stats.audio_language));
  if (stats.audio_channels) parts.push(String(stats.audio_channels));
  if (stats.audio_codec) parts.push(upper(stats.audio_codec));
  const extra = Array.isArray(stats.audio_streams)
    ? stats.audio_streams.length - 1
    : 0;
  if (extra > 0) parts.push(`+${extra}`);
  return parts.join(' ');
};

/** One compact line per language: "ENG: 5.1 AC3 384 kbps, stereo AAC 96 kbps". */
export const formatAudioStreamsTooltip = (streams) =>
  groupAudioStreamsByLanguage(streams)
    .map(({ language, tracks }) => {
      const summaries = tracks.map(formatAudioTrackCompact).filter(Boolean);
      return summaries.length > 0
        ? `${language}: ${summaries.join(', ')}`
        : language;
    })
    .join('\n');
