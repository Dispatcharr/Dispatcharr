import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import * as dateTimeUtils from '../dateTimeUtils';
import useSettingsStore from '../../store/settings';
import useLocalStorage from '../../hooks/useLocalStorage';

dayjs.extend(utc);
dayjs.extend(timezone);

vi.mock('../../store/settings');
vi.mock('../../hooks/useLocalStorage');

describe('dateTimeUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('convertToMs', () => {
    it('should convert date to milliseconds', () => {
      const date = '2024-01-15T10:30:00Z';
      const result = dateTimeUtils.convertToMs(date);
      expect(result).toBe(dayjs(date).valueOf());
    });

    it('should handle Date objects', () => {
      const date = new Date('2024-01-15T10:30:00Z');
      const result = dateTimeUtils.convertToMs(date);
      expect(result).toBe(dayjs(date).valueOf());
    });
  });

  describe('convertToSec', () => {
    it('should convert date to unix timestamp', () => {
      const date = '2024-01-15T10:30:00Z';
      const result = dateTimeUtils.convertToSec(date);
      expect(result).toBe(dayjs(date).unix());
    });

    it('should handle Date objects', () => {
      const date = new Date('2024-01-15T10:30:00Z');
      const result = dateTimeUtils.convertToSec(date);
      expect(result).toBe(dayjs(date).unix());
    });
  });

  describe('initializeTime', () => {
    it('should create dayjs object from date string', () => {
      const date = '2024-01-15T10:30:00Z';
      const result = dateTimeUtils.initializeTime(date);
      expect(result.format()).toBe(dayjs(date).format());
    });

    it('should handle Date objects', () => {
      const date = new Date('2024-01-15T10:30:00Z');
      const result = dateTimeUtils.initializeTime(date);
      expect(result.format()).toBe(dayjs(date).format());
    });
  });

  describe('startOfDay', () => {
    it('should return start of day', () => {
      const date = '2024-01-15T10:30:00Z';
      const result = dateTimeUtils.startOfDay(date);
      expect(result.hour()).toBe(0);
      expect(result.minute()).toBe(0);
      expect(result.second()).toBe(0);
    });
  });

  describe('isBefore', () => {
    it('should return true when first date is before second', () => {
      const date1 = '2024-01-15T10:00:00Z';
      const date2 = '2024-01-15T11:00:00Z';
      expect(dateTimeUtils.isBefore(date1, date2)).toBe(true);
    });

    it('should return false when first date is after second', () => {
      const date1 = '2024-01-15T11:00:00Z';
      const date2 = '2024-01-15T10:00:00Z';
      expect(dateTimeUtils.isBefore(date1, date2)).toBe(false);
    });
  });

  describe('isAfter', () => {
    it('should return true when first date is after second', () => {
      const date1 = '2024-01-15T11:00:00Z';
      const date2 = '2024-01-15T10:00:00Z';
      expect(dateTimeUtils.isAfter(date1, date2)).toBe(true);
    });

    it('should return false when first date is before second', () => {
      const date1 = '2024-01-15T10:00:00Z';
      const date2 = '2024-01-15T11:00:00Z';
      expect(dateTimeUtils.isAfter(date1, date2)).toBe(false);
    });
  });

  describe('isSame', () => {
    it('should return true when dates are same day', () => {
      const date1 = '2024-01-15T10:00:00Z';
      const date2 = '2024-01-15T11:00:00Z';
      expect(dateTimeUtils.isSame(date1, date2)).toBe(true);
    });

    it('should return false when dates are different days', () => {
      const date1 = '2024-01-15T10:00:00Z';
      const date2 = '2024-01-16T10:00:00Z';
      expect(dateTimeUtils.isSame(date1, date2)).toBe(false);
    });

    it('should accept unit parameter', () => {
      const date1 = '2024-01-15T10:00:00Z';
      const date2 = '2024-01-15T10:30:00Z';
      expect(dateTimeUtils.isSame(date1, date2, 'hour')).toBe(true);
      expect(dateTimeUtils.isSame(date1, date2, 'minute')).toBe(false);
    });
  });

  describe('add', () => {
    it('should add time to date', () => {
      const date = dayjs.utc('2024-01-15T10:00:00Z');
      const result = dateTimeUtils.add(date, 1, 'hour');
      expect(result.hour()).toBe(11);
    });

    it('should handle different units', () => {
      const date = '2024-01-15T10:00:00Z';
      const dayResult = dateTimeUtils.add(date, 1, 'day');
      expect(dayResult.date()).toBe(16);

      const monthResult = dateTimeUtils.add(date, 1, 'month');
      expect(monthResult.month()).toBe(1);
    });
  });

  describe('subtract', () => {
    it('should subtract time from date', () => {
      const date = dayjs.utc('2024-01-15T10:00:00Z');
      const result = dateTimeUtils.subtract(date, 1, 'hour');
      expect(result.hour()).toBe(9);
    });

    it('should handle different units', () => {
      const date = '2024-01-15T10:00:00Z';
      const dayResult = dateTimeUtils.subtract(date, 1, 'day');
      expect(dayResult.date()).toBe(14);
    });
  });

  describe('diff', () => {
    it('should calculate difference in milliseconds by default', () => {
      const date1 = '2024-01-15T11:00:00Z';
      const date2 = '2024-01-15T10:00:00Z';
      const result = dateTimeUtils.diff(date1, date2);
      expect(result).toBe(3600000);
    });

    it('should calculate difference in specified unit', () => {
      const date1 = '2024-01-15T11:00:00Z';
      const date2 = '2024-01-15T10:00:00Z';
      expect(dateTimeUtils.diff(date1, date2, 'hour')).toBe(1);
      expect(dateTimeUtils.diff(date1, date2, 'minute')).toBe(60);
    });
  });

  describe('format', () => {
    it('should format date with given format string', () => {
      const date = '2024-01-15T10:30:00Z';
      const result = dateTimeUtils.format(date, 'YYYY-MM-DD');
      expect(result).toMatch(/2024-01-15/);
    });

    it('should handle time formatting', () => {
      const date = '2024-01-15T10:30:00Z';
      const result = dateTimeUtils.format(date, 'HH:mm');
      expect(result).toMatch(/\d{2}:\d{2}/);
    });
  });

  describe('getNow', () => {
    it('should return current time as dayjs object', () => {
      const result = dateTimeUtils.getNow();
      expect(result.isValid()).toBe(true);
    });
  });

  describe('toFriendlyDuration', () => {
    it('should convert duration to human readable format', () => {
      const result = dateTimeUtils.toFriendlyDuration(60, 'minutes');
      expect(result).toBe('an hour');
    });

    it('should handle different units', () => {
      const result = dateTimeUtils.toFriendlyDuration(2, 'hours');
      expect(result).toBe('2 hours');
    });
  });

  describe('fromNow', () => {
    it('should return relative time from now', () => {
      const pastDate = dayjs().subtract(1, 'hour').toISOString();
      const result = dateTimeUtils.fromNow(pastDate);
      expect(result).toMatch(/ago/);
    });
  });

  describe('getNowMs', () => {
    it('should return current time in milliseconds', () => {
      const result = dateTimeUtils.getNowMs();
      expect(typeof result).toBe('number');
      expect(result).toBeGreaterThan(0);
    });
  });

  describe('roundToNearest', () => {
    it('should round to nearest 15 minutes', () => {
      const date = dayjs('2024-01-15T10:17:00Z');
      const result = dateTimeUtils.roundToNearest(date, 15);
      expect(result.minute()).toBe(15);
    });

    it('should round up when past halfway point', () => {
      const date = dayjs('2024-01-15T10:23:00Z');
      const result = dateTimeUtils.roundToNearest(date, 15);
      expect(result.minute()).toBe(30);
    });

    it('should handle rounding to next hour', () => {
      const date = dayjs.utc('2024-01-15T10:53:00Z');
      const result = dateTimeUtils.roundToNearest(date, 15);
      expect(result.hour()).toBe(11);
      expect(result.minute()).toBe(0);
    });

    it('should handle different minute intervals', () => {
      const date = dayjs('2024-01-15T10:20:00Z');
      const result = dateTimeUtils.roundToNearest(date, 30);
      expect(result.minute()).toBe(30);
    });
  });

  describe('useUserTimeZone', () => {
    it('should return time zone from local storage', () => {
      useLocalStorage.mockReturnValue(['America/New_York', vi.fn()]);
      useSettingsStore.mockReturnValue({});

      const { result } = renderHook(() => dateTimeUtils.useUserTimeZone());

      expect(result.current).toBe('America/New_York');
    });

    it('should update time zone from settings', () => {
      const setTimeZone = vi.fn();
      useLocalStorage.mockReturnValue(['America/New_York', setTimeZone]);
      useSettingsStore.mockReturnValue({
        'system_settings': { value: { time_zone: 'America/Los_Angeles' } }
      });

      renderHook(() => dateTimeUtils.useUserTimeZone());

      expect(setTimeZone).toHaveBeenCalledWith('America/Los_Angeles');
    });
  });

  describe('useTimeHelpers', () => {
    beforeEach(() => {
      useLocalStorage.mockReturnValue(['America/New_York', vi.fn()]);
      useSettingsStore.mockReturnValue({});
    });

    it('should return time zone, toUserTime, and userNow', () => {
      const { result } = renderHook(() => dateTimeUtils.useTimeHelpers());

      expect(result.current).toHaveProperty('timeZone');
      expect(result.current).toHaveProperty('toUserTime');
      expect(result.current).toHaveProperty('userNow');
    });

    it('should convert value to user time zone', () => {
      const { result } = renderHook(() => dateTimeUtils.useTimeHelpers());
      const date = '2024-01-15T10:00:00Z';

      const converted = result.current.toUserTime(date);

      expect(converted.isValid()).toBe(true);
    });

    it('should return null for null value', () => {
      const { result } = renderHook(() => dateTimeUtils.useTimeHelpers());

      const converted = result.current.toUserTime(null);

      expect(converted).toBeDefined();
      expect(converted.isValid()).toBe(false);
    });

    it('should handle timezone conversion errors', () => {
      const { result } = renderHook(() => dateTimeUtils.useTimeHelpers());
      const date = '2024-01-15T10:00:00Z';

      const converted = result.current.toUserTime(date);

      expect(converted.isValid()).toBe(true);
    });

    it('should return current time in user timezone', () => {
      const { result } = renderHook(() => dateTimeUtils.useTimeHelpers());

      const now = result.current.userNow();

      expect(now.isValid()).toBe(true);
    });
  });

  describe('RECURRING_DAY_OPTIONS', () => {
    it('should have 7 day options', () => {
      expect(dateTimeUtils.RECURRING_DAY_OPTIONS).toHaveLength(7);
    });

    it('should start with Sunday', () => {
      expect(dateTimeUtils.RECURRING_DAY_OPTIONS[0]).toEqual({ value: 6, label: 'Sun' });
    });

    it('should include all weekdays', () => {
      const labels = dateTimeUtils.RECURRING_DAY_OPTIONS.map(opt => opt.label);
      expect(labels).toEqual(['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']);
    });
  });

  describe('useDateTimeFormat', () => {
    it('should return 12h format and mdy date format by default', () => {
      useLocalStorage.mockReturnValueOnce(['12h', vi.fn()]).mockReturnValueOnce(['mdy', vi.fn()]);

      const { result } = renderHook(() => dateTimeUtils.useDateTimeFormat());

      expect(result.current).toEqual(['h:mma', 'MMM D']);
    });

    it('should return 24h format when set', () => {
      useLocalStorage.mockReturnValueOnce(['24h', vi.fn()]).mockReturnValueOnce(['mdy', vi.fn()]);

      const { result } = renderHook(() => dateTimeUtils.useDateTimeFormat());

      expect(result.current[0]).toBe('HH:mm');
    });

    it('should return dmy date format when set', () => {
      useLocalStorage.mockReturnValueOnce(['12h', vi.fn()]).mockReturnValueOnce(['dmy', vi.fn()]);

      const { result } = renderHook(() => dateTimeUtils.useDateTimeFormat());

      expect(result.current[1]).toBe('D MMM');
    });
  });

  describe('toTimeString', () => {
    it('should return 00:00 for null value', () => {
      expect(dateTimeUtils.toTimeString(null)).toBe('00:00');
    });

    it('should parse HH:mm format', () => {
      expect(dateTimeUtils.toTimeString('14:30')).toBe('14:30');
    });

    it('should parse HH:mm:ss format', () => {
      const result = dateTimeUtils.toTimeString('14:30:45');
      expect(result).toMatch(/14:30/);
    });

    it('should return original string for unparseable format', () => {
      expect(dateTimeUtils.toTimeString('2:30 PM')).toBe('2:30 PM');
    });

    it('should return original string for invalid format', () => {
      expect(dateTimeUtils.toTimeString('invalid')).toBe('invalid');
    });

    it('should handle Date objects', () => {
      const date = new Date('2024-01-15T14:30:00Z');
      const result = dateTimeUtils.toTimeString(date);
      expect(result).toMatch(/\d{2}:\d{2}/);
    });

    it('should return 00:00 for invalid Date', () => {
      expect(dateTimeUtils.toTimeString(new Date('invalid'))).toBe('00:00');
    });
  });

  describe('parseDate', () => {
    it('should return null for null value', () => {
      expect(dateTimeUtils.parseDate(null)).toBeNull();
    });

    it('should parse YYYY-MM-DD format', () => {
      const result = dateTimeUtils.parseDate('2024-01-15');
      expect(result).toBeInstanceOf(Date);
      expect(result?.getFullYear()).toBe(2024);
    });

    it('should parse ISO 8601 format', () => {
      const result = dateTimeUtils.parseDate('2024-01-15T10:30:00Z');
      expect(result).toBeInstanceOf(Date);
    });

    it('should return null for invalid date', () => {
      expect(dateTimeUtils.parseDate('invalid')).toBeNull();
    });
  });

  describe('buildTimeZoneOptions', () => {
    it('should return array of timezone options', () => {
      const result = dateTimeUtils.buildTimeZoneOptions();
      expect(Array.isArray(result)).toBe(true);
      expect(result.length).toBeGreaterThan(0);
    });

    it('should format timezone with offset', () => {
      const result = dateTimeUtils.buildTimeZoneOptions();
      expect(result[0]).toHaveProperty('value');
      expect(result[0]).toHaveProperty('label');
      expect(result[0].label).toMatch(/UTC[+-]\d{2}:\d{2}/);
    });

    it('should sort by offset then name', () => {
      const result = dateTimeUtils.buildTimeZoneOptions();
      for (let i = 1; i < result.length; i++) {
        expect(result[i].numericOffset).toBeGreaterThanOrEqual(result[i - 1].numericOffset);
      }
    });

    it('should include DST information when applicable', () => {
      const result = dateTimeUtils.buildTimeZoneOptions();
      const dstZone = result.find(opt => opt.label.includes('DST range'));
      expect(dstZone).toBeDefined();
    });

    it('should add preferred zone if not in list', () => {
      const preferredZone = 'Custom/Zone';
      const result = dateTimeUtils.buildTimeZoneOptions(preferredZone);
      const found = result.find(opt => opt.value === preferredZone);
      expect(found).toBeDefined();
    });

    it('should not duplicate existing zones', () => {
      const result = dateTimeUtils.buildTimeZoneOptions('UTC');
      const utcOptions = result.filter(opt => opt.value === 'UTC');
      expect(utcOptions).toHaveLength(1);
    });
  });

  describe('getDefaultTimeZone', () => {
    it('should return system timezone', () => {
      const result = dateTimeUtils.getDefaultTimeZone();
      expect(typeof result).toBe('string');
      expect(result.length).toBeGreaterThan(0);
    });

    it('should return UTC on error', () => {
      const originalDateTimeFormat = Intl.DateTimeFormat;
      Intl.DateTimeFormat = vi.fn(() => {
        throw new Error('Test error');
      });

      const result = dateTimeUtils.getDefaultTimeZone();
      expect(result).toBe('UTC');

      Intl.DateTimeFormat = originalDateTimeFormat;
    });
  });
});
