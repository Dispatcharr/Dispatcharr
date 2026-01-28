import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useChannelsTableStore from '../channelsTable';

describe('useChannelsTableStore', () => {
  beforeEach(() => {
    // Mock localStorage
    const mockLocalStorage = {
      getItem: vi.fn(),
      setItem: vi.fn(),
      clear: vi.fn(),
    };
    global.localStorage = mockLocalStorage;

    vi.clearAllMocks();

    // Reset store state between tests
    useChannelsTableStore.setState({
      channels: [],
      pageCount: 0,
      totalCount: 0,
      sorting: [{ id: 'channel_number', desc: false }],
      pagination: {
        pageIndex: 0,
        pageSize: 50,
      },
      selectedChannelIds: [],
      allQueryIds: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('should initialize with default values', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      expect(result.current.channels).toEqual([]);
      expect(result.current.pageCount).toBe(0);
      expect(result.current.totalCount).toBe(0);
      expect(result.current.sorting).toEqual([{ id: 'channel_number', desc: false }]);
      expect(result.current.pagination.pageIndex).toBe(0);
      expect(result.current.pagination.pageSize).toBe(50);
      expect(result.current.selectedChannelIds).toEqual([]);
      expect(result.current.allQueryIds).toEqual([]);
    });
  });

  describe('queryChannels', () => {
    it('should update channels, totalCount, and pageCount', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockResults = [
        { id: 1, name: 'Channel 1' },
        { id: 2, name: 'Channel 2' },
      ];
      const mockData = {
        results: mockResults,
        count: 150,
      };
      const mockParams = new URLSearchParams({ page_size: '50' });

      act(() => {
        result.current.queryChannels(mockData, mockParams);
      });

      expect(result.current.channels).toEqual(mockResults);
      expect(result.current.totalCount).toBe(150);
      expect(result.current.pageCount).toBe(3); // Math.ceil(150 / 50)
    });

    it('should calculate pageCount correctly with different page sizes', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockData = {
        results: [],
        count: 75,
      };
      const mockParams = new URLSearchParams({ page_size: '25' });

      act(() => {
        result.current.queryChannels(mockData, mockParams);
      });

      expect(result.current.pageCount).toBe(3); // Math.ceil(75 / 25)
    });

    it('should handle zero results', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockData = {
        results: [],
        count: 0,
      };
      const mockParams = new URLSearchParams({ page_size: '50' });

      act(() => {
        result.current.queryChannels(mockData, mockParams);
      });

      expect(result.current.channels).toEqual([]);
      expect(result.current.totalCount).toBe(0);
      expect(result.current.pageCount).toBe(0);
    });
  });

  describe('setAllQueryIds', () => {
    it('should update allQueryIds', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockIds = [1, 2, 3, 4, 5];

      act(() => {
        result.current.setAllQueryIds(mockIds);
      });

      expect(result.current.allQueryIds).toEqual(mockIds);
    });

    it('should replace existing allQueryIds', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      act(() => {
        result.current.setAllQueryIds([1, 2, 3]);
      });

      expect(result.current.allQueryIds).toEqual([1, 2, 3]);

      act(() => {
        result.current.setAllQueryIds([4, 5, 6]);
      });

      expect(result.current.allQueryIds).toEqual([4, 5, 6]);
    });
  });

  describe('setSelectedChannelIds', () => {
    it('should update selectedChannelIds', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockIds = [1, 3, 5];

      act(() => {
        result.current.setSelectedChannelIds(mockIds);
      });

      expect(result.current.selectedChannelIds).toEqual(mockIds);
    });

    it('should clear selectedChannelIds when empty array is passed', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      act(() => {
        result.current.setSelectedChannelIds([1, 2, 3]);
      });

      expect(result.current.selectedChannelIds).toEqual([1, 2, 3]);

      act(() => {
        result.current.setSelectedChannelIds([]);
      });

      expect(result.current.selectedChannelIds).toEqual([]);
    });
  });

  describe('getChannelStreams', () => {
    it('should return streams for existing channel', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockChannels = [
        { id: 1, name: 'Channel 1', streams: ['stream1', 'stream2'] },
        { id: 2, name: 'Channel 2', streams: ['stream3'] },
      ];

      act(() => {
        useChannelsTableStore.setState({ channels: mockChannels });
      });

      const streams = result.current.getChannelStreams(1);

      expect(streams).toEqual(['stream1', 'stream2']);
    });

    it('should return empty array for channel without streams', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockChannels = [
        { id: 1, name: 'Channel 1' },
      ];

      act(() => {
        useChannelsTableStore.setState({ channels: mockChannels });
      });

      const streams = result.current.getChannelStreams(1);

      expect(streams).toEqual([]);
    });

    it('should return empty array for non-existent channel', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockChannels = [
        { id: 1, name: 'Channel 1', streams: ['stream1'] },
      ];

      act(() => {
        useChannelsTableStore.setState({ channels: mockChannels });
      });

      const streams = result.current.getChannelStreams(999);

      expect(streams).toEqual([]);
    });
  });

  describe('setPagination', () => {
    it('should update pagination', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const newPagination = {
        pageIndex: 2,
        pageSize: 100,
      };

      act(() => {
        result.current.setPagination(newPagination);
      });

      expect(result.current.pagination).toEqual(newPagination);
    });

    it('should update only changed pagination properties', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      act(() => {
        result.current.setPagination({
          pageIndex: 5,
          pageSize: 50,
        });
      });

      expect(result.current.pagination.pageIndex).toBe(5);
      expect(result.current.pagination.pageSize).toBe(50);
    });
  });

  describe('setSorting', () => {
    it('should update sorting', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const newSorting = [{ id: 'name', desc: true }];

      act(() => {
        result.current.setSorting(newSorting);
      });

      expect(result.current.sorting).toEqual(newSorting);
    });

    it('should handle multiple sorting columns', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const newSorting = [
        { id: 'name', desc: false },
        { id: 'channel_number', desc: true },
      ];

      act(() => {
        result.current.setSorting(newSorting);
      });

      expect(result.current.sorting).toEqual(newSorting);
    });

    it('should clear sorting when empty array is passed', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      act(() => {
        result.current.setSorting([{ id: 'name', desc: true }]);
      });

      expect(result.current.sorting).toHaveLength(1);

      act(() => {
        result.current.setSorting([]);
      });

      expect(result.current.sorting).toEqual([]);
    });
  });

  describe('isUnlocked', () => {
    it('should initialize with default false value', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      expect(result.current.isUnlocked).toBe(false);
    });
  });

  describe('setIsUnlocked', () => {
    it('should update isUnlocked to true', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      act(() => {
        result.current.setIsUnlocked(true);
      });

      expect(result.current.isUnlocked).toBe(true);
    });

    it('should update isUnlocked to false', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      act(() => {
        result.current.setIsUnlocked(true);
      });

      expect(result.current.isUnlocked).toBe(true);

      act(() => {
        result.current.setIsUnlocked(false);
      });

      expect(result.current.isUnlocked).toBe(false);
    });
  });

  describe('updateChannel', () => {
    it('should update an existing channel', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockChannels = [
        { id: 1, name: 'Channel 1', channel_number: 1 },
        { id: 2, name: 'Channel 2', channel_number: 2 },
        { id: 3, name: 'Channel 3', channel_number: 3 },
      ];

      act(() => {
        useChannelsTableStore.setState({ channels: mockChannels });
      });

      const updatedChannel = { id: 2, name: 'Updated Channel 2', channel_number: 22 };

      act(() => {
        result.current.updateChannel(updatedChannel);
      });

      expect(result.current.channels).toEqual([
        { id: 1, name: 'Channel 1', channel_number: 1 },
        { id: 2, name: 'Updated Channel 2', channel_number: 22 },
        { id: 3, name: 'Channel 3', channel_number: 3 },
      ]);
    });

    it('should not modify channels when updating non-existent channel', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockChannels = [
        { id: 1, name: 'Channel 1', channel_number: 1 },
        { id: 2, name: 'Channel 2', channel_number: 2 },
      ];

      act(() => {
        useChannelsTableStore.setState({ channels: mockChannels });
      });

      const updatedChannel = { id: 999, name: 'Non-existent', channel_number: 999 };

      act(() => {
        result.current.updateChannel(updatedChannel);
      });

      expect(result.current.channels).toEqual(mockChannels);
    });

    it('should preserve other channels when updating one channel', () => {
      const { result } = renderHook(() => useChannelsTableStore());

      const mockChannels = [
        { id: 1, name: 'Channel 1', channel_number: 1, streams: ['stream1'] },
        { id: 2, name: 'Channel 2', channel_number: 2, streams: ['stream2'] },
      ];

      act(() => {
        useChannelsTableStore.setState({ channels: mockChannels });
      });

      const updatedChannel = { id: 1, name: 'Updated Channel 1', channel_number: 10 };

      act(() => {
        result.current.updateChannel(updatedChannel);
      });

      expect(result.current.channels[0]).toEqual(updatedChannel);
      expect(result.current.channels[1]).toEqual(mockChannels[1]);
    });
  });
});
