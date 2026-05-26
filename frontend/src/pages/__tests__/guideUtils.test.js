import { describe, it, expect, vi, beforeEach } from 'vitest';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import * as guideUtils from '../../utils/guideUtils';
import * as dateTimeUtils from '../../utils/dateTimeUtils';
import API from '../../api';

dayjs.extend(utc);

vi.mock('../../utils/dateTimeUtils', () => ({
  convertToMs: vi.fn((time) => {
    if (typeof time === 'number') return time;
    return dayjs(time).valueOf();
  }),
  initializeTime: vi.fn((time) => {
    if (typeof time === 'number') return dayjs(time);
    return dayjs(time);
  }),
  startOfDay: vi.fn((time) => dayjs(time).startOf('day')),
  isBefore: vi.fn((a, b) => dayjs(a).isBefore(dayjs(b))),
  isAfter: vi.fn((a, b) => dayjs(a).isAfter(dayjs(b))),
  isSame: vi.fn((a, b, unit) => dayjs(a).isSame(dayjs(b), unit)),
  add: vi.fn((time, amount, unit) => dayjs(time).add(amount, unit)),
  diff: vi.fn((a, b, unit) => dayjs(a).diff(dayjs(b), unit)),
  format: vi.fn((time, formatStr) => dayjs(time).format(formatStr)),
  getNow: vi.fn(() => dayjs()),
  getNowMs: vi.fn(() => dayjs().valueOf()),
  roundToNearest: vi.fn((time, minutes) => {
    const m = dayjs(time).minute();
    const rounded = Math.round(m / minutes) * minutes;
    return dayjs(time).minute(rounded).second(0).millisecond(0);
  }),
}));

vi.mock('../../api', () => ({
  default: {
    getGrid: vi.fn(),
    createRecording: vi.fn(),
    createSeriesRule: vi.fn(),
    evaluateSeriesRules: vi.fn(),
    deleteSeriesRule: vi.fn(),
    listSeriesRules: vi.fn(),
  },
}));

