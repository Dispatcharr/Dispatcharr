import {
  normalizeFieldValue,
  OVERRIDABLE_FIELDS,
} from '../forms/ChannelUtils.js';
import API from '../../api.js';

// Inline edits on auto-synced channels route into the override row so
// sync cannot overwrite them. If the new value matches the provider's,
// clear that field's override instead of writing a duplicate. Manual
// channels keep direct Channel.* writes.
export const buildInlinePatch = (rowOriginal, fieldId, newValue) => {
  if (rowOriginal?.auto_created && OVERRIDABLE_FIELDS.includes(fieldId)) {
    // Normalize both sides so a stringified form value compares
    // cleanly against the typed provider value.
    const formValue = normalizeFieldValue(fieldId, newValue);
    const providerValue = normalizeFieldValue(fieldId, rowOriginal[fieldId]);
    const overrideFieldValue = formValue === providerValue ? null : formValue;
    return {
      id: rowOriginal.id,
      override: { [fieldId]: overrideFieldValue },
    };
  }
  const normalized =
    newValue === undefined || newValue === '' ? null : newValue;
  return {
    id: rowOriginal.id,
    [fieldId]: normalized,
  };
};

export const getEpgOptions = (tvgsById, epgs) => {
  const options = [{ value: 'null', label: 'Not Assigned' }];

  // Convert tvgsById to an array and sort by EPG source name, then by tvg_id
  const tvgsArray = Object.values(tvgsById).sort((a, b) => {
    const aEpgName =
      a.epg_source && epgs[a.epg_source]
        ? epgs[a.epg_source].name
        : a.epg_source || '';
    const bEpgName =
      b.epg_source && epgs[b.epg_source]
        ? epgs[b.epg_source].name
        : b.epg_source || '';
    const epgCompare = aEpgName.localeCompare(bEpgName);
    if (epgCompare !== 0) return epgCompare;
    // Secondary sort by tvg_id
    return (a.tvg_id || '').localeCompare(b.tvg_id || '');
  });

  tvgsArray.forEach((tvg) => {
    const epgSourceName =
      tvg.epg_source && epgs[tvg.epg_source]
        ? epgs[tvg.epg_source].name
        : tvg.epg_source;
    const tvgName = tvg.name;
    // Create a comprehensive label: "EPG Name | TVG-ID | TVG Name"
    let label;
    if (epgSourceName && tvg.tvg_id) {
      label = `${epgSourceName} | ${tvg.tvg_id}`;
      if (tvgName && tvgName !== tvg.tvg_id) {
        label += ` | ${tvgName}`;
      }
    } else if (tvgName) {
      label = tvgName;
    } else {
      label = `ID: ${tvg.id}`;
    }

    options.push({
      value: String(tvg.id),
      label: label,
    });
  });

  return options;
};

export const getLogoOptions = (channelLogos) => {
  const options = [
    {
      value: 'null',
      label: 'Default',
      logo: null,
    },
  ];

  // Convert channelLogos object to array and sort by name
  const logosArray = Object.values(channelLogos).sort((a, b) =>
    (a.name || '').localeCompare(b.name || '')
  );

  logosArray.forEach((logo) => {
    options.push({
      value: String(logo.id),
      label: logo.name || `Logo ${logo.id}`,
      logo: logo,
    });
  });

  return options;
};

export const m3uUrlBase = `${window.location.protocol}//${window.location.host}/output/m3u`;
export const epgUrlBase = `${window.location.protocol}//${window.location.host}/output/epg`;
export const hdhrUrlBase = `${window.location.protocol}//${window.location.host}/hdhr`;

export const reorderChannel = (channelId, insertAfterId) => {
  return API.reorderChannel(channelId, insertAfterId);
};
export const deleteChannel = (id, options = {}) => {
  return API.deleteChannel(id, options);
};
export const deleteChannels = (channelIds, options = {}) => {
  return API.deleteChannels(channelIds, options);
};
export const queryChannels = (params) => {
  return API.queryChannels(params);
};
export const getAllChannelIds = (params) => {
  return API.getAllChannelIds(params);
};
export const updateProfileChannels = (channelIds, profileId, enabled) => {
  return API.updateProfileChannels(channelIds, profileId, enabled);
};
export const updateProfileChannel = (channelId, profileId, enabled) => {
  return API.updateProfileChannel(channelId, profileId, enabled);
};
export const addChannelProfile = (values) => {
  return API.addChannelProfile(values);
};
export const deleteChannelProfile = (id) => {
  return API.deleteChannelProfile(id);
};

