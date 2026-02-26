export const formatDuration = (seconds) => {
  if (!seconds) return '';
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return hours > 0 ? `${hours}h ${mins}m` : `${mins}m ${secs}s`;
};

export const getSeasonLabel = (vod) => {
  return vod.season_number && vod.episode_number
    ? `S${vod.season_number.toString().padStart(2, '0')}E${vod.episode_number.toString().padStart(2, '0')}`
    : '';
};
