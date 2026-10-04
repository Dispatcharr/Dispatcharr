import { describe, expect, it } from 'vitest';
import { sortLockedFirstByName } from '../profileTableUtils.js';

describe('sortLockedFirstByName', () => {
  it('puts locked profiles before unlocked ones', () => {
    const result = sortLockedFirstByName([
      { id: 1, name: 'Custom', locked: false },
      { id: 2, name: 'FFmpeg', locked: true },
      { id: 3, name: 'Mine', locked: false },
    ]);
    expect(result.map((p) => p.name)).toEqual(['FFmpeg', 'Custom', 'Mine']);
  });

  it('sorts locked profiles alphabetically among themselves', () => {
    const result = sortLockedFirstByName([
      { id: 1, name: 'VLC', locked: true },
      { id: 2, name: 'FFmpeg', locked: true },
      { id: 3, name: 'Streamlink', locked: true },
    ]);
    expect(result.map((p) => p.name)).toEqual(['FFmpeg', 'Streamlink', 'VLC']);
  });

  it('sorts unlocked profiles alphabetically among themselves', () => {
    const result = sortLockedFirstByName([
      { id: 1, name: 'Zebra', locked: false },
      { id: 2, name: 'Alpha', locked: false },
    ]);
    expect(result.map((p) => p.name)).toEqual(['Alpha', 'Zebra']);
  });

  it('orders names case-insensitively', () => {
    const result = sortLockedFirstByName([
      { id: 1, name: 'beta', locked: false },
      { id: 2, name: 'Alpha', locked: false },
      { id: 3, name: 'Gamma', locked: false },
    ]);
    expect(result.map((p) => p.name)).toEqual(['Alpha', 'beta', 'Gamma']);
  });

  it('breaks name ties by id regardless of input order', () => {
    const a = { id: 7, name: 'Same', locked: false };
    const b = { id: 3, name: 'same', locked: false };
    const c = { id: 5, name: 'SAME', locked: false };
    expect(sortLockedFirstByName([a, b, c]).map((p) => p.id)).toEqual([
      3, 5, 7,
    ]);
    expect(sortLockedFirstByName([c, a, b]).map((p) => p.id)).toEqual([
      3, 5, 7,
    ]);
  });

  it('tolerates missing name and locked fields', () => {
    const result = sortLockedFirstByName([
      { id: 1, name: 'Named' },
      { id: 2, name: null },
      { id: 3, name: 'Locked', locked: true },
    ]);
    expect(result.map((p) => p.id)).toEqual([3, 2, 1]);
  });

  it('does not mutate the input array', () => {
    const input = [
      { id: 1, name: 'B', locked: false },
      { id: 2, name: 'A', locked: true },
    ];
    const original = [...input];
    sortLockedFirstByName(input);
    expect(input).toEqual(original);
  });
});
