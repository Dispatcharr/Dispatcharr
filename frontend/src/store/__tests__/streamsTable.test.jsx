import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import useStreamsTableStore from '../streamsTable';

// Mock localStorage
const localStorageMock = (() => {
  let store = {};

  return {
    getItem: vi.fn((key) => store[key] || null),
    setItem: vi.fn((key, value) => {
      store[key] = value.toString();
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    removeItem: vi.fn((key) => {
      delete store[key];
    })
  };
})();

globalThis.localStorage = localStorageMock;

describe('useStreamsTableStore', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('Initial State', () => {
    it('should initialize with default state', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      expect(result.current.streams).toEqual([]);
      expect(result.current.pageCount).toBe(0);
      expect(result.current.totalCount).toBe(0);
      expect(result.current.sorting).toEqual([{ id: 'name', desc: false }]);
      expect(result.current.pagination).toEqual({
        pageIndex: 0,
        pageSize: 50,
      });
      expect(result.current.selectedStreamIds).toEqual([]);
      expect(result.current.allQueryIds).toEqual([]);
      expect(result.current.lastQueryParams).toBeNull();
    });

    it('should initialize pagination with localStorage value if available', () => {
      // Set localStorage BEFORE getting the store state
      localStorageMock.setItem('streams-page-size', JSON.stringify(100));

      // Now update the store to re-read from localStorage
      useStreamsTableStore.setState({
        pagination: {
          pageIndex: 0,
          pageSize: JSON.parse(localStorage.getItem('streams-page-size')) || 50,
        }
      });

      const { result } = renderHook(() => useStreamsTableStore());

      expect(result.current.pagination.pageSize).toBe(100);
    });

    it('should use default page size if localStorage is empty', () => {
      // Ensure localStorage is empty
      localStorageMock.clear();

      useStreamsTableStore.setState({
        pagination: {
          pageIndex: 0,
          pageSize: JSON.parse(localStorage.getItem('streams-page-size')) || 50,
        }
      });

      const { result } = renderHook(() => useStreamsTableStore());

      expect(result.current.pagination.pageSize).toBe(50);
    });
  });

  describe('queryStreams', () => {
    it('should update streams, totalCount, and pageCount', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const mockResults = [
        { id: 1, name: 'Stream 1' },
        { id: 2, name: 'Stream 2' },
      ];
      const mockCount = 100;
      const mockParams = new URLSearchParams({ page_size: '50' });

      act(() => {
        result.current.queryStreams(
          { results: mockResults, count: mockCount },
          mockParams
        );
      });

      expect(result.current.streams).toEqual(mockResults);
      expect(result.current.totalCount).toBe(100);
      expect(result.current.pageCount).toBe(2); // Math.ceil(100 / 50)
    });

    it('should calculate pageCount correctly with different page sizes', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const mockParams = new URLSearchParams({ page_size: '25' });

      act(() => {
        result.current.queryStreams(
          { results: [], count: 75 },
          mockParams
        );
      });

      expect(result.current.pageCount).toBe(3); // Math.ceil(75 / 25)
    });

    it('should handle empty results', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const mockParams = new URLSearchParams({ page_size: '50' });

      act(() => {
        result.current.queryStreams(
          { results: [], count: 0 },
          mockParams
        );
      });

      expect(result.current.streams).toEqual([]);
      expect(result.current.totalCount).toBe(0);
      expect(result.current.pageCount).toBe(0);
    });
  });

  describe('setAllQueryIds', () => {
    it('should update allQueryIds', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const mockIds = [1, 2, 3, 4, 5];

      act(() => {
        result.current.setAllQueryIds(mockIds);
      });

      expect(result.current.allQueryIds).toEqual(mockIds);
    });

    it('should replace previous allQueryIds', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      act(() => {
        result.current.setAllQueryIds([1, 2, 3]);
      });

      act(() => {
        result.current.setAllQueryIds([4, 5, 6]);
      });

      expect(result.current.allQueryIds).toEqual([4, 5, 6]);
    });
  });

  describe('setSelectedStreamIds', () => {
    it('should update selectedStreamIds', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const mockIds = [1, 3, 5];

      act(() => {
        result.current.setSelectedStreamIds(mockIds);
      });

      expect(result.current.selectedStreamIds).toEqual(mockIds);
    });

    it('should handle empty selection', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      act(() => {
        result.current.setSelectedStreamIds([1, 2, 3]);
      });

      act(() => {
        result.current.setSelectedStreamIds([]);
      });

      expect(result.current.selectedStreamIds).toEqual([]);
    });
  });

  describe('setPagination', () => {
    it('should update pagination state', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const newPagination = {
        pageIndex: 2,
        pageSize: 100,
      };

      act(() => {
        result.current.setPagination(newPagination);
      });

      expect(result.current.pagination).toEqual(newPagination);
    });

    it('should replace entire pagination object', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      act(() => {
        result.current.setPagination({ pageIndex: 1, pageSize: 25 });
      });

      act(() => {
        result.current.setPagination({ pageIndex: 3, pageSize: 75 });
      });

      expect(result.current.pagination).toEqual({ pageIndex: 3, pageSize: 75 });
    });
  });

  describe('setSorting', () => {
    it('should update sorting state', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const newSorting = [{ id: 'created_at', desc: true }];

      act(() => {
        result.current.setSorting(newSorting);
      });

      expect(result.current.sorting).toEqual(newSorting);
    });

    it('should handle multiple sorting columns', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const newSorting = [
        { id: 'name', desc: false },
        { id: 'created_at', desc: true },
      ];

      act(() => {
        result.current.setSorting(newSorting);
      });

      expect(result.current.sorting).toEqual(newSorting);
    });

    it('should handle empty sorting array', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      act(() => {
        result.current.setSorting([]);
      });

      expect(result.current.sorting).toEqual([]);
    });
  });

  describe('setLastQueryParams', () => {
    it('should update lastQueryParams', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      const mockParams = new URLSearchParams({ page: '1', search: 'test' });

      act(() => {
        result.current.setLastQueryParams(mockParams);
      });

      expect(result.current.lastQueryParams).toBe(mockParams);
    });

    it('should handle null value', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      act(() => {
        result.current.setLastQueryParams(new URLSearchParams());
      });

      act(() => {
        result.current.setLastQueryParams(null);
      });

      expect(result.current.lastQueryParams).toBeNull();
    });
  });

  describe('Integration Tests', () => {
    it('should handle a typical query flow', () => {
      const { result } = renderHook(() => useStreamsTableStore());

      // Set pagination
      act(() => {
        result.current.setPagination({ pageIndex: 0, pageSize: 25 });
      });

      // Set sorting
      act(() => {
        result.current.setSorting([{ id: 'created_at', desc: true }]);
      });

      // Query streams
      const mockResults = [
        { id: 1, name: 'Stream 1' },
        { id: 2, name: 'Stream 2' },
      ];
      const mockParams = new URLSearchParams({ page_size: '25' });

      act(() => {
        result.current.queryStreams(
          { results: mockResults, count: 50 },
          mockParams
        );
      });

      // Set query IDs
      act(() => {
        result.current.setAllQueryIds([1, 2, 3, 4, 5]);
      });

      // Select streams
      act(() => {
        result.current.setSelectedStreamIds([1, 2]);
      });

      // Set last query params
      act(() => {
        result.current.setLastQueryParams(mockParams);
      });

      expect(result.current.streams).toEqual(mockResults);
      expect(result.current.totalCount).toBe(50);
      expect(result.current.pageCount).toBe(2);
      expect(result.current.pagination).toEqual({ pageIndex: 0, pageSize: 25 });
      expect(result.current.sorting).toEqual([{ id: 'created_at', desc: true }]);
      expect(result.current.allQueryIds).toEqual([1, 2, 3, 4, 5]);
      expect(result.current.selectedStreamIds).toEqual([1, 2]);
      expect(result.current.lastQueryParams).toBe(mockParams);
    });
  });
});
