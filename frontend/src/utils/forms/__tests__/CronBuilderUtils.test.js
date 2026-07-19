import { describe, it, expect } from 'vitest';
import {
  buildCron,
  parseCronPreset,
  isHourlyHourPattern,
  updateCronPart,
  PRESETS,
  DAYS_OF_WEEK,
  FREQUENCY_OPTIONS,
  HOURLY_INTERVAL_OPTIONS,
  CRON_FIELDS,
} from '../CronBuilderUtils.js';

describe('CronBuilderUtils', () => {
  // ── PRESETS ────────────────────────────────────────────────────────────────────

  describe('PRESETS', () => {
    it('is a non-empty array', () => {
      expect(Array.isArray(PRESETS)).toBe(true);
      expect(PRESETS.length).toBeGreaterThan(0);
    });

    it('every preset has label, value, and description', () => {
      PRESETS.forEach((preset) => {
        expect(preset).toHaveProperty('label');
        expect(preset).toHaveProperty('value');
        expect(preset).toHaveProperty('description');
      });
    });

    it('every preset value is a valid 5-part cron string', () => {
      PRESETS.forEach((preset) => {
        expect(preset.value.split(' ')).toHaveLength(5);
      });
    });

    it('round-trips every preset through parse and build', () => {
      PRESETS.forEach((preset) => {
        const parsed = parseCronPreset(preset.value);
        expect(
          buildCron(
            parsed.frequency,
            parsed.minute,
            parsed.hour,
            parsed.dayOfWeek,
            parsed.dayOfMonth,
            parsed.hours
          )
        ).toBe(preset.value);
      });
    });
  });

  // ── DAYS_OF_WEEK ───────────────────────────────────────────────────────────────

  describe('DAYS_OF_WEEK', () => {
    it('contains 8 entries (wildcard + 7 days)', () => {
      expect(DAYS_OF_WEEK).toHaveLength(8);
    });

    it('first entry is the wildcard "Every day"', () => {
      expect(DAYS_OF_WEEK[0]).toEqual({ value: '*', label: 'Every day' });
    });

    it('every entry has value and label', () => {
      DAYS_OF_WEEK.forEach((day) => {
        expect(day).toHaveProperty('value');
        expect(day).toHaveProperty('label');
      });
    });

    it('numeric entries run 0-6', () => {
      const numeric = DAYS_OF_WEEK.filter((d) => d.value !== '*');
      expect(numeric.map((d) => d.value)).toEqual([
        '0',
        '1',
        '2',
        '3',
        '4',
        '5',
        '6',
      ]);
    });
  });

  // ── FREQUENCY_OPTIONS ──────────────────────────────────────────────────────────

  describe('FREQUENCY_OPTIONS', () => {
    it('contains exactly 4 options', () => {
      expect(FREQUENCY_OPTIONS).toHaveLength(4);
    });

    it('contains hourly, daily, weekly, monthly', () => {
      const values = FREQUENCY_OPTIONS.map((o) => o.value);
      expect(values).toEqual(['hourly', 'daily', 'weekly', 'monthly']);
    });

    it('every option has value and label', () => {
      FREQUENCY_OPTIONS.forEach((opt) => {
        expect(opt).toHaveProperty('value');
        expect(opt).toHaveProperty('label');
      });
    });
  });

  // ── CRON_FIELDS ────────────────────────────────────────────────────────────────

  describe('CRON_FIELDS', () => {
    it('contains exactly 5 fields', () => {
      expect(CRON_FIELDS).toHaveLength(5);
    });

    it('indexes run 0-4 in order', () => {
      expect(CRON_FIELDS.map((f) => f.index)).toEqual([0, 1, 2, 3, 4]);
    });

    it('every field has index, label, and placeholder', () => {
      CRON_FIELDS.forEach((field) => {
        expect(field).toHaveProperty('index');
        expect(field).toHaveProperty('label');
        expect(field).toHaveProperty('placeholder');
      });
    });
  });

  // ── HOURLY_INTERVAL_OPTIONS ────────────────────────────────────────────────────

  describe('HOURLY_INTERVAL_OPTIONS', () => {
    it('includes every-hour wildcard and common step intervals', () => {
      expect(HOURLY_INTERVAL_OPTIONS.map((o) => o.value)).toEqual([
        '*',
        '*/2',
        '*/3',
        '*/4',
        '*/6',
        '*/8',
        '*/12',
      ]);
    });

    it('every option has value and label', () => {
      HOURLY_INTERVAL_OPTIONS.forEach((opt) => {
        expect(opt).toHaveProperty('value');
        expect(opt).toHaveProperty('label');
      });
    });
  });

  // ── isHourlyHourPattern ────────────────────────────────────────────────────────

  describe('isHourlyHourPattern', () => {
    it('returns true for wildcard', () => {
      expect(isHourlyHourPattern('*')).toBe(true);
    });

    it('returns true for step values', () => {
      expect(isHourlyHourPattern('*/6')).toBe(true);
      expect(isHourlyHourPattern('*/12')).toBe(true);
    });

    it('returns true for lists and ranges', () => {
      expect(isHourlyHourPattern('0,6,12')).toBe(true);
      expect(isHourlyHourPattern('9-17')).toBe(true);
    });

    it('returns false for a single numeric hour', () => {
      expect(isHourlyHourPattern('0')).toBe(false);
      expect(isHourlyHourPattern('6')).toBe(false);
      expect(isHourlyHourPattern('23')).toBe(false);
    });
  });

  // ── buildCron ──────────────────────────────────────────────────────────────────

  describe('buildCron', () => {
    describe('hourly', () => {
      it('defaults hours pattern to wildcard', () => {
        expect(buildCron('hourly', 0, 0, '*', 1)).toBe('0 * * * *');
      });

      it('uses the provided minute value', () => {
        expect(buildCron('hourly', 30, 12, '*', 1)).toBe('30 * * * *');
      });

      it('uses the hours pattern when provided', () => {
        expect(buildCron('hourly', 0, 0, '*', 1, '*/6')).toBe('0 */6 * * *');
      });

      it('supports list and range hour patterns', () => {
        expect(buildCron('hourly', 0, 0, '*', 1, '0,6,12,18')).toBe(
          '0 0,6,12,18 * * *'
        );
        expect(buildCron('hourly', 15, 0, '*', 1, '9-17')).toBe(
          '15 9-17 * * *'
        );
      });

      it('ignores numeric hour, dayOfWeek, and dayOfMonth', () => {
        expect(buildCron('hourly', 15, 9, '1', 5)).toBe('15 * * * *');
      });
    });

    describe('daily', () => {
      it('returns minute and hour expression', () => {
        expect(buildCron('daily', 0, 3, '*', 1)).toBe('0 3 * * *');
      });

      it('uses the provided minute and hour', () => {
        expect(buildCron('daily', 30, 12, '*', 1)).toBe('30 12 * * *');
      });

      it('ignores dayOfWeek and dayOfMonth', () => {
        expect(buildCron('daily', 0, 0, '2', 15)).toBe('0 0 * * *');
      });
    });

    describe('weekly', () => {
      it('uses specific dayOfWeek when provided', () => {
        expect(buildCron('weekly', 0, 3, '1', 1)).toBe('0 3 * * 1');
      });

      it('defaults dayOfWeek to 0 when wildcard is passed', () => {
        expect(buildCron('weekly', 0, 3, '*', 1)).toBe('0 3 * * 0');
      });

      it('uses the provided minute and hour', () => {
        expect(buildCron('weekly', 15, 9, '5', 1)).toBe('15 9 * * 5');
      });

      it('ignores dayOfMonth', () => {
        expect(buildCron('weekly', 0, 0, '0', 31)).toBe('0 0 * * 0');
      });
    });

    describe('monthly', () => {
      it('returns expression with day of month', () => {
        expect(buildCron('monthly', 30, 2, '*', 1)).toBe('30 2 1 * *');
      });

      it('uses the provided dayOfMonth', () => {
        expect(buildCron('monthly', 0, 0, '*', 15)).toBe('0 0 15 * *');
      });

      it('ignores dayOfWeek', () => {
        expect(buildCron('monthly', 0, 6, '3', 10)).toBe('0 6 10 * *');
      });
    });

    describe('unknown frequency', () => {
      it('returns wildcard expression for unknown frequency', () => {
        expect(buildCron('unknown', 0, 0, '*', 1)).toBe('* * * * *');
      });

      it('returns wildcard expression for empty string', () => {
        expect(buildCron('', 0, 0, '*', 1)).toBe('* * * * *');
      });
    });
  });

  // ── parseCronPreset ────────────────────────────────────────────────────────────

  describe('parseCronPreset', () => {
    describe('hourly detection', () => {
      it('detects hourly when hour is wildcard', () => {
        const result = parseCronPreset('0 * * * *');
        expect(result.frequency).toBe('hourly');
        expect(result.hours).toBe('*');
      });

      it('returns correct minute for hourly', () => {
        expect(parseCronPreset('0 * * * *').minute).toBe(0);
      });

      it('returns dayOfWeek as wildcard for hourly', () => {
        expect(parseCronPreset('0 * * * *').dayOfWeek).toBe('*');
      });

      it('returns dayOfMonth as 1 for hourly', () => {
        expect(parseCronPreset('0 * * * *').dayOfMonth).toBe(1);
      });

      it('parses step-based hour as hourly with hours pattern', () => {
        const result = parseCronPreset('0 */6 * * *');
        expect(result.frequency).toBe('hourly');
        expect(result.hours).toBe('*/6');
        expect(result.minute).toBe(0);
      });

      it('parses step-based hour (*/12) as hourly with hours pattern', () => {
        const result = parseCronPreset('0 */12 * * *');
        expect(result.frequency).toBe('hourly');
        expect(result.hours).toBe('*/12');
      });

      it('parses list hour patterns as hourly', () => {
        const result = parseCronPreset('0 0,6,12,18 * * *');
        expect(result.frequency).toBe('hourly');
        expect(result.hours).toBe('0,6,12,18');
      });
    });

    describe('weekly detection', () => {
      it('detects weekly when weekday is not wildcard', () => {
        const result = parseCronPreset('0 3 * * 1');
        expect(result.frequency).toBe('weekly');
      });

      it('returns correct dayOfWeek', () => {
        expect(parseCronPreset('0 3 * * 1').dayOfWeek).toBe('1');
      });

      it('returns correct minute and hour for weekly', () => {
        const result = parseCronPreset('15 9 * * 5');
        expect(result.minute).toBe(15);
        expect(result.hour).toBe(9);
      });

      it('returns dayOfMonth as 1 for weekly', () => {
        expect(parseCronPreset('0 3 * * 0').dayOfMonth).toBe(1);
      });
    });

    describe('monthly detection', () => {
      it('detects monthly when day of month is not wildcard', () => {
        const result = parseCronPreset('30 2 1 * *');
        expect(result.frequency).toBe('monthly');
      });

      it('returns correct dayOfMonth', () => {
        expect(parseCronPreset('0 0 15 * *').dayOfMonth).toBe(15);
      });

      it('returns correct minute and hour for monthly', () => {
        const result = parseCronPreset('30 2 1 * *');
        expect(result.minute).toBe(30);
        expect(result.hour).toBe(2);
      });

      it('returns dayOfWeek as wildcard for monthly', () => {
        expect(parseCronPreset('30 2 1 * *').dayOfWeek).toBe('*');
      });
    });

    describe('daily detection', () => {
      it('detects daily as the default when no other conditions match', () => {
        const result = parseCronPreset('0 3 * * *');
        expect(result.frequency).toBe('daily');
      });

      it('returns correct minute and hour for daily', () => {
        const result = parseCronPreset('30 12 * * *');
        expect(result.minute).toBe(30);
        expect(result.hour).toBe(12);
      });

      it('returns dayOfWeek as wildcard for daily', () => {
        expect(parseCronPreset('0 3 * * *').dayOfWeek).toBe('*');
      });

      it('returns dayOfMonth as 1 for daily', () => {
        expect(parseCronPreset('0 3 * * *').dayOfMonth).toBe(1);
      });
    });

    describe('edge cases', () => {
      it('defaults minute to 0 for non-numeric minute field', () => {
        expect(parseCronPreset('* 3 * * *').minute).toBe(0);
      });

      it('parses midnight daily with numeric hour 0', () => {
        const result = parseCronPreset('0 0 * * *');
        expect(result.frequency).toBe('daily');
        expect(result.hour).toBe(0);
      });

      it('round-trips all PRESETS without throwing', () => {
        PRESETS.forEach((preset) => {
          expect(() => parseCronPreset(preset.value)).not.toThrow();
        });
      });
    });
  });

  // ── updateCronPart ─────────────────────────────────────────────────────────────

  describe('updateCronPart', () => {
    describe('valid 5-part cron', () => {
      it('updates the minute field (index 0)', () => {
        expect(updateCronPart('* * * * *', 0, '30')).toBe('30 * * * *');
      });

      it('updates the hour field (index 1)', () => {
        expect(updateCronPart('0 * * * *', 1, '6')).toBe('0 6 * * *');
      });

      it('updates the day of month field (index 2)', () => {
        expect(updateCronPart('0 3 * * *', 2, '15')).toBe('0 3 15 * *');
      });

      it('updates the month field (index 3)', () => {
        expect(updateCronPart('0 3 * * *', 3, '6')).toBe('0 3 * 6 *');
      });

      it('updates the day of week field (index 4)', () => {
        expect(updateCronPart('0 3 * * *', 4, '1')).toBe('0 3 * * 1');
      });

      it('preserves other parts when updating one field', () => {
        expect(updateCronPart('5 4 3 2 1', 0, '10')).toBe('10 4 3 2 1');
      });
    });

    describe('empty or falsy value', () => {
      it('replaces empty string with wildcard', () => {
        expect(updateCronPart('0 3 * * *', 0, '')).toBe('* 3 * * *');
      });

      it('replaces undefined with wildcard', () => {
        expect(updateCronPart('0 3 * * *', 0, undefined)).toBe('* 3 * * *');
      });

      it('replaces null with wildcard', () => {
        expect(updateCronPart('0 3 * * *', 0, null)).toBe('* 3 * * *');
      });
    });

    describe('invalid or short cron string', () => {
      it('falls back to all-wildcards base for a short cron string', () => {
        expect(updateCronPart('0 3', 0, '5')).toBe('5 * * * *');
      });

      it('falls back to all-wildcards for an empty string', () => {
        expect(updateCronPart('', 0, '5')).toBe('5 * * * *');
      });
    });

    describe('step and range values', () => {
      it('accepts step values like */15', () => {
        expect(updateCronPart('* * * * *', 0, '*/15')).toBe('*/15 * * * *');
      });

      it('accepts range values like 9-17', () => {
        expect(updateCronPart('* * * * *', 1, '9-17')).toBe('* 9-17 * * *');
      });

      it('accepts comma-separated values like 0,15,30,45', () => {
        expect(updateCronPart('* * * * *', 0, '0,15,30,45')).toBe(
          '0,15,30,45 * * * *'
        );
      });
    });
  });
});
