import { create } from 'zustand';
import api from '../api';
import { showNotification } from '../utils/notificationUtils.js';
import useUsersStore from './users';

const defaultProfiles = { 0: { id: '0', name: 'All', channels: new Set() } };

// Seconds-precision timestamp recorded when this module is first loaded.
// Compared against client.connected_at (also in seconds) to distinguish connections
// that were already active before the page loaded from ones that started after.
const pageLoadTime = Date.now() / 1000;

// Returns true when a client connected after the page was loaded (genuinely new).
// Falls back to true when connected_at is absent so we don't silently drop notifications.
const isClientNewSincePageLoad = (client) =>
  !client.connected_at || client.connected_at >= pageLoadTime;

// Resolve identity info for a client: { username, ip }.
// username is null when no user account is linked.
const getClientIdentity = (client) => {
  let username = null;
  if (client?.user_id && client.user_id !== '0') {
    const users = useUsersStore.getState().users;
    const user = users.find((u) => String(u.id) === String(client.user_id));
    if (user?.username) username = user.username;
  }
  return { username, ip: client?.ip_address || 'unknown' };
};

// Build a two-line notification message: channel name on top, identity below.
const clientMessage = (channelName, client) => {
  const { username, ip } = getClientIdentity(client);
  const identity = username ? `${username} (${ip})` : ip;
  return (
    <>
      <div>{channelName}</div>
      <div style={{ marginTop: 2 }}>{identity}</div>
    </>
  );
};

const reduceChannels = (channels) => {
  const channelsByUUID = {};
  const channelsByID = channels.reduce((acc, channel) => {
    acc[channel.id] = channel;
    channelsByUUID[channel.uuid] = channel.id;
    return acc;
  }, {});
  return { channelsByUUID, channelsByID };
};

const showNotificationIfChannelStopped = (
  oldChannels,
  newChannels,
  channelsByUUID,
  channels
) => {
  // Safe on first poll: oldChannels is {} so the loop body never runs and no false "stopped" notifications fire.
  for (const uuid in oldChannels) {
    if (newChannels[uuid] === undefined) {
      const channelId = channelsByUUID[uuid];
      const channel = channelId && channels[channelId];
      const channelName =
        channel?.name || oldChannels[uuid]?.channel_name || `Channel (${uuid})`;
      showNotification({
        title: 'Channel streaming stopped',
        message: channelName,
        color: 'blue.5',
      });
    }
  }
};

const showNotificationIfClientStopped = (
  oldClients,
  newClients,
  channelsByUUID,
  channels
) => {
  // Safe on first poll: oldClients is {} so the loop body never runs and no false "stopped" notifications fire.
  for (const clientId in oldClients) {
    if (newClients[clientId] === undefined) {
      const client = oldClients[clientId];
      const channelId = client?.channel_id
        ? channelsByUUID[client.channel_id]
        : undefined;
      const channel = channelId && channels[channelId];
      const channelName =
        channel?.name ||
        client?.channel_name ||
        (client?.channel_id ? `Channel (${client.channel_id})` : null);
      const { username, ip } = getClientIdentity(client);
      const identity = username ? `${username} (${ip})` : ip;
      showNotification({
        title: 'Client stopped streaming',
        message: channelName ? (
          <>
            <div>{channelName}</div>
            <div style={{ marginTop: 2 }}>{identity}</div>
          </>
        ) : (
          identity
        ),
        color: 'blue.5',
      });
    }
  }
};

