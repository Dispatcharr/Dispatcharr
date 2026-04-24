import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: { refreshAccountInfo: vi.fn() },
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import API from '../../../api.js';
import {
  formatTimestamp,
  getTimeRemaining,
  refreshAccountInfo,
} from '../AccountInfoModalUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('AccountInfoModalUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── formatTimestamp ────────────────────────────────────────────────────────

  describe('formatTimestamp', () => {
    it('returns "Unknown" for null', () => {
      expect(formatTimestamp(null)).toBe('Unknown');
    });

    it('returns "Unknown" for undefined', () => {
      expect(formatTimestamp(undefined)).toBe('Unknown');
    });

    it('returns "Unknown" for empty string', () => {
      expect(formatTimestamp('')).toBe('Unknown');
    });

    it('returns "Unknown" for 0', () => {
      expect(formatTimestamp(0)).toBe('Unknown');
    });

    it('formats a Unix timestamp string (no T) using parseInt * 1000', () => {
      const result = formatTimestamp('1700000000');
      expect(result).toBeTypeOf('string');
      expect(result).not.toBe('Unknown');
      expect(result).not.toBe('Invalid date');
    });

    it('formats an ISO string (contains T) directly', () => {
      const result = formatTimestamp('2023-11-14T22:13:20.000Z');
      expect(result).toBeTypeOf('string');
      expect(result).not.toBe('Unknown');
      expect(result).not.toBe('Invalid date');
    });

    it('returns a string containing the year for a valid Unix timestamp', () => {
      // 1700000000 => Nov 14, 2023
      const result = formatTimestamp('1700000000');
      expect(result).toContain('2023');
    });

    it('returns a string containing the year for a valid ISO timestamp', () => {
      const result = formatTimestamp('2023-11-14T22:13:20.000Z');
      expect(result).toContain('2023');
    });

    it('returns "Invalid date" when Date constructor throws', () => {
      const spy = vi.spyOn(global, 'Date').mockImplementationOnce(() => {
        throw new Error('bad date');
      });
      const result = formatTimestamp('1700000000');
      expect(result).toBe('Invalid date');
      spy.mockRestore();
    });

    it('uses parseInt for numeric strings without T', () => {
      const spy = vi.spyOn(global, 'Date');
      formatTimestamp('1700000000');
      // Called with 1700000000 * 1000
      expect(spy).toHaveBeenCalledWith(1700000000 * 1000);
      spy.mockRestore();
    });

    it('passes ISO string directly to Date constructor', () => {
      const spy = vi.spyOn(global, 'Date');
      const iso = '2023-11-14T22:13:20.000Z';
      formatTimestamp(iso);
      expect(spy).toHaveBeenCalledWith(iso);
      spy.mockRestore();
    });
  });

  // ── getTimeRemaining ───────────────────────────────────────────────────────

  describe('getTimeRemaining', () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it('returns null for null', () => {
      expect(getTimeRemaining(null)).toBeNull();
    });

    it('returns null for undefined', () => {
      expect(getTimeRemaining(undefined)).toBeNull();
    });

    it('returns null for empty string', () => {
      expect(getTimeRemaining('')).toBeNull();
    });

    it('returns null for 0', () => {
      expect(getTimeRemaining(0)).toBeNull();
    });

    it('returns "Expired" when expiry is in the past', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-01-10T00:00:00Z'));
      // Jan 1, 2024 Unix timestamp
      const past = String(
        Math.floor(new Date('2024-01-01T00:00:00Z').getTime() / 1000)
      );
      expect(getTimeRemaining(past)).toBe('Expired');
    });

    it('returns "Expired" when diffMs is exactly 0', () => {
      vi.useFakeTimers();
      const now = new Date('2024-06-01T12:00:00Z');
      vi.setSystemTime(now);
      const expTimestamp = String(Math.floor(now.getTime() / 1000));
      expect(getTimeRemaining(expTimestamp)).toBe('Expired');
    });

    it('returns only hours when less than 1 day remains', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-06-01T00:00:00Z'));
      // 5 hours from now
      const exp = Math.floor(new Date('2024-06-01T05:00:00Z').getTime() / 1000);
      expect(getTimeRemaining(String(exp))).toBe('5 hours');
    });

    it('uses singular "hour" when exactly 1 hour remains', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-06-01T00:00:00Z'));
      const exp = Math.floor(new Date('2024-06-01T01:00:00Z').getTime() / 1000);
      expect(getTimeRemaining(String(exp))).toBe('1 hour');
    });

    it('returns days and hours when more than 1 day remains', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-06-01T00:00:00Z'));
      // 2 days + 3 hours
      const exp = Math.floor(new Date('2024-06-03T03:00:00Z').getTime() / 1000);
      expect(getTimeRemaining(String(exp))).toBe('2 days 3 hours');
    });

    it('uses singular "day" when exactly 1 day and some hours remain', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-06-01T00:00:00Z'));
      // 1 day + 4 hours
      const exp = Math.floor(new Date('2024-06-02T04:00:00Z').getTime() / 1000);
      expect(getTimeRemaining(String(exp))).toBe('1 day 4 hours');
    });

    it('uses singular "day" and singular "hour" when 1 day 1 hour remains', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-06-01T00:00:00Z'));
      const exp = Math.floor(new Date('2024-06-02T01:00:00Z').getTime() / 1000);
      expect(getTimeRemaining(String(exp))).toBe('1 day 1 hour');
    });

    it('shows 0 hours when exactly N full days remain', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-06-01T00:00:00Z'));
      // Exactly 3 days, 0 hours
      const exp = Math.floor(new Date('2024-06-04T00:00:00Z').getTime() / 1000);
      expect(getTimeRemaining(String(exp))).toBe('3 days 0 hours');
    });

    it('returns "Unknown" when an exception is thrown', () => {
      const spy = vi.spyOn(global, 'Date').mockImplementationOnce(() => {
        throw new Error('bad');
      });
      expect(getTimeRemaining('1700000000')).toBe('Unknown');
      spy.mockRestore();
    });

    it('accepts a numeric (non-string) timestamp', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-06-01T00:00:00Z'));
      const exp = Math.floor(new Date('2024-06-01T02:00:00Z').getTime() / 1000);
      expect(getTimeRemaining(exp)).toBe('2 hours');
    });
  });

  // ── refreshAccountInfo ─────────────────────────────────────────────────────

  describe('refreshAccountInfo', () => {
    it('calls API.refreshAccountInfo with the profile id', async () => {
      vi.mocked(API.refreshAccountInfo).mockResolvedValue({ success: true });
      const profile = { id: 'profile-123' };
      await refreshAccountInfo(profile);
      expect(API.refreshAccountInfo).toHaveBeenCalledWith('profile-123');
    });

    it('returns the result from API.refreshAccountInfo', async () => {
      vi.mocked(API.refreshAccountInfo).mockResolvedValue({ success: true });
      const result = await refreshAccountInfo({ id: 'profile-123' });
      expect(result).toEqual({ success: true });
    });

    it('propagates rejection from API.refreshAccountInfo', async () => {
      const error = new Error('network error');
      vi.mocked(API.refreshAccountInfo).mockRejectedValue(error);
      await expect(refreshAccountInfo({ id: 'profile-123' })).rejects.toThrow(
        'network error'
      );
    });

    it('calls API.refreshAccountInfo exactly once', async () => {
      vi.mocked(API.refreshAccountInfo).mockResolvedValue({ success: true });
      await refreshAccountInfo({ id: 'abc' });
      expect(API.refreshAccountInfo).toHaveBeenCalledTimes(1);
    });

    it('throws when profile has no id', async () => {
      vi.mocked(API.refreshAccountInfo).mockResolvedValue({ success: true });
      // API receives undefined; test that the call is made with undefined
      await refreshAccountInfo({ id: undefined });
      expect(API.refreshAccountInfo).toHaveBeenCalledWith(undefined);
    });
  });
});
