import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as DVRUtils from '../DVRUtils';
import dayjs from 'dayjs';

describe('DVRUtils', () => {
  describe('categorizeRecordings', () => {
    let toUserTime;
    let now;

    beforeEach(() => {
      const baseTime = dayjs('2024-01-01T12:00:00');
      toUserTime = vi.fn((time) => dayjs(time));
      now = baseTime;
    });

    it('should categorize in-progress recordings', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
          custom_properties: {},
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.inProgress).toHaveLength(1);
      expect(result.inProgress[0].id).toBe(1);
      expect(result.upcoming).toHaveLength(0);
      expect(result.completed).toHaveLength(0);
    });

    it('should categorize upcoming recordings', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {},
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(1);
      expect(result.upcoming[0].id).toBe(1);
      expect(result.inProgress).toHaveLength(0);
      expect(result.completed).toHaveLength(0);
    });

    it('should categorize completed recordings by status', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T10:00:00',
          end_time: '2024-01-01T11:00:00',
          channel: 'ch1',
          custom_properties: { status: 'completed' },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.completed).toHaveLength(1);
      expect(result.completed[0].id).toBe(1);
      expect(result.inProgress).toHaveLength(0);
      expect(result.upcoming).toHaveLength(0);
    });

    it('should categorize interrupted recordings as completed', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
          custom_properties: { status: 'interrupted' },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.completed).toHaveLength(1);
      expect(result.inProgress).toHaveLength(0);
      expect(result.upcoming).toHaveLength(0);
    });

    it('should categorize past recordings without status as completed', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T09:00:00',
          end_time: '2024-01-01T10:00:00',
          channel: 'ch1',
          custom_properties: {},
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.completed).toHaveLength(1);
      expect(result.inProgress).toHaveLength(0);
      expect(result.upcoming).toHaveLength(0);
    });

    it('should deduplicate in-progress by program id', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { id: 100 },
          },
        },
        {
          id: 2,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch2',
          custom_properties: {
            program: { id: 100 },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.inProgress).toHaveLength(1);
    });

    it('should deduplicate in-progress by channel+slot when no program id', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { title: 'Show A' },
          },
        },
        {
          id: 2,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { title: 'Show A' },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.inProgress).toHaveLength(1);
    });

    it('should not deduplicate different channels', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { title: 'Show A' },
          },
        },
        {
          id: 2,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch2',
          custom_properties: {
            program: { title: 'Show A' },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.inProgress).toHaveLength(2);
    });

    it('should sort in-progress by start_time descending', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T10:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
          custom_properties: { program: { id: 1 } },
        },
        {
          id: 2,
          start_time: '2024-01-01T11:30:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch2',
          custom_properties: { program: { id: 2 } },
        },
        {
          id: 3,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch3',
          custom_properties: { program: { id: 3 } },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.inProgress[0].id).toBe(2);
      expect(result.inProgress[1].id).toBe(3);
      expect(result.inProgress[2].id).toBe(1);
    });

    it('should group upcoming by series and keep first episode', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Show A' },
          },
        },
        {
          id: 2,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Show A' },
          },
        },
        {
          id: 3,
          start_time: '2024-01-01T16:00:00',
          end_time: '2024-01-01T17:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Show A' },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(1);
      expect(result.upcoming[0].id).toBe(1);
      expect(result.upcoming[0]._group_count).toBe(3);
    });

    it('should group upcoming case-insensitively by title', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Show A' },
          },
        },
        {
          id: 2,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'show a' },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(1);
      expect(result.upcoming[0]._group_count).toBe(2);
    });

    it('should not group upcoming with different tvg_id', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Show A' },
          },
        },
        {
          id: 2,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show2', title: 'Show A' },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(2);
      expect(result.upcoming[0]._group_count).toBe(1);
      expect(result.upcoming[1]._group_count).toBe(1);
    });

    it('should sort upcoming by start_time ascending', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T16:00:00',
          end_time: '2024-01-01T17:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { id: 1, tvg_id: 'show1', title: 'Show A' },
          },
        },
        {
          id: 2,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch2',
          custom_properties: {
            program: { id: 2, tvg_id: 'show2', title: 'Show B' },
          },
        },
        {
          id: 3,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch3',
          custom_properties: {
            program: { id: 3, tvg_id: 'show3', title: 'Show C' },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming[0].id).toBe(2);
      expect(result.upcoming[1].id).toBe(3);
      expect(result.upcoming[2].id).toBe(1);
    });

    it('should sort completed by end_time descending', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T08:00:00',
          end_time: '2024-01-01T09:00:00',
          channel: 'ch1',
          custom_properties: { status: 'completed' },
        },
        {
          id: 2,
          start_time: '2024-01-01T10:00:00',
          end_time: '2024-01-01T11:00:00',
          channel: 'ch2',
          custom_properties: { status: 'completed' },
        },
        {
          id: 3,
          start_time: '2024-01-01T09:00:00',
          end_time: '2024-01-01T10:00:00',
          channel: 'ch3',
          custom_properties: { status: 'completed' },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.completed[0].id).toBe(2);
      expect(result.completed[1].id).toBe(3);
      expect(result.completed[2].id).toBe(1);
    });

    it('should handle recordings as object', () => {
      const recordings = {
        rec1: {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {},
        },
      };

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(1);
    });

    it('should handle empty recordings array', () => {
      const result = DVRUtils.categorizeRecordings([], toUserTime, now);

      expect(result.inProgress).toEqual([]);
      expect(result.upcoming).toEqual([]);
      expect(result.completed).toEqual([]);
    });

    it('should handle null recordings', () => {
      const result = DVRUtils.categorizeRecordings(null, toUserTime, now);

      expect(result.inProgress).toEqual([]);
      expect(result.upcoming).toEqual([]);
      expect(result.completed).toEqual([]);
    });

    it('should deduplicate by recording id', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {},
        },
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {},
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(1);
    });

    it('should handle recordings without custom_properties', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.inProgress).toHaveLength(1);
    });

    it('should handle recordings without program', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {},
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(1);
      expect(result.upcoming[0]._group_count).toBe(1);
    });

    it('should handle recording without id', () => {
      const recordings = [
        {
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {},
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(1);
    });

    it('should deduplicate upcoming by program id before grouping', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { id: 100, tvg_id: 'show1', title: 'Show A' },
          },
        },
        {
          id: 2,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch2',
          custom_properties: {
            program: { id: 100, tvg_id: 'show1', title: 'Show A' },
          },
        },
        {
          id: 3,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { id: 101, tvg_id: 'show1', title: 'Show A' },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming).toHaveLength(1);
      expect(result.upcoming[0]._group_count).toBe(2);
    });

    it('should preserve _group_count property on grouped recordings', () => {
      const recordings = [
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Show A' },
          },
        },
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming[0]._group_count).toBe(1);
    });
  });

  describe('filterRecordings', () => {
    const makeRec = (id, title, subTitle, description, channel) => ({
      id,
      channel,
      custom_properties: {
        program: { title, sub_title: subTitle, description },
      },
    });

    it('returns all recordings when no filters active', () => {
      const recs = [makeRec(1, 'News', 'Episode 1', 'Daily news', 5)];
      expect(DVRUtils.filterRecordings(recs, '', null)).toEqual(recs);
    });

    it('filters by title case-insensitively', () => {
      const recs = [
        makeRec(1, 'Morning News', '', '', 1),
        makeRec(2, 'Sports Center', '', '', 1),
      ];
      const result = DVRUtils.filterRecordings(recs, 'news', null);
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });

    it('filters by sub_title', () => {
      const recs = [
        makeRec(1, 'Show A', 'Pilot Episode', '', 1),
        makeRec(2, 'Show B', 'Finale', '', 1),
      ];
      const result = DVRUtils.filterRecordings(recs, 'pilot', null);
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });

    it('filters by description', () => {
      const recs = [
        makeRec(1, 'Show A', '', 'A thriller about detectives', 1),
        makeRec(2, 'Show B', '', 'A comedy special', 1),
      ];
      const result = DVRUtils.filterRecordings(recs, 'detective', null);
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });

    it('filters by channel id', () => {
      const recs = [
        makeRec(1, 'Show A', '', '', 5),
        makeRec(2, 'Show B', '', '', 10),
      ];
      const result = DVRUtils.filterRecordings(recs, '', '5');
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });

    it('combines search and channel filter with AND logic', () => {
      const recs = [
        makeRec(1, 'News', '', '', 5),
        makeRec(2, 'News', '', '', 10),
        makeRec(3, 'Sports', '', '', 5),
      ];
      const result = DVRUtils.filterRecordings(recs, 'news', '5');
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });

    it('handles recordings without custom_properties', () => {
      const recs = [{ id: 1, channel: 5 }];
      const result = DVRUtils.filterRecordings(recs, 'anything', null);
      expect(result).toHaveLength(0);
    });

    it('handles recordings without custom_properties and no search', () => {
      const recs = [{ id: 1, channel: 5 }];
      const result = DVRUtils.filterRecordings(recs, '', null);
      expect(result).toHaveLength(1);
    });

    it('handles empty array', () => {
      expect(DVRUtils.filterRecordings([], 'test', '5')).toEqual([]);
    });

    it('falls back to custom_properties.description', () => {
      const recs = [{
        id: 1,
        channel: 1,
        custom_properties: {
          description: 'A fallback description',
          program: { title: 'Show' },
        },
      }];
      const result = DVRUtils.filterRecordings(recs, 'fallback', null);
      expect(result).toHaveLength(1);
    });
  });

  describe('buildChannelOptions', () => {
    const channelsById = {
      5: { id: 5, name: 'CNN', channel_number: '5' },
      10: { id: 10, name: 'ESPN', channel_number: '10' },
      3: { id: 3, name: 'NBC', channel_number: '3' },
      20: { id: 20, name: 'Local Access' },
    };

    it('returns only channels present in recordings', () => {
      const bucket = [{ channel: 5 }, { channel: 10 }];
      const result = DVRUtils.buildChannelOptions(channelsById, bucket);
      expect(result).toHaveLength(2);
      expect(result.map((o) => o.value)).toEqual(['5', '10']);
    });

    it('sorts by channel number numerically', () => {
      const bucket = [{ channel: 10 }, { channel: 3 }, { channel: 5 }];
      const result = DVRUtils.buildChannelOptions(channelsById, bucket);
      expect(result[0].label).toBe('3 - NBC');
      expect(result[1].label).toBe('5 - CNN');
      expect(result[2].label).toBe('10 - ESPN');
    });

    it('handles multiple buckets', () => {
      const b1 = [{ channel: 5 }];
      const b2 = [{ channel: 10 }];
      const b3 = [{ channel: 3 }];
      const result = DVRUtils.buildChannelOptions(channelsById, b1, b2, b3);
      expect(result).toHaveLength(3);
    });

    it('deduplicates channels across buckets', () => {
      const b1 = [{ channel: 5 }, { channel: 10 }];
      const b2 = [{ channel: 5 }, { channel: 3 }];
      const result = DVRUtils.buildChannelOptions(channelsById, b1, b2);
      expect(result).toHaveLength(3);
    });

    it('skips channels not in channelsById', () => {
      const bucket = [{ channel: 5 }, { channel: 999 }];
      const result = DVRUtils.buildChannelOptions(channelsById, bucket);
      expect(result).toHaveLength(1);
      expect(result[0].value).toBe('5');
    });

    it('formats label with channel number when available', () => {
      const bucket = [{ channel: 5 }];
      const result = DVRUtils.buildChannelOptions(channelsById, bucket);
      expect(result[0].label).toBe('5 - CNN');
    });

    it('formats label without channel number when missing', () => {
      const bucket = [{ channel: 20 }];
      const result = DVRUtils.buildChannelOptions(channelsById, bucket);
      expect(result[0].label).toBe('Local Access');
    });

    it('returns empty array for empty buckets', () => {
      const result = DVRUtils.buildChannelOptions(channelsById, [], []);
      expect(result).toEqual([]);
    });
  });
});
