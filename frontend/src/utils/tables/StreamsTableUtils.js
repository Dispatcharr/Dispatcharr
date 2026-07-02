import API from '../../api.js';

export const addStreamsToChannel = (channelId, existingStreams, newStreams) => {
  return API.addStreamsToChannel(channelId, existingStreams, newStreams);
};
export const queryStreamsTable = (params) => {
  return API.queryStreamsTable(params);
};
export const getStreams = (streamIds) => {
  return API.getStreams(streamIds);
};
export const createChannelsFromStreamsAsync = (
  streamIds,
  channelProfileIds,
  startingChannelNumber
) =>
  API.createChannelsFromStreamsAsync(
    streamIds,
    channelProfileIds,
    startingChannelNumber
  );
export const deleteStream = (id) => API.deleteStream(id);
export const deleteStreams = (ids) => {
  return API.deleteStreams(ids);
};
export const requeryStreams = () => {
  return API.requeryStreams();
};
export const createChannelFromStream = (values) =>
  API.createChannelFromStream(values);
export const getAllStreamIds = (params) => {
  return API.getAllStreamIds(params);
};
export const getStreamFilterOptions = (params) => {
  return API.getStreamFilterOptions(params);
};

export const getStatsTooltip = (stats) => {
  // Build compact display (resolution + video codec)
  const parts = [];
  if (stats.resolution) {
    // Convert "1920x1080" to "1080p" format
    const height = stats.resolution.split('x')[1];
    if (height) parts.push(`${height}p`);
  }
  if (stats.video_codec) {
    parts.push(stats.video_codec.toUpperCase());
  }
  const compactDisplay = parts.length > 0 ? parts.join(' ') : '-';

  // Build tooltip content with friendly labels
  const tooltipLines = [];
  if (stats.resolution) tooltipLines.push(`Resolution: ${stats.resolution}`);
  if (stats.video_codec)
    tooltipLines.push(`Video Codec: ${stats.video_codec.toUpperCase()}`);
  if (stats.video_bitrate)
    tooltipLines.push(`Video Bitrate: ${stats.video_bitrate} kbps`);
  if (stats.source_fps)
    tooltipLines.push(`Frame Rate: ${stats.source_fps} FPS`);
  if (stats.audio_codec)
    tooltipLines.push(`Audio Codec: ${stats.audio_codec.toUpperCase()}`);
  if (stats.audio_channels)
    tooltipLines.push(`Audio Channels: ${stats.audio_channels}`);
  if (stats.audio_bitrate)
    tooltipLines.push(`Audio Bitrate: ${stats.audio_bitrate} kbps`);

  const tooltipContent =
    tooltipLines.length > 0
      ? tooltipLines.join('\n')
      : 'No source info available';
  return { compactDisplay, tooltipContent };
};

export const appendFetchPageParams = (params, pagination, sorting) => {
  params.append('page', pagination.pageIndex + 1);
  params.append('page_size', pagination.pageSize);

  if (sorting.length > 0) {
    const columnId = sorting[0].id;
    const fieldMapping = {
      name: 'name',
      group: 'channel_group__name',
      m3u: 'm3u_account__name',
      tvg_id: 'tvg_id',
    };
    const sortField = fieldMapping[columnId] || columnId;
    const sortDirection = sorting[0].desc ? '-' : '';
    params.append('ordering', `${sortDirection}${sortField}`);
  }
};

export const getChannelProfileIds = (profileIds, selectedProfileId) => {
  // Convert profile selection: 'all' means all profiles (null), 'none' means no profiles ([]), specific IDs otherwise
  if (profileIds) {
    if (profileIds.includes('none')) {
      return [];
    } else if (profileIds.includes('all')) {
      return null;
    } else {
      return profileIds.map((id) => parseInt(id));
    }
  } else {
    return selectedProfileId !== '0' ? [parseInt(selectedProfileId)] : null;
  }
};

export const getChannelNumberValue = (mode, startNumber) => {
  return mode === 'provider'
    ? null
    : mode === 'auto'
      ? 0
      : mode === 'highest'
        ? -1
        : Number(startNumber);
};

export const getFilterParams = (debouncedFilters) => {
  const params = new URLSearchParams();
  Object.entries(debouncedFilters).forEach(([key, value]) => {
    if (typeof value === 'boolean') {
      if (value) params.append(key, 'true');
    } else if (value !== null && value !== undefined && value !== '') {
      params.append(key, String(value));
    }
  });
  return params;
};
