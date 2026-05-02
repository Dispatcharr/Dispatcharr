import API from '../../api.js';
import { refreshPlaylist, updatePlaylist } from './M3uUtils.js';

const updateM3UGroupSettings = async (
  playlist,
  groupSettings,
  categorySettings
) => {
  await API.updateM3UGroupSettings(
    playlist.id,
    groupSettings,
    categorySettings
  );
};

export const buildGroupStates = (channelGroups, playlistChannelGroups) => {
  return playlistChannelGroups
    .filter((group) => channelGroups[group.channel_group])
    .map((group) => ({
      ...group,
      name: channelGroups[group.channel_group].name,
      auto_channel_sync: group.auto_channel_sync || false,
      auto_sync_channel_start: group.auto_sync_channel_start || 1.0,
      custom_properties: parseCustomProperties(group.custom_properties),
    }));
};

const parseCustomProperties = (raw) => {
  if (!raw) return {};
  try {
    return typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch {
    return {};
  }
};

export const saveAndRefreshPlaylist = async (
  playlist,
  groupStates,
  movieCategoryStates,
  seriesCategoryStates,
  autoEnableSettings
) => {
  const groupSettings = prepareGroupSettings(groupStates);
  const categorySettings = prepareCategorySettings(
    movieCategoryStates,
    seriesCategoryStates
  );

  await updatePlaylist(playlist, autoEnableSettings);
  await updateM3UGroupSettings(playlist, groupSettings, categorySettings);
  await refreshPlaylist(playlist);
};

const prepareGroupSettings = (groupStates) => {
  return groupStates.map((state) => ({
    ...state,
    custom_properties: state.custom_properties || undefined,
  }));
};

const prepareCategorySettings = (movieCategoryStates, seriesCategoryStates) => {
  return [...movieCategoryStates, ...seriesCategoryStates]
    .map((state) => ({
      ...state,
      custom_properties: state.custom_properties || undefined,
    }))
    .filter((state) => state.enabled !== state.original_enabled);
};