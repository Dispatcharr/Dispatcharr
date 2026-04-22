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
    user_hidden: channel?.user_hidden ?? false,
    user_locked: channel?.user_locked ?? false,
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

// Fields that auto-sync overwrites. Editing any of these on an auto-created
// channel implies user_locked=true so the customization persists across
// future refreshes.
export const IDENTITY_FIELDS = ['name', 'channel_number', 'channel_group_id'];

// Shared helper for bulk-selection flows that need to scope a user_locked
// PATCH to auto-created rows only. Returns {ids, count} in one pass so
// callers don't re-filter later.
export const selectAutoCreatedInSelection = (channelIds, rows) => {
  if (!channelIds?.length || !rows?.length) return { ids: [], count: 0 };
  const selected = new Set(channelIds.map((id) => parseInt(id, 10)));
  const ids = rows
    .filter((c) => selected.has(c.id) && c.auto_created)
    .map((c) => c.id);
  return { ids, count: ids.length };
};

export const applyAutoProtect = (channel, values, formattedValues) => {
  if (!channel?.auto_created) return;
  if (channel.user_locked) return;
  if (values.user_locked) return;
  const identityChanged = IDENTITY_FIELDS.some(
    (field) => formattedValues[field] !== channel[field]
  );
  if (identityChanged) {
    formattedValues.user_locked = true;
  }
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
