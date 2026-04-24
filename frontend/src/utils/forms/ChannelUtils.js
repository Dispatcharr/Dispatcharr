import API from '../../api.js';

export const matchChannelEpg = (channel) => {
  return API.matchChannelEpg(channel.id);
};
export const createLogo = (newLogoData) => {
  return API.createLogo(newLogoData);
};
const setChannelEPG = (channel, values) => {
  return API.setChannelEPG(channel.id, values.epg_data_id);
};
const updateChannel = (values) => {
  return API.updateChannel(values);
};
export const addChannel = (channel) => {
  return API.addChannel(channel);
};
export const requeryChannels = () => {
  API.requeryChannels();
};

export const getChannelFormDefaultValues = (channel, channelGroups) => {
  return {
    name: channel?.name || '',
    channel_number:
      channel?.channel_number !== null && channel?.channel_number !== undefined
        ? channel.channel_number
        : '',
    channel_group_id: channel?.channel_group_id
      ? `${channel.channel_group_id}`
      : Object.keys(channelGroups).length > 0
        ? Object.keys(channelGroups)[0]
        : '',
    stream_profile_id: channel?.stream_profile_id
      ? `${channel.stream_profile_id}`
      : '0',
    tvg_id: channel?.tvg_id || '',
    tvc_guide_stationid: channel?.tvc_guide_stationid || '',
    epg_data_id: channel?.epg_data_id ?? '',
    logo_id: channel?.logo_id ? `${channel.logo_id}` : '',
    user_level: `${channel?.user_level ?? '0'}`,
    is_adult: channel?.is_adult ?? false,
  };
};

export const getFormattedValues = (values) => {
  const formattedValues = { ...values };

  // Convert empty or "0" stream_profile_id to null for the API
  if (
    !formattedValues.stream_profile_id ||
    formattedValues.stream_profile_id === '0'
  ) {
    formattedValues.stream_profile_id = null;
  }

  // Ensure tvg_id is properly included (no empty strings)
  formattedValues.tvg_id = formattedValues.tvg_id || null;

  // Ensure tvc_guide_stationid is properly included (no empty strings)
  formattedValues.tvc_guide_stationid =
    formattedValues.tvc_guide_stationid || null;

  return formattedValues;
};

export const handleEpgUpdate = async (
  channel,
  values,
  formattedValues,
  channelStreams
) => {
  // If there's an EPG to set, use our enhanced endpoint
  if (values.epg_data_id !== (channel.epg_data_id ?? '')) {
    // Use the special endpoint to set EPG and trigger refresh
    await setChannelEPG(channel, values);

    // Remove epg_data_id from values since we've handled it separately
    const { epg_data_id: _epg_data_id, ...otherValues } = formattedValues;

    // Update other channel fields if needed
    if (Object.keys(otherValues).length > 0) {
      await updateChannel({
        id: channel.id,
        ...otherValues,
        streams: channelStreams.map((stream) => stream.id),
      });
    }
  } else {
    // No EPG change, regular update
    await updateChannel({
      id: channel.id,
      ...formattedValues,
      streams: channelStreams.map((stream) => stream.id),
    });
  }
};
