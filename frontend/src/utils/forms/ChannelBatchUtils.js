import API from '../../api.js';

export const getChannelGroupChange = (selectedChannelGroup, channelGroups) => {
  if (!selectedChannelGroup || selectedChannelGroup === '-1') return null;
  const groupName = channelGroups[selectedChannelGroup]?.name || 'Unknown';
  return `• Channel Group: ${groupName}`;
};

export const getLogoChange = (selectedLogoId, channelLogos) => {
  if (!selectedLogoId || selectedLogoId === '-1') return null;
  if (selectedLogoId === '0') return `• Logo: Use Default`;
  const logoName = channelLogos[selectedLogoId]?.name || 'Selected Logo';
  return `• Logo: ${logoName}`;
};

export const getStreamProfileChange = (streamProfileId, streamProfiles) => {
  if (!streamProfileId || streamProfileId === '-1') return null;
  if (streamProfileId === '0') return `• Stream Profile: Use Default`;
  const profile = streamProfiles.find(
    (p) => `${p.id}` === `${streamProfileId}`
  );
  return `• Stream Profile: ${profile?.name || 'Selected Profile'}`;
};

export const getUserLevelChange = (userLevel, userLevelLabels) => {
  if (!userLevel || userLevel === '-1') return null;
  return `• User Level: ${userLevelLabels[userLevel] || userLevel}`;
};

export const getMatureContentChange = (isAdult) => {
  if (!isAdult || isAdult === '-1') return null;
  return `• Mature Content: ${isAdult === 'true' ? 'Yes' : 'No'}`;
};

export const getRegexNameChange = (regexFind, regexReplace) => {
  if (!regexFind?.trim()) return null;
  return `• Name Change: Apply regex find "${regexFind}" replace with "${regexReplace || ''}"`;
};

export const getEpgChange = (selectedDummyEpgId, epgs) => {
  if (!selectedDummyEpgId) return null;
  if (selectedDummyEpgId === 'clear')
    return `• EPG: Clear Assignment (use default dummy)`;
  const epgName = epgs[selectedDummyEpgId]?.name || 'Selected EPG';
  return `• Dummy EPG: ${epgName}`;
};

export const updateChannels = (channelIds, values) => {
  return API.updateChannels(channelIds, values);
};

export const bulkRegexRenameChannels = (
  channelIds,
  regexFind,
  regexReplace,
  flags
) => {
  return API.bulkRegexRenameChannels(
    channelIds,
    regexFind,
    regexReplace ?? '',
    flags
  );
};

export const batchSetEPG = (associations) => {
  return API.batchSetEPG(associations);
};

export const getEpgData = () => {
  return API.getEPGData();
};

export const setChannelNamesFromEpg = (channelIds) => {
  return API.setChannelNamesFromEpg(channelIds);
};

export const setChannelLogosFromEpg = (channelIds) => {
  return API.setChannelLogosFromEpg(channelIds);
};

export const setChannelTvgIdsFromEpg = (channelIds) => {
  return API.setChannelTvgIdsFromEpg(channelIds);
};

export const computeRegexPreview = (
  channelIds,
  nameById,
  find,
  replace,
  limit = 25
) => {
  if (!find) return [];

  let re;
  try {
    re = new RegExp(find, 'g');
  } catch (error) {
    console.error('Invalid regex:', error);
    return [{ before: 'Invalid regex', after: '' }];
  }

  // Limit preview to items that exist on the current page
  const pageOnlyIds = channelIds.filter((id) => nameById[id] !== undefined);
  const items = [];

  for (let i = 0; i < Math.min(pageOnlyIds.length, limit); i++) {
    const before = nameById[pageOnlyIds[i]] ?? '';
    const after = before.replace(re, replace ?? '');
    if (before !== after) items.push({ before, after });
  }

  return items;
};

export const buildSubmitValues = (
  formValues,
  selectedChannelGroup,
  selectedLogoId
) => {
  const values = { ...formValues };

  // Handle channel group ID - convert to integer if it exists
  if (selectedChannelGroup && selectedChannelGroup !== '-1') {
    values.channel_group_id = parseInt(selectedChannelGroup);
  } else {
    delete values.channel_group_id;
  }

  if (selectedLogoId && selectedLogoId !== '-1') {
    values.logo_id = selectedLogoId === '0' ? null : parseInt(selectedLogoId);
  }
  delete values.logo;
  // Remove the channel_group field from form values as we use channel_group_id
  delete values.channel_group;

  // Handle stream profile ID - convert special values
  if (!values.stream_profile_id || values.stream_profile_id === '-1') {
    delete values.stream_profile_id;
  } else if (
    values.stream_profile_id === '0' ||
    values.stream_profile_id === 0
  ) {
    values.stream_profile_id = null; // Convert "use default" to null
  }

  if (values.user_level == '-1') delete values.user_level;

  if (values.is_adult === '-1') {
    delete values.is_adult;
  } else {
    values.is_adult = values.is_adult === 'true';
  }

  return values;
};

export const buildEpgAssociations = async (
  selectedDummyEpgId,
  channelIds,
  epgs,
  tvgs
) => {
  if (!selectedDummyEpgId) return null;

  if (selectedDummyEpgId === 'clear') {
    // Clear EPG assignments
    return channelIds.map((id) => ({ channel_id: id, epg_data_id: null }));
  }

  // Assign the selected dummy EPG
  const selectedEpg = epgs[selectedDummyEpgId];
  if (!selectedEpg?.epg_data_count) return null;

  const epgSourceId = parseInt(selectedDummyEpgId, 10);
  // Check if we already have EPG data loaded in the store
  let epgData = tvgs.find((data) => data.epg_source === epgSourceId);

  if (!epgData) {
    const epgDataList = await getEpgData();
    epgData = epgDataList.find((data) => data.epg_source === epgSourceId);
  }

  if (!epgData) return null;
  return channelIds.map((id) => ({ channel_id: id, epg_data_id: epgData.id }));
};
