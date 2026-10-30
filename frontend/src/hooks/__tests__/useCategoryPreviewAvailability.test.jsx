import { renderHook, waitFor, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import API from '../../api.js';
import useCategoryPreviewAvailability, {
  EMPTY_CATEGORY_PREVIEW_HINT,
} from '../useCategoryPreviewAvailability.jsx';

let timings;
vi.mock('../../api.js', () => ({
  default: { getM3UGroupContentAvailability: vi.fn() },
}));
vi.mock('../../store/playlists', () => ({
  default: (selector) =>
    selector({
      playlists: [{ id: 1, custom_properties: { refresh_timings: timings } }],
    }),
}));

describe('Category preview availability', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    timings = {};
    API.getM3UGroupContentAvailability.mockResolvedValue({
      live: [3],
      movie: [8],
      series: [],
    });
  });
  it('loads all three scopes once and exposes only imported IDs', async () => {
    const { result } = renderHook(() =>
      useCategoryPreviewAvailability(1, true)
    );
    await waitFor(() =>
      expect(result.current.availability?.movie.has(8)).toBe(true)
    );
    expect(result.current.availability.live.has(3)).toBe(true);
    expect(result.current.availability.series.size).toBe(0);
    expect(result.current.hint).toBe(EMPTY_CATEGORY_PREVIEW_HINT);
    expect(API.getM3UGroupContentAvailability).toHaveBeenCalledTimes(1);
  });
  it('does not load for a closed dialog', () => {
    renderHook(() => useCategoryPreviewAvailability(1, false));
    expect(API.getM3UGroupContentAvailability).not.toHaveBeenCalled();
  });
  it('checks again after a completed refresh changes its timestamp', async () => {
    const { result, rerender } = renderHook(() =>
      useCategoryPreviewAvailability(1, true)
    );
    await waitFor(() => expect(result.current.availability).not.toBeNull());
    timings = { vod_completed_at: '2026-10-14T17:00:00Z' };
    rerender();
    await waitFor(() =>
      expect(API.getM3UGroupContentAvailability).toHaveBeenCalledTimes(2)
    );
  });
  it('explains a failed check instead of treating it as imported content', async () => {
    API.getM3UGroupContentAvailability.mockRejectedValueOnce(
      new Error('Unavailable')
    );
    const { result } = renderHook(() =>
      useCategoryPreviewAvailability(1, true)
    );
    await waitFor(() =>
      expect(result.current.hint).toContain('could not be checked')
    );
    expect(result.current.availability).toBeNull();
  });
  it('ignores a late result from a previously selected account', async () => {
    let resolveFirst;
    API.getM3UGroupContentAvailability.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve;
        })
    );
    const { result, rerender } = renderHook(
      ({ id }) => useCategoryPreviewAvailability(id, true),
      { initialProps: { id: 1 } }
    );
    rerender({ id: 2 });
    await waitFor(() =>
      expect(result.current.availability?.movie.has(8)).toBe(true)
    );
    await act(async () => resolveFirst({ live: [999], movie: [], series: [] }));
    expect(result.current.availability.live.has(999)).toBe(false);
  });
});
