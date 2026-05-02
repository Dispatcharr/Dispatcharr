import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  addM3UFilter,
  updateM3UFilter,
  deleteM3UFilter,
} from '../M3uFilterUtils.js';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    addM3UFilter: vi.fn(),
    updateM3UFilter: vi.fn(),
    deleteM3UFilter: vi.fn(),
  },
}));

import API from '../../../api.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeM3U = (overrides = {}) => ({ id: 'm3u-1', name: 'My Playlist', ...overrides });
const makeFilter = (overrides = {}) => ({ id: 'filter-1', name: 'Filter A', ...overrides });
const makeValues = (overrides = {}) => ({ keyword: 'sports', type: 'include', ...overrides });

describe('M3uFilterUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── addM3UFilter ───────────────────────────────────────────────────────────

  describe('addM3UFilter', () => {
    it('calls API.addM3UFilter with the m3u id and values', async () => {
      vi.mocked(API.addM3UFilter).mockResolvedValue(undefined);

      await addM3UFilter(makeM3U(), makeValues());

      expect(API.addM3UFilter).toHaveBeenCalledWith('m3u-1', makeValues());
    });

    it('calls API.addM3UFilter exactly once', async () => {
      vi.mocked(API.addM3UFilter).mockResolvedValue(undefined);

      await addM3UFilter(makeM3U(), makeValues());

      expect(API.addM3UFilter).toHaveBeenCalledTimes(1);
    });

    it('uses only the id from the m3u object', async () => {
      vi.mocked(API.addM3UFilter).mockResolvedValue(undefined);
      const m3u = makeM3U({ id: 'm3u-99', name: 'Irrelevant' });

      await addM3UFilter(m3u, makeValues());

      expect(API.addM3UFilter).toHaveBeenCalledWith('m3u-99', expect.anything());
    });

    it('passes values through unmodified', async () => {
      vi.mocked(API.addM3UFilter).mockResolvedValue(undefined);
      const values = { keyword: 'news', type: 'exclude', extra: 'data' };

      await addM3UFilter(makeM3U(), values);

      expect(API.addM3UFilter).toHaveBeenCalledWith(expect.anything(), values);
    });

    it('propagates rejection from API.addM3UFilter', async () => {
      vi.mocked(API.addM3UFilter).mockRejectedValue(new Error('Add failed'));

      await expect(addM3UFilter(makeM3U(), makeValues())).rejects.toThrow('Add failed');
    });

    it('resolves without returning a value', async () => {
      vi.mocked(API.addM3UFilter).mockResolvedValue({ id: 'filter-2' });

      const result = await addM3UFilter(makeM3U(), makeValues());

      expect(result).toBeUndefined();
    });
  });

  // ── updateM3UFilter ────────────────────────────────────────────────────────

  describe('updateM3UFilter', () => {
    it('calls API.updateM3UFilter with the m3u id, filter id, and values', () => {
      vi.mocked(API.updateM3UFilter).mockReturnValue({ id: 'filter-1' });

      updateM3UFilter(makeM3U(), makeFilter(), makeValues());

      expect(API.updateM3UFilter).toHaveBeenCalledWith('m3u-1', 'filter-1', makeValues());
    });

    it('returns the result of API.updateM3UFilter', () => {
      const mockResult = { id: 'filter-1', keyword: 'sports' };
      vi.mocked(API.updateM3UFilter).mockReturnValue(mockResult);

      const result = updateM3UFilter(makeM3U(), makeFilter(), makeValues());

      expect(result).toBe(mockResult);
    });

    it('calls API.updateM3UFilter exactly once', () => {
      vi.mocked(API.updateM3UFilter).mockReturnValue({});

      updateM3UFilter(makeM3U(), makeFilter(), makeValues());

      expect(API.updateM3UFilter).toHaveBeenCalledTimes(1);
    });

    it('uses only the id from the m3u object', () => {
      vi.mocked(API.updateM3UFilter).mockReturnValue({});
      const m3u = makeM3U({ id: 'm3u-42', name: 'Irrelevant' });

      updateM3UFilter(m3u, makeFilter(), makeValues());

      expect(API.updateM3UFilter).toHaveBeenCalledWith('m3u-42', expect.anything(), expect.anything());
    });

    it('uses only the id from the filter object', () => {
      vi.mocked(API.updateM3UFilter).mockReturnValue({});
      const filter = makeFilter({ id: 'filter-99', name: 'Irrelevant' });

      updateM3UFilter(makeM3U(), filter, makeValues());

      expect(API.updateM3UFilter).toHaveBeenCalledWith(expect.anything(), 'filter-99', expect.anything());
    });

    it('passes values through unmodified', () => {
      vi.mocked(API.updateM3UFilter).mockReturnValue({});
      const values = { keyword: 'movies', type: 'exclude', extra: 'data' };

      updateM3UFilter(makeM3U(), makeFilter(), values);

      expect(API.updateM3UFilter).toHaveBeenCalledWith(expect.anything(), expect.anything(), values);
    });
  });

  // ── deleteM3UFilter ────────────────────────────────────────────────────────

  describe('deleteM3UFilter', () => {
    it('calls API.deleteM3UFilter with the playlist id and filter id', async () => {
      vi.mocked(API.deleteM3UFilter).mockResolvedValue(undefined);

      await deleteM3UFilter(makeM3U(), 'filter-1');

      expect(API.deleteM3UFilter).toHaveBeenCalledWith('m3u-1', 'filter-1');
    });

    it('calls API.deleteM3UFilter exactly once', async () => {
      vi.mocked(API.deleteM3UFilter).mockResolvedValue(undefined);

      await deleteM3UFilter(makeM3U(), 'filter-1');

      expect(API.deleteM3UFilter).toHaveBeenCalledTimes(1);
    });

    it('uses only the id from the playlist object', async () => {
      vi.mocked(API.deleteM3UFilter).mockResolvedValue(undefined);
      const playlist = makeM3U({ id: 'playlist-99', name: 'Irrelevant' });

      await deleteM3UFilter(playlist, 'filter-1');

      expect(API.deleteM3UFilter).toHaveBeenCalledWith('playlist-99', expect.anything());
    });

    it('passes the filter id through unmodified', async () => {
      vi.mocked(API.deleteM3UFilter).mockResolvedValue(undefined);

      await deleteM3UFilter(makeM3U(), 'filter-42');

      expect(API.deleteM3UFilter).toHaveBeenCalledWith(expect.anything(), 'filter-42');
    });

    it('propagates rejection from API.deleteM3UFilter', async () => {
      vi.mocked(API.deleteM3UFilter).mockRejectedValue(new Error('Delete failed'));

      await expect(deleteM3UFilter(makeM3U(), 'filter-1')).rejects.toThrow('Delete failed');
    });

    it('resolves without returning a value', async () => {
      vi.mocked(API.deleteM3UFilter).mockResolvedValue({ success: true });

      const result = await deleteM3UFilter(makeM3U(), 'filter-1');

      expect(result).toBeUndefined();
    });
  });
});