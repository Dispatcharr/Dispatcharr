import API from '../../api.js';
import {
  format,
  initializeTime,
  toFriendlyDuration,
} from '../dateTimeUtils.js';

export const getBufferingSpeedThreshold = (proxySetting) => {
  const value = parseFloat(proxySetting?.value?.buffering_speed);
  return Number.isFinite(value) && value > 0 ? value : 1.0;
};

// Classic: hard green/red at Buffering Speed. Experimental: green within 2%
// of that threshold, orange from 5% to 2% below, red farther below.
export const getSpeedBadgeColor = (speed, proxySetting) => {
  if (!Number.isFinite(speed)) {
    return 'gray';
  }
  const threshold = getBufferingSpeedThreshold(proxySetting);
  if (!proxySetting?.value?.experimental_ingest_buffer) {
    return speed >= threshold ? 'green' : 'red';
  }
  const ratio = speed / threshold;
  if (ratio >= 0.98) return 'green';
  if (ratio >= 0.95) return 'orange';
  return 'red';
};

// New Client Buffer budget for the experimental cushion badge.
export const getNewClientBehindSeconds = (proxySetting) => {
  try {
    if (proxySetting?.value) {
      const value = parseFloat(proxySetting.value.new_client_behind_seconds);
      if (Number.isFinite(value) && value >= 0) {
        return value;
      }
    }
  } catch (error) {
    console.error('Error getting new client behind seconds:', error);
  }
  return 5.0;
};

// Green above half of New Client Buffer, orange from half down to empty,
// red at 0. Hard buffering waits for empty held for the confirm window.
export const getBufferBudgetColor = (remaining, budget) => {
  if (!Number.isFinite(remaining) || !Number.isFinite(budget) || budget <= 0) {
    return 'gray';
  }
  const half = budget * 0.5;
  if (remaining > half) {
    return 'green';
  }
  if (remaining > 0) {
    return 'orange';
  }
  return 'red';
};

export const getStartDate = (startedAt) => {
  if (!startedAt) return 'Unknown';
  return new Date(startedAt * 1000).toLocaleString();
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

export const connectedAccessor = (fullDateTimeFormat) => {
  return (row) => {
    if (row.connected_at) {
      return format(
        initializeTime(row.connected_at * 1000),
        fullDateTimeFormat
      );
    }
    return 'Unknown';
  };
};

export const durationAccessor = () => {
  return (row) => {
    if (row.connected_at) {
      return toFriendlyDuration(
        Date.now() / 1000 - row.connected_at,
        'seconds'
      );
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
