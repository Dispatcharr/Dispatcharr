import API from '../../api.js';
import {
  format,
  getNow,
  initializeTime,
  subtract,
  toFriendlyDuration,
} from '../dateTimeUtils.js';

// Get buffering_speed from proxy settings
export const getBufferingSpeedThreshold = (proxySetting) => {
  try {
    if (proxySetting?.value) {
      return parseFloat(proxySetting.value.buffering_speed) || 1.0;
    }
  } catch (error) {
    console.error('Error getting buffering speed:', error);
  }
  return 1.0; // Default fallback
};

export const getStartDate = (uptime) => {
  // Get the current date and time
  const currentDate = new Date();
  // Calculate the start date by subtracting uptime (in milliseconds)
  const startDate = new Date(currentDate.getTime() - uptime * 1000);
  // Format the date as a string (you can adjust the format as needed)
  return startDate.toLocaleString({
    weekday: 'short', // optional, adds day of the week
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true, // 12-hour format with AM/PM
  });
};

export const getM3uAccountsMap = (m3uAccounts) => {
  const map = {};
  if (m3uAccounts && Array.isArray(m3uAccounts)) {
    m3uAccounts.forEach((account) => {
      if (account.id) {
        map[account.id] = account.name;
      }
    });
  }
  return map;
};

export const getChannelStreams = async (channelId) => {
  return await API.getChannelStreams(channelId);
};

export const getMatchingStreamByUrl = (streamData, channelUrl) => {
  return streamData.find(
    (stream) =>
      channelUrl.includes(stream.url) || stream.url.includes(channelUrl)
  );
};

export const getSelectedStream = (availableStreams, streamId) => {
  return availableStreams.find((s) => s.id.toString() === streamId);
};

export const switchStream = (channel, streamId) => {
  return API.switchStream(channel.channel_id, streamId);
};

export const connectedAccessor = (dateFormat) => {
  return (row) => {
    // Check for connected_since (which is seconds since connection)
    if (row.connected_since) {
      // Calculate the actual connection time by subtracting the seconds from current time
      const connectedTime = subtract(getNow(), row.connected_since, 'second');
      return format(connectedTime, `${dateFormat} HH:mm:ss`);
    }

    // Fallback to connected_at if it exists
    if (row.connected_at) {
      const connectedTime = initializeTime(row.connected_at * 1000);
      return format(connectedTime, `${dateFormat} HH:mm:ss`);
    }

    return 'Unknown';
  };
};

export const durationAccessor = () => {
  return (row) => {
    if (row.connected_since) {
      return toFriendlyDuration(row.connected_since, 'seconds');
    }

    if (row.connection_duration) {
      return toFriendlyDuration(row.connection_duration, 'seconds');
    }

    return '-';
  };
};

export const getLogoUrl = (logoId, logos, previewedStream) => {
  return (
    (logoId && logos && logos[logoId] ? logos[logoId].cache_url : null) ||
    previewedStream?.logo_url ||
    null
  );
};

export const getStreamsByIds = (streamId) => {
  return API.getStreamsByIds([streamId]);
};

export const getStreamOptions = (availableStreams, m3uAccountsMap) => {
  return availableStreams.map((stream) => {
    // Get account name from our mapping if it exists
    const accountName =
      stream.m3u_account && m3uAccountsMap[stream.m3u_account]
        ? m3uAccountsMap[stream.m3u_account]
        : stream.m3u_account
          ? `M3U #${stream.m3u_account}`
          : 'Unknown M3U';

    return {
      value: stream.id.toString(),
      label: `${stream.name || `Stream #${stream.id}`} [${accountName}]`,
    };
  });
};
