import { describe, it, expect } from 'vitest';
import * as VODsUtils from '../VODsUtils';

describe('VODsUtils', () => {
  describe('getCategoryOptions', () => {
    it('should return all categories option plus formatted categories', () => {
      const categories = {
        'cat1': { name: 'Action', category_type: 'movie' },
        'cat2': { name: 'Drama', category_type: 'series' }
      };
      const filters = { type: 'all' };

      const result = VODsUtils.getCategoryOptions(categories, filters);

      expect(result).toHaveLength(3);
      expect(result[0]).toEqual({ value: '', label: 'All Categories' });
      expect(result[1]).toEqual({ value: 'Action|movie', label: 'Action (movie)' });
      expect(result[2]).toEqual({ value: 'Drama|series', label: 'Drama (series)' });
    });

    it('should filter to only movies when type is movies', () => {
      const categories = {
        'cat1': { name: 'Action', category_type: 'movie' },
        'cat2': { name: 'Drama', category_type: 'series' },
        'cat3': { name: 'Comedy', category_type: 'movie' }
      };
      const filters = { type: 'movies' };

      const result = VODsUtils.getCategoryOptions(categories, filters);

      expect(result).toHaveLength(3);
      expect(result[0]).toEqual({ value: '', label: 'All Categories' });
      expect(result[1].label).toContain('(movie)');
      expect(result[2].label).toContain('(movie)');
    });

    it('should filter to only series when type is series', () => {
      const categories = {
        'cat1': { name: 'Action', category_type: 'movie' },
        'cat2': { name: 'Drama', category_type: 'series' },
        'cat3': { name: 'Sitcom', category_type: 'series' }
      };
      const filters = { type: 'series' };

      const result = VODsUtils.getCategoryOptions(categories, filters);

      expect(result).toHaveLength(3);
      expect(result[0]).toEqual({ value: '', label: 'All Categories' });
      expect(result[1].label).toContain('(series)');
      expect(result[2].label).toContain('(series)');
    });

    it('should show all categories when type is all', () => {
      const categories = {
        'cat1': { name: 'Action', category_type: 'movie' },
        'cat2': { name: 'Drama', category_type: 'series' }
      };
      const filters = { type: 'all' };

      const result = VODsUtils.getCategoryOptions(categories, filters);

      expect(result).toHaveLength(3);
    });

    it('should handle empty categories object', () => {
      const categories = {};
      const filters = { type: 'all' };

      const result = VODsUtils.getCategoryOptions(categories, filters);

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({ value: '', label: 'All Categories' });
    });

    it('should create value with name and category_type separated by pipe', () => {
      const categories = {
        'cat1': { name: 'Action', category_type: 'movie' }
      };
      const filters = { type: 'all' };

      const result = VODsUtils.getCategoryOptions(categories, filters);

      expect(result[1].value).toBe('Action|movie');
    });

    it('should handle undefined type filter', () => {
      const categories = {
        'cat1': { name: 'Action', category_type: 'movie' },
        'cat2': { name: 'Drama', category_type: 'series' }
      };
      const filters = {};

      const result = VODsUtils.getCategoryOptions(categories, filters);

      expect(result).toHaveLength(3);
    });

    it('should filter out categories that do not match type', () => {
      const categories = {
        'cat1': { name: 'Action', category_type: 'movie' },
        'cat2': { name: 'Drama', category_type: 'series' },
        'cat3': { name: 'Comedy', category_type: 'movie' }
      };
      const filters = { type: 'series' };

      const result = VODsUtils.getCategoryOptions(categories, filters);

      expect(result).toHaveLength(2);
      expect(result[1].value).toBe('Drama|series');
    });
  });

  describe('filterCategoriesToEnabled', () => {
    it('should return only categories with enabled m3u_accounts', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          m3u_accounts: [
            { id: 1, enabled: true }
          ]
        },
        'cat2': {
          name: 'Drama',
          m3u_accounts: [
            { id: 2, enabled: false }
          ]
        }
      };

      const result = VODsUtils.filterCategoriesToEnabled(allCategories);

      expect(result).toHaveProperty('cat1');
      expect(result).not.toHaveProperty('cat2');
    });

    it('should include category if any m3u_account is enabled', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          m3u_accounts: [
            { id: 1, enabled: false },
            { id: 2, enabled: true },
            { id: 3, enabled: false }
          ]
        }
      };

      const result = VODsUtils.filterCategoriesToEnabled(allCategories);

      expect(result).toHaveProperty('cat1');
    });

    it('should exclude category if all m3u_accounts are disabled', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          m3u_accounts: [
            { id: 1, enabled: false },
            { id: 2, enabled: false }
          ]
        }
      };

      const result = VODsUtils.filterCategoriesToEnabled(allCategories);

      expect(result).not.toHaveProperty('cat1');
    });

    it('should exclude category with empty m3u_accounts array', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          m3u_accounts: []
        }
      };

      const result = VODsUtils.filterCategoriesToEnabled(allCategories);

      expect(result).not.toHaveProperty('cat1');
    });

    it('should preserve original category data', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          category_type: 'movie',
          m3u_accounts: [
            { id: 1, enabled: true }
          ]
        }
      };

      const result = VODsUtils.filterCategoriesToEnabled(allCategories);

      expect(result.cat1).toEqual(allCategories.cat1);
    });

    it('should handle empty allCategories object', () => {
      const result = VODsUtils.filterCategoriesToEnabled({});

      expect(result).toEqual({});
    });

    it('should filter multiple categories correctly', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          m3u_accounts: [{ id: 1, enabled: true }]
        },
        'cat2': {
          name: 'Drama',
          m3u_accounts: [{ id: 2, enabled: false }]
        },
        'cat3': {
          name: 'Comedy',
          m3u_accounts: [{ id: 3, enabled: true }]
        }
      };

      const result = VODsUtils.filterCategoriesToEnabled(allCategories);

      expect(Object.keys(result)).toHaveLength(2);
      expect(result).toHaveProperty('cat1');
      expect(result).toHaveProperty('cat3');
      expect(result).not.toHaveProperty('cat2');
    });

    it('should handle category with null m3u_accounts', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          m3u_accounts: null
        }
      };

      expect(() => {
        VODsUtils.filterCategoriesToEnabled(allCategories);
      }).toThrow();
    });

    it('should handle truthy enabled values', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          m3u_accounts: [
            { id: 1, enabled: 1 },
            { id: 2, enabled: false }
          ]
        }
      };

      const result = VODsUtils.filterCategoriesToEnabled(allCategories);

      expect(result).not.toHaveProperty('cat1');
    });

    it('should only match strict true for enabled', () => {
      const allCategories = {
        'cat1': {
          name: 'Action',
          m3u_accounts: [
            { id: 1, enabled: 'true' }
          ]
        }
      };

      const result = VODsUtils.filterCategoriesToEnabled(allCategories);

      expect(result).not.toHaveProperty('cat1');
    });
  });
});
