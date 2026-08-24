import { describe, expect, it } from 'vitest';
import {
  findGrowResizeNeighbor,
  transferGrowColumnResize,
} from '../transferGrowColumnResize';

describe('transferGrowColumnResize', () => {
  const defaults = { name: 200, epg: 200 };

  it('transfers a grow-column delta onto the neighbor column', () => {
    expect(
      transferGrowColumnResize({
        previousSizing: { name: 200, epg: 200 },
        nextSizing: { name: 250, epg: 200 },
        growColumnId: 'name',
        neighborId: 'epg',
        defaults,
        neighborMin: 120,
      })
    ).toEqual({ name: 250, epg: 150 });
  });

  it('clamps against the neighbor minimum', () => {
    expect(
      transferGrowColumnResize({
        previousSizing: { name: 200, epg: 200 },
        nextSizing: { name: 400, epg: 200 },
        growColumnId: 'name',
        neighborId: 'epg',
        defaults,
        neighborMin: 120,
      })
    ).toEqual({ name: 280, epg: 120 });
  });

  it('passes through unrelated column size changes', () => {
    expect(
      transferGrowColumnResize({
        previousSizing: { name: 200, epg: 200, channel_number: 40 },
        nextSizing: { name: 200, epg: 200, channel_number: 60 },
        growColumnId: 'name',
        neighborId: 'epg',
        defaults,
        neighborMin: 120,
      })
    ).toEqual({ name: 200, epg: 200, channel_number: 60 });
  });

  it('returns the next sizing unchanged when no neighbor is available', () => {
    expect(
      transferGrowColumnResize({
        previousSizing: { name: 200 },
        nextSizing: { name: 250 },
        growColumnId: 'name',
        neighborId: null,
        defaults,
      })
    ).toEqual({ name: 250 });
  });

  it('applies deltas from drag-start sizes so clamps do not double-count', () => {
    expect(
      transferGrowColumnResize({
        previousSizing: { name: 280, epg: 120 },
        nextSizing: { name: 400, epg: 120 },
        growColumnId: 'name',
        neighborId: 'epg',
        defaults,
        neighborMin: 120,
        dragStart: { sourceSize: 200, neighborSize: 200 },
      })
    ).toEqual({ name: 280, epg: 120 });
  });
});

describe('findGrowResizeNeighbor', () => {
  const columns = [
    { id: 'name', grow: true, transferResizeToNeighbor: true, size: 200 },
    { id: 'group', size: 150, minSize: 75 },
    { id: 'm3u', size: 150, minSize: 75 },
    { id: 'logo', size: 75, enableResizing: false },
  ];

  it('returns the next visible fixed resizable column', () => {
    expect(findGrowResizeNeighbor(columns, 'name')).toMatchObject({
      id: 'group',
    });
  });

  it('skips hidden columns when choosing a transfer target', () => {
    expect(
      findGrowResizeNeighbor(columns, 'name', { group: false })
    ).toMatchObject({ id: 'm3u' });
  });

  it('can transfer into a non-resizable final content column', () => {
    const withEpgTransfer = [
      { id: 'name', grow: true, transferResizeToNeighbor: true, size: 200 },
      { id: 'epg', size: 200, minSize: 120, transferResizeToNeighbor: true },
      { id: 'group', size: 150, minSize: 75, enableResizing: false },
    ];
    expect(findGrowResizeNeighbor(withEpgTransfer, 'epg')).toMatchObject({
      id: 'group',
    });
  });
});
