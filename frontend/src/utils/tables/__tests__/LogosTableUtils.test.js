import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as LogosTableUtils from '../LogosTableUtils';

// ── Dependency mocks ────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    deleteLogo: vi.fn(),
    deleteLogos: vi.fn(),
    cleanupUnusedLogos: vi.fn(),
  },
}));

import API from '../../../api.js';

describe('LogosTableUtils', () => {
  beforeEach(() => vi.clearAllMocks());

  // ── getFilteredLogos ────────────────────────────────────────────────────────
  describe('getFilteredLogos', () => {
    const logos = {
      1: { id: 1, name: 'ABC Logo', is_used: true },
      2: { id: 2, name: 'NBC Logo', is_used: false },
      3: { id: 3, name: 'CBS Logo', is_used: true },
      4: { id: 4, name: 'abc sports', is_used: false },
    };

    it('returns all logos sorted by id when no filters applied', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, '', 'all');
      expect(result.map((l) => l.id)).toEqual([1, 2, 3, 4]);
    });

    it('returns empty array for null logos', () => {
      expect(LogosTableUtils.getFilteredLogos(null, '', 'all')).toEqual([]);
    });

    it('returns empty array for undefined logos', () => {
      expect(LogosTableUtils.getFilteredLogos(undefined, '', 'all')).toEqual(
        []
      );
    });

    it('filters by name case-insensitively', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, 'abc', 'all');
      expect(result).toHaveLength(2);
      expect(result.map((l) => l.id)).toEqual([1, 4]);
    });

    it('filters by exact name match', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, 'NBC Logo', 'all');
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(2);
    });

    it('returns empty array when name filter matches nothing', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, 'xyz', 'all');
      expect(result).toHaveLength(0);
    });

    it('filters to used logos only when filtersUsed is "used"', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, '', 'used');
      expect(result.every((l) => l.is_used)).toBe(true);
      expect(result).toHaveLength(2);
    });

    it('filters to unused logos only when filtersUsed is "unused"', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, '', 'unused');
      expect(result.every((l) => !l.is_used)).toBe(true);
      expect(result).toHaveLength(2);
    });

    it('applies name filter and used filter together', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, 'abc', 'used');
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(1);
    });

    it('applies name filter and unused filter together', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, 'abc', 'unused');
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe(4);
    });

    it('sorts results by id ascending', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, '', 'all');
      expect(result).toHaveLength(4);
      for (let i = 1; i < result.length; i++) {
        expect(result[i].id).toBeGreaterThan(result[i - 1].id);
      }
    });

    it('returns empty array when logos object is empty', () => {
      expect(LogosTableUtils.getFilteredLogos({}, '', 'all')).toEqual([]);
    });

    it('does not filter when debouncedNameFilter is empty string', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, '', 'all');
      expect(result).toHaveLength(4);
    });

    it('does not apply usage filter for unrecognized filtersUsed value', () => {
      const result = LogosTableUtils.getFilteredLogos(logos, '', 'all');
      expect(result).toHaveLength(4);
    });
  });

  // ── deleteLogo ──────────────────────────────────────────────────────────────
  describe('deleteLogo', () => {
    it('calls API.deleteLogo with id and deleteFile', () => {
      const mockReturn = Promise.resolve(undefined);
      API.deleteLogo.mockReturnValue(mockReturn);
      const result = LogosTableUtils.deleteLogo(5, true);
      expect(API.deleteLogo).toHaveBeenCalledWith(5, true);
      expect(result).toBe(mockReturn);
    });

    it('passes deleteFile=false correctly', () => {
      LogosTableUtils.deleteLogo(3, false);
      expect(API.deleteLogo).toHaveBeenCalledWith(3, false);
    });
  });

  // ── deleteLogos ─────────────────────────────────────────────────────────────
  describe('deleteLogos', () => {
    it('calls API.deleteLogos with ids and deleteFiles', () => {
      const mockReturn = Promise.resolve(undefined);
      API.deleteLogos.mockReturnValue(mockReturn);
      const result = LogosTableUtils.deleteLogos([1, 2, 3], true);
      expect(API.deleteLogos).toHaveBeenCalledWith([1, 2, 3], true);
      expect(result).toBe(mockReturn);
    });

    it('passes deleteFiles=false correctly', () => {
      LogosTableUtils.deleteLogos([4, 5], false);
      expect(API.deleteLogos).toHaveBeenCalledWith([4, 5], false);
    });
  });

  // ── cleanupUnusedLogos ──────────────────────────────────────────────────────
  describe('cleanupUnusedLogos', () => {
    it('calls API.cleanupUnusedLogos with deleteFiles=true', () => {
      const mockReturn = Promise.resolve(undefined);
      API.cleanupUnusedLogos.mockReturnValue(mockReturn);
      const result = LogosTableUtils.cleanupUnusedLogos(true);
      expect(API.cleanupUnusedLogos).toHaveBeenCalledWith(true);
      expect(result).toBe(mockReturn);
    });

    it('calls API.cleanupUnusedLogos with deleteFiles=false', () => {
      LogosTableUtils.cleanupUnusedLogos(false);
      expect(API.cleanupUnusedLogos).toHaveBeenCalledWith(false);
    });
  });

  // ── generateUsageLabel ──────────────────────────────────────────────────────
  describe('generateUsageLabel', () => {
    describe('single type — channels only', () => {
      it('returns singular "channel" for 1 channel', () => {
        const names = ['Channel: HBO'];
        expect(LogosTableUtils.generateUsageLabel(names, 1)).toBe('1 channel');
      });

      it('returns plural "channels" for multiple channels', () => {
        const names = ['Channel: HBO', 'Channel: CNN', 'Channel: ESPN'];
        expect(LogosTableUtils.generateUsageLabel(names, 3)).toBe('3 channels');
      });
    });

    describe('single type — movies only', () => {
      it('returns singular "movie" for 1 movie', () => {
        const names = ['Movie: Inception'];
        expect(LogosTableUtils.generateUsageLabel(names, 1)).toBe('1 movie');
      });

      it('returns plural "movies" for multiple movies', () => {
        const names = ['Movie: Inception', 'Movie: Interstellar'];
        expect(LogosTableUtils.generateUsageLabel(names, 2)).toBe('2 movies');
      });
    });

    describe('single type — series only', () => {
      it('returns "series" for 1 series', () => {
        const names = ['Series: Breaking Bad'];
        expect(LogosTableUtils.generateUsageLabel(names, 1)).toBe('1 series');
      });

      it('returns "series" for multiple series', () => {
        const names = ['Series: Breaking Bad', 'Series: The Wire'];
        expect(LogosTableUtils.generateUsageLabel(names, 2)).toBe('2 series');
      });
    });

    describe('multiple types — generic items', () => {
      it('returns singular "item" when channelCount is 1', () => {
        const names = ['Channel: HBO', 'Movie: Inception'];
        expect(LogosTableUtils.generateUsageLabel(names, 1)).toBe('1 item');
      });

      it('returns plural "items" when channelCount > 1', () => {
        const names = ['Channel: HBO', 'Movie: Inception', 'Series: Lost'];
        expect(LogosTableUtils.generateUsageLabel(names, 3)).toBe('3 items');
      });

      it('uses channelCount not array length for generic label', () => {
        const names = ['Channel: HBO', 'Movie: Inception'];
        expect(LogosTableUtils.generateUsageLabel(names, 5)).toBe('5 items');
      });
    });

    describe('edge cases', () => {
      it('returns "0 items" for empty names array (no types match)', () => {
        expect(LogosTableUtils.generateUsageLabel([], 0)).toBe('0 items');
      });

      it('ignores unrecognized name prefixes', () => {
        const names = ['Unknown: Foo', 'Channel: HBO'];
        expect(LogosTableUtils.generateUsageLabel(names, 1)).toBe('1 channel');
      });
    });
  });
});
