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

    if(isNaN(s) || isNaN(e)) throw new Error('Invalid date');

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

export const getTvgOptions = (tvgs) => {
  const seen = new Set();
  const options = [];
  for (const t of tvgs || []) {
    if (!t.tvg_id || seen.has(t.tvg_id)) continue;
    seen.add(t.tvg_id);
    options.push({
      value: t.tvg_id,
      label: t.name ? `${t.name} (${t.tvg_id})` : t.tvg_id,
    });
  }
  return options.sort((a, b) => a.label.localeCompare(b.label));
};

export const getChannelOptions = (allChannels, tvgsById, tvgId) => {
  const sorted = sortedChannelOptions(allChannels, numberedChannelLabel);
  const matching = [];
  const others = [];
  for (const item of sorted) {
    const channel = allChannels.find((c) => String(c.id) === item.value);
    const cTvg = channel?.epg_data_id
      ? tvgsById?.[channel.epg_data_id]?.tvg_id
      : null;
    if (tvgId && cTvg && String(cTvg) === String(tvgId)) {
      matching.push(item);
    } else {
      others.push(item);
    }
  }
  return [...matching, ...others];
};