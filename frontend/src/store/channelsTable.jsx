import { create } from 'zustand';

// Stable empty array to avoid creating new references in getChannelStreams
const emptyStreams = [];

const useChannelsTableStore = create((set, get) => ({
  channels: [],
  pageCount: 0,
  totalCount: 0,
  hasUnassignedEPGChannels: false,
  sorting: [{ id: 'channel_number', desc: false }],
  pagination: {
    pageIndex: 0,
    pageSize:
      JSON.parse(localStorage.getItem('channel-table-prefs'))?.pageSize || 50,
  },
  selectedChannelIds: [],
  expandedChannelId: null,
  allQueryIds: [],
  isUnlocked: false,

  queryChannels: ({ results, count, has_unassigned_epg_channels }, params) => {
    set((state) => ({
      channels: results,
      totalCount: count,
      pageCount: Math.ceil(count / params.get('page_size')),
      ...(has_unassigned_epg_channels !== undefined && {
        hasUnassignedEPGChannels: has_unassigned_epg_channels,
      }),
    }));
  },

  setAllQueryIds: (allQueryIds) => {
    set((state) => ({
      allQueryIds,
    }));
  },

  setSelectedChannelIds: (selectedChannelIds) => {
    set({
      selectedChannelIds,
    });
  },

  setExpandedChannelId: (expandedChannelId) => {
    set({
      expandedChannelId,
    });
  },

  getChannelStreams: (id) => {
    const channel = get().channels.find((c) => c.id === id);
    return channel?.streams || emptyStreams;
  },

  setPagination: (pagination) => {
    set((state) => ({
      pagination,
    }));
  },

  setSorting: (sorting) => {
    set((state) => ({
      sorting,
    }));
  },

  setIsUnlocked: (isUnlocked) => {
    set({ isUnlocked });
  },

  updateChannel: (updatedChannel) => {
    set((state) => ({
      channels: state.channels.map((channel) =>
        channel.id === updatedChannel.id ? updatedChannel : channel
      ),
    }));
  },

  /**
   * Merges stream-stats deltas into the target channel's streams. Preserves
   * object identity for unchanged streams and channels so memoized rows
   * don't re-render.
   */
  patchChannelStreamStats: (channelId, updates) => {
    if (!Array.isArray(updates) || updates.length === 0) return;
    set((state) => {
      const updateMap = new Map(updates.map((u) => [u.id, u]));
      let channelChanged = false;
      const nextChannels = state.channels.map((channel) => {
        if (channel.id !== channelId) return channel;
        const streams = channel.streams || [];
        let streamsChanged = false;
        const nextStreams = streams.map((stream) => {
          const u = updateMap.get(stream.id);
          if (!u) return stream;
          if (
            stream.stream_stats_updated_at === u.stream_stats_updated_at &&
            stream.stream_stats === u.stream_stats
          ) {
            return stream;
          }
          streamsChanged = true;
          return {
            ...stream,
            stream_stats: u.stream_stats,
            stream_stats_updated_at: u.stream_stats_updated_at,
          };
        });
        if (!streamsChanged) return channel;
        channelChanged = true;
        return { ...channel, streams: nextStreams };
      });
      if (!channelChanged) return state;
      return { channels: nextChannels };
    });
  },
}));

export default useChannelsTableStore;
