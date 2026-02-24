import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as RecurringRuleModalUtils from '../RecurringRuleModalUtils';
import API from '../../../api.js';
import dayjs from 'dayjs';

vi.mock('../../../api.js', () => ({
  default: {
    updateRecurringRule: vi.fn(),
    deleteRecurringRule: vi.fn(),
  },
}));

describe('RecurringRuleModalUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getChannelOptions', () => {
    it('should return sorted channel options by channel number', () => {
      const channels = {
        ch1: { id: 1, channel_number: '10', name: 'ABC' },
        ch2: { id: 2, channel_number: '5', name: 'NBC' },
        ch3: { id: 3, channel_number: '15', name: 'CBS' },
      };

      const result = RecurringRuleModalUtils.getChannelOptions(channels);

      expect(result).toEqual([
        { value: '2', label: 'NBC' },
        { value: '1', label: 'ABC' },
        { value: '3', label: 'CBS' },
      ]);
    });

    it('should sort alphabetically by name when channel numbers are equal', () => {
      const channels = {
        ch1: { id: 1, channel_number: '10', name: 'ZBC' },
        ch2: { id: 2, channel_number: '10', name: 'ABC' },
        ch3: { id: 3, channel_number: '10', name: 'MBC' },
      };

      const result = RecurringRuleModalUtils.getChannelOptions(channels);

      expect(result).toEqual([
        { value: '2', label: 'ABC' },
        { value: '3', label: 'MBC' },
        { value: '1', label: 'ZBC' },
      ]);
    });

    it('should handle missing channel numbers', () => {
      const channels = {
        ch1: { id: 1, name: 'ABC' },
        ch2: { id: 2, channel_number: '5', name: 'NBC' },
      };

      const result = RecurringRuleModalUtils.getChannelOptions(channels);

      expect(result).toEqual([
        { value: '1', label: 'ABC' },
        { value: '2', label: 'NBC' },
      ]);
    });

    it('should use fallback label when name is missing', () => {
      const channels = {
        ch1: { id: 1, channel_number: '10' },
        ch2: { id: 2, channel_number: '5', name: '' },
      };

      const result = RecurringRuleModalUtils.getChannelOptions(channels);

      expect(result).toEqual([
        { value: '2', label: 'Channel 2' },
        { value: '1', label: 'Channel 1' },
      ]);
    });

    it('should handle empty channels object', () => {
      const result = RecurringRuleModalUtils.getChannelOptions({});

      expect(result).toEqual([]);
    });

    it('should handle null channels', () => {
      const result = RecurringRuleModalUtils.getChannelOptions(null);

      expect(result).toEqual([]);
    });

    it('should handle undefined channels', () => {
      const result = RecurringRuleModalUtils.getChannelOptions(undefined);

      expect(result).toEqual([]);
    });

    it('should convert channel id to string value', () => {
      const channels = {
        ch1: { id: 123, channel_number: '10', name: 'ABC' },
      };

      const result = RecurringRuleModalUtils.getChannelOptions(channels);

      expect(result[0].value).toBe('123');
      expect(typeof result[0].value).toBe('string');
    });

    it('should handle non-numeric channel numbers', () => {
      const channels = {
        ch1: { id: 1, channel_number: 'HD1', name: 'ABC' },
        ch2: { id: 2, channel_number: '5', name: 'NBC' },
      };

      const result = RecurringRuleModalUtils.getChannelOptions(channels);

      expect(result).toHaveLength(2);
    });
  });

  describe('getUpcomingOccurrences', () => {
    let toUserTime;
    let userNow;

    beforeEach(() => {
      const baseTime = dayjs('2024-01-01T12:00:00');
      toUserTime = vi.fn((time) => dayjs(time));
      userNow = vi.fn(() => baseTime);
    });

    it('should filter recordings by rule id and future start time', () => {
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
        {
          start_time: '2024-01-03T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
        {
          start_time: '2024-01-04T12:00:00',
          custom_properties: { rule: { id: 2 } },
        },
      ];

      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        recordings,
        userNow,
        1,
        toUserTime
      );

      expect(result).toHaveLength(2);
      expect(result[0].custom_properties.rule.id).toBe(1);
      expect(result[1].custom_properties.rule.id).toBe(1);
    });

    it('should exclude past recordings', () => {
      const recordings = [
        {
          start_time: '2023-12-31T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
        {
          start_time: '2024-01-02T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
      ];

      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        recordings,
        userNow,
        1,
        toUserTime
      );

      expect(result).toHaveLength(1);
      expect(result[0].start_time).toBe('2024-01-02T12:00:00');
    });

    it('should sort by start time ascending', () => {
      const recordings = [
        {
          start_time: '2024-01-04T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
        {
          start_time: '2024-01-02T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
        {
          start_time: '2024-01-03T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
      ];

      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        recordings,
        userNow,
        1,
        toUserTime
      );

      expect(result).toHaveLength(3);
      expect(result[0].start_time).toBe('2024-01-02T12:00:00');
      expect(result[1].start_time).toBe('2024-01-03T12:00:00');
      expect(result[2].start_time).toBe('2024-01-04T12:00:00');
    });

    it('should handle recordings as object', () => {
      const recordings = {
        rec1: {
          start_time: '2024-01-02T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
        rec2: {
          start_time: '2024-01-03T12:00:00',
          custom_properties: { rule: { id: 1 } },
        },
      };

      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        recordings,
        userNow,
        1,
        toUserTime
      );

      expect(result).toHaveLength(2);
    });

    it('should handle empty recordings array', () => {
      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        [],
        userNow,
        1,
        toUserTime
      );

      expect(result).toEqual([]);
    });

    it('should handle null recordings', () => {
      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        null,
        userNow,
        1,
        toUserTime
      );

      expect(result).toEqual([]);
    });

    it('should handle recordings without custom_properties', () => {
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
        },
      ];

      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        recordings,
        userNow,
        1,
        toUserTime
      );

      expect(result).toEqual([]);
    });

    it('should handle recordings without rule', () => {
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          custom_properties: {},
        },
      ];

      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        recordings,
        userNow,
        1,
        toUserTime
      );

      expect(result).toEqual([]);
    });

    it('should handle recordings with null rule', () => {
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          custom_properties: { rule: null },
        },
      ];

      const result = RecurringRuleModalUtils.getUpcomingOccurrences(
        recordings,
        userNow,
        1,
        toUserTime
      );

      expect(result).toEqual([]);
    });
  });

  describe('updateRecurringRule', () => {
    it('should call API with formatted values', async () => {
      const values = {
        channel_id: '5',
        days_of_week: ['1', '3', '5'],
        start_time: '14:30',
        end_time: '16:00',
        start_date: '2024-01-01',
        end_date: '2024-12-31',
        rule_name: 'My Rule',
        enabled: true,
      };

      await RecurringRuleModalUtils.updateRecurringRule(1, values);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        channel: '5',
        days_of_week: [1, 3, 5],
        start_time: '14:30',
        end_time: '16:00',
        start_date: '2024-01-01',
        end_date: '2024-12-31',
        name: 'My Rule',
        enabled: true,
      });
    });

    it('should convert days_of_week to numbers', async () => {
      const values = {
        channel_id: '5',
        days_of_week: ['0', '6'],
        start_time: '10:00',
        end_time: '11:00',
        enabled: false,
      };

      await RecurringRuleModalUtils.updateRecurringRule(1, values);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        channel: '5',
        days_of_week: [0, 6],
        start_time: '10:00',
        end_time: '11:00',
        start_date: null,
        end_date: null,
        name: '',
        enabled: false,
      });
    });

    it('should handle empty days_of_week', async () => {
      const values = {
        channel_id: '5',
        start_time: '10:00',
        end_time: '11:00',
        enabled: true,
      };

      await RecurringRuleModalUtils.updateRecurringRule(1, values);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        channel: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: null,
        end_date: null,
        name: '',
        enabled: true,
      });
    });

    it('should format dates correctly', async () => {
      const values = {
        channel_id: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: dayjs('2024-06-15'),
        end_date: dayjs('2024-12-25'),
        enabled: true,
      };

      await RecurringRuleModalUtils.updateRecurringRule(1, values);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        channel: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: '2024-06-15',
        end_date: '2024-12-25',
        name: '',
        enabled: true,
      });
    });

    it('should handle null dates', async () => {
      const values = {
        channel_id: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: null,
        end_date: null,
        enabled: true,
      };

      await RecurringRuleModalUtils.updateRecurringRule(1, values);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        channel: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: null,
        end_date: null,
        name: '',
        enabled: true,
      });
    });

    it('should trim rule name', async () => {
      const values = {
        channel_id: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        rule_name: '  Trimmed Name  ',
        enabled: true,
      };

      await RecurringRuleModalUtils.updateRecurringRule(1, values);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        channel: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: null,
        end_date: null,
        name: 'Trimmed Name',
        enabled: true,
      });
    });

    it('should handle missing rule_name', async () => {
      const values = {
        channel_id: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        enabled: true,
      };

      await RecurringRuleModalUtils.updateRecurringRule(1, values);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        channel: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: null,
        end_date: null,
        name: '',
        enabled: true,
      });
    });

    it('should convert enabled to boolean', async () => {
      const values = {
        channel_id: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        enabled: 'true',
      };

      await RecurringRuleModalUtils.updateRecurringRule(1, values);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        channel: '5',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: null,
        end_date: null,
        name: '',
        enabled: true,
      });
    });
  });

  describe('deleteRecurringRuleById', () => {
    it('should call API deleteRecurringRule with rule id', async () => {
      await RecurringRuleModalUtils.deleteRecurringRuleById(123);

      expect(API.deleteRecurringRule).toHaveBeenCalledWith(123);
      expect(API.deleteRecurringRule).toHaveBeenCalledTimes(1);
    });

    it('should handle string rule id', async () => {
      await RecurringRuleModalUtils.deleteRecurringRuleById('456');

      expect(API.deleteRecurringRule).toHaveBeenCalledWith('456');
    });
  });

  describe('updateRecurringRuleEnabled', () => {
    it('should call API updateRecurringRule with enabled true', async () => {
      await RecurringRuleModalUtils.updateRecurringRuleEnabled(1, true);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        enabled: true,
      });
    });

    it('should call API updateRecurringRule with enabled false', async () => {
      await RecurringRuleModalUtils.updateRecurringRuleEnabled(1, false);

      expect(API.updateRecurringRule).toHaveBeenCalledWith(1, {
        enabled: false,
      });
    });
  });
});
