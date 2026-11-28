import API from '../../api.js';

export const updateChannelGroup = (channelGroup, values) => {
  return API.updateChannelGroup({
    id: channelGroup.id,
    ...values,
  });
};
export const reorderChannelGroups = (groupIds) =>
  API.reorderChannelGroups(groupIds);
export const addChannelGroup = (values) => {
  return API.addChannelGroup(values);
};
export const deleteChannelGroup = (group) => {
  return API.deleteChannelGroup(group.id);
};
export const cleanupUnusedChannelGroups = (includeCustom = false) => {
  return API.cleanupUnusedChannelGroups(includeCustom);
};
export const claimChannelGroupAsCustom = (group) => {
  return API.claimChannelGroupAsCustom(group.id);
};
export const unclaimChannelGroup = (group) => {
  return API.unclaimChannelGroup(group.id);
};
