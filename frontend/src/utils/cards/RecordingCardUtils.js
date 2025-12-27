import API from '../../api.js';
import useChannelsStore from '../../store/channels.jsx';

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

export const getPosterUrl = (posterLogoId, customProperties, posterUrl) => {
  let purl = posterLogoId
    ? `/api/channels/logos/${posterLogoId}/cache/`
    : customProperties?.poster_url || posterUrl || '/logo.png';
  if (
    typeof import.meta !== 'undefined' &&
    import.meta.env &&
    import.meta.env.DEV &&
    purl &&
    purl.startsWith('/')
  ) {
    purl = `${window.location.protocol}//${window.location.hostname}:5656${purl}`;
  }
  return purl;
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
  return season && episode
    ? `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`
    : onscreen || null;
};

export const getSeriesInfo = (customProps) => {
  const cp = customProps || {};
  const pr = cp.program || {};
  return { tvg_id: pr.tvg_id, title: pr.title };
};