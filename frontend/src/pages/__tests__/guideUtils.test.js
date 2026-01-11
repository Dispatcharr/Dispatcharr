import { describe, it, expect, vi, beforeEach } from 'vitest';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import * as guideUtils from '../guideUtils';
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
      const channels = [
        { id: 1, uuid: 'uuid-1', epg_data_id: 'epg-1' },
      ];
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
      const channels = [
        { id: 1, uuid: 'uuid-1', epg_data_id: 'epg-1' },
      ];
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
      const channels = [
        { id: 1, uuid: 'uuid-1', epg_data_id: 'epg-1' },
      ];
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

  describe('mapProgramsByChannel', () => {
    it('should return empty map when no programs', () => {
      const channelIdByTvgId = new Map();

      const result = guideUtils.mapProgramsByChannel([], channelIdByTvgId);

      expect(result.size).toBe(0);
    });

    it('should return empty map when no channel mapping', () => {
      const programs = [{ tvg_id: 'tvg-1' }];

      const result = guideUtils.mapProgramsByChannel(programs, new Map());

      expect(result.size).toBe(0);
    });

    it('should map programs to channels', () => {
      const nowMs = 1000000;
      dateTimeUtils.getNowMs.mockReturnValue(nowMs);

      const programs = [
        {
          id: 1,
          tvg_id: 'tvg-1',
          start_time: '2024-01-15T10:00:00Z',
          end_time: '2024-01-15T11:00:00Z',
        },
      ];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)).toHaveLength(1);
      expect(result.get(1)[0]).toMatchObject({
        id: 1,
        tvg_id: 'tvg-1',
      });
    });

    it('should precompute startMs and endMs', () => {
      dateTimeUtils.getNowMs.mockReturnValue(1000000);
      dateTimeUtils.convertToMs.mockImplementation((time) =>
        typeof time === 'number' ? time : dayjs(time).valueOf()
      );

      const programs = [
        {
          id: 1,
          tvg_id: 'tvg-1',
          start_time: '2024-01-15T10:00:00Z',
          end_time: '2024-01-15T11:00:00Z',
        },
      ];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)[0]).toHaveProperty('startMs');
      expect(result.get(1)[0]).toHaveProperty('endMs');
    });

    it('should mark program as live when now is between start and end', () => {
      const startMs = 1000;
      const endMs = 2000;
      const nowMs = 1500;
      dateTimeUtils.getNowMs.mockReturnValue(nowMs);

      const programs = [
        {
          id: 1,
          tvg_id: 'tvg-1',
          startMs,
          endMs,
          start_time: '2024-01-15T10:00:00Z',
          end_time: '2024-01-15T11:00:00Z',
        },
      ];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)[0].isLive).toBe(true);
      expect(result.get(1)[0].isPast).toBe(false);
    });

    it('should mark program as past when now is after end', () => {
      const startMs = 1000;
      const endMs = 2000;
      const nowMs = 3000;
      dateTimeUtils.getNowMs.mockReturnValue(nowMs);

      const programs = [
        {
          id: 1,
          tvg_id: 'tvg-1',
          startMs,
          endMs,
          start_time: '2024-01-15T10:00:00Z',
          end_time: '2024-01-15T11:00:00Z',
        },
      ];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)[0].isLive).toBe(false);
      expect(result.get(1)[0].isPast).toBe(true);
    });

    it('should add program to multiple channels with same tvg_id', () => {
      dateTimeUtils.getNowMs.mockReturnValue(1000000);

      const programs = [
        {
          id: 1,
          tvg_id: 'tvg-1',
          start_time: '2024-01-15T10:00:00Z',
          end_time: '2024-01-15T11:00:00Z',
        },
      ];
      const channelIdByTvgId = new Map([['tvg-1', [1, 2, 3]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)).toHaveLength(1);
      expect(result.get(2)).toHaveLength(1);
      expect(result.get(3)).toHaveLength(1);
    });

    it('should sort programs by start time', () => {
      dateTimeUtils.getNowMs.mockReturnValue(1000000);

      const programs = [
        {
          id: 2,
          tvg_id: 'tvg-1',
          startMs: 2000,
          endMs: 3000,
          start_time: '2024-01-15T11:00:00Z',
          end_time: '2024-01-15T12:00:00Z',
        },
        {
          id: 1,
          tvg_id: 'tvg-1',
          startMs: 1000,
          endMs: 2000,
          start_time: '2024-01-15T10:00:00Z',
          end_time: '2024-01-15T11:00:00Z',
        },
      ];
      const channelIdByTvgId = new Map([['tvg-1', [1]]]);

      const result = guideUtils.mapProgramsByChannel(programs, channelIdByTvgId);

      expect(result.get(1)[0].id).toBe(1);
      expect(result.get(1)[1].id).toBe(2);
    });
  });

  describe('computeRowHeights', () => {
    it('should return empty array when no channels', () => {
      const result = guideUtils.computeRowHeights([], new Map(), null);

      expect(result).toEqual([]);
    });

    it('should return default height for all channels when none expanded', () => {
      const channels = [{ id: 1 }, { id: 2 }];
      const programsByChannelId = new Map();

      const result = guideUtils.computeRowHeights(channels, programsByChannelId, null);

      expect(result).toEqual([guideUtils.PROGRAM_HEIGHT, guideUtils.PROGRAM_HEIGHT]);
    });

    it('should return expanded height for channel with expanded program', () => {
      const channels = [{ id: 1 }, { id: 2 }];
      const programsByChannelId = new Map([
        [1, [{ id: 'program-1' }]],
        [2, [{ id: 'program-2' }]],
      ]);

      const result = guideUtils.computeRowHeights(channels, programsByChannelId, 'program-1');

      expect(result).toEqual([guideUtils.EXPANDED_PROGRAM_HEIGHT, guideUtils.PROGRAM_HEIGHT]);
    });

    it('should use custom heights when provided', () => {
      const channels = [{ id: 1 }];
      const programsByChannelId = new Map([[1, [{ id: 'program-1' }]]]);
      const customDefault = 100;
      const customExpanded = 200;

      const result = guideUtils.computeRowHeights(
        channels,
        programsByChannelId,
        'program-1',
        customDefault,
        customExpanded
      );

      expect(result).toEqual([customExpanded]);
    });
  });

  describe('fetchPrograms', () => {
    it('should fetch and transform programs', async () => {
      const mockPrograms = [
        {
          id: 1,
          start_time: '2024-01-15T10:00:00Z',
          end_time: '2024-01-15T11:00:00Z',
        },
      ];
      API.getGrid.mockResolvedValue(mockPrograms);
      dateTimeUtils.convertToMs.mockReturnValue(1000);

      const result = await guideUtils.fetchPrograms();

      expect(API.getGrid).toHaveBeenCalledTimes(1);
      expect(result).toHaveLength(1);
      expect(result[0]).toHaveProperty('startMs');
      expect(result[0]).toHaveProperty('endMs');
    });
  });

  describe('sortChannels', () => {
    it('should sort channels by channel number', () => {
      const channels = {
        1: { id: 1, channel_number: 3 },
        2: { id: 2, channel_number: 1 },
        3: { id: 3, channel_number: 2 },
      };

      const result = guideUtils.sortChannels(channels);

      expect(result[0].channel_number).toBe(1);
      expect(result[1].channel_number).toBe(2);
      expect(result[2].channel_number).toBe(3);
    });

    it('should put channels without number at end', () => {
      const channels = {
        1: { id: 1, channel_number: 2 },
        2: { id: 2, channel_number: null },
        3: { id: 3, channel_number: 1 },
      };

      const result = guideUtils.sortChannels(channels);

      expect(result[0].channel_number).toBe(1);
      expect(result[1].channel_number).toBe(2);
      expect(result[2].channel_number).toBeNull();
    });
  });

  describe('filterGuideChannels', () => {
    it('should return all channels when no filters', () => {
      const channels = [
        { id: 1, name: 'Channel 1' },
        { id: 2, name: 'Channel 2' },
      ];

      const result = guideUtils.filterGuideChannels(channels, '', 'all', 'all', {});

      expect(result).toHaveLength(2);
    });

    it('should filter by search query', () => {
      const channels = [
        { id: 1, name: 'ESPN' },
        { id: 2, name: 'CNN' },
      ];

      const result = guideUtils.filterGuideChannels(channels, 'espn', 'all', 'all', {});

      expect(result).toHaveLength(1);
      expect(result[0].name).toBe('ESPN');
    });

    it('should filter by channel group', () => {
      const channels = [
        { id: 1, name: 'Channel 1', channel_group_id: 1 },
        { id: 2, name: 'Channel 2', channel_group_id: 2 },
      ];

      const result = guideUtils.filterGuideChannels(channels, '', '1', 'all', {});

      expect(result).toHaveLength(1);
      expect(result[0].channel_group_id).toBe(1);
    });

    it('should filter by profile with array of channels', () => {
      const channels = [
        { id: 1, name: 'Channel 1' },
        { id: 2, name: 'Channel 2' },
      ];
      const profiles = {
        profile1: {
          channels: [
            { id: 1, enabled: true },
            { id: 2, enabled: false },
          ],
        },
      };

      const result = guideUtils.filterGuideChannels(channels, '', 'all', 'profile1', profiles);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });

    it('should filter by profile with Set of channels', () => {
      const channels = [
        { id: 1, name: 'Channel 1' },
        { id: 2, name: 'Channel 2' },
      ];
      const profiles = {
        profile1: {
          channels: new Set([1]),
        },
      };

      const result = guideUtils.filterGuideChannels(channels, '', 'all', 'profile1', profiles);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });

    it('should apply multiple filters together', () => {
      const channels = [
        { id: 1, name: 'ESPN', channel_group_id: 1 },
        { id: 2, name: 'ESPN2', channel_group_id: 2 },
        { id: 3, name: 'CNN', channel_group_id: 1 },
      ];
      const profiles = {
        profile1: {
          channels: [
            { id: 1, enabled: true },
            { id: 3, enabled: true },
          ],
        },
      };

      const result = guideUtils.filterGuideChannels(channels, 'espn', '1', 'profile1', profiles);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });
  });

  describe('calculateEarliestProgramStart', () => {
    it('should return default when no programs', () => {
      const defaultStart = dayjs('2024-01-15T00:00:00Z');

      const result = guideUtils.calculateEarliestProgramStart([], defaultStart);

      expect(result).toBe(defaultStart);
    });

    it('should return earliest program start', () => {
      dateTimeUtils.initializeTime.mockImplementation((time) => dayjs.utc(time));
      dateTimeUtils.isBefore.mockImplementation((a, b) => dayjs(a).isBefore(dayjs(b)));

      const programs = [
        { start_time: '2024-01-15T12:00:00Z' },
        { start_time: '2024-01-15T10:00:00Z' },
        { start_time: '2024-01-15T14:00:00Z' },
      ];
      const defaultStart = dayjs.utc('2024-01-16T00:00:00Z');

      const result = guideUtils.calculateEarliestProgramStart(programs, defaultStart);

      expect(result.hour()).toBe(10);
    });
  });

  describe('calculateLatestProgramEnd', () => {
    it('should return default when no programs', () => {
      const defaultEnd = dayjs('2024-01-16T00:00:00Z');

      const result = guideUtils.calculateLatestProgramEnd([], defaultEnd);

      expect(result).toBe(defaultEnd);
    });

    it('should return latest program end', () => {
      dateTimeUtils.initializeTime.mockImplementation((time) => dayjs.utc(time));
      dateTimeUtils.isAfter.mockImplementation((a, b) => dayjs(a).isAfter(dayjs(b)));

      const programs = [
        { end_time: '2024-01-15T12:00:00Z' },
        { end_time: '2024-01-15T18:00:00Z' },
        { end_time: '2024-01-15T14:00:00Z' },
      ];
      const defaultEnd = dayjs.utc('2024-01-15T00:00:00Z');

      const result = guideUtils.calculateLatestProgramEnd(programs, defaultEnd);

      expect(result.hour()).toBe(18);
    });
  });

  describe('calculateStart', () => {
    it('should return earliest when before default', () => {
      const earliest = dayjs('2024-01-15T08:00:00Z');
      const defaultStart = dayjs('2024-01-15T10:00:00Z');
      dateTimeUtils.isBefore.mockReturnValue(true);

      const result = guideUtils.calculateStart(earliest, defaultStart);

      expect(result).toBe(earliest);
    });

    it('should return default when earliest is after', () => {
      const earliest = dayjs('2024-01-15T12:00:00Z');
      const defaultStart = dayjs('2024-01-15T10:00:00Z');
      dateTimeUtils.isBefore.mockReturnValue(false);

      const result = guideUtils.calculateStart(earliest, defaultStart);

      expect(result).toBe(defaultStart);
    });
  });

  describe('calculateEnd', () => {
    it('should return latest when after default', () => {
      const latest = dayjs('2024-01-16T02:00:00Z');
      const defaultEnd = dayjs('2024-01-16T00:00:00Z');
      dateTimeUtils.isAfter.mockReturnValue(true);

      const result = guideUtils.calculateEnd(latest, defaultEnd);

      expect(result).toBe(latest);
    });

    it('should return default when latest is before', () => {
      const latest = dayjs('2024-01-15T22:00:00Z');
      const defaultEnd = dayjs('2024-01-16T00:00:00Z');
      dateTimeUtils.isAfter.mockReturnValue(false);

      const result = guideUtils.calculateEnd(latest, defaultEnd);

      expect(result).toBe(defaultEnd);
    });
  });

  describe('mapChannelsById', () => {
    it('should create map of channels by id', () => {
      const channels = [
        { id: 1, name: 'Channel 1' },
        { id: 2, name: 'Channel 2' },
      ];

      const result = guideUtils.mapChannelsById(channels);

      expect(result.get(1).name).toBe('Channel 1');
      expect(result.get(2).name).toBe('Channel 2');
    });
  });

  describe('mapRecordingsByProgramId', () => {
    it('should return empty map for null recordings', () => {
      const result = guideUtils.mapRecordingsByProgramId(null);

      expect(result.size).toBe(0);
    });

    it('should map recordings by program id', () => {
      const recordings = [
        {
          id: 1,
          custom_properties: {
            program: { id: 'program-1' },
          },
        },
        {
          id: 2,
          custom_properties: {
            program: { id: 'program-2' },
          },
        },
      ];

      const result = guideUtils.mapRecordingsByProgramId(recordings);

      expect(result.get('program-1').id).toBe(1);
      expect(result.get('program-2').id).toBe(2);
    });

    it('should skip recordings without program id', () => {
      const recordings = [
        {
          id: 1,
          custom_properties: {},
        },
      ];

      const result = guideUtils.mapRecordingsByProgramId(recordings);

      expect(result.size).toBe(0);
    });
  });

  describe('formatTime', () => {
    it('should return "Today" for today', () => {
      const today = dayjs();
      dateTimeUtils.getNow.mockReturnValue(today);
      dateTimeUtils.startOfDay.mockImplementation((time) => dayjs(time).startOf('day'));
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.isSame.mockReturnValueOnce(true);

      const result = guideUtils.formatTime(today, 'MM/DD');

      expect(result).toBe('Today');
    });

    it('should return "Tomorrow" for tomorrow', () => {
      const today = dayjs();
      const tomorrow = today.add(1, 'day');
      dateTimeUtils.getNow.mockReturnValue(today);
      dateTimeUtils.startOfDay.mockImplementation((time) => dayjs(time).startOf('day'));
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.isSame.mockReturnValueOnce(false).mockReturnValueOnce(true);

      const result = guideUtils.formatTime(tomorrow, 'MM/DD');

      expect(result).toBe('Tomorrow');
    });

    it('should return day name within a week', () => {
      const today = dayjs();
      const future = today.add(3, 'day');
      dateTimeUtils.getNow.mockReturnValue(today);
      dateTimeUtils.startOfDay.mockImplementation((time) => dayjs(time).startOf('day'));
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.isSame.mockReturnValue(false);
      dateTimeUtils.isBefore.mockReturnValue(true);
      dateTimeUtils.format.mockReturnValue('Wednesday');

      const result = guideUtils.formatTime(future, 'MM/DD');

      expect(result).toBe('Wednesday');
    });

    it('should return formatted date beyond a week', () => {
      const today = dayjs();
      const future = today.add(10, 'day');
      dateTimeUtils.getNow.mockReturnValue(today);
      dateTimeUtils.startOfDay.mockImplementation((time) => dayjs(time).startOf('day'));
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.isSame.mockReturnValue(false);
      dateTimeUtils.isBefore.mockReturnValue(false);
      dateTimeUtils.format.mockReturnValue('01/25');

      const result = guideUtils.formatTime(future, 'MM/DD');

      expect(result).toBe('01/25');
    });
  });

  describe('calculateHourTimeline', () => {
    it('should generate hours between start and end', () => {
      const start = dayjs('2024-01-15T10:00:00Z');
      const end = dayjs('2024-01-15T13:00:00Z');
      dateTimeUtils.isBefore.mockImplementation((a, b) => dayjs(a).isBefore(dayjs(b)));
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.startOfDay.mockImplementation((time) => dayjs(time).startOf('day'));
      dateTimeUtils.isSame.mockReturnValue(true);

      const formatDayLabel = vi.fn((time) => 'Today');
      const result = guideUtils.calculateHourTimeline(start, end, formatDayLabel);

      expect(result).toHaveLength(3);
      expect(formatDayLabel).toHaveBeenCalledTimes(3);
    });

    it('should mark new day transitions', () => {
      const start = dayjs('2024-01-15T23:00:00Z');
      const end = dayjs('2024-01-16T02:00:00Z');
      dateTimeUtils.isBefore.mockImplementation((a, b) => dayjs(a).isBefore(dayjs(b)));
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.startOfDay.mockImplementation((time) => dayjs(time).startOf('day'));
      dateTimeUtils.isSame.mockImplementation((a, b, unit) => dayjs(a).isSame(dayjs(b), unit));

      const formatDayLabel = vi.fn((time) => 'Day');
      const result = guideUtils.calculateHourTimeline(start, end, formatDayLabel);

      expect(result[0].isNewDay).toBe(true);
    });
  });

  describe('calculateNowPosition', () => {
    it('should return -1 when now is before start', () => {
      const now = dayjs('2024-01-15T09:00:00Z');
      const start = dayjs('2024-01-15T10:00:00Z');
      const end = dayjs('2024-01-15T18:00:00Z');
      dateTimeUtils.isBefore.mockReturnValue(true);

      const result = guideUtils.calculateNowPosition(now, start, end);

      expect(result).toBe(-1);
    });

    it('should return -1 when now is after end', () => {
      const now = dayjs('2024-01-15T19:00:00Z');
      const start = dayjs('2024-01-15T10:00:00Z');
      const end = dayjs('2024-01-15T18:00:00Z');
      dateTimeUtils.isBefore.mockReturnValue(false);
      dateTimeUtils.isAfter.mockReturnValue(true);

      const result = guideUtils.calculateNowPosition(now, start, end);

      expect(result).toBe(-1);
    });

    it('should calculate position when now is between start and end', () => {
      const now = dayjs('2024-01-15T11:00:00Z');
      const start = dayjs('2024-01-15T10:00:00Z');
      const end = dayjs('2024-01-15T18:00:00Z');
      dateTimeUtils.isBefore.mockReturnValue(false);
      dateTimeUtils.isAfter.mockReturnValue(false);
      dateTimeUtils.diff.mockReturnValue(60);

      const result = guideUtils.calculateNowPosition(now, start, end);

      expect(result).toBeGreaterThan(0);
    });
  });

  describe('calculateScrollPosition', () => {
    it('should calculate scroll position for current time', () => {
      const now = dayjs('2024-01-15T11:00:00Z');
      const start = dayjs('2024-01-15T10:00:00Z');
      const rounded = dayjs('2024-01-15T11:00:00Z');
      dateTimeUtils.roundToNearest.mockReturnValue(rounded);
      dateTimeUtils.diff.mockReturnValue(60);

      const result = guideUtils.calculateScrollPosition(now, start);

      expect(result).toBeGreaterThanOrEqual(0);
    });

    it('should return 0 when calculated position is negative', () => {
      const now = dayjs('2024-01-15T10:00:00Z');
      const start = dayjs('2024-01-15T10:00:00Z');
      const rounded = dayjs('2024-01-15T10:00:00Z');
      dateTimeUtils.roundToNearest.mockReturnValue(rounded);
      dateTimeUtils.diff.mockReturnValue(0);

      const result = guideUtils.calculateScrollPosition(now, start);

      expect(result).toBe(0);
    });
  });

  describe('matchChannelByTvgId', () => {
    it('should return null when no matching channel ids', () => {
      const channelIdByTvgId = new Map();
      const channelById = new Map();

      const result = guideUtils.matchChannelByTvgId(channelIdByTvgId, channelById, 'tvg-1');

      expect(result).toBeNull();
    });

    it('should return first matching channel', () => {
      const channel = { id: 1, name: 'Channel 1' };
      const channelIdByTvgId = new Map([['tvg-1', [1, 2, 3]]]);
      const channelById = new Map([[1, channel]]);

      const result = guideUtils.matchChannelByTvgId(channelIdByTvgId, channelById, 'tvg-1');

      expect(result).toBe(channel);
    });

    it('should return null when channel not in channelById map', () => {
      const channelIdByTvgId = new Map([['tvg-1', [999]]]);
      const channelById = new Map();

      const result = guideUtils.matchChannelByTvgId(channelIdByTvgId, channelById, 'tvg-1');

      expect(result).toBeNull();
    });
  });

  describe('fetchRules', () => {
    it('should fetch series rules from API', async () => {
      const mockRules = [{ id: 1, tvg_id: 'tvg-1' }];
      API.listSeriesRules.mockResolvedValue(mockRules);

      const result = await guideUtils.fetchRules();

      expect(API.listSeriesRules).toHaveBeenCalledTimes(1);
      expect(result).toBe(mockRules);
    });
  });

  describe('getRuleByProgram', () => {
    it('should return null when no rules', () => {
      const program = { tvg_id: 'tvg-1', title: 'Show' };

      const result = guideUtils.getRuleByProgram(null, program);

      expect(result).toBeUndefined();
    });

    it('should find rule by tvg_id without title', () => {
      const rules = [{ tvg_id: 'tvg-1', title: null }];
      const program = { tvg_id: 'tvg-1', title: 'Show' };

      const result = guideUtils.getRuleByProgram(rules, program);

      expect(result).toBe(rules[0]);
    });

    it('should find rule by tvg_id and title', () => {
      const rules = [
        { tvg_id: 'tvg-1', title: 'Show A' },
        { tvg_id: 'tvg-1', title: 'Show B' },
      ];
      const program = { tvg_id: 'tvg-1', title: 'Show B' };

      const result = guideUtils.getRuleByProgram(rules, program);

      expect(result).toBe(rules[1]);
    });

    it('should handle string comparison for tvg_id', () => {
      const rules = [{ tvg_id: 123, title: null }];
      const program = { tvg_id: '123', title: 'Show' };

      const result = guideUtils.getRuleByProgram(rules, program);

      expect(result).toBe(rules[0]);
    });
  });

  describe('createRecording', () => {
    it('should create recording via API', async () => {
      const channel = { id: 1 };
      const program = {
        start_time: '2024-01-15T10:00:00Z',
        end_time: '2024-01-15T11:00:00Z',
      };

      await guideUtils.createRecording(channel, program);

      expect(API.createRecording).toHaveBeenCalledWith({
        channel: '1',
        start_time: program.start_time,
        end_time: program.end_time,
        custom_properties: { program },
      });
    });
  });

  describe('createSeriesRule', () => {
    it('should create series rule via API', async () => {
      const program = { tvg_id: 'tvg-1', title: 'Show' };
      const mode = 'all';

      await guideUtils.createSeriesRule(program, mode);

      expect(API.createSeriesRule).toHaveBeenCalledWith({
        tvg_id: program.tvg_id,
        mode,
        title: program.title,
      });
    });
  });

  describe('evaluateSeriesRule', () => {
    it('should evaluate series rule via API', async () => {
      const program = { tvg_id: 'tvg-1' };

      await guideUtils.evaluateSeriesRule(program);

      expect(API.evaluateSeriesRules).toHaveBeenCalledWith(program.tvg_id);
    });
  });

  describe('calculateLeftScrollPosition', () => {
    it('should calculate left position using startMs', () => {
      const program = {
        startMs: dayjs.utc('2024-01-15T11:00:00Z').valueOf(),
      };
      const start = dayjs.utc('2024-01-15T10:00:00Z').valueOf();
      dateTimeUtils.convertToMs.mockImplementation((time) => {
        if (typeof time === 'number') return time;
        return dayjs.utc(time).valueOf();
      });

      const result = guideUtils.calculateLeftScrollPosition(program, start);

      expect(result).toBeGreaterThanOrEqual(0);
    });

    it('should calculate left position from start_time when no startMs', () => {
      const program = {
        start_time: '2024-01-15T10:30:00Z',
      };
      const start = '2024-01-15T10:00:00Z';
      dateTimeUtils.convertToMs.mockImplementation((time) => dayjs(time).valueOf());

      const result = guideUtils.calculateLeftScrollPosition(program, start);

      expect(result).toBeGreaterThanOrEqual(0);
    });
  });

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

  describe('calculateScrollPositionByTimeClick', () => {
    it('should calculate scroll position from time click', () => {
      const event = {
        currentTarget: {
          getBoundingClientRect: () => ({ left: 100, width: 450 }),
        },
        clientX: 325,
      };
      const clickedTime = dayjs('2024-01-15T10:00:00Z');
      const start = dayjs('2024-01-15T09:00:00Z');
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.diff.mockReturnValue(60);

      const result = guideUtils.calculateScrollPositionByTimeClick(event, clickedTime, start);

      expect(result).toBeGreaterThanOrEqual(0);
    });

    it('should snap to 15-minute increments', () => {
      const event = {
        currentTarget: {
          getBoundingClientRect: () => ({ left: 0, width: 450 }),
        },
        clientX: 112.5,
      };
      const clickedTime = dayjs('2024-01-15T10:00:00Z');
      const start = dayjs('2024-01-15T09:00:00Z');
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.diff.mockReturnValue(75);

      guideUtils.calculateScrollPositionByTimeClick(event, clickedTime, start);

      expect(dateTimeUtils.diff).toHaveBeenCalled();
    });

    it('should handle click at end of hour', () => {
      const event = {
        currentTarget: {
          getBoundingClientRect: () => ({ left: 0, width: 450 }),
        },
        clientX: 450,
      };
      const clickedTime = dayjs('2024-01-15T10:00:00Z');
      const start = dayjs('2024-01-15T09:00:00Z');
      dateTimeUtils.add.mockImplementation((time, amount, unit) => dayjs(time).add(amount, unit));
      dateTimeUtils.diff.mockReturnValue(120);

      const result = guideUtils.calculateScrollPositionByTimeClick(event, clickedTime, start);

      expect(dateTimeUtils.add).toHaveBeenCalledWith(expect.anything(), 1, 'hour');
    });
  });

  describe('getGroupOptions', () => {
    it('should return only "All" when no channel groups', () => {
      const result = guideUtils.getGroupOptions(null, []);

      expect(result).toHaveLength(1);
      expect(result[0].value).toBe('all');
    });

    it('should include groups used by channels', () => {
      const channelGroups = {
        1: { id: 1, name: 'Sports' },
        2: { id: 2, name: 'News' },
      };
      const channels = [
        { id: 1, channel_group_id: 1 },
        { id: 2, channel_group_id: 1 },
      ];

      const result = guideUtils.getGroupOptions(channelGroups, channels);

      expect(result).toHaveLength(2);
      expect(result[1].label).toBe('Sports');
    });

    it('should exclude groups not used by any channel', () => {
      const channelGroups = {
        1: { id: 1, name: 'Sports' },
        2: { id: 2, name: 'News' },
      };
      const channels = [
        { id: 1, channel_group_id: 1 },
      ];

      const result = guideUtils.getGroupOptions(channelGroups, channels);

      expect(result).toHaveLength(2);
      expect(result[1].label).toBe('Sports');
    });

    it('should sort groups alphabetically', () => {
      const channelGroups = {
        1: { id: 1, name: 'Z Group' },
        2: { id: 2, name: 'A Group' },
        3: { id: 3, name: 'M Group' },
      };
      const channels = [
        { id: 1, channel_group_id: 1 },
        { id: 2, channel_group_id: 2 },
        { id: 3, channel_group_id: 3 },
      ];

      const result = guideUtils.getGroupOptions(channelGroups, channels);

      expect(result[1].label).toBe('A Group');
      expect(result[2].label).toBe('M Group');
      expect(result[3].label).toBe('Z Group');
    });
  });

  describe('getProfileOptions', () => {
    it('should return only "All" when no profiles', () => {
      const result = guideUtils.getProfileOptions(null);

      expect(result).toHaveLength(1);
      expect(result[0].value).toBe('all');
    });

    it('should include all profiles except id 0', () => {
      const profiles = {
        0: { id: '0', name: 'All' },
        1: { id: '1', name: 'Profile 1' },
        2: { id: '2', name: 'Profile 2' },
      };

      const result = guideUtils.getProfileOptions(profiles);

      expect(result).toHaveLength(3);
      expect(result[1].label).toBe('Profile 1');
      expect(result[2].label).toBe('Profile 2');
    });
  });

  describe('deleteSeriesRuleByTvgId', () => {
    it('should delete series rule via API', async () => {
      await guideUtils.deleteSeriesRuleByTvgId('tvg-1');

      expect(API.deleteSeriesRule).toHaveBeenCalledWith('tvg-1');
    });
  });

  describe('evaluateSeriesRulesByTvgId', () => {
    it('should evaluate series rules via API', async () => {
      await guideUtils.evaluateSeriesRulesByTvgId('tvg-1');

      expect(API.evaluateSeriesRules).toHaveBeenCalledWith('tvg-1');
    });
  });
});
