import { describe, it, expect, vi } from 'vitest';
import dayjs from 'dayjs';

vi.mock('../../../api.js', () => ({
  default: {
    getChannelsSummary: vi.fn(),
    updateRecording: vi.fn(),
    createRecording: vi.fn(),
    createRecurringRule: vi.fn(),
  },
}));

vi.mock('../../dateTimeUtils.js', () => ({
  add: vi.fn((d, amount, unit) => dayjs(d).add(amount, unit)),
  diff: vi.fn((a, b, unit) => dayjs(a).diff(dayjs(b), unit)),
  format: vi.fn((d, fmt) => (d ? dayjs(d).format(fmt) : null)),
  getNow: vi.fn(() => dayjs('2024-06-15T10:00:00')),
  initializeTime: vi.fn((val, fmts, ref, strict) => {
    for (const fmt of fmts) {
      const p = dayjs(val, fmt, strict);
      if (p.isValid()) return p;
    }
    return dayjs('invalid');
  }),
  isValid: vi.fn((d) => dayjs(d).isValid()),
  roundToNearest: vi.fn((d) => d),
  setMillisecond: vi.fn((d, ms) => dayjs(d).millisecond(ms)),
  setSecond: vi.fn((d, s) => dayjs(d).second(s)),
  toDate: vi.fn((d) => (d ? dayjs(d).toDate() : new Date())),
  toTimeString: vi.fn((t) => {
    if (!t) return '00:00';
    const match = String(t).match(/(\d{2}:\d{2})/);
    return match ? match[1] : t;
  }),
}));

vi.mock('@mantine/form', () => ({
  isNotEmpty: vi.fn((msg) => (value) => (value ? null : msg)),
}));

import API from '../../../api.js';
import {
  asDate,
  toIsoIfDate,
  toDateString,
  createRoundedDate,
  timeChange,
  getChannelsSummary,
  updateRecording,
  createRecording,
  createRecurringRule,
  sortedChannelOptions,
  numberedChannelLabel,
  getSingleFormDefaults,
  getRecurringFormDefaults,
  buildSinglePayload,
  buildRecurringPayload,
  singleFormValidators,
  recurringFormValidators,
} from '../RecordingUtils.js';

