import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as StreamsTableUtils from '../StreamsTableUtils';

// ── Dependency mocks ────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    addStreamsToChannel: vi.fn(),
    queryStreamsTable: vi.fn(),
    getStreams: vi.fn(),
    createChannelsFromStreamsAsync: vi.fn(),
    deleteStream: vi.fn(),
    deleteStreams: vi.fn(),
    requeryStreams: vi.fn(),
    createChannelFromStream: vi.fn(),
    getAllStreamIds: vi.fn(),
    getStreamFilterOptions: vi.fn(),
  },
}));

import API from '../../../api.js';

describe('StreamsTableUtils', () => {
  beforeEach(() => vi.clearAllMocks());

  // ── API wrappers ────────────────────────────────────────────────────────────
  describe('API wrappers', () => {
    it('addStreamsToChannel calls API with correct args', () => {
      const mockReturn = Promise.resolve(undefined);
      API.addStreamsToChannel.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.addStreamsToChannel('ch-1', [1], [2, 3]);
      expect(API.addStreamsToChannel).toHaveBeenCalledWith('ch-1', [1], [2, 3]);
      expect(result).toBe(mockReturn);
    });

    it('queryStreamsTable calls API with params', () => {
      const params = new URLSearchParams({ page: '1' });
      const mockReturn = Promise.resolve({ results: [] });
      API.queryStreamsTable.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.queryStreamsTable(params);
      expect(API.queryStreamsTable).toHaveBeenCalledWith(params);
      expect(result).toBe(mockReturn);
    });

    it('getStreams calls API with streamIds', () => {
      const mockReturn = Promise.resolve([]);
      API.getStreams.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.getStreams([10, 20]);
      expect(API.getStreams).toHaveBeenCalledWith([10, 20]);
      expect(result).toBe(mockReturn);
    });

    it('createChannelsFromStreamsAsync calls API with correct args', () => {
      const mockReturn = Promise.resolve(undefined);
      API.createChannelsFromStreamsAsync.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.createChannelsFromStreamsAsync(
        [1, 2],
        [3],
        100
      );
      expect(API.createChannelsFromStreamsAsync).toHaveBeenCalledWith(
        [1, 2],
        [3],
        100
      );
      expect(result).toBe(mockReturn);
    });

    it('deleteStream calls API with id', () => {
      const mockReturn = Promise.resolve(undefined);
      API.deleteStream.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.deleteStream(5);
      expect(API.deleteStream).toHaveBeenCalledWith(5);
      expect(result).toBe(mockReturn);
    });

    it('deleteStreams calls API with ids', () => {
      const mockReturn = Promise.resolve(undefined);
      API.deleteStreams.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.deleteStreams([1, 2, 3]);
      expect(API.deleteStreams).toHaveBeenCalledWith([1, 2, 3]);
      expect(result).toBe(mockReturn);
    });

    it('requeryStreams calls API', () => {
      const mockReturn = Promise.resolve(undefined);
      API.requeryStreams.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.requeryStreams();
      expect(API.requeryStreams).toHaveBeenCalled();
      expect(result).toBe(mockReturn);
    });

    it('createChannelFromStream calls API with values', () => {
      const mockReturn = Promise.resolve({ id: 1 });
      API.createChannelFromStream.mockReturnValue(mockReturn);
      const values = { name: 'New Channel' };
      const result = StreamsTableUtils.createChannelFromStream(values);
      expect(API.createChannelFromStream).toHaveBeenCalledWith(values);
      expect(result).toBe(mockReturn);
    });

    it('getAllStreamIds calls API with params', () => {
      const params = new URLSearchParams();
      const mockReturn = Promise.resolve([1, 2, 3]);
      API.getAllStreamIds.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.getAllStreamIds(params);
      expect(API.getAllStreamIds).toHaveBeenCalledWith(params);
      expect(result).toBe(mockReturn);
    });

    it('getStreamFilterOptions calls API with params', () => {
      const params = new URLSearchParams();
      const mockReturn = Promise.resolve({});
      API.getStreamFilterOptions.mockReturnValue(mockReturn);
      const result = StreamsTableUtils.getStreamFilterOptions(params);
      expect(API.getStreamFilterOptions).toHaveBeenCalledWith(params);
      expect(result).toBe(mockReturn);
    });
  });

  // ── getStatsTooltip ─────────────────────────────────────────────────────────
  describe('getStatsTooltip', () => {
    it('returns "-" compact display for empty stats', () => {
      const { compactDisplay } = StreamsTableUtils.getStatsTooltip({});
      expect(compactDisplay).toBe('-');
    });

    it('returns "No source info available" tooltip for empty stats', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({});
      expect(tooltipContent).toBe('No source info available');
    });

    it('converts resolution "1920x1080" to "1080p" in compact display', () => {
      const { compactDisplay } = StreamsTableUtils.getStatsTooltip({
        resolution: '1920x1080',
      });
      expect(compactDisplay).toBe('1080p');
    });

    it('converts resolution "1280x720" to "720p" in compact display', () => {
      const { compactDisplay } = StreamsTableUtils.getStatsTooltip({
        resolution: '1280x720',
      });
      expect(compactDisplay).toBe('720p');
    });

    it('uppercases video_codec in compact display', () => {
      const { compactDisplay } = StreamsTableUtils.getStatsTooltip({
        video_codec: 'h264',
      });
      expect(compactDisplay).toBe('H264');
    });

    it('combines resolution and video_codec in compact display', () => {
      const { compactDisplay } = StreamsTableUtils.getStatsTooltip({
        resolution: '1920x1080',
        video_codec: 'hevc',
      });
      expect(compactDisplay).toBe('1080p HEVC');
    });

    it('includes Resolution in tooltip when present', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({
        resolution: '1920x1080',
      });
      expect(tooltipContent).toContain('Resolution: 1920x1080');
    });

    it('includes uppercased Video Codec in tooltip', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({
        video_codec: 'h264',
      });
      expect(tooltipContent).toContain('Video Codec: H264');
    });

    it('includes Video Bitrate in tooltip', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({
        video_bitrate: 5000,
      });
      expect(tooltipContent).toContain('Video Bitrate: 5000 kbps');
    });

    it('includes Frame Rate in tooltip', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({
        source_fps: 30,
      });
      expect(tooltipContent).toContain('Frame Rate: 30 FPS');
    });

    it('includes uppercased Audio Codec in tooltip', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({
        audio_codec: 'aac',
      });
      expect(tooltipContent).toContain('Audio Codec: AAC');
    });

    it('includes Audio Channels in tooltip', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({
        audio_channels: 2,
      });
      expect(tooltipContent).toContain('Audio Channels: 2');
    });

    it('includes Audio Bitrate in tooltip', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({
        audio_bitrate: 192,
      });
      expect(tooltipContent).toContain('Audio Bitrate: 192 kbps');
    });

    it('builds multi-line tooltip joined by newlines', () => {
      const { tooltipContent } = StreamsTableUtils.getStatsTooltip({
        resolution: '1920x1080',
        video_codec: 'h264',
        audio_codec: 'aac',
      });
      const lines = tooltipContent.split('\n');
      expect(lines).toHaveLength(3);
    });

    it('handles resolution with no height part gracefully', () => {
      const { compactDisplay } = StreamsTableUtils.getStatsTooltip({
        resolution: 'unknown',
      });
      // No 'x' separator — height is undefined, so no height part added
      expect(compactDisplay).toBe('-');
    });
  });

  // ── appendFetchPageParams ───────────────────────────────────────────────────
  describe('appendFetchPageParams', () => {
    it('appends page incremented by 1 from pageIndex', () => {
      const params = new URLSearchParams();
      StreamsTableUtils.appendFetchPageParams(
        params,
        { pageIndex: 2, pageSize: 25 },
        []
      );
      expect(params.get('page')).toBe('3');
      expect(params.get('page_size')).toBe('25');
    });

    it('does not append ordering when sorting is empty', () => {
      const params = new URLSearchParams();
      StreamsTableUtils.appendFetchPageParams(
        params,
        { pageIndex: 0, pageSize: 50 },
        []
      );
      expect(params.get('ordering')).toBeNull();
    });

    it('appends ascending ordering for known column', () => {
      const params = new URLSearchParams();
      StreamsTableUtils.appendFetchPageParams(
        params,
        { pageIndex: 0, pageSize: 50 },
        [{ id: 'name', desc: false }]
      );
      expect(params.get('ordering')).toBe('name');
    });

    it('appends descending ordering with "-" prefix', () => {
      const params = new URLSearchParams();
      StreamsTableUtils.appendFetchPageParams(
        params,
        { pageIndex: 0, pageSize: 50 },
        [{ id: 'name', desc: true }]
      );
      expect(params.get('ordering')).toBe('-name');
    });

    it('maps "group" column to "channel_group__name"', () => {
      const params = new URLSearchParams();
      StreamsTableUtils.appendFetchPageParams(
        params,
        { pageIndex: 0, pageSize: 50 },
        [{ id: 'group', desc: false }]
      );
      expect(params.get('ordering')).toBe('channel_group__name');
    });

    it('maps "m3u" column to "m3u_account__name"', () => {
      const params = new URLSearchParams();
      StreamsTableUtils.appendFetchPageParams(
        params,
        { pageIndex: 0, pageSize: 50 },
        [{ id: 'm3u', desc: false }]
      );
      expect(params.get('ordering')).toBe('m3u_account__name');
    });

    it('maps "tvg_id" column to "tvg_id"', () => {
      const params = new URLSearchParams();
      StreamsTableUtils.appendFetchPageParams(
        params,
        { pageIndex: 0, pageSize: 50 },
        [{ id: 'tvg_id', desc: false }]
      );
      expect(params.get('ordering')).toBe('tvg_id');
    });

    it('uses column id directly for unmapped columns', () => {
      const params = new URLSearchParams();
      StreamsTableUtils.appendFetchPageParams(
        params,
        { pageIndex: 0, pageSize: 50 },
        [{ id: 'custom_field', desc: false }]
      );
      expect(params.get('ordering')).toBe('custom_field');
    });
  });

  // ── getChannelProfileIds ────────────────────────────────────────────────────
  describe('getChannelProfileIds', () => {
    it('returns [] when profileIds includes "none"', () => {
      expect(StreamsTableUtils.getChannelProfileIds(['none'], '0')).toEqual([]);
    });

    it('returns null when profileIds includes "all"', () => {
      expect(StreamsTableUtils.getChannelProfileIds(['all'], '0')).toBeNull();
    });

    it('returns parsed integer array for specific profile ids', () => {
      expect(
        StreamsTableUtils.getChannelProfileIds(['1', '2', '3'], '0')
      ).toEqual([1, 2, 3]);
    });

    it('returns [selectedProfileId as int] when profileIds is null and selectedProfileId is not "0"', () => {
      expect(StreamsTableUtils.getChannelProfileIds(null, '3')).toEqual([3]);
    });

    it('returns null when profileIds is null and selectedProfileId is "0"', () => {
      expect(StreamsTableUtils.getChannelProfileIds(null, '0')).toBeNull();
    });

    it('returns null when profileIds is undefined and selectedProfileId is "0"', () => {
      expect(StreamsTableUtils.getChannelProfileIds(undefined, '0')).toBeNull();
    });
  });

  // ── getChannelNumberValue ───────────────────────────────────────────────────
  describe('getChannelNumberValue', () => {
    it('returns null for "provider" mode', () => {
      expect(
        StreamsTableUtils.getChannelNumberValue('provider', 100)
      ).toBeNull();
    });

    it('returns 0 for "auto" mode', () => {
      expect(StreamsTableUtils.getChannelNumberValue('auto', 100)).toBe(0);
    });

    it('returns -1 for "highest" mode', () => {
      expect(StreamsTableUtils.getChannelNumberValue('highest', 100)).toBe(-1);
    });

    it('returns startNumber as Number for any other mode', () => {
      expect(StreamsTableUtils.getChannelNumberValue('manual', 42)).toBe(42);
    });

    it('converts string startNumber to number', () => {
      expect(StreamsTableUtils.getChannelNumberValue('manual', '200')).toBe(
        200
      );
    });
  });

  // ── getFilterParams ─────────────────────────────────────────────────────────
  describe('getFilterParams', () => {
    it('returns empty URLSearchParams for empty filters', () => {
      const result = StreamsTableUtils.getFilterParams({});
      expect(result.toString()).toBe('');
    });

    it('appends string filter values', () => {
      const result = StreamsTableUtils.getFilterParams({ name: 'CNN' });
      expect(result.get('name')).toBe('CNN');
    });

    it('appends "true" for boolean true values', () => {
      const result = StreamsTableUtils.getFilterParams({ is_active: true });
      expect(result.get('is_active')).toBe('true');
    });

    it('does not append boolean false values', () => {
      const result = StreamsTableUtils.getFilterParams({ is_active: false });
      expect(result.get('is_active')).toBeNull();
    });

    it('does not append null values', () => {
      const result = StreamsTableUtils.getFilterParams({ name: null });
      expect(result.get('name')).toBeNull();
    });

    it('does not append undefined values', () => {
      const result = StreamsTableUtils.getFilterParams({ name: undefined });
      expect(result.get('name')).toBeNull();
    });

    it('does not append empty string values', () => {
      const result = StreamsTableUtils.getFilterParams({ name: '' });
      expect(result.get('name')).toBeNull();
    });

    it('appends numeric values as strings', () => {
      const result = StreamsTableUtils.getFilterParams({ page: 2 });
      expect(result.get('page')).toBe('2');
    });

    it('handles multiple filters', () => {
      const result = StreamsTableUtils.getFilterParams({
        name: 'ESPN',
        is_active: true,
        group: '',
      });
      expect(result.get('name')).toBe('ESPN');
      expect(result.get('is_active')).toBe('true');
      expect(result.get('group')).toBeNull();
    });
  });
});
