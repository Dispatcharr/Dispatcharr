import { format, getNowMs, toFriendlyDuration } from '../dateTimeUtils.js';

export const formatDuration = (seconds) => {
  if (!seconds) return 'Unknown';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
};

// Format time for display (e.g., "1:23:45" or "23:45")
export const formatTime = (seconds) => {
  if (!seconds || seconds === 0) return '0:00';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  } else {
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  }
};

export const getMovieDisplayTitle = (vodContent) => {
  return vodContent.content_name;
};

export const getEpisodeDisplayTitle = (metadata) => {
  const season = metadata.season_number
    ? `S${metadata.season_number.toString().padStart(2, '0')}`
    : 'S??';
  const episode = metadata.episode_number
    ? `E${metadata.episode_number.toString().padStart(2, '0')}`
    : 'E??';
  return `${metadata.series_name} - ${season}${episode}`;
};

export const getMovieSubtitle = (metadata) => {
  const parts = [];
  if (metadata.genre) parts.push(metadata.genre);
  // We'll handle rating separately as a badge now
  return parts;
};

export const getEpisodeSubtitle = (metadata) => {
  return [metadata.episode_name || 'Episode'];
};

export const calculateProgress = (connection, duration_secs) => {
  if (!connection || !duration_secs) {
    return {
      percentage: 0,
      currentTime: 0,
      totalTime: duration_secs || 0,
    };
  }

  const totalSeconds = duration_secs;
  let percentage = 0;
  let currentTime = 0;
  const now = getNowMs() / 1000; // Current time in seconds

  // Priority 1: Use last_seek_percentage if available (most accurate from range requests)
  if (
    connection.last_seek_percentage &&
    connection.last_seek_percentage > 0 &&
    connection.last_seek_timestamp
  ) {
    // Calculate the position at the time of seek
    const seekPosition = Math.round(
      (connection.last_seek_percentage / 100) * totalSeconds
    );

    // Add elapsed time since the seek
    const elapsedSinceSeek = now - connection.last_seek_timestamp;
    currentTime = seekPosition + Math.floor(elapsedSinceSeek);

    // Don't exceed the total duration
    currentTime = Math.min(currentTime, totalSeconds);

    percentage = (currentTime / totalSeconds) * 100;
  }
  // Priority 2: Use position_seconds if available
  else if (connection.position_seconds && connection.position_seconds > 0) {
    currentTime = connection.position_seconds;
    percentage = (currentTime / totalSeconds) * 100;
  }

  return {
    percentage: Math.min(percentage, 100), // Cap at 100%
    currentTime: Math.max(0, currentTime), // Don't go negative
    totalTime: totalSeconds,
  };
};

export const calculateConnectionDuration = (connection) => {
  // If duration is provided by API, use it
  if (connection.duration && connection.duration > 0) {
    return toFriendlyDuration(connection.duration, 'seconds');
  }

  // Fallback: try to extract from client_id timestamp
  if (connection.client_id && connection.client_id.startsWith('vod_')) {
    try {
      const parts = connection.client_id.split('_');
      if (parts.length >= 2) {
        const clientStartTime = parseInt(parts[1]) / 1000; // Convert ms to seconds
        const currentTime = getNowMs() / 1000;
        return toFriendlyDuration(currentTime - clientStartTime, 'seconds');
      }
    } catch {
      // Ignore parsing errors
    }
  }

  return 'Unknown duration';
};

export const calculateConnectionStartTime = (
  connection,
  fullDateTimeFormat
) => {
  if (connection.connected_at) {
    return format(connection.connected_at * 1000, fullDateTimeFormat);
  }

  // Fallback: calculate from client_id timestamp
  if (connection.client_id && connection.client_id.startsWith('vod_')) {
    try {
      const parts = connection.client_id.split('_');
      if (parts.length >= 2) {
        const clientStartTime = parseInt(parts[1]);
        return format(clientStartTime, fullDateTimeFormat);
      }
    } catch {
      // Ignore parsing errors
    }
  }

  return 'Unknown';
};