describe('RecordingUtils', () => {
  // ─── asDate ───────────────────────────────────────────────────────────────────

  describe('asDate', () => {
    it('returns null for falsy input', () => {
      expect(asDate(null)).toBeNull();
      expect(asDate(undefined)).toBeNull();
      expect(asDate('')).toBeNull();
    });

    it('returns a Date instance unchanged', () => {
      const d = new Date('2024-06-15');
      expect(asDate(d)).toBe(d);
    });

    it('parses a valid ISO string to a Date', () => {
      const result = asDate('2024-06-15T10:00:00Z');
      expect(result).toBeInstanceOf(Date);
      expect(result.toISOString()).toContain('2024-06-15');
    });

    it('returns null for an invalid date string', () => {
      expect(asDate('not-a-date')).toBeNull();
    });
  });

// ─── toIsoIfDate ──────────────────────────────────────────────────────────────

  describe('toIsoIfDate', () => {
    it('returns ISO string for a valid Date', () => {
      const d = new Date('2024-06-15T00:00:00Z');
      expect(toIsoIfDate(d)).toBe(d.toISOString());
    });

    it('returns ISO string for a valid date string', () => {
      const result = toIsoIfDate('2024-06-15T10:00:00Z');
      expect(result).toMatch(/2024-06-15/);
    });

    it('returns the original value when not a valid date', () => {
      expect(toIsoIfDate('some-string')).toBe('some-string');
    });

    it('returns null for null input', () => {
      expect(toIsoIfDate(null)).toBeNull();
    });
  });

// ─── toDateString ─────────────────────────────────────────────────────────────

  describe('toDateString', () => {
    it('formats a Date to YYYY-MM-DD', () => {
      const d = new Date('2024-06-15T12:00:00Z');
      const result = toDateString(d);
      expect(result).toBe('2024-06-15');
    });

    it('formats a valid ISO string to YYYY-MM-DD', () => {
      expect(toDateString('2024-06-15T12:00:00')).toBe('2024-06-15');
    });

    it('returns null for null input', () => {
      expect(toDateString(null)).toBeNull();
    });

    it('returns null for an invalid string', () => {
      expect(toDateString('not-a-date')).toBeNull();
    });
  });

// ─── createRoundedDate ────────────────────────────────────────────────────────

  describe('createRoundedDate', () => {
    it('returns a Date', () => {
      expect(createRoundedDate()).toBeInstanceOf(Date);
    });

    it('returns a Date when minutesAhead is provided', () => {
      expect(createRoundedDate(60)).toBeInstanceOf(Date);
    });
  });

// ─── timeChange ───────────────────────────────────────────────────────────────

  describe('timeChange', () => {
    it('calls setter with string directly', () => {
      const setter = vi.fn();
      timeChange(setter)('10:30');
      expect(setter).toHaveBeenCalledWith('10:30');
    });

    it('calls setter with currentTarget.value from event', () => {
      const setter = vi.fn();
      timeChange(setter)({ currentTarget: { value: '09:00' } });
      expect(setter).toHaveBeenCalledWith('09:00');
    });

    it('does not call setter for unrecognized input', () => {
      const setter = vi.fn();
      timeChange(setter)(42);
      expect(setter).not.toHaveBeenCalled();
    });
  });

// ─── API wrappers ─────────────────────────────────────────────────────────────

  describe('getChannelsSummary', () => {
    it('calls API.getChannelsSummary', () => {
      API.getChannelsSummary.mockResolvedValueOnce([]);
      getChannelsSummary();
      expect(API.getChannelsSummary).toHaveBeenCalled();
    });
  });

  describe('updateRecording', () => {
    it('calls API.updateRecording with id and data', () => {
      API.updateRecording.mockResolvedValueOnce({});
      updateRecording(1, { name: 'test' });
      expect(API.updateRecording).toHaveBeenCalledWith(1, { name: 'test' });
    });
  });

  describe('createRecording', () => {
    it('calls API.createRecording with data', () => {
      API.createRecording.mockResolvedValueOnce({});
      createRecording({ channel: 1 });
      expect(API.createRecording).toHaveBeenCalledWith({ channel: 1 });
    });
  });

  describe('createRecurringRule', () => {
    it('calls API.createRecurringRule with data', () => {
      API.createRecurringRule.mockResolvedValueOnce({});
      createRecurringRule({ channel: 1 });
      expect(API.createRecurringRule).toHaveBeenCalledWith({ channel: 1 });
    });
  });

// ─── sortedChannelOptions ─────────────────────────────────────────────────────

  describe('sortedChannelOptions', () => {
    const channels = [
      { id: 3, name: 'CNN',  channel_number: 20 },
      { id: 1, name: 'ESPN', channel_number: 5  },
      { id: 2, name: 'HBO',  channel_number: 10 },
    ];

    it('sorts channels by channel_number ascending', () => {
      const result = sortedChannelOptions(channels);
      // ESPN(5) < HBO(10) < CNN(20) → ids 1, 2, 3
      expect(result.map((o) => o.value)).toEqual(['1', '2', '3']);
    });

    it('maps each channel to { value, label }', () => {
      const result = sortedChannelOptions([{ id: 7, name: 'FOX', channel_number: 3 }]);
      expect(result[0]).toEqual({ value: '7', label: 'FOX' });
    });

    it('uses custom labelFn when provided', () => {
      const result = sortedChannelOptions(
        [{ id: 1, name: 'ESPN', channel_number: 5 }],
        (item) => `CH${item.channel_number} ${item.name}`
      );
      expect(result[0].label).toBe('CH5 ESPN');
    });

    it('falls back to "Channel id" when name is missing', () => {
      const result = sortedChannelOptions([{ id: 9, channel_number: 1 }]);
      expect(result[0].label).toBe('Channel 9');
    });

    it('accepts an object (dict) of channels', () => {
      const dict = {
        a: { id: 1, name: 'A', channel_number: 2 },
        b: { id: 2, name: 'B', channel_number: 1 },
      };
      const result = sortedChannelOptions(dict);
      expect(result[0].value).toBe('2');
      expect(result[1].value).toBe('1');
    });

    it('returns empty array for null input', () => {
      expect(sortedChannelOptions(null)).toEqual([]);
    });

    it('returns empty array for empty array input', () => {
      expect(sortedChannelOptions([])).toEqual([]);
    });

    it('sorts by name when channel_numbers are equal', () => {
      const input = [
        { id: 2, name: 'Zebra', channel_number: 5 },
        { id: 1, name: 'Apple', channel_number: 5 },
      ];
      const result = sortedChannelOptions(input);
      expect(result[0].label).toBe('Apple');
      expect(result[1].label).toBe('Zebra');
    });

    it('puts channels with no channel_number (0) first in numeric order', () => {
      const input = [
        { id: 1, name: 'A', channel_number: 5 },
        { id: 2, name: 'B', channel_number: null },
      ];
      const result = sortedChannelOptions(input);
      // null → 0, so it sorts before 5
      expect(result[0].value).toBe('2');
    });
  });

// ─── numberedChannelLabel ─────────────────────────────────────────────────────

  describe('numberedChannelLabel', () => {
    it('returns "number - name" when both are present', () => {
      expect(numberedChannelLabel({ id: 1, name: 'HBO', channel_number: 501 }))
        .toBe('501 - HBO');
    });

    it('returns name only when channel_number is falsy', () => {
      expect(numberedChannelLabel({ id: 1, name: 'HBO', channel_number: null }))
        .toBe('HBO');
    });

    it('falls back to "Channel id" when name is missing and number present', () => {
      expect(numberedChannelLabel({ id: 5, channel_number: 10 }))
        .toBe('10 - Channel 5');
    });

    it('falls back to "Channel id" when both name and number are missing', () => {
      expect(numberedChannelLabel({ id: 7 })).toBe('Channel 7');
    });
  });

// ─── getSingleFormDefaults ────────────────────────────────────────────────────

  describe('getSingleFormDefaults', () => {
    it('returns defaults with no arguments', () => {
      const result = getSingleFormDefaults();
      expect(result.channel_id).toBe('');
      expect(result.start_time).toBeInstanceOf(Date);
      expect(result.end_time).toBeInstanceOf(Date);
    });

    it('uses recording values when provided', () => {
      const recording = {
        channel: 3,
        start_time: '2024-06-15T08:00:00Z',
        end_time: '2024-06-15T09:00:00Z',
      };
      const result = getSingleFormDefaults(recording);
      expect(result.channel_id).toBe('3');
      expect(result.start_time).toBeInstanceOf(Date);
      expect(result.end_time).toBeInstanceOf(Date);
    });

    it('uses channel id when channel is provided and recording is null', () => {
      const result = getSingleFormDefaults(null, { id: 7 });
      expect(result.channel_id).toBe('7');
    });
  });

// ─── getRecurringFormDefaults ─────────────────────────────────────────────────

  describe('getRecurringFormDefaults', () => {
    it('returns defaults with no arguments', () => {
      const result = getRecurringFormDefaults();
      expect(result.channel_id).toBe('');
      expect(result.days_of_week).toEqual([]);
      expect(result.rule_name).toBe('');
      expect(typeof result.start_time).toBe('string');
      expect(typeof result.end_time).toBe('string');
      expect(result.start_date).toBeInstanceOf(Date);
      expect(result.end_date).toBeInstanceOf(Date);
    });

    it('uses channel name and id when channel is provided', () => {
      const result = getRecurringFormDefaults({ id: 5, name: 'ESPN' });
      expect(result.channel_id).toBe('5');
      expect(result.rule_name).toBe('ESPN');
    });
  });

// ─── buildSinglePayload ───────────────────────────────────────────────────────

  describe('buildSinglePayload', () => {
    it('builds payload from values', () => {
      const values = {
        channel_id: '2',
        start_time: new Date('2024-06-15T08:00:00Z'),
        end_time: new Date('2024-06-15T09:00:00Z'),
      };
      const result = buildSinglePayload(values);
      expect(result.channel).toBe('2');
      expect(result.start_time).toContain('2024-06-15');
      expect(result.end_time).toContain('2024-06-15');
    });
  });

// ─── buildRecurringPayload ────────────────────────────────────────────────────

  describe('buildRecurringPayload', () => {
    it('builds payload from values', () => {
      const values = {
        channel_id: '3',
        days_of_week: ['1', '3', '5'],
        start_time: '08:00',
        end_time: '09:00',
        start_date: new Date('2024-06-15T12:00:00'),
        end_date: new Date('2024-12-25T12:00:00'),
        rule_name: '  Morning News  ',
      };
      const result = buildRecurringPayload(values);
      expect(result.channel).toBe('3');
      expect(result.days_of_week).toEqual([1, 3, 5]);
      expect(result.start_time).toBe('08:00');
      expect(result.end_time).toBe('09:00');
      expect(result.start_date).toBe('2024-06-15');
      expect(result.end_date).toBe('2024-12-25');
      expect(result.name).toBe('Morning News');
    });

    it('handles empty days_of_week', () => {
      const values = {
        channel_id: '1',
        days_of_week: [],
        start_time: '10:00',
        end_time: '11:00',
        start_date: new Date('2024-06-15T12:00:00'),
        end_date: new Date('2024-06-15T12:00:00'),
        rule_name: '',
      };
      const result = buildRecurringPayload(values);
      expect(result.days_of_week).toEqual([]);
      expect(result.name).toBe('');
    });
  });

// ─── singleFormValidators ─────────────────────────────────────────────────────

  describe('singleFormValidators', () => {
    describe('end_time', () => {
      it('returns error when end time is missing', () => {
        expect(singleFormValidators.end_time(null, { start_time: null })).toBe(
          'Select an end time'
        );
      });

      it('returns error when end time is not after start time', () => {
        const start = new Date('2024-06-15T10:00:00Z');
        const end = new Date('2024-06-15T09:00:00Z');
        expect(singleFormValidators.end_time(end, { start_time: start })).toBe(
          'End time must be after start time'
        );
      });

      it('returns error when end equals start', () => {
        const t = new Date('2024-06-15T10:00:00Z');
        expect(singleFormValidators.end_time(t, { start_time: t })).toBe(
          'End time must be after start time'
        );
      });

      it('returns null when end is after start', () => {
        const start = new Date('2024-06-15T09:00:00Z');
        const end = new Date('2024-06-15T10:00:00Z');
        expect(singleFormValidators.end_time(end, { start_time: start })).toBeNull();
      });
    });
  });

// ─── recurringFormValidators ──────────────────────────────────────────────────

  describe('recurringFormValidators', () => {
    describe('days_of_week', () => {
      it('returns error for empty array', () => {
        expect(recurringFormValidators.days_of_week([])).toBe(
          'Pick at least one day'
        );
      });

      it('returns null for non-empty array', () => {
        expect(recurringFormValidators.days_of_week([1])).toBeNull();
      });
    });

    describe('start_time', () => {
      it('returns error for falsy value', () => {
        expect(recurringFormValidators.start_time(null)).toBe(
          'Select a start time'
        );
      });

      it('returns null for a valid time string', () => {
        expect(recurringFormValidators.start_time('10:00')).toBeNull();
      });
    });

    describe('end_time', () => {
      it('returns error when value is falsy', () => {
        expect(recurringFormValidators.end_time(null, { start_time: '2024-06-15T10:00:00' })).toBe(
          'Select an end time'
        );
      });

      it('returns error when end equals start (diff === 0)', () => {
        const result = recurringFormValidators.end_time('2024-06-15T10:00:00', {
          start_time: '2024-06-15T10:00:00',
        });
        expect(result).toBe('End time must differ from start time');
      });

      it('returns null when end differs from start', () => {
        const result = recurringFormValidators.end_time('2024-06-15T11:00:00', {
          start_time: '2024-06-15T10:00:00',
        });
        expect(result).toBeNull();
      });
    });

    describe('end_date', () => {
      it('returns error when end_date is missing', () => {
        expect(
          recurringFormValidators.end_date(null, { start_date: new Date() })
        ).toBe('Select an end date');
      });

      it('returns error when end_date is before start_date', () => {
        const start = new Date('2024-06-15');
        const end = new Date('2024-06-01');
        expect(recurringFormValidators.end_date(end, { start_date: start })).toBe(
          'End date cannot be before start date'
        );
      });

      it('returns null when end_date is on or after start_date', () => {
        const start = new Date('2024-06-15');
        const end = new Date('2024-06-15');
        expect(recurringFormValidators.end_date(end, { start_date: start })).toBeNull();
      });
    });
  });
});
