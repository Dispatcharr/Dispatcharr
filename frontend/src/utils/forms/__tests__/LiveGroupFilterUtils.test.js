import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getEPGs,
  getChannelsInRange,
  getStreamsRegexPreview,
  isExpectedOccupantForGroup,
  effectiveSyncGroupId,
  rangeFor,
  abortTimers,
  getRegexOptions,
  computeAutoSyncStart,
  isGroupVisible,
} from '../LiveGroupFilterUtils.js';

// ── API mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    getEPGs: vi.fn(),
    getChannelsInRange: vi.fn(),
    getStreamsRegexPreview: vi.fn(),
  },
}));

import API from '../../../api.js';

// ── Helpers ──────────────────────────────────────────────────────────────────
const makeEpgSource = (overrides = {}) => ({
  id: 1,
  name: 'Source One',
  source_type: 'xmltv',
  ...overrides,
});

const makeGroup = (overrides = {}) => ({
  name: 'Group A',
  enabled: true,
  auto_channel_sync: true,
  auto_sync_channel_start: 100,
  auto_sync_channel_end: 200,
  custom_properties: {},
  channel_group: 1,
  ...overrides,
});

const makeOccupant = (overrides = {}) => ({
  auto_created: true,
  has_channel_number_override: false,
  channel_group_id: 1,
  auto_created_by_account_id: 42,
  ...overrides,
});

const makePlaylist = (overrides = {}) => ({
  id: 42,
  ...overrides,
});

const makeController = () => {
  const controller = { signal: {} };
  return controller;
};

