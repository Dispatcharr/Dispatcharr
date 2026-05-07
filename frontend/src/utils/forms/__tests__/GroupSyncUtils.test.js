import { describe, it, expect } from 'vitest';
import {
  getGroupReservation,
  detectGroupReservationOverlaps,
  formatOverlapMessage,
} from '../GroupSyncUtils';

const makeGroup = (overrides = {}) => ({
  channel_group: 1,
  name: 'Entertainment',
  enabled: true,
  auto_channel_sync: true,
  auto_sync_channel_start: 100,
  auto_sync_channel_end: 110,
  custom_properties: { channel_numbering_mode: 'fixed' },
  ...overrides,
});

describe('getGroupReservation', () => {
  it('returns [start, end] for a bounded Fixed group', () => {
    expect(getGroupReservation(makeGroup())).toEqual([100, 110]);
  });

  it('returns null when the group is disabled', () => {
    expect(getGroupReservation(makeGroup({ enabled: false }))).toBeNull();
  });

  it('returns null when auto_channel_sync is off', () => {
    expect(
      getGroupReservation(makeGroup({ auto_channel_sync: false }))
    ).toBeNull();
  });

  it('returns null when end is missing (unbounded group does not reserve)', () => {
    expect(
      getGroupReservation(makeGroup({ auto_sync_channel_end: null }))
    ).toBeNull();
  });

  it('returns null for Next Available mode regardless of bounds', () => {
    expect(
      getGroupReservation(
        makeGroup({
          custom_properties: { channel_numbering_mode: 'next_available' },
        })
      )
    ).toBeNull();
  });

  it('reads fallback as Start for Provider mode', () => {
    expect(
      getGroupReservation(
        makeGroup({
          auto_sync_channel_start: null,
          auto_sync_channel_end: 250,
          custom_properties: {
            channel_numbering_mode: 'provider',
            channel_numbering_fallback: 200,
          },
        })
      )
    ).toEqual([200, 250]);
  });

  it('returns null when end < start', () => {
    expect(
      getGroupReservation(
        makeGroup({ auto_sync_channel_start: 500, auto_sync_channel_end: 100 })
      )
    ).toBeNull();
  });
});

describe('detectGroupReservationOverlaps', () => {
  it('returns no conflicts when ranges are disjoint', () => {
    const a = makeGroup({
      channel_group: 1,
      name: 'A',
      auto_sync_channel_start: 1,
      auto_sync_channel_end: 100,
    });
    const b = makeGroup({
      channel_group: 2,
      name: 'B',
      auto_sync_channel_start: 101,
      auto_sync_channel_end: 200,
    });
    expect(detectGroupReservationOverlaps([a, b])).toEqual([]);
  });

  it('flags a straight overlap', () => {
    const a = makeGroup({
      channel_group: 1,
      name: 'A',
      auto_sync_channel_start: 1,
      auto_sync_channel_end: 100,
    });
    const b = makeGroup({
      channel_group: 2,
      name: 'B',
      auto_sync_channel_start: 50,
      auto_sync_channel_end: 150,
    });
    const conflicts = detectGroupReservationOverlaps([a, b]);
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].a.name).toBe('A');
    expect(conflicts[0].b.name).toBe('B');
  });

  it('flags an enclosed range (one reservation inside another)', () => {
    const outer = makeGroup({
      channel_group: 1,
      name: 'Outer',
      auto_sync_channel_start: 1,
      auto_sync_channel_end: 1000,
    });
    const inner = makeGroup({
      channel_group: 2,
      name: 'Inner',
      auto_sync_channel_start: 500,
      auto_sync_channel_end: 600,
    });
    expect(detectGroupReservationOverlaps([outer, inner])).toHaveLength(1);
  });

  it('ignores groups without reservations', () => {
    const unbounded = makeGroup({
      channel_group: 1,
      name: 'Unbounded',
      auto_sync_channel_end: null,
    });
    const next_avail = makeGroup({
      channel_group: 2,
      name: 'Next',
      custom_properties: { channel_numbering_mode: 'next_available' },
    });
    expect(detectGroupReservationOverlaps([unbounded, next_avail])).toEqual([]);
  });

  it('returns all pairwise overlaps when three groups collide', () => {
    const groups = [1, 2, 3].map((id) =>
      makeGroup({
        channel_group: id,
        name: `G${id}`,
        auto_sync_channel_start: 1,
        auto_sync_channel_end: 100,
      })
    );
    expect(detectGroupReservationOverlaps(groups)).toHaveLength(3);
  });
});

describe('formatOverlapMessage', () => {
  it('produces one line per conflict', () => {
    const conflicts = [
      {
        a: { name: 'A', start: 1, end: 100 },
        b: { name: 'B', start: 50, end: 150 },
      },
    ];
    const msg = formatOverlapMessage(conflicts);
    expect(msg).toContain('"A" [1-100]');
    expect(msg).toContain('"B" [50-150]');
  });

  it('truncates at five entries with a "... and N more" suffix', () => {
    const conflicts = Array.from({ length: 8 }, (_, i) => ({
      a: { name: `A${i}`, start: 1, end: 10 },
      b: { name: `B${i}`, start: 5, end: 15 },
    }));
    const msg = formatOverlapMessage(conflicts);
    expect(msg).toContain('and 3 more');
  });

  it('returns empty string for no conflicts', () => {
    expect(formatOverlapMessage([])).toBe('');
  });
});
