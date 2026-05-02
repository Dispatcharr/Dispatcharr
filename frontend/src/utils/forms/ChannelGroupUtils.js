import API from '../../api.js';

export const updateChannelGroup = (channelGroup, values) => {
  return API.updateChannelGroup({
    id: channelGroup.id,
    ...values,
  });
};
export const addChannelGroup = (values) => {
  return API.addChannelGroup(values);
};
export const deleteChannelGroup = (group) => {
  return API.deleteChannelGroup(group.id);
};
export const cleanupUnusedChannelGroups = () => {
  return API.cleanupUnusedChannelGroups();
};
