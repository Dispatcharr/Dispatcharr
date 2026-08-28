import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useBrowserStorage, {
  readStoredJSON,
  writeStoredJSON,
} from '../useBrowserStorage';

const createStorageMock = () => {
  let store = {};

  return {
    getItem: vi.fn((key) => (key in store ? store[key] : null)),
    setItem: vi.fn((key, value) => {
      store[key] = value.toString();
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    removeItem: vi.fn((key) => {
      delete store[key];
    }),
  };
};

const localStorageMock = createStorageMock();
const sessionStorageMock = createStorageMock();

globalThis.localStorage = localStorageMock;
globalThis.sessionStorage = sessionStorageMock;

// Mock console.error to avoid cluttering test output
globalThis.console.error = vi.fn();

describe('readStoredJSON / writeStoredJSON', () => {
  beforeEach(() => {
    localStorageMock.clear();
    sessionStorageMock.clear();
    vi.clearAllMocks();
  });

  it('returns default when storage is empty', () => {
    expect(readStoredJSON('missing', 'fallback')).toBe('fallback');
  });

  it('reads and writes localStorage by default', () => {
    writeStoredJSON('prefs', { a: 1 });
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      'prefs',
      JSON.stringify({ a: 1 })
    );
    expect(readStoredJSON('prefs', {})).toEqual({ a: 1 });
  });

  it('reads and writes sessionStorage when storage is session', () => {
    writeStoredJSON('filters', { name: 'espn' }, 'session');
    expect(sessionStorageMock.setItem).toHaveBeenCalledWith(
      'filters',
      JSON.stringify({ name: 'espn' })
    );
    expect(readStoredJSON('filters', {}, 'session')).toEqual({ name: 'espn' });
    expect(localStorageMock.setItem).not.toHaveBeenCalled();
  });

  it('shallow-merges plain objects with defaults on read', () => {
    writeStoredJSON('filters', { name: 'espn' }, 'session');
    expect(
      readStoredJSON(
        'filters',
        { name: '', hide_stale: false, is_catchup: false },
        'session'
      )
    ).toEqual({ name: 'espn', hide_stale: false, is_catchup: false });
  });

  it('returns default on invalid JSON', () => {
    localStorageMock.getItem.mockReturnValueOnce('invalid json{');
    expect(readStoredJSON('bad', 'default')).toBe('default');
    expect(console.error).toHaveBeenCalled();
  });
});

describe('useBrowserStorage', () => {
  beforeEach(() => {
    localStorageMock.clear();
    sessionStorageMock.clear();
    vi.clearAllMocks();
  });

  it('should initialize with default value when localStorage is empty', () => {
    const { result } = renderHook(() =>
      useBrowserStorage('testKey', 'defaultValue')
    );

    expect(result.current[0]).toBe('defaultValue');
  });

  it('should initialize with value from localStorage if available', () => {
    localStorageMock.setItem('testKey', JSON.stringify('storedValue'));

    const { result } = renderHook(() =>
      useBrowserStorage('testKey', 'defaultValue')
    );

    expect(result.current[0]).toBe('storedValue');
  });

  it('should update localStorage when value changes', () => {
    const { result } = renderHook(() =>
      useBrowserStorage('testKey', 'initial')
    );

    act(() => {
      result.current[1]('updated');
    });

    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      'testKey',
      JSON.stringify('updated')
    );
    expect(result.current[0]).toBe('updated');
  });

  it('should handle complex objects', () => {
    const complexObject = { name: 'test', count: 42, nested: { value: true } };

    const { result } = renderHook(() =>
      useBrowserStorage('testKey', complexObject)
    );

    act(() => {
      result.current[1]({ name: 'updated', count: 100 });
    });

    expect(result.current[0]).toEqual({ name: 'updated', count: 100 });
  });

  it('should handle errors when reading from localStorage', () => {
    localStorageMock.getItem.mockImplementationOnce(() => {
      throw new Error('Read error');
    });

    const { result } = renderHook(() =>
      useBrowserStorage('testKey', 'defaultValue')
    );

    expect(result.current[0]).toBe('defaultValue');
    expect(console.error).toHaveBeenCalledWith(
      'Error reading key "testKey":',
      expect.any(Error)
    );
  });

  it('should handle errors when writing to localStorage', () => {
    localStorageMock.setItem.mockImplementationOnce(() => {
      throw new Error('Write error');
    });

    const { result } = renderHook(() =>
      useBrowserStorage('testKey', 'initial')
    );

    act(() => {
      result.current[1]('updated');
    });

    expect(console.error).toHaveBeenCalledWith(
      'Error saving setting: testKey:',
      expect.any(Error)
    );
  });

  it('should handle invalid JSON in localStorage', () => {
    localStorageMock.getItem.mockReturnValueOnce('invalid json{');

    const { result } = renderHook(() =>
      useBrowserStorage('testKey', 'defaultValue')
    );

    expect(result.current[0]).toBe('defaultValue');
    expect(console.error).toHaveBeenCalled();
  });

  it('should use sessionStorage when storage option is session', () => {
    sessionStorageMock.setItem(
      'sessionKey',
      JSON.stringify({ name: 'restored' })
    );

    const { result } = renderHook(() =>
      useBrowserStorage('sessionKey', { name: '' }, { storage: 'session' })
    );

    expect(result.current[0]).toEqual({ name: 'restored' });

    act(() => {
      result.current[1]({ name: 'updated' });
    });

    expect(sessionStorageMock.setItem).toHaveBeenCalledWith(
      'sessionKey',
      JSON.stringify({ name: 'updated' })
    );
    expect(
      localStorageMock.setItem.mock.calls.some(([key]) => key === 'sessionKey')
    ).toBe(false);
  });

  it('should merge stored objects with defaults on init', () => {
    localStorageMock.setItem('objKey', JSON.stringify({ name: 'espn' }));

    const { result } = renderHook(() =>
      useBrowserStorage('objKey', { name: '', hide_stale: false })
    );

    expect(result.current[0]).toEqual({ name: 'espn', hide_stale: false });
  });
});
