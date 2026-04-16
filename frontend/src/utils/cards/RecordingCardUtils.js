import API from '../../api.js';
import useChannelsStore from '../../store/channels.jsx';
import defaultLogo from '../../images/logo.png';
import { formatSeasonEpisode } from '../guideUtils.js';

export const removeRecording = (id) => {
  // Optimistically remove immediately from UI
  try {
    useChannelsStore.getState().removeRecording(id);
  } catch (error) {
    console.error('Failed to optimistically remove recording', error);
  }
  // Fire-and-forget server delete; websocket will keep others in sync
  API.deleteRecording(id).catch(() => {
    // On failure, fallback to refetch to restore state
    try {
      useChannelsStore.getState().fetchRecordings();
    } catch (error) {
      console.error('Failed to refresh recordings after delete', error);
    }
  });
};

/**
 * Resolve the channel logo cache URL from either a full channel object
 * (has logo.cache_url) or a summary object (has logo_id integer).
 */
export const getChannelLogoUrl = (channel) => {
  if (!channel) return null;
  let url = channel.logo_id
    ? `/api/channels/logos/${channel.logo_id}/cache/`
    : channel.logo?.cache_url || null;
  if (
    url &&
    url.startsWith('/') &&
    typeof import.meta !== 'undefined' &&
    import.meta.env &&
    import.meta.env.DEV
  ) {
    url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
  }
  return url;
};

export const getPosterUrl = (posterLogoId, customProperties, posterUrl) => {
  let purl = posterLogoId
    ? `/api/channels/logos/${posterLogoId}/cache/`
    : customProperties?.poster_url || posterUrl || null;
  if (
    purl &&
    typeof import.meta !== 'undefined' &&
    import.meta.env &&
    import.meta.env.DEV &&
    purl.startsWith('/')
  ) {
    purl = `${window.location.protocol}//${window.location.hostname}:5656${purl}`;
  }
  return purl || defaultLogo;
};

export const getShowVideoUrl = (channel, env_mode) => {
  let url = `/proxy/ts/stream/${channel.uuid}`;
  if (env_mode === 'dev') {
    url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
  }
  return url;
};

export const runComSkip = async (recording) => {
  await API.runComskip(recording.id);
};

export const deleteRecordingById = async (recordingId) => {
  await API.deleteRecording(recordingId);
};

export const stopRecordingById = async (recordingId) => {
  await API.stopRecording(recordingId);
};

export const extendRecordingById = async (recordingId, extraMinutes) => {
  await API.extendRecording(recordingId, extraMinutes);
};

export const deleteSeriesAndRule = async (seriesInfo) => {
  const { tvg_id, title } = seriesInfo;
  if (tvg_id) {
    try {
      await API.bulkRemoveSeriesRecordings({
        tvg_id,
        title,
        scope: 'title',
      });
    } catch (error) {
      console.error('Failed to remove series recordings', error);
    }
    try {
      await API.deleteSeriesRule(tvg_id);
    } catch (error) {
      console.error('Failed to delete series rule', error);
    }
  }
};

export const getRecordingUrl = (customProps, env_mode) => {
  let fileUrl = customProps?.file_url || customProps?.output_file_url;
  if (fileUrl && env_mode === 'dev' && fileUrl.startsWith('/')) {
    fileUrl = `${window.location.protocol}//${window.location.hostname}:5656${fileUrl}`;
  }
  return fileUrl;
};

export const getSeasonLabel = (season, episode, onscreen) => {
  if (season != null && episode != null)
    return formatSeasonEpisode(season, episode);
  return onscreen || null;
};

export const getSeriesInfo = (customProps) => {
  const cp = customProps || {};
  const pr = cp.program || {};
  return { tvg_id: pr.tvg_id, title: pr.title };
};
