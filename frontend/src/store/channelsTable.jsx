import { create } from 'zustand';
import { readStoredJSON, writeStoredJSON } from '../hooks/useBrowserStorage';

// Stable empty array to avoid creating new references in getChannelStreams
const emptyStreams = [];

const DEFAULT_CHANNELS_SORTING = [{ id: 'channel_number', desc: false }];
const CHANNELS_SORTING_KEY = 'channels-table-sorting';

const normalizeChannelPage = (payload) => {
  if (Array.isArray(payload)) {
    return {
      results: payload,
      count: payload.length,
      hasUnassignedEPGChannels: undefined,
    };
  }
  if (!payload || !Array.isArray(payload.results)) return null;
  return {
    results: payload.results,
    count: Number.isFinite(Number(payload.count))
      ? Number(payload.count)
      : payload.results.length,
    hasUnassignedEPGChannels: payload.has_unassigned_epg_channels,
  };
};

const useChannelsTableStore = create((set, get) => ({
  channels: [],
  pageCount: 0,
  totalCount: 0,
  hasUnassignedEPGChannels: false,
  sorting: readStoredJSON(
    CHANNELS_SORTING_KEY,
    DEFAULT_CHANNELS_SORTING,
    'session'
  ),
  pagination: {
    pageIndex: 0,
    pageSize:
      JSON.parse(localStorage.getItem('channel-table-prefs'))?.pageSize || 50,
  },
  selectedChannelIds: [],
  expandedChannelId: null,
  allQueryIds: [],
  isUnlocked: false,

  queryChannels: (payload, params) => {
    const page = normalizeChannelPage(payload);
    if (!page) {
      console.error(
        '[channelsTable] Ignored a channel-list response without an array.'
      );
      return false;
    }
    const pageSize = Math.max(1, Number(params?.get?.('page_size')) || 50);
    set(() => ({
      channels: page.results,
      totalCount: page.count,
      pageCount: Math.ceil(page.count / pageSize),
      ...(page.hasUnassignedEPGChannels !== undefined && {
        hasUnassignedEPGChannels: page.hasUnassignedEPGChannels,
      }),
    }));
    return true;
  },

  setAllQueryIds: (allQueryIds) => {
    set(() => ({
      allQueryIds: Array.isArray(allQueryIds) ? allQueryIds : [],
    }));
  },

  setSelectedChannelIds: (selectedChannelIds) => {
    set({
      selectedChannelIds: Array.isArray(selectedChannelIds)
        ? selectedChannelIds
        : [],
    });
  },

  setExpandedChannelId: (expandedChannelId) => {
    set({
      expandedChannelId,
    });
  },

  getChannelStreams: (id) => {
    const channels = get().channels;
    const channel = (Array.isArray(channels) ? channels : []).find(
      (c) => c?.id === id
    );
    return channel?.streams || emptyStreams;
  },

  setPagination: (pagination) => {
    set(() => ({
      pagination,
    }));
  },

  setSorting: (sorting) => {
    writeStoredJSON(CHANNELS_SORTING_KEY, sorting, 'session');
    set(() => ({
      sorting,
    }));
  },

  setIsUnlocked: (isUnlocked) => {
    set({ isUnlocked });
  },

  updateChannel: (updatedChannel) => {
    set((state) => ({
      channels: (Array.isArray(state.channels) ? state.channels : []).map(
        (channel) =>
          channel?.id === updatedChannel.id ? updatedChannel : channel
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
      const nextChannels = (
        Array.isArray(state.channels) ? state.channels : []
      ).map((channel) => {
        if (!channel || channel.id !== channelId) return channel;
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
