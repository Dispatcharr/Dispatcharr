import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import useTablePreferences from '../useTablePreferences';

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

global.localStorage = localStorageMock;

describe('useTablePreferences', () => {
  let consoleErrorSpy;

  beforeEach(() => {
    // Spy on console.error
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    localStorageMock.clear();

    // Mock window.addEventListener and removeEventListener
    vi.spyOn(window, 'addEventListener');
    vi.spyOn(window, 'removeEventListener');
  });

  afterEach(() => {
    vi.clearAllMocks();
    consoleErrorSpy.mockRestore();
  });

  describe('Initial State', () => {
    it('should initialize with default values when localStorage is empty', () => {
      const { result } = renderHook(() => useTablePreferences());

      expect(result.current.headerPinned).toBe(false);
      expect(result.current.tableSize).toBe('default');
    });

    it('should initialize headerPinned from localStorage', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({ headerPinned: true }));

      const { result } = renderHook(() => useTablePreferences());

      expect(result.current.headerPinned).toBe(true);
    });

    it('should initialize tableSize from localStorage', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({ tableSize: 'compact' }));

      const { result } = renderHook(() => useTablePreferences());

      expect(result.current.tableSize).toBe('compact');
    });

    it('should initialize both preferences from localStorage', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({ headerPinned: true, tableSize: 'comfortable' }));

      const { result } = renderHook(() => useTablePreferences());

      expect(result.current.headerPinned).toBe(true);
      expect(result.current.tableSize).toBe('comfortable');
    });

    it('should migrate tableSize from old localStorage location', () => {
      localStorageMock.setItem('table-size', JSON.stringify('compact'));

      const { result } = renderHook(() => useTablePreferences());

      expect(result.current.tableSize).toBe('compact');
    });

    it('should prefer new localStorage location over old location', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({ tableSize: 'comfortable' }));
      localStorageMock.setItem('table-size', JSON.stringify('compact'));

      const { result } = renderHook(() => useTablePreferences());

      expect(result.current.tableSize).toBe('comfortable');
    });

    it('should handle malformed JSON in localStorage gracefully', () => {
      localStorageMock.setItem('table-preferences', 'invalid json');

      const { result } = renderHook(() => useTablePreferences());

      expect(result.current.headerPinned).toBe(false);
      expect(result.current.tableSize).toBe('default');
      expect(consoleErrorSpy).toHaveBeenCalledTimes(2);
    });
  });

  describe('setHeaderPinned', () => {
    it('should update headerPinned state', () => {
      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setHeaderPinned(true);
      });

      expect(result.current.headerPinned).toBe(true);
    });

    it('should persist headerPinned to localStorage', () => {
      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setHeaderPinned(true);
      });

      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'table-preferences',
        JSON.stringify({ headerPinned: true })
      );
    });

    it('should preserve existing preferences when updating headerPinned', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({ tableSize: 'compact' }));

      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setHeaderPinned(true);
      });

      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'table-preferences',
        JSON.stringify({ tableSize: 'compact', headerPinned: true })
      );
    });

    it('should dispatch custom event when updating headerPinned', () => {
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setHeaderPinned(true);
      });

      expect(dispatchEventSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'table-preferences-changed',
          detail: { headerPinned: true },
        })
      );

      dispatchEventSpy.mockRestore();
    });

    it('should handle localStorage errors gracefully', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({})); // Ensure it exists
      localStorageMock.setItem.mockImplementationOnce(() => {
        throw new Error('Storage error');
      });

      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setHeaderPinned(true);
      });

      expect(result.current.headerPinned).toBe(true);
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Error saving headerPinned to localStorage:',
        expect.any(Error)
      );
    });
  });

  describe('setTableSize', () => {
    it('should update tableSize state', () => {
      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setTableSize('compact');
      });

      expect(result.current.tableSize).toBe('compact');
    });

    it('should persist tableSize to localStorage', () => {
      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setTableSize('comfortable');
      });

      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'table-preferences',
        JSON.stringify({ tableSize: 'comfortable' })
      );
    });

    it('should preserve existing preferences when updating tableSize', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({ headerPinned: true }));

      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setTableSize('compact');
      });

      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'table-preferences',
        JSON.stringify({ headerPinned: true, tableSize: 'compact' })
      );
    });

    it('should dispatch custom event when updating tableSize', () => {
      const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent');

      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setTableSize('compact');
      });

      expect(dispatchEventSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'table-preferences-changed',
          detail: { tableSize: 'compact' },
        })
      );

      dispatchEventSpy.mockRestore();
    });

    it('should handle localStorage errors gracefully', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({})); // Ensure it exists
      localStorageMock.setItem.mockImplementationOnce(() => {
        throw new Error('Storage error');
      });

      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        result.current.setTableSize('compact');
      });

      expect(result.current.tableSize).toBe('compact');
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Error saving tableSize to localStorage:',
        expect.any(Error)
      );
    });
  });

  describe('Event Listeners', () => {
    it('should register event listener on mount', () => {
      renderHook(() => useTablePreferences());

      expect(window.addEventListener).toHaveBeenCalledWith(
        'table-preferences-changed',
        expect.any(Function)
      );
    });

    it('should remove event listener on unmount', () => {
      const { unmount } = renderHook(() => useTablePreferences());

      unmount();

      expect(window.removeEventListener).toHaveBeenCalledWith(
        'table-preferences-changed',
        expect.any(Function)
      );
    });

    it('should update headerPinned from custom event', () => {
      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        const event = new CustomEvent('table-preferences-changed', {
          detail: { headerPinned: true },
        });
        window.dispatchEvent(event);
      });

      expect(result.current.headerPinned).toBe(true);
    });

    it('should update tableSize from custom event', () => {
      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        const event = new CustomEvent('table-preferences-changed', {
          detail: { tableSize: 'compact' },
        });
        window.dispatchEvent(event);
      });

      expect(result.current.tableSize).toBe('compact');
    });

    it('should update both preferences from custom event', () => {
      const { result } = renderHook(() => useTablePreferences());

      act(() => {
        const event = new CustomEvent('table-preferences-changed', {
          detail: { headerPinned: true, tableSize: 'comfortable' },
        });
        window.dispatchEvent(event);
      });

      expect(result.current.headerPinned).toBe(true);
      expect(result.current.tableSize).toBe('comfortable');
    });

    it('should not update if value is the same', () => {
      localStorageMock.setItem('table-preferences', JSON.stringify({ headerPinned: true }));

      const { result } = renderHook(() => useTablePreferences());
      const initialHeaderPinned = result.current.headerPinned;

      act(() => {
        const event = new CustomEvent('table-preferences-changed', {
          detail: { headerPinned: true },
        });
        window.dispatchEvent(event);
      });

      expect(result.current.headerPinned).toBe(initialHeaderPinned);
    });
  });

  describe('Integration Tests', () => {
    it('should handle complete workflow', () => {
      const { result } = renderHook(() => useTablePreferences());

      // Update headerPinned
      act(() => {
        result.current.setHeaderPinned(true);
      });

      expect(result.current.headerPinned).toBe(true);
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'table-preferences',
        JSON.stringify({ headerPinned: true })
      );

      // Update tableSize
      act(() => {
        result.current.setTableSize('compact');
      });

      expect(result.current.tableSize).toBe('compact');
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'table-preferences',
        JSON.stringify({ headerPinned: true, tableSize: 'compact' })
      );

      // Verify both preferences are maintained
      expect(result.current.headerPinned).toBe(true);
      expect(result.current.tableSize).toBe('compact');
    });

    it('should sync changes across multiple hook instances via events', () => {
      const { result: result1 } = renderHook(() => useTablePreferences());
      const { result: result2 } = renderHook(() => useTablePreferences());

      // Update from first instance
      act(() => {
        result1.current.setHeaderPinned(true);
      });

      // Second instance should receive the event
      act(() => {
        const event = new CustomEvent('table-preferences-changed', {
          detail: { headerPinned: true },
        });
        window.dispatchEvent(event);
      });

      expect(result2.current.headerPinned).toBe(true);
    });
  });
});