const useChannelsStore = create((set, get) => ({
  channels: [],
  channelIds: [],
  channelsByUUID: {},
  channelGroups: {},
  profiles: {},
  selectedProfileId: '0',
  channelsPageSelection: [],
  stats: {},
  activeChannels: {},
  activeClients: {},
  activeVodConnections: [],
  recordings: [],
  recurringRules: [],
  isLoading: false,
  error: null,
  forceUpdate: 0,

  triggerUpdate: () => {
    set({ forceUpdate: new Date() });
  },

  fetchChannelIds: async () => {
    set({ isLoading: true, error: null });
    try {
      const channelIds = await api.getAllChannelIds();
      set({
        channelIds,
        isLoading: false,
      });
    } catch (error) {
      set({ error: error.message, isLoading: false });
    }
  },

  fetchChannels: async () => {
    set({ isLoading: true, error: null });
    try {
      const channels = await api.getChannels();
      const { channelsByUUID, channelsByID } = reduceChannels(channels);
      set({
        channels: channelsByID,
        channelsByUUID,
        isLoading: false,
      });
    } catch (error) {
      set({ error: error.message, isLoading: false });
    }
  },

  fetchChannelGroups: async () => {
    try {
      const channelGroups = await api.getChannelGroups();

      // Process groups to add association flags
      const processedGroups = channelGroups.reduce((acc, group) => {
        acc[group.id] = {
          ...group,
          hasChannels: group.channel_count > 0,
          hasM3UAccounts: group.m3u_account_count > 0,
          canEdit: group.m3u_account_count === 0,
          canDelete: group.channel_count === 0 && group.m3u_account_count === 0,
        };
        return acc;
      }, {});

      set((state) => ({
        channelGroups: processedGroups,
      }));
    } catch (error) {
      console.error('Failed to fetch channel groups:', error);
      set({ error: 'Failed to load channel groups.', isLoading: false });
    }
  },

  fetchChannelProfiles: async () => {
    set({ isLoading: true, error: null });
    try {
      const profiles = await api.getChannelProfiles();
      set({
        profiles: profiles.reduce((acc, profile) => {
          acc[profile.id] = {
            ...profile,
            channels: new Set(profile.channels),
          };
          return acc;
        }, defaultProfiles),
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch channel profiles:', error);
      set({ error: 'Failed to load channel profiles.', isLoading: false });
    }
  },

  addChannel: (newChannel) => {
    get().fetchChannelProfiles();
    set((state) => {
      const profiles = { ...state.profiles };
      Object.values(profiles).forEach((item) => {
        item.channels.add(newChannel.id);
      });

      return {
        channels: {
          ...state.channels,
          [newChannel.id]: newChannel,
        },
        channelsByUUID: {
          ...state.channelsByUUID,
          [newChannel.uuid]: newChannel.id,
        },
        profiles,
      };
    });
  },

  addChannels: (newChannels) =>
    set((state) => {
      const { channelsByUUID, channelsByID } = reduceChannels(newChannels);

      // Don't automatically add to all profiles anymore - let the backend handle profile assignments
      // Just maintain the existing profile structure
      return {
        channels: {
          ...state.channels,
          ...channelsByID,
        },
        channelsByUUID: {
          ...state.channelsByUUID,
          ...channelsByUUID,
        },
      };
    }),

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

  updateChannels: (channels) => {
    // Ensure channels is an array
    if (!Array.isArray(channels)) {
      console.error(
        'updateChannels expects an array, received:',
        typeof channels,
        channels
      );
      return;
    }

    const { channelsByUUID, updatedChannels } = reduceChannels(channels);

    set((state) => ({
      channels: {
        ...state.channels,
        ...updatedChannels,
      },
      channelsByUUID: {
        ...state.channelsByUUID,
        ...channelsByUUID,
      },
    }));
  },

  removeChannels: (channelIds) => {
    set((state) => {
      const updatedChannels = { ...state.channels };
      const channelsByUUID = { ...state.channelsByUUID };
      const channelIdsSet = new Set(state.channelIds); // Convert to Set for O(1) lookups
      for (const id of channelIds) {
        delete updatedChannels[id];
        channelIdsSet.delete(id);

        for (const uuid in channelsByUUID) {
          if (channelsByUUID[uuid] == id) {
            delete channelsByUUID[uuid];
            break;
          }
        }
      }

      console.log(channelIdsSet);
      return {
        channels: updatedChannels,
        channelsByUUID,
        channelIds: Array.from(channelIdsSet),
      };
    });
  },

  addChannelGroup: (newChannelGroup) =>
    set((state) => ({
      channelGroups: {
        ...state.channelGroups,
        [newChannelGroup.id]: newChannelGroup,
      },
    })),

  updateChannelGroup: (channelGroup) =>
    set((state) => ({
      channelGroups: {
        ...state.channelGroups,
        [channelGroup.id]: channelGroup,
      },
    })),

  removeChannelGroup: (groupId) =>
    set((state) => {
      const { [groupId]: removed, ...remainingGroups } = state.channelGroups;
      return { channelGroups: remainingGroups };
    }),

  addProfile: (profile) =>
    set((state) => ({
      profiles: {
        ...state.profiles,
        [profile.id]: {
          ...profile,
          channels: new Set(profile.channels),
        },
      },
    })),

  updateProfile: (profile) =>
    set((state) => ({
      profiles: {
        ...state.profiles,
        [profile.id]: {
          ...profile,
          channels: new Set(profile.channels),
        },
      },
    })),

  removeProfiles: (profileIds) =>
    set((state) => {
      const updatedProfiles = { ...state.profiles };
      for (const id of profileIds) {
        delete updatedProfiles[id];
      }

      const additionalUpdates = profileIds.includes(state.selectedProfileId)
        ? { selectedProfileId: '0' }
        : {};

      return {
        profiles: updatedProfiles,
        selectedProfileId: profileIds.includes(state.selectedProfileId)
          ? '0'
          : state.selectedProfileId,
        ...additionalUpdates,
      };
    }),

  updateProfileChannels: (channelIds, profileId, enabled) =>
    set((state) => {
      const profile = state.profiles[profileId];
      if (!profile) return {};

      const currentChannelsSet = profile.channels;
      let hasChanged = false;

      if (enabled) {
        for (const id of channelIds) {
          if (!currentChannelsSet.has(id)) {
            currentChannelsSet.add(id);
            hasChanged = true;
          }
        }
      } else {
        for (const id of channelIds) {
          if (currentChannelsSet.has(id)) {
            currentChannelsSet.delete(id);
            hasChanged = true;
          }
        }
      }

      if (!hasChanged) return {}; // No need to update anything

      const updatedProfile = {
        ...profile,
        channels: currentChannelsSet,
      };

      return {
        profiles: {
          ...state.profiles,
          [profileId]: updatedProfile,
        },
      };
    }),

  setChannelsPageSelection: (channelsPageSelection) =>
    set(() => ({ channelsPageSelection })),

  setSelectedProfileId: (id) =>
    set(() => ({
      selectedProfileId: id,
    })),

  setChannelStats: (stats) => {
    return set((state) => {
      const {
        channels,
        activeChannels: oldChannels,
        activeClients: oldClients,
        channelsByUUID,
      } = state;
      const newClients = {};

      const newChannels = stats.channels.reduce((acc, ch) => {
        acc[ch.channel_id] = ch;
        return acc;
      }, {});

      stats.channels.forEach((ch) => {
        const channelId = channelsByUUID[ch.channel_id];
        const channel = channelId ? channels[channelId] : null;
        const channelName =
          channel?.name || ch.channel_name || `Channel (${ch.channel_id})`;
        const isNewChannel = oldChannels[ch.channel_id] === undefined;

        ch.clients.forEach((client) => {
          newClients[client.client_id] = client;
        });

        if (isNewChannel) {
          // Only notify for clients that connected after the page loaded.
          // This naturally suppresses pre-existing connections on the first poll
          // while still firing for connections that started mid-session.
          const genuinelyNewClients = ch.clients.filter(
            (client) =>
              oldClients[client.client_id] === undefined &&
              isClientNewSincePageLoad(client)
          );
          if (genuinelyNewClients.length > 0) {
            showNotification({
              title: 'Channel started streaming',
              message: clientMessage(channelName, genuinelyNewClients[0]),
              color: 'blue.5',
            });
            genuinelyNewClients.slice(1).forEach((client) => {
              showNotification({
                title: 'New client started streaming',
                message: clientMessage(channelName, client),
                color: 'blue.5',
              });
            });
          }
        } else {
          // Existing channel, notify only for clients that just joined.
          ch.clients.forEach((client) => {
            if (
              oldClients[client.client_id] === undefined &&
              isClientNewSincePageLoad(client)
            ) {
              showNotification({
                title: 'New client started streaming',
                message: clientMessage(channelName, client),
                color: 'blue.5',
              });
            }
          });
        }
      });

      showNotificationIfChannelStopped(
        oldChannels,
        newChannels,
        channelsByUUID,
        channels
      );
      showNotificationIfClientStopped(
        oldClients,
        newClients,
        channelsByUUID,
        channels
      );

      return {
        stats,
        activeChannels: newChannels,
        activeClients: newClients,
      };
    });
  },

  setVodStats: (stats) => {
    set({ activeVodConnections: stats.vod_connections || [] });
  },

  fetchRecordings: async () => {
    try {
      set({ recordings: await api.getRecordings() });
    } catch (error) {
      console.error('Failed to fetch recordings:', error);
    }
  },

  fetchRecurringRules: async () => {
    try {
      const rules = await api.listRecurringRules();
      set({ recurringRules: Array.isArray(rules) ? rules : [] });
    } catch (error) {
      console.error('Failed to fetch recurring DVR rules:', error);
      set({ error: 'Failed to load recurring DVR rules.' });
    }
  },

  removeRecurringRule: (id) =>
    set((state) => ({
      recurringRules: Array.isArray(state.recurringRules)
        ? state.recurringRules.filter((rule) => String(rule?.id) !== String(id))
        : [],
    })),

  // Optimistically remove a single recording from the local store
  removeRecording: (id) =>
    set((state) => {
      const target = String(id);
      const current = state.recordings;
      if (Array.isArray(current)) {
        // Early return if item doesn't exist — avoids a new array reference
        // (and thus a needless re-render) when called redundantly, e.g. both
        // the optimistic API delete and the WS recording_cancelled handler.
        if (!current.some((r) => String(r?.id) === target)) return {};
        return {
          recordings: current.filter((r) => String(r?.id) !== target),
        };
      }
      if (current && typeof current === 'object') {
        if (!Object.values(current).some((r) => String(r?.id) === target))
          return {};
        const next = { ...current };
        for (const k of Object.keys(next)) {
          try {
            if (String(next[k]?.id) === target) delete next[k];
          } catch {}
        }
        return { recordings: next };
      }
      return {};
    }),

  // Add helper methods for validation
  canEditChannelGroup: (groupIdOrGroup) => {
    const groupId =
      typeof groupIdOrGroup === 'object' ? groupIdOrGroup.id : groupIdOrGroup;
    return get().channelGroups[groupId]?.canEdit ?? true;
  },

  canDeleteChannelGroup: (groupIdOrGroup) => {
    const groupId =
      typeof groupIdOrGroup === 'object' ? groupIdOrGroup.id : groupIdOrGroup;
    return get().channelGroups[groupId]?.canDelete ?? true;
  },
}));

export default useChannelsStore;
