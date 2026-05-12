import API from '../../api.js';

export const getEpgSourceValue = (cp) => {
  // Show custom EPG if set
  if (cp?.custom_epg_id !== undefined && cp?.custom_epg_id !== null) {
    return cp.custom_epg_id.toString();
  }
  // Show "No EPG" if force_dummy_epg is set
  if (cp?.force_dummy_epg) {
    return '0';
  }
  // Otherwise show empty/placeholder
  return null;
};

export const getEpgSourceData = (epgSources) => {
  return [
    { value: '0', label: 'No EPG (Disabled)' },
    ...[...epgSources]
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((source) => ({
        value: source.id.toString(),
        label: `${source.name} (${
          source.source_type === 'dummy'
            ? 'Dummy'
            : source.source_type === 'xmltv'
              ? 'XMLTV'
              : source.source_type === 'schedules_direct'
                ? 'Schedules Direct'
                : source.source_type
        })`,
      })),
  ];
};

export const repackGroupChannels = (playlist, group) => {
  return API.repackGroupChannels(playlist.id, group.channel_group);
};

// Header line for the preview box. Adds a scan-cap suffix when the
// backend only scanned the first SCAN_CAP streams of the group.
export const formatPreviewSummary = (label, result) => {
  if (!result) return null;
  const { match_count, total_in_group, total_scanned, scan_limit_hit } = result;
  const matchWord = `match${match_count === 1 ? '' : 'es'}`;
  if (scan_limit_hit) {
    return `${match_count} ${matchWord} in first ${total_scanned.toLocaleString()} streams scanned (of ${total_in_group.toLocaleString()} total)`;
  }
  return `${match_count} ${label} ${matchWord} in ${total_scanned.toLocaleString()} stream${total_scanned === 1 ? '' : 's'}`;
};
