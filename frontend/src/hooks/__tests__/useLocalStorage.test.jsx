import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useLocalStorage from '../useLocalStorage';

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
    }),
  };
})();

global.localStorage = localStorageMock;

// Mock console.error to avoid cluttering test output
global.console.error = vi.fn();

describe('useLocalStorage', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.clearAllMocks();
  });

  it('should initialize with default value when localStorage is empty', () => {
    const { result } = renderHook(() =>
      useLocalStorage('testKey', 'defaultValue')
    );

    expect(result.current[0]).toBe('defaultValue');
  });

  it('should initialize with value from localStorage if available', () => {
    localStorageMock.setItem('testKey', JSON.stringify('storedValue'));

    const { result } = renderHook(() =>
      useLocalStorage('testKey', 'defaultValue')
    );

    expect(result.current[0]).toBe('storedValue');
  });

  it('should update localStorage when value changes', () => {
    const { result } = renderHook(() => useLocalStorage('testKey', 'initial'));

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
      useLocalStorage('testKey', complexObject)
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
      useLocalStorage('testKey', 'defaultValue')
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

    const { result } = renderHook(() => useLocalStorage('testKey', 'initial'));

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
      useLocalStorage('testKey', 'defaultValue')
    );

    expect(result.current[0]).toBe('defaultValue');
    expect(console.error).toHaveBeenCalled();
  });
});
