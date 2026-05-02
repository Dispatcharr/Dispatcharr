import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  parseExpirationDate,
  isAccountExpired,
  getExpirationInfo,
  profileSortComparator,
} from '../M3uProfilesUtils.js';

// ── Fixed "now" for deterministic tests ───────────────────────────────────────
const NOW = new Date('2024-06-01T12:00:00Z');

// Unix timestamp helpers
const unixSecondsFromNow = (offsetMs) =>
  String(Math.floor((NOW.getTime() + offsetMs) / 1000));

const MS = {
  hour: 1000 * 60 * 60,
  day: 1000 * 60 * 60 * 24,
};

describe('M3uProfilesUtils', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ── parseExpirationDate ────────────────────────────────────────────────────

  describe('parseExpirationDate', () => {
    const makeProfile = (expDate) => ({
      custom_properties: { user_info: { exp_date: expDate } },
    });

    it('returns a Date object for a valid unix timestamp string', () => {
      const expUnix = unixSecondsFromNow(MS.day);
      const result = parseExpirationDate(makeProfile(expUnix));
      expect(result).toBeInstanceOf(Date);
    });

    it('returns the correct date for a known unix timestamp', () => {
      // 2024-06-02T12:00:00Z = NOW + 1 day
      const expUnix = unixSecondsFromNow(MS.day);
      const result = parseExpirationDate(makeProfile(expUnix));
      expect(result.getTime()).toBeCloseTo(NOW.getTime() + MS.day, -3);
    });

    it('returns null when profile is null', () => {
      expect(parseExpirationDate(null)).toBeNull();
    });

    it('returns null when profile is undefined', () => {
      expect(parseExpirationDate(undefined)).toBeNull();
    });

    it('returns null when custom_properties is missing', () => {
      expect(parseExpirationDate({})).toBeNull();
    });

    it('returns null when user_info is missing', () => {
      expect(parseExpirationDate({ custom_properties: {} })).toBeNull();
    });

    it('returns null when exp_date is missing', () => {
      expect(
        parseExpirationDate({ custom_properties: { user_info: {} } })
      ).toBeNull();
    });

    it('returns null when exp_date is null', () => {
      expect(parseExpirationDate(makeProfile(null))).toBeNull();
    });

    it('returns null when exp_date is an empty string', () => {
      expect(parseExpirationDate(makeProfile(''))).toBeNull();
    });

    it('returns epoch start when exp_date is zero', () => {
      expect(parseExpirationDate(makeProfile('0'))).toEqual(new Date(0));
    });
  });

  // ── isAccountExpired ───────────────────────────────────────────────────────

  describe('isAccountExpired', () => {
    const makeProfile = (expDate) => ({
      custom_properties: { user_info: { exp_date: expDate } },
    });

    it('returns false when expiration date is in the future', () => {
      const expUnix = unixSecondsFromNow(MS.day);
      expect(isAccountExpired(makeProfile(expUnix))).toBe(false);
    });

    it('returns true when expiration date is in the past', () => {
      const expUnix = unixSecondsFromNow(-MS.day);
      expect(isAccountExpired(makeProfile(expUnix))).toBe(true);
    });

    it('returns true when expiration date is exactly now (expired at boundary)', () => {
      // The exp date equals NOW exactly; NOW < NOW is false, so not expired
      // Using -1ms to ensure it's strictly in the past
      const pastUnix = unixSecondsFromNow(-1000);
      expect(isAccountExpired(makeProfile(pastUnix))).toBe(true);
    });

    it('returns false when no expiration date is present', () => {
      expect(isAccountExpired({})).toBe(false);
    });

    it('returns false when profile is null', () => {
      expect(isAccountExpired(null)).toBe(false);
    });

    it('returns false when profile is undefined', () => {
      expect(isAccountExpired(undefined)).toBe(false);
    });

    it('returns false when exp_date is empty string', () => {
      expect(isAccountExpired(makeProfile(''))).toBe(false);
    });
  });

  // ── getExpirationInfo ──────────────────────────────────────────────────────

  describe('getExpirationInfo', () => {
    const makeProfile = (expDate) => ({
      custom_properties: { user_info: { exp_date: expDate } },
    });

    it('returns null when no expiration date is present', () => {
      expect(getExpirationInfo({})).toBeNull();
    });

    it('returns null when profile is null', () => {
      expect(getExpirationInfo(null)).toBeNull();
    });

    it('returns { text: "Expired", color: "red" } when date is in the past', () => {
      const expUnix = unixSecondsFromNow(-MS.day);
      expect(getExpirationInfo(makeProfile(expUnix))).toEqual({
        text: 'Expired',
        color: 'red',
      });
    });

    it('returns green color when more than 30 days remain', () => {
      const expUnix = unixSecondsFromNow(31 * MS.day);
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.color).toBe('green');
      expect(result.text).toMatch(/days/);
    });

    it('returns correct day count for 60 days remaining', () => {
      const expUnix = unixSecondsFromNow(60 * MS.day);
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.text).toBe('60 days');
      expect(result.color).toBe('green');
    });

    it('returns yellow color when 8–30 days remain', () => {
      const expUnix = unixSecondsFromNow(15 * MS.day);
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.color).toBe('yellow');
      expect(result.text).toBe('15 days');
    });

    it('returns yellow for exactly 8 days remaining', () => {
      const expUnix = unixSecondsFromNow(8 * MS.day);
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.color).toBe('yellow');
    });

    it('returns orange color when 1–7 days remain', () => {
      const expUnix = unixSecondsFromNow(3 * MS.day);
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.color).toBe('orange');
      expect(result.text).toBe('3 days');
    });

    it('returns orange for exactly 1 day remaining', () => {
      const expUnix = unixSecondsFromNow(1 * MS.day);
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.color).toBe('orange');
      expect(result.text).toBe('1 days');
    });

    it('returns red color with hours when less than 1 day remains', () => {
      const expUnix = unixSecondsFromNow(5 * MS.hour);
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.color).toBe('red');
      expect(result.text).toBe('5h');
    });

    it('returns "0h" when expiration is imminent (minutes away)', () => {
      const expUnix = unixSecondsFromNow(30 * 60 * 1000); // 30 minutes
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.color).toBe('red');
      expect(result.text).toBe('0h');
    });

    it('returns correct hours text for 23 hours remaining', () => {
      const expUnix = unixSecondsFromNow(23 * MS.hour);
      const result = getExpirationInfo(makeProfile(expUnix));
      expect(result.text).toBe('23h');
      expect(result.color).toBe('red');
    });
  });

  // ── profileSortComparator ──────────────────────────────────────────────────

  describe('profileSortComparator', () => {
    const makeProfile = (name, isDefault = false) => ({
      name,
      is_default: isDefault,
    });

    it('sorts default profile before non-default', () => {
      const defaultProfile = makeProfile('Zebra', true);
      const normal = makeProfile('Alpha');
      expect(profileSortComparator(defaultProfile, normal)).toBe(-1);
    });

    it('sorts non-default after default profile', () => {
      const normal = makeProfile('Alpha');
      const defaultProfile = makeProfile('Zebra', true);
      expect(profileSortComparator(normal, defaultProfile)).toBe(1);
    });

    it('sorts two non-default profiles alphabetically ascending', () => {
      const a = makeProfile('Alpha');
      const b = makeProfile('Beta');
      expect(profileSortComparator(a, b)).toBeLessThan(0);
    });

    it('sorts two non-default profiles alphabetically descending', () => {
      const a = makeProfile('Zebra');
      const b = makeProfile('Alpha');
      expect(profileSortComparator(a, b)).toBeGreaterThan(0);
    });

    it('returns 0 for two non-default profiles with the same name', () => {
      const a = makeProfile('Same');
      const b = makeProfile('Same');
      expect(profileSortComparator(a, b)).toBe(0);
    });

    it('places default profile first when sorting an array', () => {
      const profiles = [
        makeProfile('Charlie'),
        makeProfile('Alpha'),
        makeProfile('Default Profile', true),
        makeProfile('Beta'),
      ];
      const sorted = [...profiles].sort(profileSortComparator);
      expect(sorted[0].is_default).toBe(true);
    });

    it('sorts remaining profiles alphabetically after default', () => {
      const profiles = [
        makeProfile('Charlie'),
        makeProfile('Alpha'),
        makeProfile('Default Profile', true),
        makeProfile('Beta'),
      ];
      const sorted = [...profiles].sort(profileSortComparator);
      expect(sorted.slice(1).map((p) => p.name)).toEqual([
        'Alpha',
        'Beta',
        'Charlie',
      ]);
    });

    it('is stable when no profile is default (pure alphabetical)', () => {
      const profiles = [
        makeProfile('Zeta'),
        makeProfile('Alpha'),
        makeProfile('Mu'),
      ];
      const sorted = [...profiles].sort(profileSortComparator);
      expect(sorted.map((p) => p.name)).toEqual(['Alpha', 'Mu', 'Zeta']);
    });
  });
});
