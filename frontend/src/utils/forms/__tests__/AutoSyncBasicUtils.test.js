import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  computeRangeOverlapsFor,
  clampChannelNumber,
} from '../AutoSyncBasicUtils.js';

vi.mock('../GroupSyncUtils.js', () => ({
  getGroupReservation: vi.fn(),
}));

import { getGroupReservation } from '../GroupSyncUtils.js';

const makeGroup = (overrides = {}) => ({
  channel_group: 1,
  name: 'Group A',
  ...overrides,
});

describe('AutoSyncBasicUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── computeRangeOverlapsFor ───────────────────────────────────────────────
  describe('computeRangeOverlapsFor', () => {
    it('returns [] when the target group has no reservation', () => {
      getGroupReservation.mockReturnValue(null);
      expect(computeRangeOverlapsFor(makeGroup(), [])).toEqual([]);
    });

    it('returns [] when there are no other groups', () => {
      getGroupReservation.mockReturnValue([100, 200]);
      expect(computeRangeOverlapsFor(makeGroup(), [])).toEqual([]);
    });

    it('skips groups with the same channel_group id', () => {
      const group = makeGroup({ channel_group: 1 });
      const same = makeGroup({ channel_group: 1, name: 'Same' });
      getGroupReservation.mockReturnValue([100, 200]);
      expect(computeRangeOverlapsFor(group, [same])).toEqual([]);
    });

    it('skips other groups with no reservation', () => {
      const group = makeGroup({ channel_group: 1 });
      const other = makeGroup({ channel_group: 2, name: 'Other' });
      getGroupReservation
        .mockReturnValueOnce([100, 200]) // target group
        .mockReturnValueOnce(null); // other group
      expect(computeRangeOverlapsFor(group, [other])).toEqual([]);
    });

    it('detects exact overlap', () => {
      const group = makeGroup({ channel_group: 1 });
      const other = makeGroup({ channel_group: 2, name: 'Other' });
      getGroupReservation
        .mockReturnValueOnce([100, 200])
        .mockReturnValueOnce([100, 200]);
      expect(computeRangeOverlapsFor(group, [other])).toEqual([
        { name: 'Other', start: 100, end: 200 },
      ]);
    });

    it('detects partial overlap at start boundary', () => {
      const group = makeGroup({ channel_group: 1 });
      const other = makeGroup({ channel_group: 2, name: 'Other' });
      getGroupReservation
        .mockReturnValueOnce([150, 250])
        .mockReturnValueOnce([100, 150]);
      expect(computeRangeOverlapsFor(group, [other])).toEqual([
        { name: 'Other', start: 100, end: 150 },
      ]);
    });

    it('detects partial overlap at end boundary', () => {
      const group = makeGroup({ channel_group: 1 });
      const other = makeGroup({ channel_group: 2, name: 'Other' });
      getGroupReservation
        .mockReturnValueOnce([100, 200])
        .mockReturnValueOnce([200, 300]);
      expect(computeRangeOverlapsFor(group, [other])).toEqual([
        { name: 'Other', start: 200, end: 300 },
      ]);
    });

    it('returns [] when other group is entirely before target', () => {
      const group = makeGroup({ channel_group: 1 });
      const other = makeGroup({ channel_group: 2, name: 'Other' });
      getGroupReservation
        .mockReturnValueOnce([200, 300])
        .mockReturnValueOnce([100, 199]);
      expect(computeRangeOverlapsFor(group, [other])).toEqual([]);
    });

    it('returns [] when other group is entirely after target', () => {
      const group = makeGroup({ channel_group: 1 });
      const other = makeGroup({ channel_group: 2, name: 'Other' });
      getGroupReservation
        .mockReturnValueOnce([100, 199])
        .mockReturnValueOnce([200, 300]);
      expect(computeRangeOverlapsFor(group, [other])).toEqual([]);
    });

    it('returns multiple overlapping groups', () => {
      const group = makeGroup({ channel_group: 1 });
      const other1 = makeGroup({ channel_group: 2, name: 'B' });
      const other2 = makeGroup({ channel_group: 3, name: 'C' });
      getGroupReservation
        .mockReturnValueOnce([100, 300]) // target
        .mockReturnValueOnce([150, 200]) // other1 overlaps
        .mockReturnValueOnce([250, 350]); // other2 overlaps
      expect(computeRangeOverlapsFor(group, [other1, other2])).toEqual([
        { name: 'B', start: 150, end: 200 },
        { name: 'C', start: 250, end: 350 },
      ]);
    });
  });

  // ── clampChannelNumber ────────────────────────────────────────────────────
  describe('clampChannelNumber', () => {
    it('returns the value unchanged when within range', () => {
      expect(clampChannelNumber(500)).toBe(500);
    });

    it('clamps below 1 to 1', () => {
      expect(clampChannelNumber(0)).toBe(1);
      expect(clampChannelNumber(-50)).toBe(1);
    });

    it('clamps above 999999 to 999999', () => {
      expect(clampChannelNumber(1000000)).toBe(999999);
      expect(clampChannelNumber(99999999)).toBe(999999);
    });

    it('floors decimal values', () => {
      expect(clampChannelNumber(5.9)).toBe(5);
      expect(clampChannelNumber(1.1)).toBe(1);
    });

    it('coerces numeric strings', () => {
      expect(clampChannelNumber('42')).toBe(42);
    });

    it('falls back to 1 for NaN inputs', () => {
      expect(clampChannelNumber('abc')).toBe(1);
      expect(clampChannelNumber(NaN)).toBe(1);
      expect(clampChannelNumber(undefined)).toBe(1);
      expect(clampChannelNumber(null)).toBe(1);
    });

    it('returns 1 for boundary value 1', () => {
      expect(clampChannelNumber(1)).toBe(1);
    });

    it('returns 999999 for boundary value 999999', () => {
      expect(clampChannelNumber(999999)).toBe(999999);
    });
  });
});