const getSortParam = (sorting) => {
  let sortField = sorting[0].id;
  // Map frontend column ids to backend ordering field names
  const fieldMapping = {
    channel_group: 'channel_group__name',
    epg: 'epg_data__name',
  };
  if (fieldMapping[sortField]) {
    sortField = fieldMapping[sortField];
  }
  const sortDirection = sorting[0].desc ? '-' : '';
  return { sortField, sortDirection };
};

const applyDebouncedFilters = (debouncedFilters, params) => {
  // Apply debounced filters
  Object.entries(debouncedFilters).forEach(([key, value]) => {
    if (value) {
      if (Array.isArray(value)) {
        // Convert null values to "null" string for URL parameter
        const processedValue = value
          .map((v) => (v === null ? 'null' : v))
          .join(',');
        params.append(key, processedValue);
      } else {
        params.append(key, value);
      }
    }
  });
};

// Build URLs with parameters
export const buildM3UUrl = (m3uParams, m3uUrl) => {
  const params = new URLSearchParams();
  if (!m3uParams.cachedlogos) params.append('cachedlogos', 'false');
  if (m3uParams.direct) params.append('direct', 'true');
  if (m3uParams.tvg_id_source !== 'channel_number')
    params.append('tvg_id_source', m3uParams.tvg_id_source);
  if (m3uParams.output_format)
    params.append('output_format', m3uParams.output_format);
  if (m3uParams.output_profile)
    params.append('output_profile', m3uParams.output_profile);

  const baseUrl = m3uUrl;
  return params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
};

export const buildEPGUrl = (epgParams, epgUrl) => {
  const params = new URLSearchParams();
  if (!epgParams.cachedlogos) params.append('cachedlogos', 'false');
  if (epgParams.tvg_id_source !== 'channel_number')
    params.append('tvg_id_source', epgParams.tvg_id_source);
  if (epgParams.days > 0) params.append('days', epgParams.days.toString());
  if (epgParams.prev_days > 0)
    params.append('prev_days', epgParams.prev_days.toString());

  const baseUrl = epgUrl;
  return params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
};

export const buildFetchParams = ({
  pagination,
  sorting,
  debouncedFilters,
  selectedProfileId,
  showDisabled,
  showOnlyStreamlessChannels,
  showOnlyStaleChannels,
  showOnlyOverriddenChannels,
  visibilityFilter,
  showOnlyCatchupChannels,
}) => {
  const params = new URLSearchParams();
  params.append('page', pagination.pageIndex + 1);
  params.append('page_size', pagination.pageSize);
  params.append('include_streams', 'true');

  if (selectedProfileId !== '0')
    params.append('channel_profile_id', selectedProfileId);
  if (showDisabled) params.append('show_disabled', true);
  if (showOnlyStreamlessChannels) params.append('only_streamless', true);
  if (showOnlyStaleChannels) params.append('only_stale', true);
  if (showOnlyOverriddenChannels) params.append('only_has_overrides', true);
  if (showOnlyCatchupChannels) params.append('only_catchup', true);
  if (visibilityFilter && visibilityFilter !== 'active')
    params.append('visibility_filter', visibilityFilter);
  if (sorting.length > 0) {
    const { sortField, sortDirection } = getSortParam(sorting);
    params.append('ordering', `${sortDirection}${sortField}`);
  }

  applyDebouncedFilters(debouncedFilters, params);
  return params;
};

export const buildHDHRUrl = (hdhrOutputProfileId, hdhrUrl) => {
  if (!hdhrOutputProfileId) return hdhrUrl;
  // Insert output_profile segment before the trailing slash (or at end)
  const base = hdhrUrl.replace(/\/$/, '');
  return `${base}/output_profile/${hdhrOutputProfileId}`;
};