describe('LiveGroupFilterUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── getEPGs ────────────────────────────────────────────────────────────────
  describe('getEPGs', () => {
    it('delegates to API.getEPGs', () => {
      const result = [makeEpgSource()];
      vi.mocked(API.getEPGs).mockResolvedValue(result);
      expect(getEPGs()).resolves.toEqual(result);
      expect(API.getEPGs).toHaveBeenCalledOnce();
    });
  });

  // ── getChannelsInRange ─────────────────────────────────────────────────────
  describe('getChannelsInRange', () => {
    it('calls API.getChannelsInRange with start, end, and signal', () => {
      const controller = makeController();
      const result = [{ id: 1 }];
      vi.mocked(API.getChannelsInRange).mockResolvedValue(result);

      getChannelsInRange(100, 200, controller);

      expect(API.getChannelsInRange).toHaveBeenCalledWith(100, 200, {
        signal: controller.signal,
      });
    });

    it('returns the API promise', () => {
      const controller = makeController();
      const result = [{ id: 1 }];
      vi.mocked(API.getChannelsInRange).mockResolvedValue(result);

      expect(getChannelsInRange(100, 200, controller)).resolves.toEqual(result);
    });
  });

  // ── getStreamsRegexPreview ─────────────────────────────────────────────────
  describe('getStreamsRegexPreview', () => {
    it('calls API with correct params when all values provided', () => {
      const group = { name: 'Group A' };
      const controller = makeController();
      const playlist = makePlaylist();
      vi.mocked(API.getStreamsRegexPreview).mockResolvedValue([]);

      getStreamsRegexPreview(
        group,
        'find',
        'replace',
        'match',
        'exclude',
        controller,
        playlist
      );

      expect(API.getStreamsRegexPreview).toHaveBeenCalledWith('Group A', {
        find: 'find',
        replace: 'replace',
        match: 'match',
        exclude: 'exclude',
        limit: 10,
        signal: controller.signal,
        m3uAccountId: 42,
      });
    });

    it('omits find/replace when find is falsy', () => {
      const group = { name: 'Group A' };
      const controller = makeController();
      vi.mocked(API.getStreamsRegexPreview).mockResolvedValue([]);

      getStreamsRegexPreview(group, '', 'replace', '', '', controller, null);

      expect(API.getStreamsRegexPreview).toHaveBeenCalledWith('Group A', {
        find: undefined,
        replace: undefined,
        match: undefined,
        exclude: undefined,
        limit: 10,
        signal: controller.signal,
        m3uAccountId: undefined,
      });
    });

    it('omits replace when find is falsy but keeps match/exclude if truthy', () => {
      const group = { name: 'Group A' };
      const controller = makeController();
      vi.mocked(API.getStreamsRegexPreview).mockResolvedValue([]);

      getStreamsRegexPreview(
        group,
        '',
        '',
        'match',
        'exclude',
        controller,
        null
      );

      expect(API.getStreamsRegexPreview).toHaveBeenCalledWith('Group A', {
        find: undefined,
        replace: undefined,
        match: 'match',
        exclude: 'exclude',
        limit: 10,
        signal: controller.signal,
        m3uAccountId: undefined,
      });
    });
  });

  // ── isExpectedOccupantForGroup ─────────────────────────────────────────────
  describe('isExpectedOccupantForGroup', () => {
    it('returns false for null occupant', () => {
      expect(isExpectedOccupantForGroup(null, 1, makePlaylist())).toBe(false);
    });

    it('returns false when occupant is not auto_created', () => {
      const occupant = makeOccupant({ auto_created: false });
      expect(isExpectedOccupantForGroup(occupant, 1, makePlaylist())).toBe(
        false
      );
    });

    it('returns false when occupant has a channel number override', () => {
      const occupant = makeOccupant({ has_channel_number_override: true });
      expect(isExpectedOccupantForGroup(occupant, 1, makePlaylist())).toBe(
        false
      );
    });

    it('returns false when occupant belongs to a different group', () => {
      const occupant = makeOccupant({ channel_group_id: 99 });
      expect(isExpectedOccupantForGroup(occupant, 1, makePlaylist())).toBe(
        false
      );
    });

    it('returns false when occupant was created by a different account', () => {
      const occupant = makeOccupant({ auto_created_by_account_id: 99 });
      expect(
        isExpectedOccupantForGroup(occupant, 1, makePlaylist({ id: 42 }))
      ).toBe(false);
    });

    it('returns true for a valid expected occupant', () => {
      const occupant = makeOccupant();
      expect(isExpectedOccupantForGroup(occupant, 1, makePlaylist())).toBe(
        true
      );
    });

    it('returns true when channel_group_id is undefined', () => {
      const occupant = makeOccupant({ channel_group_id: undefined });
      expect(isExpectedOccupantForGroup(occupant, 1, makePlaylist())).toBe(
        true
      );
    });

    it('returns true when auto_created_by_account_id is undefined', () => {
      const occupant = makeOccupant({ auto_created_by_account_id: undefined });
      expect(isExpectedOccupantForGroup(occupant, 1, makePlaylist())).toBe(
        true
      );
    });
  });

  // ── effectiveSyncGroupId ───────────────────────────────────────────────────
  describe('effectiveSyncGroupId', () => {
    it('returns the source channel_group when there is no override', () => {
      expect(effectiveSyncGroupId(makeGroup({ channel_group: 7 }))).toBe(7);
    });

    it('returns the group_override target when set', () => {
      const group = makeGroup({
        channel_group: 7,
        custom_properties: { group_override: 9 },
      });
      expect(effectiveSyncGroupId(group)).toBe(9);
    });

    it('coerces a string-stored group_override to a number', () => {
      const group = makeGroup({
        channel_group: 7,
        custom_properties: { group_override: '9' },
      });
      expect(effectiveSyncGroupId(group)).toBe(9);
    });

    it('falls back to the source group when group_override is blank', () => {
      const group = makeGroup({
        channel_group: 7,
        custom_properties: { group_override: '' },
      });
      expect(effectiveSyncGroupId(group)).toBe(7);
    });

    // Regression guard for the group-override range-conflict false positive:
    // the auto-sync's own channels land in the override target group, so
    // comparing against the source group (pre-fix) flags them as a conflict,
    // while comparing against the effective target recognizes them as this
    // config's own output.
    it("makes group-override occupants count as this group's own", () => {
      const group = makeGroup({
        channel_group: 7,
        custom_properties: { group_override: 9 },
      });
      const occupant = makeOccupant({ channel_group_id: 9 });
      // Pre-fix comparison (source group) treats own channels as a conflict.
      expect(
        isExpectedOccupantForGroup(
          occupant,
          group.channel_group,
          makePlaylist()
        )
      ).toBe(false);
      // Comparing against the effective target recognizes them as expected.
      expect(
        isExpectedOccupantForGroup(
          occupant,
          effectiveSyncGroupId(group),
          makePlaylist()
        )
      ).toBe(true);
    });

    // Guards against over-suppression: resolving the effective target group
    // must still surface genuine collisions in an override config's range.
    // Only the config's own output (auto-created, this account, in the
    // target group, unpinned) is excluded.
    it('still flags genuine collisions in a group-override config', () => {
      const group = makeGroup({
        channel_group: 7,
        custom_properties: { group_override: 9 },
      });
      const target = effectiveSyncGroupId(group);
      // Manual channel sitting in the range.
      expect(
        isExpectedOccupantForGroup(
          makeOccupant({ channel_group_id: 9, auto_created: false }),
          target,
          makePlaylist()
        )
      ).toBe(false);
      // Auto-created by a different account.
      expect(
        isExpectedOccupantForGroup(
          makeOccupant({
            channel_group_id: 9,
            auto_created_by_account_id: 999,
          }),
          target,
          makePlaylist()
        )
      ).toBe(false);
      // A channel in a different group than the override target.
      expect(
        isExpectedOccupantForGroup(
          makeOccupant({ channel_group_id: 123 }),
          target,
          makePlaylist()
        )
      ).toBe(false);
      // A user-pinned channel number.
      expect(
        isExpectedOccupantForGroup(
          makeOccupant({
            channel_group_id: 9,
            has_channel_number_override: true,
          }),
          target,
          makePlaylist()
        )
      ).toBe(false);
    });
  });

  // ── rangeFor ──────────────────────────────────────────────────────────────
  describe('rangeFor', () => {
    it('returns null when group is disabled', () => {
      expect(rangeFor(makeGroup({ enabled: false }))).toBeNull();
    });

    it('returns null when auto_channel_sync is off', () => {
      expect(rangeFor(makeGroup({ auto_channel_sync: false }))).toBeNull();
    });

    it('returns null when mode is next_available', () => {
      const group = makeGroup({
        custom_properties: { channel_numbering_mode: 'next_available' },
      });
      expect(rangeFor(group)).toBeNull();
    });

    it('returns null when start is not finite', () => {
      const group = makeGroup({ auto_sync_channel_start: 'abc' });
      expect(rangeFor(group)).toBeNull();
    });

    it('returns correct range for fixed mode', () => {
      const group = makeGroup({
        auto_sync_channel_start: 100,
        auto_sync_channel_end: 200,
        custom_properties: { channel_numbering_mode: 'fixed' },
      });
      expect(rangeFor(group)).toEqual({ start: 100, end: 200, startRaw: 100 });
    });

    it('uses fallback start for provider mode', () => {
      const group = makeGroup({
        custom_properties: {
          channel_numbering_mode: 'provider',
          channel_numbering_fallback: 50,
        },
        auto_sync_channel_end: 150,
      });
      expect(rangeFor(group)).toEqual({ start: 50, end: 150, startRaw: 50 });
    });

    it('uses start as end when end is null', () => {
      const group = makeGroup({
        auto_sync_channel_start: 100,
        auto_sync_channel_end: null,
      });
      expect(rangeFor(group)).toEqual({ start: 100, end: 100, startRaw: 100 });
    });

    it('uses start as end when end is empty string', () => {
      const group = makeGroup({
        auto_sync_channel_start: 100,
        auto_sync_channel_end: '',
      });
      expect(rangeFor(group)).toEqual({ start: 100, end: 100, startRaw: 100 });
    });

    it('defaults start to 1 when auto_sync_channel_start is undefined', () => {
      const group = makeGroup({
        auto_sync_channel_start: undefined,
        auto_sync_channel_end: 10,
      });
      expect(rangeFor(group)).toEqual({ start: 1, end: 10, startRaw: 1 });
    });
  });

  // ── abortTimers ───────────────────────────────────────────────────────────
  describe('abortTimers', () => {
    it('clears all timeouts and aborts all controllers', () => {
      const t1 = setTimeout(() => {}, 10000);
      const clearSpy = vi.spyOn(globalThis, 'clearTimeout');

      const abortFn = vi.fn();
      const timerRef = { current: { a: t1 } };
      const abortRef = { current: { b: { abort: abortFn } } };

      abortTimers(timerRef, abortRef);

      expect(clearSpy).toHaveBeenCalledWith(t1);
      expect(abortFn).toHaveBeenCalledOnce();
      expect(timerRef.current).toEqual({});
      expect(abortRef.current).toEqual({});

      clearSpy.mockRestore();
    });

    it('does not throw when abort throws', () => {
      const timerRef = { current: {} };
      const abortRef = {
        current: {
          a: {
            abort: () => {
              throw new Error('already aborted');
            },
          },
        },
      };

      expect(() => abortTimers(timerRef, abortRef)).not.toThrow();
      expect(abortRef.current).toEqual({});
    });
  });

  // ── getRegexOptions ───────────────────────────────────────────────────────
  describe('getRegexOptions', () => {
    it('returns an object with the four regex fields', () => {
      expect(getRegexOptions('find', 'replace', 'filter', 'exclude')).toEqual({
        find: 'find',
        replace: 'replace',
        match: 'filter',
        exclude: 'exclude',
      });
    });

    it('preserves empty string values', () => {
      expect(getRegexOptions('', '', '', '')).toEqual({
        find: '',
        replace: '',
        match: '',
        exclude: '',
      });
    });
  });

  // ── computeAutoSyncStart ──────────────────────────────────────────────────
  describe('computeAutoSyncStart', () => {
    it('returns 1 when no other groups are active', () => {
      expect(computeAutoSyncStart([], 1)).toBe(1);
    });

    it('skips groups with the same id', () => {
      const groups = [
        makeGroup({
          channel_group: 1,
          auto_sync_channel_start: 100,
          auto_sync_channel_end: 200,
        }),
      ];
      expect(computeAutoSyncStart(groups, 1)).toBe(1);
    });

    it('skips disabled groups', () => {
      const groups = [
        makeGroup({
          channel_group: 2,
          enabled: false,
          auto_sync_channel_start: 100,
          auto_sync_channel_end: 200,
        }),
      ];
      expect(computeAutoSyncStart(groups, 1)).toBe(1);
    });

    it('skips groups with auto_channel_sync off', () => {
      const groups = [
        makeGroup({
          channel_group: 2,
          auto_channel_sync: false,
          auto_sync_channel_start: 100,
          auto_sync_channel_end: 200,
        }),
      ];
      expect(computeAutoSyncStart(groups, 1)).toBe(1);
    });

    it('skips groups with next_available mode', () => {
      const groups = [
        makeGroup({
          channel_group: 2,
          custom_properties: { channel_numbering_mode: 'next_available' },
          auto_sync_channel_start: 100,
          auto_sync_channel_end: 200,
        }),
      ];
      expect(computeAutoSyncStart(groups, 1)).toBe(1);
    });

    it('returns upper + 1 of the highest active group range', () => {
      const groups = [
        makeGroup({
          channel_group: 2,
          auto_sync_channel_start: 100,
          auto_sync_channel_end: 200,
        }),
      ];
      expect(computeAutoSyncStart(groups, 1)).toBe(201);
    });

    it('handles multiple groups and picks the highest upper bound', () => {
      const groups = [
        makeGroup({
          channel_group: 2,
          auto_sync_channel_start: 100,
          auto_sync_channel_end: 200,
        }),
        makeGroup({
          channel_group: 3,
          auto_sync_channel_start: 300,
          auto_sync_channel_end: 400,
        }),
      ];
      expect(computeAutoSyncStart(groups, 1)).toBe(401);
    });

    it('uses start as end when end is null', () => {
      const groups = [
        makeGroup({
          channel_group: 2,
          auto_sync_channel_start: 50,
          auto_sync_channel_end: null,
        }),
      ];
      expect(computeAutoSyncStart(groups, 1)).toBe(51);
    });

    it('uses provider fallback for provider mode', () => {
      const groups = [
        makeGroup({
          channel_group: 2,
          custom_properties: {
            channel_numbering_mode: 'provider',
            channel_numbering_fallback: 500,
          },
          auto_sync_channel_end: 600,
        }),
      ];
      expect(computeAutoSyncStart(groups, 1)).toBe(601);
    });
  });

  // ── isGroupVisible ────────────────────────────────────────────────────────
  describe('isGroupVisible', () => {
    it('returns true when text and status both match', () => {
      const group = makeGroup({ name: 'Sports', enabled: true });
      expect(isGroupVisible(group, 'sport', 'enabled')).toBe(true);
    });

    it('returns false when text does not match', () => {
      const group = makeGroup({ name: 'Sports', enabled: true });
      expect(isGroupVisible(group, 'news', 'all')).toBe(false);
    });

    it('returns false when status filter is enabled but group is disabled', () => {
      const group = makeGroup({ name: 'Sports', enabled: false });
      expect(isGroupVisible(group, 'sport', 'enabled')).toBe(false);
    });

    it('returns false when status filter is disabled but group is enabled', () => {
      const group = makeGroup({ name: 'Sports', enabled: true });
      expect(isGroupVisible(group, 'sport', 'disabled')).toBe(false);
    });

    it('returns true for disabled group with disabled filter', () => {
      const group = makeGroup({ name: 'Sports', enabled: false });
      expect(isGroupVisible(group, 'sport', 'disabled')).toBe(true);
    });

    it('matches regardless of case', () => {
      const group = makeGroup({ name: 'Sports HD', enabled: true });
      expect(isGroupVisible(group, 'SPORTS', 'all')).toBe(true);
    });

    it('returns true with empty text filter', () => {
      const group = makeGroup({ name: 'Sports', enabled: true });
      expect(isGroupVisible(group, '', 'all')).toBe(true);
    });
  });
});