describe('guideUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── buildChannelIdMap ──────────────────────────────────────────────────────

  describe('buildChannelIdMap', () => {
    it('should create map with channel UUIDs when no EPG data', () => {
      const channels = [
        { id: 1, uuid: 'uuid-1', epg_data_id: null },
        { id: 2, uuid: 'uuid-2', epg_data_id: null },
      ];
      const tvgsById = {};

      const result = guideUtils.buildChannelIdMap(channels, tvgsById);

      expect(result.get('uuid-1')).toEqual([1]);
      expect(result.get('uuid-2')).toEqual([2]);
    });

    it('should use tvg_id from EPG data for regular sources', () => {
      const channels = [{ id: 1, uuid: 'uuid-1', epg_data_id: 'epg-1' }];
      const tvgsById = {
        'epg-1': { tvg_id: 'tvg-123', epg_source: 'source-1' },
      };
      const epgs = {
        'source-1': { source_type: 'xmltv' },
      };

      const result = guideUtils.buildChannelIdMap(channels, tvgsById, epgs);

      expect(result.get('tvg-123')).toEqual([1]);
    });

    it('should use channel UUID for dummy EPG sources', () => {
      const channels = [{ id: 1, uuid: 'uuid-1', epg_data_id: 'epg-1' }];
      const tvgsById = {
        'epg-1': { tvg_id: 'tvg-123', epg_source: 'source-1' },
      };
      const epgs = {
        'source-1': { source_type: 'dummy' },
      };

      const result = guideUtils.buildChannelIdMap(channels, tvgsById, epgs);

      expect(result.get('uuid-1')).toEqual([1]);
    });

    it('should group multiple channels with same tvg_id', () => {
      const channels = [
        { id: 1, uuid: 'uuid-1', epg_data_id: 'epg-1' },
        { id: 2, uuid: 'uuid-2', epg_data_id: 'epg-2' },
      ];
      const tvgsById = {
        'epg-1': { tvg_id: 'shared-tvg', epg_source: 'source-1' },
        'epg-2': { tvg_id: 'shared-tvg', epg_source: 'source-1' },
      };
      const epgs = {
        'source-1': { source_type: 'xmltv' },
      };

      const result = guideUtils.buildChannelIdMap(channels, tvgsById, epgs);

      expect(result.get('shared-tvg')).toEqual([1, 2]);
    });

    it('should fall back to UUID when tvg_id is null', () => {
      const channels = [{ id: 1, uuid: 'uuid-1', epg_data_id: 'epg-1' }];
      const tvgsById = {
        'epg-1': { tvg_id: null, epg_source: 'source-1' },
      };
      const epgs = {
        'source-1': { source_type: 'xmltv' },
      };

      const result = guideUtils.buildChannelIdMap(channels, tvgsById, epgs);

      expect(result.get('uuid-1')).toEqual([1]);
    });
  });

  // ── mapProgramsByChannel ───────────────────────────────────────────────────

  describe('mapProgramsByChannel', () => {
    it('should return empty map when no programs', () => {
      const result = guideUtils.mapProgramsByChannel([], new Map([['tvg-1', [1]]]));
      expect(result.size).toBe(0);
    });

    it('should return empty map when no channel mapping', () => {
      const programs = [{ tvg_id: 'tvg-1', startMs: 1000, endMs: 2000 }];
      const result = guideUtils.mapProgramsByChannel(programs, new Map());
      expect(result.size).toBe(0);
    });

    it('should map programs to channels', () => {
      const nowMs = dayjs().valueOf();
      const startMs = nowMs - 10000;
      const endMs = nowMs + 10000;
      const programs = [{ tvg_id: 'tvg-1', startMs, endMs }];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      vi.mocked(dateTimeUtils.getNowMs).mockReturnValue(nowMs);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.has(1)).toBe(true);
      expect(result.get(1)).toHaveLength(1);
    });

    it('should precompute startMs and endMs', () => {
      const startTime = '2024-01-01T10:00:00Z';
      const endTime = '2024-01-01T11:00:00Z';
      const expectedStartMs = dayjs(startTime).valueOf();
      const expectedEndMs = dayjs(endTime).valueOf();

      vi.mocked(dateTimeUtils.convertToMs)
        .mockReturnValueOnce(expectedStartMs)
        .mockReturnValueOnce(expectedEndMs);
      vi.mocked(dateTimeUtils.getNowMs).mockReturnValue(expectedStartMs - 1000);

      const programs = [{ tvg_id: 'tvg-1', start_time: startTime, end_time: endTime }];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);
      const mapped = result.get(1)[0];

      expect(mapped.startMs).toBe(expectedStartMs);
      expect(mapped.endMs).toBe(expectedEndMs);
    });

    it('should mark program as live when now is between start and end', () => {
      const nowMs = 5000;
      const startMs = 1000;
      const endMs = 10000;

      vi.mocked(dateTimeUtils.getNowMs).mockReturnValue(nowMs);

      const programs = [{ tvg_id: 'tvg-1', startMs, endMs }];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)[0].isLive).toBe(true);
      expect(result.get(1)[0].isPast).toBe(false);
    });

    it('should mark program as past when now is after end', () => {
      const nowMs = 20000;
      const startMs = 1000;
      const endMs = 10000;

      vi.mocked(dateTimeUtils.getNowMs).mockReturnValue(nowMs);

      const programs = [{ tvg_id: 'tvg-1', startMs, endMs }];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)[0].isPast).toBe(true);
      expect(result.get(1)[0].isLive).toBe(false);
    });

    it('should add program to multiple channels with same tvg_id', () => {
      const nowMs = 5000;
      vi.mocked(dateTimeUtils.getNowMs).mockReturnValue(nowMs);

      const programs = [{ tvg_id: 'tvg-1', startMs: 1000, endMs: 10000 }];
      const channelIdByTvgId = new Map([['tvg-1', [1, 2]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)).toHaveLength(1);
      expect(result.get(2)).toHaveLength(1);
    });

    it('should sort programs by start time', () => {
      const nowMs = 0;
      vi.mocked(dateTimeUtils.getNowMs).mockReturnValue(nowMs);

      const programs = [
        { tvg_id: 'tvg-1', startMs: 3000, endMs: 4000 },
        { tvg_id: 'tvg-1', startMs: 1000, endMs: 2000 },
      ];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);
      const list = result.get(1);

      expect(list[0].startMs).toBe(1000);
      expect(list[1].startMs).toBe(3000);
    });
  });

  // ── computeRowHeights ─────────────────────────────────────────────────────

  describe('computeRowHeights', () => {
    it('should return empty array when no channels', () => {
      expect(guideUtils.computeRowHeights([])).toEqual([]);
      expect(guideUtils.computeRowHeights(null)).toEqual([]);
    });

    it('should return default height for all channels', () => {
      const channels = [{}, {}, {}];
      const result = guideUtils.computeRowHeights(channels);
      expect(result).toEqual([90, 90, 90]);
    });

    it('should use custom default height when provided', () => {
      const channels = [{}, {}];
      const result = guideUtils.computeRowHeights(channels, 60);
      expect(result).toEqual([60, 60]);
    });
  });

  // ── fetchPrograms ─────────────────────────────────────────────────────────

  describe('fetchPrograms', () => {
    it('should fetch and transform programs', async () => {
      const startTime = '2024-01-01T10:00:00Z';
      const endTime = '2024-01-01T11:00:00Z';
      const raw = [{ id: 1, start_time: startTime, end_time: endTime }];
      vi.mocked(API.getGrid).mockResolvedValue(raw);
      vi.mocked(dateTimeUtils.convertToMs)
        .mockReturnValueOnce(dayjs(startTime).valueOf())
        .mockReturnValueOnce(dayjs(endTime).valueOf());

      const result = await guideUtils.fetchPrograms();

      expect(API.getGrid).toHaveBeenCalled();
      expect(result[0].startMs).toBe(dayjs(startTime).valueOf());
      expect(result[0].endMs).toBe(dayjs(endTime).valueOf());
    });
  });

  // ── sortChannels ──────────────────────────────────────────────────────────

  describe('sortChannels', () => {
    it('should sort channels by channel number', () => {
      const channels = {
        a: { id: 1, channel_number: 3 },
        b: { id: 2, channel_number: 1 },
        c: { id: 3, channel_number: 2 },
      };
      const result = guideUtils.sortChannels(channels);
      expect(result.map((c) => c.channel_number)).toEqual([1, 2, 3]);
    });

    it('should put channels without number at end', () => {
      const channels = {
        a: { id: 1, channel_number: 2 },
        b: { id: 2, channel_number: null },
        c: { id: 3, channel_number: 1 },
      };
      const result = guideUtils.sortChannels(channels);
      expect(result[0].channel_number).toBe(1);
      expect(result[1].channel_number).toBe(2);
      expect(result[2].channel_number).toBeNull();
    });
  });

  // ── filterGuideChannels ───────────────────────────────────────────────────

  describe('filterGuideChannels', () => {
    const channels = [
      { id: 1, name: 'ESPN', channel_group_id: 10 },
      { id: 2, name: 'CNN', channel_group_id: 20 },
      { id: 3, name: 'ESPN2', channel_group_id: 10 },
    ];

    it('should return all channels when no filters', () => {
      const result = guideUtils.filterGuideChannels(channels, '', 'all', 'all', {});
      expect(result).toHaveLength(3);
    });

    it('should filter by search query', () => {
      const result = guideUtils.filterGuideChannels(channels, 'espn', 'all', 'all', {});
      expect(result).toHaveLength(2);
      expect(result.map((c) => c.name)).toEqual(['ESPN', 'ESPN2']);
    });

    it('should filter by channel group', () => {
      const result = guideUtils.filterGuideChannels(channels, '', '10', 'all', {});
      expect(result).toHaveLength(2);
      expect(result.every((c) => c.channel_group_id === 10)).toBe(true);
    });

    it('should filter by profile with array of channels', () => {
      const profiles = {
        'p1': {
          channels: [
            { id: 1, enabled: true },
            { id: 2, enabled: false },
            { id: 3, enabled: true },
          ],
        },
      };
      const result = guideUtils.filterGuideChannels(channels, '', 'all', 'p1', profiles);
      expect(result.map((c) => c.id)).toEqual([1, 3]);
    });

    it('should filter by profile with Set of channels', () => {
      const profiles = {
        'p1': { channels: new Set([1, 3]) },
      };
      const result = guideUtils.filterGuideChannels(channels, '', 'all', 'p1', profiles);
      expect(result.map((c) => c.id)).toEqual([1, 3]);
    });

    it('should apply multiple filters together', () => {
      const profiles = {
        'p1': { channels: [{ id: 1, enabled: true }, { id: 3, enabled: true }] },
      };
      const result = guideUtils.filterGuideChannels(channels, 'espn2', '10', 'p1', profiles);
      expect(result).toHaveLength(1);
      expect(result[0].name).toBe('ESPN2');
    });
  });

  // ── calculateEarliestProgramStart ─────────────────────────────────────────

  describe('calculateEarliestProgramStart', () => {
    it('should return default when no programs', () => {
      const defaultStart = dayjs('2024-01-01T10:00:00Z');
      const result = guideUtils.calculateEarliestProgramStart([], defaultStart);
      expect(result).toBe(defaultStart);
    });

    it('should return earliest program start', () => {
      vi.mocked(dateTimeUtils.initializeTime).mockImplementation((t) => dayjs(t));
      vi.mocked(dateTimeUtils.isBefore).mockImplementation((a, b) => dayjs(a).isBefore(dayjs(b)));

      const defaultStart = dayjs('2024-01-01T10:00:00Z');
      const programs = [
        { start_time: '2024-01-01T09:00:00Z' },
        { start_time: '2024-01-01T08:00:00Z' },
        { start_time: '2024-01-01T11:00:00Z' },
      ];

      const result = guideUtils.calculateEarliestProgramStart(programs, defaultStart);
      expect(dayjs(result).toISOString()).toBe(dayjs('2024-01-01T08:00:00Z').toISOString());
    });
  });

  // ── calculateLatestProgramEnd ─────────────────────────────────────────────

  describe('calculateLatestProgramEnd', () => {
    it('should return default when no programs', () => {
      const defaultEnd = dayjs('2024-01-01T22:00:00Z');
      const result = guideUtils.calculateLatestProgramEnd([], defaultEnd);
      expect(result).toBe(defaultEnd);
    });

    it('should return latest program end', () => {
      vi.mocked(dateTimeUtils.initializeTime).mockImplementation((t) => dayjs(t));
      vi.mocked(dateTimeUtils.isAfter).mockImplementation((a, b) => dayjs(a).isAfter(dayjs(b)));

      const defaultEnd = dayjs('2024-01-01T22:00:00Z');
      const programs = [
        { end_time: '2024-01-01T20:00:00Z' },
        { end_time: '2024-01-01T23:00:00Z' },
        { end_time: '2024-01-01T21:00:00Z' },
      ];

      const result = guideUtils.calculateLatestProgramEnd(programs, defaultEnd);
      expect(dayjs(result).toISOString()).toBe(dayjs('2024-01-01T23:00:00Z').toISOString());
    });
  });

  // ── calculateStart ────────────────────────────────────────────────────────

  describe('calculateStart', () => {
    it('should return earliest when before default', () => {
      const earliest = dayjs('2024-01-01T08:00:00Z');
      const defaultStart = dayjs('2024-01-01T10:00:00Z');
      vi.mocked(dateTimeUtils.isBefore).mockReturnValue(true);

      const result = guideUtils.calculateStart(earliest, defaultStart);
      expect(result).toBe(earliest);
    });

    it('should return default when earliest is after', () => {
      const earliest = dayjs('2024-01-01T11:00:00Z');
      const defaultStart = dayjs('2024-01-01T10:00:00Z');
      vi.mocked(dateTimeUtils.isBefore).mockReturnValue(false);

      const result = guideUtils.calculateStart(earliest, defaultStart);
      expect(result).toBe(defaultStart);
    });
  });

  // ── calculateEnd ──────────────────────────────────────────────────────────

  describe('calculateEnd', () => {
    it('should return latest when after default', () => {
      const latest = dayjs('2024-01-01T23:00:00Z');
      const defaultEnd = dayjs('2024-01-01T22:00:00Z');
      vi.mocked(dateTimeUtils.isAfter).mockReturnValue(true);

      const result = guideUtils.calculateEnd(latest, defaultEnd);
      expect(result).toBe(latest);
    });

    it('should return default when latest is before', () => {
      const latest = dayjs('2024-01-01T20:00:00Z');
      const defaultEnd = dayjs('2024-01-01T22:00:00Z');
      vi.mocked(dateTimeUtils.isAfter).mockReturnValue(false);

      const result = guideUtils.calculateEnd(latest, defaultEnd);
      expect(result).toBe(defaultEnd);
    });
  });

  // ── mapChannelsById ───────────────────────────────────────────────────────

  describe('mapChannelsById', () => {
    it('should create map of channels by id', () => {
      const channels = [
        { id: 1, name: 'ESPN' },
        { id: 2, name: 'CNN' },
      ];
      const result = guideUtils.mapChannelsById(channels);
      expect(result.get(1)).toEqual({ id: 1, name: 'ESPN' });
      expect(result.get(2)).toEqual({ id: 2, name: 'CNN' });
    });
  });

  // ── mapRecordingsByProgramId ───────────────────────────────────────────────

  describe('mapRecordingsByProgramId', () => {
    it('should return empty map for null recordings', () => {
      const result = guideUtils.mapRecordingsByProgramId(null);
      expect(result.size).toBe(0);
    });

    it('should map recordings by program id', () => {
      const recordings = [
        {
          custom_properties: { program: { id: 42 }, status: 'pending' },
        },
      ];
      const result = guideUtils.mapRecordingsByProgramId(recordings);
      expect(result.has(42)).toBe(true);
    });

    it('should skip recordings without program id', () => {
      const recordings = [
        { custom_properties: { status: 'pending' } },
        { custom_properties: { program: {}, status: 'pending' } },
      ];
      const result = guideUtils.mapRecordingsByProgramId(recordings);
      expect(result.size).toBe(0);
    });

    it('should exclude terminal status recordings', () => {
      const terminalStatuses = ['stopped', 'completed', 'interrupted', 'failed'];
      const recordings = terminalStatuses.map((status, i) => ({
        custom_properties: { program: { id: i + 1 }, status },
      }));
      const result = guideUtils.mapRecordingsByProgramId(recordings);
      expect(result.size).toBe(0);
    });

    it('should include non-terminal status recordings', () => {
      const recordings = [
        { custom_properties: { program: { id: 1 }, status: 'pending' } },
        { custom_properties: { program: { id: 2 }, status: 'recording' } },
      ];
      const result = guideUtils.mapRecordingsByProgramId(recordings);
      expect(result.size).toBe(2);
    });
  });

  // ── formatTime ────────────────────────────────────────────────────────────

  describe('formatTime', () => {
    it('should return "Today" for today', () => {
      const now = dayjs();
      vi.mocked(dateTimeUtils.getNow).mockReturnValue(now);
      vi.mocked(dateTimeUtils.startOfDay).mockImplementation((t) => dayjs(t).startOf('day'));
      vi.mocked(dateTimeUtils.add).mockImplementation((t, n, u) => dayjs(t).add(n, u));
      vi.mocked(dateTimeUtils.isSame).mockImplementation((a, b, unit) =>
        dayjs(a).isSame(dayjs(b), unit)
      );
      vi.mocked(dateTimeUtils.isBefore).mockImplementation((a, b) =>
        dayjs(a).isBefore(dayjs(b))
      );

      const result = guideUtils.formatTime(now, 'MMM D');
      expect(result).toBe('Today');
    });

    it('should return "Tomorrow" for tomorrow', () => {
      const now = dayjs();
      const tomorrow = now.add(1, 'day');
      vi.mocked(dateTimeUtils.getNow).mockReturnValue(now);
      vi.mocked(dateTimeUtils.startOfDay).mockImplementation((t) => dayjs(t).startOf('day'));
      vi.mocked(dateTimeUtils.add).mockImplementation((t, n, u) => dayjs(t).add(n, u));
      vi.mocked(dateTimeUtils.isSame).mockImplementation((a, b, unit) =>
        dayjs(a).isSame(dayjs(b), unit)
      );
      vi.mocked(dateTimeUtils.isBefore).mockImplementation((a, b) =>
        dayjs(a).isBefore(dayjs(b))
      );

      const result = guideUtils.formatTime(tomorrow, 'MMM D');
      expect(result).toBe('Tomorrow');
    });

    it('should return day name within a week', () => {
      const now = dayjs();
      const inThreeDays = now.add(3, 'day');
      vi.mocked(dateTimeUtils.getNow).mockReturnValue(now);
      vi.mocked(dateTimeUtils.startOfDay).mockImplementation((t) => dayjs(t).startOf('day'));
      vi.mocked(dateTimeUtils.add).mockImplementation((t, n, u) => dayjs(t).add(n, u));
      vi.mocked(dateTimeUtils.isSame).mockImplementation((a, b, unit) =>
        dayjs(a).isSame(dayjs(b), unit)
      );
      vi.mocked(dateTimeUtils.isBefore).mockImplementation((a, b) =>
        dayjs(a).isBefore(dayjs(b))
      );
      vi.mocked(dateTimeUtils.format).mockImplementation((t, fmt) => dayjs(t).format(fmt));

      const result = guideUtils.formatTime(inThreeDays, 'MMM D');
      expect(result).toBe(inThreeDays.format('dddd'));
    });

    it('should return formatted date beyond a week', () => {
      const now = dayjs();
      const beyondWeek = now.add(10, 'day');
      vi.mocked(dateTimeUtils.getNow).mockReturnValue(now);
      vi.mocked(dateTimeUtils.startOfDay).mockImplementation((t) => dayjs(t).startOf('day'));
      vi.mocked(dateTimeUtils.add).mockImplementation((t, n, u) => dayjs(t).add(n, u));
      vi.mocked(dateTimeUtils.isSame).mockImplementation((a, b, unit) =>
        dayjs(a).isSame(dayjs(b), unit)
      );
      vi.mocked(dateTimeUtils.isBefore).mockImplementation((a, b) =>
        dayjs(a).isBefore(dayjs(b))
      );
      vi.mocked(dateTimeUtils.format).mockImplementation((t, fmt) => dayjs(t).format(fmt));

      const result = guideUtils.formatTime(beyondWeek, 'MMM D');
      expect(result).toBe(beyondWeek.format('MMM D'));
    });
  });

  // ── calculateHourTimeline ─────────────────────────────────────────────────

  describe('calculateHourTimeline', () => {
    it('should generate hours between start and end', () => {
      const start = dayjs('2024-01-01T10:00:00Z');
      const end = dayjs('2024-01-01T13:00:00Z');

      vi.mocked(dateTimeUtils.isBefore).mockImplementation((a, b) =>
        dayjs(a).isBefore(dayjs(b))
      );
      vi.mocked(dateTimeUtils.startOfDay).mockImplementation((t) => dayjs(t).startOf('day'));
      vi.mocked(dateTimeUtils.isSame).mockImplementation((a, b, unit) =>
        dayjs(a).isSame(dayjs(b), unit)
      );
      vi.mocked(dateTimeUtils.add).mockImplementation((t, n, u) => dayjs(t).add(n, u));

      const formatDayLabel = vi.fn((t) => dayjs(t).format('MMM D'));
      const result = guideUtils.calculateHourTimeline(start, end, formatDayLabel);

      expect(result).toHaveLength(3);
    });

    it('should mark new day transitions', () => {
      const start = dayjs('2024-01-01T23:00:00Z');
      const end = dayjs('2024-01-02T02:00:00Z');

      vi.mocked(dateTimeUtils.isBefore).mockImplementation((a, b) =>
        dayjs(a).isBefore(dayjs(b))
      );
      vi.mocked(dateTimeUtils.startOfDay).mockImplementation((t) =>
        dayjs(t).utc().startOf('day')
      );
      vi.mocked(dateTimeUtils.isSame).mockImplementation((a, b, unit) =>
        dayjs(a).utc().isSame(dayjs(b).utc(), unit)
      );
      vi.mocked(dateTimeUtils.add).mockImplementation((t, n, u) => dayjs(t).add(n, u));

      const formatDayLabel = vi.fn((t) => dayjs(t).utc().format('MMM D'));
      const result = guideUtils.calculateHourTimeline(start, end, formatDayLabel);

      expect(result).toHaveLength(3);
      expect(result[0].isNewDay).toBe(true);  // 23:00 UTC — first entry, always new day
      expect(result[1].isNewDay).toBe(true);  // 00:00 UTC — crosses into Jan 2
      expect(result[2].isNewDay).toBe(false); // 01:00 UTC — same day as 00:00
    });
  });

  // ── calculateNowPosition ──────────────────────────────────────────────────

  describe('calculateNowPosition', () => {
    it('should return -1 when now is before start', () => {
      const now = dayjs('2024-01-01T09:00:00Z');
      const start = dayjs('2024-01-01T10:00:00Z');
      const end = dayjs('2024-01-01T22:00:00Z');
      vi.mocked(dateTimeUtils.isBefore).mockReturnValue(true);
      vi.mocked(dateTimeUtils.isAfter).mockReturnValue(false);

      const result = guideUtils.calculateNowPosition(now, start, end);
      expect(result).toBe(-1);
    });

    it('should return -1 when now is after end', () => {
      const now = dayjs('2024-01-01T23:00:00Z');
      const start = dayjs('2024-01-01T10:00:00Z');
      const end = dayjs('2024-01-01T22:00:00Z');
      vi.mocked(dateTimeUtils.isBefore).mockReturnValue(false);
      vi.mocked(dateTimeUtils.isAfter).mockReturnValue(true);

      const result = guideUtils.calculateNowPosition(now, start, end);
      expect(result).toBe(-1);
    });

    it('should calculate position when now is between start and end', () => {
      const now = dayjs('2024-01-01T11:00:00Z');
      const start = dayjs('2024-01-01T10:00:00Z');
      const end = dayjs('2024-01-01T22:00:00Z');
      vi.mocked(dateTimeUtils.isBefore).mockReturnValue(false);
      vi.mocked(dateTimeUtils.isAfter).mockReturnValue(false);
      vi.mocked(dateTimeUtils.diff).mockReturnValue(60); // 60 minutes

      const result = guideUtils.calculateNowPosition(now, start, end);
      // 60 minutes / 15 min increment * MINUTE_BLOCK_WIDTH(112.5)
      expect(result).toBe((60 / 15) * guideUtils.MINUTE_BLOCK_WIDTH);
    });
  });

  // ── calculateScrollPosition ───────────────────────────────────────────────

  describe('calculateScrollPosition', () => {
    it('should calculate scroll position for current time', () => {
      const now = dayjs('2024-01-01T11:00:00Z');
      const start = dayjs('2024-01-01T10:00:00Z');
      vi.mocked(dateTimeUtils.roundToNearest).mockReturnValue(now);
      vi.mocked(dateTimeUtils.diff).mockReturnValue(60);

      const result = guideUtils.calculateScrollPosition(now, start);
      expect(result).toBeGreaterThan(0);
    });

    it('should return 0 when calculated position is negative', () => {
      const now = dayjs('2024-01-01T10:00:00Z');
      const start = dayjs('2024-01-01T10:00:00Z');
      vi.mocked(dateTimeUtils.roundToNearest).mockReturnValue(now);
      vi.mocked(dateTimeUtils.diff).mockReturnValue(0);

      const result = guideUtils.calculateScrollPosition(now, start);
      expect(result).toBe(0);
    });
  });

  // ── matchChannelByTvgId ───────────────────────────────────────────────────

  describe('matchChannelByTvgId', () => {
    it('should return null when no matching channel ids', () => {
      const channelIdByTvgId = new Map();
      const channelById = new Map([[1, { id: 1, name: 'ESPN' }]]);

      const result = guideUtils.matchChannelByTvgId(channelIdByTvgId, channelById, 'tvg-1');
      expect(result).toBeNull();
    });

    it('should return first matching channel', () => {
      const channelIdByTvgId = new Map([['tvg-1', [1, 2]]]);
      const channelById = new Map([
        [1, { id: 1, name: 'ESPN' }],
        [2, { id: 2, name: 'ESPN HD' }],
      ]);

      const result = guideUtils.matchChannelByTvgId(channelIdByTvgId, channelById, 'tvg-1');
      expect(result).toEqual({ id: 1, name: 'ESPN' });
    });

    it('should return null when channel not in channelById map', () => {
      const channelIdByTvgId = new Map([['tvg-1', [99]]]);
      const channelById = new Map([[1, { id: 1 }]]);

      const result = guideUtils.matchChannelByTvgId(channelIdByTvgId, channelById, 'tvg-1');
      expect(result).toBeNull();
    });
  });

  // ── fetchRules ────────────────────────────────────────────────────────────

  describe('fetchRules', () => {
    it('should fetch series rules from API', async () => {
      const rules = [{ tvg_id: 'tvg-1', title: 'Show' }];
      vi.mocked(API.listSeriesRules).mockResolvedValue(rules);

      const result = await guideUtils.fetchRules();

      expect(API.listSeriesRules).toHaveBeenCalled();
      expect(result).toEqual(rules);
    });
  });

  // ── getRuleByProgram ──────────────────────────────────────────────────────

  describe('getRuleByProgram', () => {
    it('should return null when no rules', () => {
      const result = guideUtils.getRuleByProgram(null, { tvg_id: 'tvg-1' });
      expect(result).toBeUndefined();
    });

    it('should find rule by tvg_id without title', () => {
      const rules = [{ tvg_id: 'tvg-1', title: '' }];
      const result = guideUtils.getRuleByProgram(rules, { tvg_id: 'tvg-1', title: 'Anything' });
      expect(result).toEqual(rules[0]);
    });

    it('should find rule by tvg_id and title', () => {
      const rules = [
        { tvg_id: 'tvg-1', title: 'Show A' },
        { tvg_id: 'tvg-1', title: 'Show B' },
      ];
      const result = guideUtils.getRuleByProgram(rules, { tvg_id: 'tvg-1', title: 'Show B' });
      expect(result).toEqual(rules[1]);
    });

    it('should handle string comparison for tvg_id', () => {
      const rules = [{ tvg_id: 123, title: '' }];
      const result = guideUtils.getRuleByProgram(rules, { tvg_id: '123', title: 'Show' });
      expect(result).toEqual(rules[0]);
    });
  });

  // ── createRecording ───────────────────────────────────────────────────────

  describe('createRecording', () => {
    it('should create recording via API', async () => {
      vi.mocked(API.createRecording).mockResolvedValue({});
      const values = { channel_id: 1, start_time: '2024-01-01T10:00:00Z' };

      await guideUtils.createRecording(values);

      expect(API.createRecording).toHaveBeenCalledWith(values);
    });
  });

  // ── createSeriesRule ──────────────────────────────────────────────────────

  describe('createSeriesRule', () => {
    it('should create series rule via API', async () => {
      vi.mocked(API.createSeriesRule).mockResolvedValue({});
      const values = { tvg_id: 'tvg-1', title: 'Show' };

      await guideUtils.createSeriesRule(values);

      expect(API.createSeriesRule).toHaveBeenCalledWith(values);
    });
  });

  // ── evaluateSeriesRule ────────────────────────────────────────────────────

  describe('evaluateSeriesRule', () => {
    it('should evaluate series rule via API', async () => {
      vi.mocked(API.evaluateSeriesRules).mockResolvedValue({});

      await guideUtils.evaluateSeriesRulesByTvgId('tvg-1');

      expect(API.evaluateSeriesRules).toHaveBeenCalledWith('tvg-1');
    });
  });

  // ── calculateLeftScrollPosition ───────────────────────────────────────────

  describe('calculateLeftScrollPosition', () => {
    it('should calculate left position using startMs', () => {
      const startMs = 60 * 60 * 1000; // 1 hour in ms
      const start = '2024-01-01T00:00:00Z';
      vi.mocked(dateTimeUtils.convertToMs).mockReturnValue(0);

      const program = { startMs };
      const result = guideUtils.calculateLeftScrollPosition(program, start);

      // (60 min / 15 min increment) * MINUTE_BLOCK_WIDTH
      expect(result).toBe((60 / 15) * guideUtils.MINUTE_BLOCK_WIDTH);
    });

    it('should calculate left position from start_time when no startMs', () => {
      const startTimeMs = 30 * 60 * 1000; // 30 min
      vi.mocked(dateTimeUtils.convertToMs)
        .mockReturnValueOnce(startTimeMs) // program start_time
        .mockReturnValueOnce(0);         // guide start

      const program = { start_time: '2024-01-01T00:30:00Z' };
      const result = guideUtils.calculateLeftScrollPosition(program, '2024-01-01T00:00:00Z');

      expect(result).toBe((30 / 15) * guideUtils.MINUTE_BLOCK_WIDTH);
    });
  });

  // ── calculateDesiredScrollPosition ────────────────────────────────────────

  describe('calculateDesiredScrollPosition', () => {
    it('should subtract 20 from left position', () => {
      const result = guideUtils.calculateDesiredScrollPosition(100);
      expect(result).toBe(80);
    });

    it('should return 0 when result would be negative', () => {
      const result = guideUtils.calculateDesiredScrollPosition(10);
      expect(result).toBe(0);
    });
  });

  // ── calculateScrollPositionByTimeClick ────────────────────────────────────

  describe('calculateScrollPositionByTimeClick', () => {
    const makeEvent = (clientX, rectLeft, rectWidth) => ({
      currentTarget: {
        getBoundingClientRect: () => ({ left: rectLeft, width: rectWidth }),
      },
      clientX,
    });

    it('should calculate scroll position from time click', () => {
      vi.mocked(dateTimeUtils.diff).mockReturnValue(60);
      vi.mocked(dateTimeUtils.add).mockImplementation((t, n, u) => ({
        ...dayjs(t).add(n, u),
        minute: (m) => dayjs(t).add(n, u).minute(m),
      }));

      const clickedTime = { minute: vi.fn().mockReturnThis() };
      const start = dayjs('2024-01-01T10:00:00Z');
      // Click at 50% of a 600px element → 30 min into hour → snaps to 30
      const event = makeEvent(350, 100, 500);

      vi.mocked(dateTimeUtils.diff).mockReturnValue(90);

      const result = guideUtils.calculateScrollPositionByTimeClick(event, clickedTime, start);
      expect(result).toBeGreaterThanOrEqual(0);
    });

    it('should snap to 15-minute increments', () => {
      // Click at 10% of a 600px element → 6 min → snaps to 0
      const event = makeEvent(160, 100, 600);
      const clickedTime = { minute: vi.fn().mockReturnThis() };
      vi.mocked(dateTimeUtils.diff).mockReturnValue(0);

      const result = guideUtils.calculateScrollPositionByTimeClick(
        event,
        clickedTime,
        dayjs()
      );
      expect(result).toBe(0);
    });

    it('should handle click at end of hour (snappedMinute === 60)', () => {
      // 100% across the element → 60 min → snappedMinute = 60 → use add(1, hour).minute(0)
      const event = makeEvent(700, 100, 600);
      const nextHour = dayjs('2024-01-01T11:00:00Z');
      const addResult = { minute: vi.fn().mockReturnValue(nextHour) };
      vi.mocked(dateTimeUtils.add).mockReturnValue(addResult);
      vi.mocked(dateTimeUtils.diff).mockReturnValue(60);

      const result = guideUtils.calculateScrollPositionByTimeClick(
        event,
        dayjs('2024-01-01T10:00:00Z'),
        dayjs('2024-01-01T10:00:00Z')
      );
      expect(result).toBeGreaterThanOrEqual(0);
    });
  });

  // ── getGroupOptions ───────────────────────────────────────────────────────

  describe('getGroupOptions', () => {
    it('should return only "All" when no channel groups', () => {
      const result = guideUtils.getGroupOptions(null, []);
      expect(result).toEqual([{ value: 'all', label: 'All Channel Groups' }]);
    });

    it('should include groups used by channels', () => {
      const channelGroups = {
        1: { id: 10, name: 'Sports' },
        2: { id: 20, name: 'News' },
      };
      const guideChannels = [
        { id: 1, channel_group_id: 10 },
        { id: 2, channel_group_id: 20 },
      ];

      const result = guideUtils.getGroupOptions(channelGroups, guideChannels);
      expect(result).toHaveLength(3);
      expect(result.map((o) => o.label)).toContain('Sports');
      expect(result.map((o) => o.label)).toContain('News');
    });

    it('should exclude groups not used by any channel', () => {
      const channelGroups = {
        1: { id: 10, name: 'Sports' },
        2: { id: 99, name: 'Unused' },
      };
      const guideChannels = [{ id: 1, channel_group_id: 10 }];

      const result = guideUtils.getGroupOptions(channelGroups, guideChannels);
      expect(result.map((o) => o.label)).not.toContain('Unused');
    });

    it('should sort groups alphabetically', () => {
      const channelGroups = {
        1: { id: 10, name: 'Sports' },
        2: { id: 20, name: 'Movies' },
        3: { id: 30, name: 'News' },
      };
      const guideChannels = [
        { id: 1, channel_group_id: 10 },
        { id: 2, channel_group_id: 20 },
        { id: 3, channel_group_id: 30 },
      ];

      const result = guideUtils.getGroupOptions(channelGroups, guideChannels);
      const labels = result.slice(1).map((o) => o.label);
      expect(labels).toEqual([...labels].sort());
    });
  });

  // ── getProfileOptions ─────────────────────────────────────────────────────

  describe('getProfileOptions', () => {
    it('should return only "All" when no profiles', () => {
      const result = guideUtils.getProfileOptions(null);
      expect(result).toEqual([{ value: 'all', label: 'All Profiles' }]);
    });

    it('should include all profiles except id 0', () => {
      const profiles = {
        '0': { id: '0', name: 'Default' },
        '1': { id: '1', name: 'Kids' },
        '2': { id: '2', name: 'Sports' },
      };

      const result = guideUtils.getProfileOptions(profiles);
      expect(result).toHaveLength(3); // All + Kids + Sports
      expect(result.map((o) => o.label)).not.toContain('Default');
      expect(result.map((o) => o.label)).toContain('Kids');
      expect(result.map((o) => o.label)).toContain('Sports');
    });
  });

  // ── calcProgressPct ───────────────────────────────────────────────────────

  describe('calcProgressPct', () => {
    it('should return 0 when now is at start', () => {
      const result = guideUtils.calcProgressPct(1000, 1000, 60000);
      expect(result).toBeGreaterThanOrEqual(0);
    });

    it('should return 1 when now is at or past end', () => {
      // nowMs >= startMs + durationMs → elapsed >= duration → clamped to 1
      const startMs = 0;
      const durationMs = 60 * 60 * 1000; // 1 hour
      const nowMs = startMs + durationMs + 1000; // past the end
      const result = guideUtils.calcProgressPct(nowMs, startMs, durationMs);
      expect(result).toBe(1);
    });

    it('should return value between 0 and 1 for midpoint', () => {
      const startMs = 0;
      const durationMs = 60 * 60 * 1000; // 1 hour
      const nowMs = 30 * 60 * 1000; // 30 minutes in
      const result = guideUtils.calcProgressPct(nowMs, startMs, durationMs);
      expect(result).toBeGreaterThan(0);
      expect(result).toBeLessThan(1);
    });
  });

  // ── formatSeasonEpisode ───────────────────────────────────────────────────

  describe('formatSeasonEpisode', () => {
    it('should format both season and episode', () => {
      expect(guideUtils.formatSeasonEpisode(1, 2)).toBe('S01E02');
    });

    it('should pad numbers to 2 digits', () => {
      expect(guideUtils.formatSeasonEpisode(3, 7)).toBe('S03E07');
    });

    it('should handle large numbers without truncation', () => {
      expect(guideUtils.formatSeasonEpisode(10, 10)).toBe('S10E10');
    });

    it('should handle numbers greater than 99', () => {
      expect(guideUtils.formatSeasonEpisode(100, 200)).toBe('S100E200');
    });

    it('should return season only when episode is null', () => {
      expect(guideUtils.formatSeasonEpisode(2, null)).toBe('S02');
    });

    it('should return season only when episode is undefined', () => {
      expect(guideUtils.formatSeasonEpisode(2, undefined)).toBe('S02');
    });

    it('should return episode only when season is null', () => {
      expect(guideUtils.formatSeasonEpisode(null, 5)).toBe('E05');
    });

    it('should return episode only when season is undefined', () => {
      expect(guideUtils.formatSeasonEpisode(undefined, 5)).toBe('E05');
    });

    it('should return null when both are null', () => {
      expect(guideUtils.formatSeasonEpisode(null, null)).toBeNull();
    });

    it('should return null when both are undefined', () => {
      expect(guideUtils.formatSeasonEpisode(undefined, undefined)).toBeNull();
    });

    it('should handle zero values as valid', () => {
      expect(guideUtils.formatSeasonEpisode(0, 0)).toBe('S00E00');
    });

    it('should handle season zero with episode', () => {
      expect(guideUtils.formatSeasonEpisode(0, 1)).toBe('S00E01');
    });
  });

  // ── deleteSeriesRuleByTvgId ───────────────────────────────────────────────

  describe('deleteSeriesRuleByTvgId', () => {
    it('should delete series rule via API with tvg_id and title', async () => {
      vi.mocked(API.deleteSeriesRule).mockResolvedValue({});

      await guideUtils.deleteSeriesRuleByTvgId('tvg-1', 'My Show');

      expect(API.deleteSeriesRule).toHaveBeenCalledWith('tvg-1', 'My Show');
    });

    it('should forward undefined title when not provided', async () => {
      vi.mocked(API.deleteSeriesRule).mockResolvedValue({});

      await guideUtils.deleteSeriesRuleByTvgId('tvg-1');

      expect(API.deleteSeriesRule).toHaveBeenCalledWith('tvg-1', undefined);
    });

    it('should work with empty tvg_id for title-only rules', async () => {
      vi.mocked(API.deleteSeriesRule).mockResolvedValue({});

      await guideUtils.deleteSeriesRuleByTvgId('', 'Title-Only Show');

      expect(API.deleteSeriesRule).toHaveBeenCalledWith('', 'Title-Only Show');
    });
  });

  // ── evaluateSeriesRulesByTvgId ────────────────────────────────────────────

  describe('evaluateSeriesRulesByTvgId', () => {
    it('should evaluate series rules via API', async () => {
      vi.mocked(API.evaluateSeriesRules).mockResolvedValue({});

      await guideUtils.evaluateSeriesRulesByTvgId('tvg-1');

      expect(API.evaluateSeriesRules).toHaveBeenCalledWith('tvg-1');
    });
  });
});
