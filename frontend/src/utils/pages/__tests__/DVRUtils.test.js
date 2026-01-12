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
          custom_properties: {}
        }
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
          custom_properties: {}
        }
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
          custom_properties: { status: 'completed' }
        }
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
          custom_properties: { status: 'interrupted' }
        }
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
          custom_properties: {}
        }
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
            program: { id: 100 }
          }
        },
        {
          id: 2,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch2',
          custom_properties: {
            program: { id: 100 }
          }
        }
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
            program: { title: 'Show A' }
          }
        },
        {
          id: 2,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { title: 'Show A' }
          }
        }
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
            program: { title: 'Show A' }
          }
        },
        {
          id: 2,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch2',
          custom_properties: {
            program: { title: 'Show A' }
          }
        }
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
          custom_properties: { program: { id: 1 } }
        },
        {
          id: 2,
          start_time: '2024-01-01T11:30:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch2',
          custom_properties: { program: { id: 2 } }
        },
        {
          id: 3,
          start_time: '2024-01-01T11:00:00',
          end_time: '2024-01-01T13:00:00',
          channel: 'ch3',
          custom_properties: { program: { id: 3 } }
        }
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
            program: { tvg_id: 'show1', title: 'Show A' }
          }
        },
        {
          id: 2,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Show A' }
          }
        },
        {
          id: 3,
          start_time: '2024-01-01T16:00:00',
          end_time: '2024-01-01T17:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Show A' }
          }
        }
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
            program: { tvg_id: 'show1', title: 'Show A' }
          }
        },
        {
          id: 2,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'show a' }
          }
        }
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
            program: { tvg_id: 'show1', title: 'Show A' }
          }
        },
        {
          id: 2,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show2', title: 'Show A' }
          }
        }
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
          custom_properties: { program: { id: 1, tvg_id: 'show1', title: 'Show A' } }
        },
        {
          id: 2,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch2',
          custom_properties: { program: { id: 2, tvg_id: 'show2', title: 'Show B' } }
        },
        {
          id: 3,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch3',
          custom_properties: { program: { id: 3, tvg_id: 'show3', title: 'Show C' } }
        }
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
          custom_properties: { status: 'completed' }
        },
        {
          id: 2,
          start_time: '2024-01-01T10:00:00',
          end_time: '2024-01-01T11:00:00',
          channel: 'ch2',
          custom_properties: { status: 'completed' }
        },
        {
          id: 3,
          start_time: '2024-01-01T09:00:00',
          end_time: '2024-01-01T10:00:00',
          channel: 'ch3',
          custom_properties: { status: 'completed' }
        }
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
          custom_properties: {}
        }
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
          custom_properties: {}
        },
        {
          id: 1,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch1',
          custom_properties: {}
        }
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
          channel: 'ch1'
        }
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
          custom_properties: {}
        }
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
          custom_properties: {}
        }
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
            program: { id: 100, tvg_id: 'show1', title: 'Show A' }
          }
        },
        {
          id: 2,
          start_time: '2024-01-01T14:00:00',
          end_time: '2024-01-01T15:00:00',
          channel: 'ch2',
          custom_properties: {
            program: { id: 100, tvg_id: 'show1', title: 'Show A' }
          }
        },
        {
          id: 3,
          start_time: '2024-01-01T15:00:00',
          end_time: '2024-01-01T16:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { id: 101, tvg_id: 'show1', title: 'Show A' }
          }
        }
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
            program: { tvg_id: 'show1', title: 'Show A' }
          }
        }
      ];

      const result = DVRUtils.categorizeRecordings(recordings, toUserTime, now);

      expect(result.upcoming[0]._group_count).toBe(1);
    });
  });
});
