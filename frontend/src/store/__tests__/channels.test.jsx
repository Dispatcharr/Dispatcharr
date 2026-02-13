import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useChannelsStore from '../channels';
import api from '../../api';
import { showNotification } from '../../utils/notificationUtils';

// Mock dependencies
vi.mock('../../api');
vi.mock('../../utils/notificationUtils');

describe('useChannelsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset store state between tests
    useChannelsStore.setState({
      channels: {},
      channelsByUUID: {},
      channelGroups: {},
      profiles: { 0: { id: '0', name: 'All', channels: new Set() } },
      selectedProfileId: '0',
      channelsPageSelection: [],
      stats: {},
      activeChannels: {},
      activeClients: {},
      recordings: [],
      recurringRules: [],
      isLoading: false,
      error: null,
      forceUpdate: 0,
    });
  });

  describe('fetchChannelIds', () => {
    it('should fetch and store channels successfully', async () => {
      const mockChannels = [
        { id: 1, uuid: 'uuid-1', name: 'Channel 1' },
        { id: 2, uuid: 'uuid-2', name: 'Channel 2' },
      ];
      api.getChannels.mockResolvedValue(mockChannels);

      const { result } = renderHook(() => useChannelsStore());

      await act(async () => {
        await result.current.fetchChannelIds();
      });

      expect(api.getAllChannelIds).toHaveBeenCalledOnce();
      expect(result.current.channels).toEqual({
        1: mockChannels[0].id,
        2: mockChannels[1].id,
      });
      expect(result.current.channelsByUUID).toEqual({
        'uuid-1': 1,
        'uuid-2': 2,
      });
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('should handle fetch error', async () => {
      const errorMessage = 'Network error';
      api.getChannels.mockRejectedValue(new Error(errorMessage));

      const { result } = renderHook(() => useChannelsStore());

      expect(result.current.error).toBe(errorMessage);
      expect(result.current.isLoading).toBe(false);
    });
  });

  describe('fetchChannelGroups', () => {
    it('should fetch and process channel groups', async () => {
      const mockGroups = [
        { id: 1, name: 'Group 1', channel_count: 5, m3u_account_count: 0 },
        { id: 2, name: 'Group 2', channel_count: 0, m3u_account_count: 2 },
      ];
      api.getChannelGroups.mockResolvedValue(mockGroups);

      const { result } = renderHook(() => useChannelsStore());

      await act(async () => {
        await result.current.fetchChannelGroups();
      });

      expect(api.getChannelGroups).toHaveBeenCalledOnce();
      expect(result.current.channelGroups[1]).toMatchObject({
        hasChannels: true,
        hasM3UAccounts: false,
        canEdit: true,
        canDelete: false,
      });
      expect(result.current.channelGroups[2]).toMatchObject({
        hasChannels: false,
        hasM3UAccounts: true,
        canEdit: false,
        canDelete: false,
      });
    });
  });

  describe('fetchChannelProfiles', () => {
    it('should fetch and process channel profiles', async () => {
      const mockProfiles = [
        { id: '1', name: 'Profile 1', channels: [1, 2, 3] },
      ];
      api.getChannelProfiles.mockResolvedValue(mockProfiles);

      const { result } = renderHook(() => useChannelsStore());

      await act(async () => {
        await result.current.fetchChannelProfiles();
      });

      expect(api.getChannelProfiles).toHaveBeenCalledOnce();
      expect(result.current.profiles['1'].channels).toBeInstanceOf(Set);
      expect(result.current.profiles['1'].channels.has(1)).toBe(true);
    });
  });

  describe('addChannel', () => {
    it('should add a new channel', async () => {
      const newChannel = { id: 3, uuid: 'uuid-3', name: 'Channel 3' };
      api.getChannelProfiles.mockResolvedValue([]);

      const { result } = renderHook(() => useChannelsStore());

      await act(async () => {
        result.current.addChannel(newChannel);
      });

      expect(result.current.channels[3]).toEqual(newChannel);
      expect(result.current.channelsByUUID['uuid-3']).toBe(3);
    });
  });

  describe('updateChannel', () => {
    it('should update an existing channel', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          channels: { 1: { id: 1, uuid: 'uuid-1', name: 'Old Name' } },
          channelsByUUID: { 'uuid-1': 1 },
        });
      });

      const updatedChannel = { id: 1, uuid: 'uuid-1', name: 'New Name' };

      act(() => {
        result.current.updateChannel(updatedChannel);
      });

      expect(result.current.channels[1].name).toBe('New Name');
    });
  });

  describe('removeChannels', () => {
    it('should remove channels by IDs', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          channels: {
            1: { id: 1, uuid: 'uuid-1' },
            2: { id: 2, uuid: 'uuid-2' },
          },
          channelsByUUID: { 'uuid-1': 1, 'uuid-2': 2 },
        });
      });

      act(() => {
        result.current.removeChannels([1]);
      });

      expect(result.current.channels[1]).toBeUndefined();
      expect(result.current.channelsByUUID['uuid-1']).toBeUndefined();
      expect(result.current.channels[2]).toBeDefined();
    });
  });

  describe('channel groups operations', () => {
    it('should add a channel group', () => {
      const { result } = renderHook(() => useChannelsStore());
      const newGroup = { id: 1, name: 'New Group' };

      act(() => {
        result.current.addChannelGroup(newGroup);
      });

      expect(result.current.channelGroups[1]).toEqual(newGroup);
    });

    it('should update a channel group', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          channelGroups: { 1: { id: 1, name: 'Old Name' } },
        });
      });

      act(() => {
        result.current.updateChannelGroup({ id: 1, name: 'Updated Name' });
      });

      expect(result.current.channelGroups[1].name).toBe('Updated Name');
    });

    it('should remove a channel group', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          channelGroups: { 1: { id: 1, name: 'Group' } },
        });
      });

      act(() => {
        result.current.removeChannelGroup(1);
      });

      expect(result.current.channelGroups[1]).toBeUndefined();
    });
  });

  describe('profile operations', () => {
    it('should add a profile', () => {
      const { result } = renderHook(() => useChannelsStore());
      const newProfile = { id: '1', name: 'Profile', channels: [1, 2] };

      act(() => {
        result.current.addProfile(newProfile);
      });

      expect(result.current.profiles['1'].channels).toBeInstanceOf(Set);
    });

    it('should update a profile', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        result.current.updateProfile({
          id: '1',
          name: 'Updated',
          channels: [3],
        });
      });

      expect(result.current.profiles['1'].name).toBe('Updated');
    });

    it('should remove profiles and reset selected if needed', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          profiles: { 1: { id: '1' }, 2: { id: '2' } },
          selectedProfileId: '1',
        });
      });

      act(() => {
        result.current.removeProfiles(['1']);
      });

      expect(result.current.profiles['1']).toBeUndefined();
      expect(result.current.selectedProfileId).toBe('0');
    });
  });

  describe('updateProfileChannels', () => {
    it('should add channels to profile', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          profiles: { 1: { id: '1', channels: new Set([1]) } },
        });
      });

      act(() => {
        result.current.updateProfileChannels([2, 3], '1', true);
      });

      expect(result.current.profiles['1'].channels.has(2)).toBe(true);
      expect(result.current.profiles['1'].channels.has(3)).toBe(true);
    });

    it('should remove channels from profile', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          profiles: { 1: { id: '1', channels: new Set([1, 2, 3]) } },
        });
      });

      act(() => {
        result.current.updateProfileChannels([2], '1', false);
      });

      expect(result.current.profiles['1'].channels.has(2)).toBe(false);
    });
  });

  describe('setChannelStats', () => {
    it('should update stats and show notifications for new channels', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          channels: { 1: { id: 1, name: 'Channel 1' } },
          channelsByUUID: { 'uuid-1': 1 },
          stats: { channels: [] },
        });
      });

      const newStats = {
        channels: [{ channel_id: 'uuid-1', clients: [] }],
      };

      act(() => {
        result.current.setChannelStats(newStats);
      });

      expect(result.current.stats).toEqual(newStats);
      expect(showNotification).toHaveBeenCalled();
    });
  });

  describe('recordings operations', () => {
    it('should fetch recordings', async () => {
      const mockRecordings = [{ id: 1, title: 'Recording 1' }];
      api.getRecordings.mockResolvedValue(mockRecordings);

      const { result } = renderHook(() => useChannelsStore());

      await act(async () => {
        await result.current.fetchRecordings();
      });

      expect(result.current.recordings).toEqual(mockRecordings);
    });

    it('should remove a recording', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          recordings: [{ id: 1 }, { id: 2 }],
        });
      });

      act(() => {
        result.current.removeRecording(1);
      });

      expect(result.current.recordings).toHaveLength(1);
      expect(result.current.recordings[0].id).toBe(2);
    });
  });

  describe('recurring rules operations', () => {
    it('should fetch recurring rules', async () => {
      const mockRules = [{ id: 1, name: 'Rule 1' }];
      api.listRecurringRules.mockResolvedValue(mockRules);

      const { result } = renderHook(() => useChannelsStore());

      await act(async () => {
        await result.current.fetchRecurringRules();
      });

      expect(result.current.recurringRules).toEqual(mockRules);
    });

    it('should remove a recurring rule', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          recurringRules: [{ id: 1 }, { id: 2 }],
        });
      });

      act(() => {
        result.current.removeRecurringRule(1);
      });

      expect(result.current.recurringRules).toHaveLength(1);
    });
  });

  describe('helper methods', () => {
    it('should validate if channel group can be edited', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          channelGroups: {
            1: { id: 1, canEdit: true },
            2: { id: 2, canEdit: false },
          },
        });
      });

      expect(result.current.canEditChannelGroup(1)).toBe(true);
      expect(result.current.canEditChannelGroup(2)).toBe(false);
    });

    it('should validate if channel group can be deleted', () => {
      const { result } = renderHook(() => useChannelsStore());

      act(() => {
        useChannelsStore.setState({
          channelGroups: {
            1: { id: 1, canDelete: true },
            2: { id: 2, canDelete: false },
          },
        });
      });

      expect(result.current.canDeleteChannelGroup(1)).toBe(true);
      expect(result.current.canDeleteChannelGroup(2)).toBe(false);
    });
  });

  describe('triggerUpdate', () => {
    it('should update forceUpdate timestamp', () => {
      const { result } = renderHook(() => useChannelsStore());
      const initialUpdate = result.current.forceUpdate;

      act(() => {
        result.current.triggerUpdate();
      });

      expect(result.current.forceUpdate).not.toBe(initialUpdate);
    });
  });
});
