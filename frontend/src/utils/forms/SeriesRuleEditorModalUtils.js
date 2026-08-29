import API from '../../api.js';
import {
  numberedChannelLabel,
  sortedChannelOptions,
} from './RecordingUtils.js';

export const TITLE_MODES = [
  { label: 'Exact', value: 'exact' },
  { label: 'Contains', value: 'contains' },
  { label: 'Whole word', value: 'search' },
  { label: 'Regex', value: 'regex' },
];
export const DESCRIPTION_MODES = [
  { label: 'Contains', value: 'contains' },
  { label: 'Whole word', value: 'search' },
  { label: 'Regex', value: 'regex' },
];
export const EPISODE_MODES = [
  { label: 'All episodes', value: 'all' },
  { label: 'New only', value: 'new' },
];

export function formatRange(start, end) {
  try {
    const s = new Date(start);
    const e = new Date(end);

    if (isNaN(s) || isNaN(e)) throw new Error('Invalid date');

    const sameDay = s.toDateString() === e.toDateString();
    const dateStr = s.toLocaleDateString();
    const startStr = s.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
    const endStr = e.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
    return sameDay
      ? `${dateStr} ${startStr} - ${endStr}`
      : `${dateStr} ${startStr} -> ${e.toLocaleString()}`;
  } catch {
    return `${start} - ${end}`;
  }
}

export const previewSeriesRule = (debouncedPreviewKey, controller) => {
  return API.previewSeriesRule(debouncedPreviewKey, {
    signal: controller.signal,
  });
};

export const TVG_OPTION_SEP = '::';

export const encodeTvgOptionValue = (tvg) => {
  if (!tvg?.tvg_id) return '';
  if (tvg.epg_source == null || tvg.epg_source === '') {
    return String(tvg.tvg_id);
  }
  return `${tvg.tvg_id}${TVG_OPTION_SEP}${tvg.epg_source}`;
};

export const parseTvgOptionValue = (value) => {
  if (!value) return { tvg_id: '', epg_source_id: null };
  const idx = String(value).lastIndexOf(TVG_OPTION_SEP);
  if (idx === -1) {
    return { tvg_id: String(value), epg_source_id: null };
  }
  const tvg_id = String(value).slice(0, idx);
  const src = String(value).slice(idx + TVG_OPTION_SEP.length);
  const n = Number(src);
  if (src !== '' && Number.isInteger(n) && n > 0) {
    return { tvg_id, epg_source_id: n };
  }
  return { tvg_id: String(value), epg_source_id: null };
};

export const mappedEpgDataIdsFromChannels = (allChannels) => {
  const ids = new Set();
  for (const ch of allChannels || []) {
    if (ch.epg_data_id != null && ch.epg_data_id !== '') {
      ids.add(String(ch.epg_data_id));
    }
  }
  return ids;
};

export const tvgSelectValueFromRule = (
  rule,
  tvgs = [],
  mappedEpgDataIds = null
) => {
  if (!rule?.tvg_id) return '';
  if (rule.epg_source_id != null && rule.epg_source_id !== '') {
    return `${rule.tvg_id}${TVG_OPTION_SEP}${rule.epg_source_id}`;
  }
  // Unsourced legacy rule: bind to the only mapped copy of this tvg_id.
  // Unmapped duplicates (the .first() bug) are ignored. If two mapped
  // copies exist, leave the select empty so the user picks one.
  if (!mappedEpgDataIds || mappedEpgDataIds.size === 0) {
    return '';
  }
  const matches = (tvgs || []).filter(
    (t) =>
      String(t.tvg_id) === String(rule.tvg_id) &&
      t.epg_source != null &&
      t.epg_source !== '' &&
      mappedEpgDataIds.has(String(t.id))
  );
  if (matches.length === 1) {
    return encodeTvgOptionValue(matches[0]);
  }
  return '';
};

export const getTvgOptions = (tvgs, epgs = {}, mappedEpgDataIds = null) => {
  const options = [];
  // A Set (even empty) means "only stations a channel uses". Omit the
  // argument to list every tvg. An empty set must not fall through to the
  // unfiltered 20k-station list while the channel summary is still loading.
  const restrictMapped = mappedEpgDataIds instanceof Set;
  for (const t of tvgs || []) {
    if (!t.tvg_id) continue;
    if (restrictMapped && !mappedEpgDataIds.has(String(t.id))) continue;
    const sourceName =
      t.epg_source && epgs[t.epg_source] ? epgs[t.epg_source].name : '';
    const base = t.name ? `${t.name} (${t.tvg_id})` : t.tvg_id;
    const label = sourceName ? `${base} · ${sourceName}` : base;
    options.push({
      value: encodeTvgOptionValue(t),
      label,
    });
  }
  return options.sort((a, b) => a.label.localeCompare(b.label));
};

export const getChannelOptions = (
  allChannels,
  tvgsById,
  tvgId,
  epgSourceId = null
) => {
  const sorted = sortedChannelOptions(allChannels, numberedChannelLabel);
  const matching = [];
  const others = [];
  for (const item of sorted) {
    const channel = allChannels.find((c) => String(c.id) === item.value);
    const tvg = channel?.epg_data_id ? tvgsById?.[channel.epg_data_id] : null;
    const cTvg = tvg?.tvg_id;
    const sourceOk =
      epgSourceId == null ||
      epgSourceId === '' ||
      String(tvg?.epg_source) === String(epgSourceId);
    if (tvgId && cTvg && String(cTvg) === String(tvgId) && sourceOk) {
      matching.push(item);
    } else {
      others.push(item);
    }
  }
  if (!tvgId || matching.length === 0) return sorted;
  return [...matching, ...others];
};
