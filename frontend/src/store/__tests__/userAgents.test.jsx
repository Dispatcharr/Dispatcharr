import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useUserAgentsStore from '../userAgents';
import api from '../../api';

vi.mock('../../api');

describe('useUserAgentsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUserAgentsStore.setState({
      userAgents: [],
      isLoading: false,
      error: null,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useUserAgentsStore());

    expect(result.current.userAgents).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should fetch user agents successfully', async () => {
    const mockUserAgents = [
      { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
      { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
    ];

    api.getUserAgents.mockResolvedValue(mockUserAgents);

    const { result } = renderHook(() => useUserAgentsStore());

    await act(async () => {
      await result.current.fetchUserAgents();
    });

    expect(api.getUserAgents).toHaveBeenCalled();
    expect(result.current.userAgents).toEqual(mockUserAgents);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should handle fetch user agents error', async () => {
    const mockError = new Error('Network error');
    api.getUserAgents.mockRejectedValue(mockError);

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { result } = renderHook(() => useUserAgentsStore());

    await act(async () => {
      await result.current.fetchUserAgents();
    });

    expect(result.current.error).toBe('Failed to load userAgents.');
    expect(result.current.isLoading).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to fetch userAgents:', mockError);

    consoleErrorSpy.mockRestore();
  });

  it('should set loading state during fetch', async () => {
    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    api.getUserAgents.mockReturnValue(promise);

    const { result } = renderHook(() => useUserAgentsStore());

    act(() => {
      result.current.fetchUserAgents();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBe(null);

    await act(async () => {
      resolvePromise([]);
      await promise;
    });

    expect(result.current.isLoading).toBe(false);
  });

  it('should add user agent', () => {
    useUserAgentsStore.setState({
      userAgents: [{ id: 1, name: 'Chrome', string: 'Mozilla/5.0...' }],
    });

    const { result } = renderHook(() => useUserAgentsStore());
    const newUserAgent = { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' };

    act(() => {
      result.current.addUserAgent(newUserAgent);
    });

    expect(result.current.userAgents).toEqual([
      { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
      { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
    ]);
  });

  it('should add user agent to empty user agents', () => {
    const { result } = renderHook(() => useUserAgentsStore());
    const newUserAgent = { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' };

    act(() => {
      result.current.addUserAgent(newUserAgent);
    });

    expect(result.current.userAgents).toEqual([newUserAgent]);
  });

  it('should update user agent', () => {
    useUserAgentsStore.setState({
      userAgents: [
        { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
        { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
      ],
    });

    const { result } = renderHook(() => useUserAgentsStore());
    const updatedUserAgent = { id: 1, name: 'Chrome Updated', string: 'Mozilla/5.0 Updated...' };

    act(() => {
      result.current.updateUserAgent(updatedUserAgent);
    });

    expect(result.current.userAgents).toEqual([
      { id: 1, name: 'Chrome Updated', string: 'Mozilla/5.0 Updated...' },
      { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
    ]);
  });

  it('should not modify other user agents when updating', () => {
    useUserAgentsStore.setState({
      userAgents: [
        { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
        { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
      ],
    });

    const { result } = renderHook(() => useUserAgentsStore());
    const updatedUserAgent = { id: 1, name: 'Chrome Updated', string: 'Mozilla/5.0 Updated...' };

    act(() => {
      result.current.updateUserAgent(updatedUserAgent);
    });

    expect(result.current.userAgents[1]).toEqual({ id: 2, name: 'Firefox', string: 'Mozilla/5.0...' });
  });

  it('should not modify user agents when updating non-existent user agent', () => {
    const initialUserAgents = [
      { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
      { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
    ];

    useUserAgentsStore.setState({
      userAgents: initialUserAgents,
    });

    const { result } = renderHook(() => useUserAgentsStore());
    const nonExistentUserAgent = { id: 999, name: 'Non-existent', string: 'Mozilla/5.0...' };

    act(() => {
      result.current.updateUserAgent(nonExistentUserAgent);
    });

    expect(result.current.userAgents).toEqual(initialUserAgents);
  });

  it('should remove single user agent', () => {
    useUserAgentsStore.setState({
      userAgents: [
        { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
        { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
        { id: 3, name: 'Safari', string: 'Mozilla/5.0...' },
      ],
    });

    const { result } = renderHook(() => useUserAgentsStore());

    act(() => {
      result.current.removeUserAgents([2]);
    });

    expect(result.current.userAgents).toEqual([
      { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
      { id: 3, name: 'Safari', string: 'Mozilla/5.0...' },
    ]);
  });

  it('should remove multiple user agents', () => {
    useUserAgentsStore.setState({
      userAgents: [
        { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
        { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
        { id: 3, name: 'Safari', string: 'Mozilla/5.0...' },
      ],
    });

    const { result } = renderHook(() => useUserAgentsStore());

    act(() => {
      result.current.removeUserAgents([1, 3]);
    });

    expect(result.current.userAgents).toEqual([
      { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
    ]);
  });

  it('should handle removing non-existent user agents', () => {
    const initialUserAgents = [
      { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
      { id: 2, name: 'Firefox', string: 'Mozilla/5.0...' },
    ];

    useUserAgentsStore.setState({
      userAgents: initialUserAgents,
    });

    const { result } = renderHook(() => useUserAgentsStore());

    act(() => {
      result.current.removeUserAgents([999]);
    });

    expect(result.current.userAgents).toEqual(initialUserAgents);
  });

  it('should handle removing from empty user agents', () => {
    const { result } = renderHook(() => useUserAgentsStore());

    act(() => {
      result.current.removeUserAgents([1, 2]);
    });

    expect(result.current.userAgents).toEqual([]);
  });

  it('should handle empty array when removing user agents', () => {
    const initialUserAgents = [
      { id: 1, name: 'Chrome', string: 'Mozilla/5.0...' },
    ];

    useUserAgentsStore.setState({
      userAgents: initialUserAgents,
    });

    const { result } = renderHook(() => useUserAgentsStore());

    act(() => {
      result.current.removeUserAgents([]);
    });

    expect(result.current.userAgents).toEqual(initialUserAgents);
  });

  it('should handle fetch with empty results', async () => {
    api.getUserAgents.mockResolvedValue([]);

    const { result } = renderHook(() => useUserAgentsStore());

    await act(async () => {
      await result.current.fetchUserAgents();
    });

    expect(result.current.userAgents).toEqual([]);
  });
});
