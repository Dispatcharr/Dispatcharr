import { describe, it, expect } from 'vitest';
import dayjs from 'dayjs';
import {
  PROGRAM_HEIGHT,
  EXPANDED_PROGRAM_HEIGHT,
  buildChannelIdMap,
  mapProgramsByChannel,
  computeRowHeights,
} from '../guideUtils.js';

describe('guideUtils', () => {
  describe('buildChannelIdMap', () => {
    it('maps tvg ids from epg records and falls back to channel uuid', () => {
      const channels = [
        { id: 1, epg_data_id: 'epg-1', uuid: 'uuid-1' },
        { id: 2, epg_data_id: null, uuid: 'uuid-2' },
      ];
      const tvgsById = {
        'epg-1': { tvg_id: 'alpha' },
      };

      const map = buildChannelIdMap(channels, tvgsById);

      expect(map.get('alpha')).toBe(1);
      expect(map.get('uuid-2')).toBe(2);
    });
  });

  describe('mapProgramsByChannel', () => {
    it('groups programs by channel and sorts them by start time', () => {
      const programs = [
        {
          id: 10,
          tvg_id: 'alpha',
          start_time: dayjs('2025-01-01T02:00:00Z').toISOString(),
          end_time: dayjs('2025-01-01T03:00:00Z').toISOString(),
          title: 'Late Show',
        },
        {
          id: 11,
          tvg_id: 'alpha',
          start_time: dayjs('2025-01-01T01:00:00Z').toISOString(),
          end_time: dayjs('2025-01-01T02:00:00Z').toISOString(),
          title: 'Evening News',
        },
        {
          id: 20,
          tvg_id: 'beta',
          start_time: dayjs('2025-01-01T00:00:00Z').toISOString(),
          end_time: dayjs('2025-01-01T01:00:00Z').toISOString(),
          title: 'Morning Show',
        },
      ];

      const channelIdByTvgId = new Map([
        ['alpha', 1],
        ['beta', 2],
      ]);

      const map = mapProgramsByChannel(programs, channelIdByTvgId);

      expect(map.get(1)).toHaveLength(2);
      expect(map.get(1)?.map((item) => item.id)).toEqual([11, 10]);
      expect(map.get(2)).toHaveLength(1);
      expect(map.get(2)?.[0].startMs).toBeTypeOf('number');
      expect(map.get(2)?.[0].endMs).toBeTypeOf('number');
    });
  });

  describe('computeRowHeights', () => {
    it('returns program heights with expanded rows when needed', () => {
      const filteredChannels = [
        { id: 1 },
        { id: 2 },
      ];

      const programsByChannel = new Map([
        [1, [{ id: 10 }, { id: 11 }]],
        [2, [{ id: 20 }]],
      ]);

      const collapsed = computeRowHeights(
        filteredChannels,
        programsByChannel,
        null
      );
      expect(collapsed).toEqual([PROGRAM_HEIGHT, PROGRAM_HEIGHT]);

      const expanded = computeRowHeights(
        filteredChannels,
        programsByChannel,
        10
      );
      expect(expanded).toEqual([
        EXPANDED_PROGRAM_HEIGHT,
        PROGRAM_HEIGHT,
      ]);
    });
  });
});
