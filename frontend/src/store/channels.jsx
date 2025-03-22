import { create } from 'zustand';
import api from '../api';
import { notifications } from '@mantine/notifications';

const useChannelsStore = create((set, get) => ({
  channels: [],
  channelsByUUID: {},
  channelGroups: {},
  channelsPageSelection: [],
  stats: {},
  activeChannels: {},
  activeClients: {},
  isLoading: false,
  error: null,

  fetchChannels: async () => {
    set({ isLoading: true, error: null });
    try {
      const channels = await api.getChannels();
      const channelsByUUID = {};
      const channelsByID = channels.reduce((acc, channel) => {
        acc[channel.id] = channel;
        channelsByUUID[channel.uuid] = channel.id;
        return acc;
      }, {});
      set({
        channels: channelsByID,
        channelsByUUID,
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch channels:', error);
      set({ error: 'Failed to load channels.', isLoading: false });
    }
  },

  fetchChannelGroups: async () => {
    set({ isLoading: true, error: null });
    try {
      const channelGroups = await api.getChannelGroups();
      set({
        channelGroups: channelGroups.reduce((acc, group) => {
          acc[group.id] = group;
          return acc;
        }, {}),
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch channel groups:', error);
      set({ error: 'Failed to load channel groups.', isLoading: false });
    }
  },

  addChannel: (newChannel) =>
    set((state) => ({
      channels: {
        ...state.channels,
        [newChannel.id]: newChannel,
      },
      channelsByUUID: {
        ...state.channelsByUUID,
        [newChannel.uuid]: newChannel.id,
      },
    })),

  addChannels: (newChannels) => {
    const channelsByUUID = {};
    const channelsByID = newChannels.reduce((acc, channel) => {
      acc[channel.id] = channel;
      channelsByUUID[channel.uuid] = channel.id;
      return acc;
    }, {});
    return set((state) => ({
      channels: {
        ...state.channels,
        ...channelsByID,
      },
      channelsByUUID: {
        ...state.channelsByUUID,
        ...channelsByUUID,
      },
    }));
  },

  updateChannel: (channel) =>
    set((state) => ({
      channels: {
        ...state.channels,
        [channel.id]: channel,
      },
      channelsByUUID: {
        ...state.channelsByUUID,
        [channel.uuid]: channel.id,
      },
    })),

  removeChannels: (channelIds) =>
    set((state) => {
      const updatedChannels = { ...state.channels };
      const channelsByUUID = { ...state.channelsByUUID };
      for (const id of channelIds) {
        delete updatedChannels[id];

        for (const uuid in channelsByUUID) {
          if (channelsByUUID[uuid] == id) {
            delete channelsByUUID[uuid];
            break;
          }
        }
      }

      return { channels: updatedChannels, channelsByUUID };
    }),

  addChannelGroup: (newChannelGroup) =>
    set((state) => ({
      channelGroups: {
        ...state.channelGroups,
        [newChannelGroup.id]: newChannelGroup,
      },
    })),

  updateChannelGroup: (channelGroup) =>
    set((state) => ({
      ...state.channelGroups,
      [channelGroup.id]: channelGroup,
    })),

  setChannelsPageSelection: (channelsPageSelection) =>
    set((state) => ({ channelsPageSelection })),

  setChannelStats: (stats) => {
    const {
      channels,
      stats: currentStats,
      activeChannels: oldChannels,
      activeClients: oldClients,
      channelsByUUID,
    } = get();

    const newClients = {};
    const newChannels = stats.channels.reduce((acc, ch) => {
      acc[ch.channel_id] = ch;

      if (currentStats.channels) {
        if (oldChannels[ch.channel_id] === undefined) {
          notifications.show({
            title: 'New channel streaming',
            message: channels[channelsByUUID[ch.channel_id]].name,
            color: 'blue.5',
          });
        }
      }

      ch.clients.map((client) => {
        newClients[client.client_id] = client;
        // This check prevents the notifications if streams are active on page load
        if (currentStats.channels) {
          if (oldClients[client.client_id] === undefined) {
            notifications.show({
              title: 'New client started streaming',
              message: `Client streaming from ${client.ip_address}`,
              color: 'blue.5',
            });
          }
        }
      });

      return acc;
    }, {});

    // This check prevents the notifications if streams are active on page load
    if (currentStats.channels) {
      for (const uuid in oldChannels) {
        if (newChannels[uuid] === undefined) {
          notifications.show({
            title: 'Channel streaming stopped',
            message: channels[channelsByUUID[uuid]].name,
            color: 'blue.5',
          });
        }
      }

      for (const clientId in oldClients) {
        if (newClients[clientId] === undefined) {
          notifications.show({
            title: 'Client stopped streaming',
            message: `Client stopped streaming from ${oldClients[clientId].ip_address}`,
            color: 'blue.5',
          });
        }
      }
    }

    return set((state) => ({
      stats,
      activeChannels: newChannels,
      activeClients: newClients,
    }));
  },
}));

export default useChannelsStore;
