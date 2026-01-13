import API from '../../api.js';

export const stopChannel = async (id) => {
  await API.stopChannel(id);
};

export const stopClient = async (channelId, clientId) => {
  await API.stopClient(channelId, clientId);
};

export const stopVODClient = async (clientId) => {
  await API.stopVODClient(clientId);
};

export const fetchActiveChannelStats = async () => {
  return await API.fetchActiveChannelStats();
};

export const getVODStats = async () => {
  return await API.getVODStats();
};

export const getCombinedConnections = (channelHistory, vodConnections) => {
  const activeStreams = Object.values(channelHistory).map((channel) => ({
    type: 'stream',
    data: channel,
    id: channel.channel_id,
    sortKey: channel.uptime || 0, // Use uptime for sorting streams
  }));

  // Flatten VOD connections so each individual client gets its own card
  const vodItems = vodConnections.flatMap((vodContent) => {
    return (vodContent.connections || []).map((connection, index) => ({
      type: 'vod',
      data: {
        ...vodContent,
        // Override the connections array to contain only this specific connection
        connections: [connection],
        connection_count: 1, // Each card now represents a single connection
        // Add individual connection details at the top level for easier access
        individual_connection: connection,
      },
      id: `${vodContent.content_type}-${vodContent.content_uuid}-${connection.client_id}-${index}`,
      sortKey: connection.connected_at || Date.now() / 1000, // Use connection time for sorting
    }));
  });

  // Combine and sort by newest connections first (higher sortKey = more recent)
  return [...activeStreams, ...vodItems].sort((a, b) => b.sortKey - a.sortKey);
};

const getChannelWithMetadata = (
  prevChannelHistory,
  ch,
  channelsByUUID,
  channels,
  streamProfiles
) => {
  let bitrates = [];
  if (prevChannelHistory[ch.channel_id]) {
    bitrates = [...(prevChannelHistory[ch.channel_id].bitrates || [])];
    const bitrate =
      ch.total_bytes - prevChannelHistory[ch.channel_id].total_bytes;
    if (bitrate > 0) {
      bitrates.push(bitrate);
    }

    if (bitrates.length > 15) {
      bitrates = bitrates.slice(1);
    }
  }

  // Find corresponding channel data
  const channelData =
    channelsByUUID && ch.channel_id
      ? channels[channelsByUUID[ch.channel_id]]
      : null;

  // Find stream profile
  const streamProfile = streamProfiles.find(
    (profile) => profile.id == parseInt(ch.stream_profile)
  );

  return {
    ...ch,
    ...(channelData || {}), // Safely merge channel data if available
    bitrates,
    stream_profile: streamProfile || { name: 'Unknown' },
    // Make sure stream_id is set from the active stream info
    stream_id: ch.stream_id || null,
  };
};

export const getClientStats = (stats) => {
  return Object.values(stats).reduce((acc, ch) => {
    if (ch.clients && Array.isArray(ch.clients)) {
      return acc.concat(
        ch.clients.map((client) => ({
          ...client,
          channel: ch,
        }))
      );
    }
    return acc;
  }, []);
};

export const getStatsByChannelId = (
  channelStats,
  prevChannelHistory,
  channelsByUUID,
  channels,
  streamProfiles
) => {
  const stats = {};

  channelStats.channels.forEach((ch) => {
    // Make sure we have a valid channel_id
    if (!ch.channel_id) {
      console.warn('Found channel without channel_id:', ch);
      return;
    }

    stats[ch.channel_id] = getChannelWithMetadata(
      prevChannelHistory,
      ch,
      channelsByUUID,
      channels,
      streamProfiles
    );
  });
  return stats;
};
