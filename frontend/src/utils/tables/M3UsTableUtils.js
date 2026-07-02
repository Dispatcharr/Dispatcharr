import API from '../../api.js';
import { format } from '../dateTimeUtils.js';
import { formatDuration } from '../dateTimeUtils.js';
import { formatSpeed } from '../networkUtils.js';

export const refreshPlaylist = (id) => API.refreshPlaylist(id);

export const getPlaylistAutoCreatedChannelsCount = (id) =>
  API.getPlaylistAutoCreatedChannelsCount(id);

export const deletePlaylist = (id) => API.deletePlaylist(id);

export const updatePlaylist = (values, playlist, isToggle = false) =>
  API.updatePlaylist({ ...values, id: playlist.id }, isToggle);

export const formatStatusText = (status) => {
  switch (status) {
    case 'idle':          return 'Idle';
    case 'fetching':      return 'Fetching';
    case 'parsing':       return 'Parsing';
    case 'error':         return 'Error';
    case 'success':       return 'Success';
    case 'pending_setup': return 'Pending Setup';
    default:
      return status
        ? status.charAt(0).toUpperCase() + status.slice(1)
        : 'Unknown';
  }
};

export const getStatusColor = (status) => {
  switch (status) {
    case 'idle':          return 'gray.5';
    case 'fetching':      return 'blue.5';
    case 'parsing':       return 'indigo.5';
    case 'error':         return 'red.5';
    case 'success':       return 'green.5';
    case 'pending_setup': return 'orange.5';
    default:              return 'gray.5';
  }
};

export const getExpirationInfo = (daysLeft, earliest, fullDateFormat) => {
  let color;
  let label;
  if (daysLeft < 0) {
    color = 'red.7';
    label = 'Expired';
  } else if (daysLeft === 0) {
    color = 'red.5';
    label = 'Expires today';
  } else if (daysLeft <= 7) {
    color = 'orange.5';
    label = `${daysLeft}d left`;
  } else if (daysLeft <= 30) {
    color = 'yellow.5';
    label = `${daysLeft}d left`;
  } else {
    label = format(earliest, fullDateFormat);
  }
  return { color, label };
};

export const getExpirationTooltip = (allExpirations, fullDateTimeFormat, label) => {
  return allExpirations.length > 0
    ? allExpirations
        .map(
          (e) =>
            `${e.profile_name}: ${format(e.exp_date, fullDateTimeFormat)}${
              !e.is_active ? ' (inactive)' : ''
            }`
        )
        .join('\n')
    : label;
};

export const getSortedPlaylists = (playlists, compareColumn, compareDesc) => {
  return playlists
    .filter((playlist) => playlist.locked === false)
    .sort((a, b) => {
      const aVal = a[compareColumn];
      const bVal = b[compareColumn];

      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;

      const comparison =
        typeof aVal === 'string'
          ? aVal.localeCompare(bVal)
          : aVal < bVal ? -1 : aVal > bVal ? 1 : 0;

      return compareDesc ? -comparison : comparison;
    });
};

export const getStatusContent = (data) => {
  if (data.progress === 100) return null;

  switch (data.action) {
    case 'initializing':
      return { type: 'initializing' };

    case 'downloading':
      if (data.progress === 0) return { type: 'simple', label: 'Downloading...' };
      return {
        type: 'downloading',
        progress: parseInt(data.progress),
        speed: formatSpeed(data.speed),
        timeRemaining: data.time_remaining
          ? formatDuration(data.time_remaining)
          : 'calculating...',
      };

    case 'processing_groups':
      if (data.progress === 0) return { type: 'simple', label: 'Processing groups...' };
      return {
        type: 'groups',
        progress: parseInt(data.progress),
        elapsedTime: formatDuration(data.elapsed_time),
        groupsProcessed: data.groups_processed,
      };

    case 'parsing':
      if (data.progress === 0) return { type: 'simple', label: 'Parsing...' };
      return {
        type: 'parsing',
        progress: parseInt(data.progress),
        elapsedTime: formatDuration(data.elapsed_time),
        timeRemaining: data.time_remaining
          ? formatDuration(data.time_remaining)
          : 'calculating...',
        streamsProcessed: data.streams_processed,
      };

    default:
      return data.status === 'error'
        ? { type: 'error', error: data.error }
        : { type: 'simple', label: `${data.action || 'Processing'}...` };
  }
};

