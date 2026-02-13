import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useStreamsStore from '../streams';
import api from '../../api';

vi.mock('../../api');

describe('useStreamsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStreamsStore.setState({
      streams: [],
      count: 0,
      isLoading: false,
      error: null,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useStreamsStore());

    expect(result.current.streams).toEqual([]);
    expect(result.current.count).toBe(0);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should fetch streams successfully', async () => {
    const mockResponse = {
      results: [
        { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
        { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
      ],
      count: 2,
    };

    api.getStreams.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useStreamsStore());

    await act(async () => {
      await result.current.fetchStreams();
    });

    expect(api.getStreams).toHaveBeenCalled();
    expect(result.current.streams).toEqual(mockResponse.results);
    expect(result.current.count).toBe(2);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should handle fetch streams error', async () => {
    const mockError = new Error('Network error');
    api.getStreams.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useStreamsStore());

    await act(async () => {
      await result.current.fetchStreams();
    });

    expect(result.current.error).toBe('Failed to load streams.');
    expect(result.current.isLoading).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch streams:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should set loading state during fetch', async () => {
    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    api.getStreams.mockReturnValue(promise);

    const { result } = renderHook(() => useStreamsStore());

    act(() => {
      result.current.fetchStreams();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBe(null);

    await act(async () => {
      resolvePromise({ results: [], count: 0 });
      await promise;
    });

    expect(result.current.isLoading).toBe(false);
  });

  it('should add stream', () => {
    useStreamsStore.setState({
      streams: [{ id: 1, name: 'Stream 1', url: 'http://example.com/1' }],
    });

    const { result } = renderHook(() => useStreamsStore());
    const newStream = { id: 2, name: 'Stream 2', url: 'http://example.com/2' };

    act(() => {
      result.current.addStream(newStream);
    });

    expect(result.current.streams).toEqual([
      { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
      { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
    ]);
  });

  it('should add stream to empty streams', () => {
    const { result } = renderHook(() => useStreamsStore());
    const newStream = { id: 1, name: 'Stream 1', url: 'http://example.com/1' };

    act(() => {
      result.current.addStream(newStream);
    });

    expect(result.current.streams).toEqual([newStream]);
  });

  it('should update stream', () => {
    useStreamsStore.setState({
      streams: [
        { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
        { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
      ],
    });

    const { result } = renderHook(() => useStreamsStore());
    const updatedStream = {
      id: 1,
      name: 'Updated Stream',
      url: 'http://example.com/updated',
    };

    act(() => {
      result.current.updateStream(updatedStream);
    });

    expect(result.current.streams).toEqual([
      { id: 1, name: 'Updated Stream', url: 'http://example.com/updated' },
      { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
    ]);
  });

  it('should not modify other streams when updating', () => {
    useStreamsStore.setState({
      streams: [
        { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
        { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
      ],
    });

    const { result } = renderHook(() => useStreamsStore());
    const updatedStream = {
      id: 1,
      name: 'Updated Stream',
      url: 'http://example.com/updated',
    };

    act(() => {
      result.current.updateStream(updatedStream);
    });

    expect(result.current.streams[1]).toEqual({
      id: 2,
      name: 'Stream 2',
      url: 'http://example.com/2',
    });
  });

  it('should not modify streams when updating non-existent stream', () => {
    const initialStreams = [
      { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
      { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
    ];

    useStreamsStore.setState({
      streams: initialStreams,
    });

    const { result } = renderHook(() => useStreamsStore());
    const nonExistentStream = {
      id: 999,
      name: 'Non-existent',
      url: 'http://example.com/999',
    };

    act(() => {
      result.current.updateStream(nonExistentStream);
    });

    expect(result.current.streams).toEqual(initialStreams);
  });

  it('should remove single stream', () => {
    useStreamsStore.setState({
      streams: [
        { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
        { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
        { id: 3, name: 'Stream 3', url: 'http://example.com/3' },
      ],
    });

    const { result } = renderHook(() => useStreamsStore());

    act(() => {
      result.current.removeStreams([2]);
    });

    expect(result.current.streams).toEqual([
      { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
      { id: 3, name: 'Stream 3', url: 'http://example.com/3' },
    ]);
  });

  it('should remove multiple streams', () => {
    useStreamsStore.setState({
      streams: [
        { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
        { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
        { id: 3, name: 'Stream 3', url: 'http://example.com/3' },
      ],
    });

    const { result } = renderHook(() => useStreamsStore());

    act(() => {
      result.current.removeStreams([1, 3]);
    });

    expect(result.current.streams).toEqual([
      { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
    ]);
  });

  it('should handle removing non-existent streams', () => {
    const initialStreams = [
      { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
      { id: 2, name: 'Stream 2', url: 'http://example.com/2' },
    ];

    useStreamsStore.setState({
      streams: initialStreams,
    });

    const { result } = renderHook(() => useStreamsStore());

    act(() => {
      result.current.removeStreams([999]);
    });

    expect(result.current.streams).toEqual(initialStreams);
  });

  it('should handle removing from empty streams', () => {
    const { result } = renderHook(() => useStreamsStore());

    act(() => {
      result.current.removeStreams([1, 2]);
    });

    expect(result.current.streams).toEqual([]);
  });

  it('should handle empty array when removing streams', () => {
    const initialStreams = [
      { id: 1, name: 'Stream 1', url: 'http://example.com/1' },
    ];

    useStreamsStore.setState({
      streams: initialStreams,
    });

    const { result } = renderHook(() => useStreamsStore());

    act(() => {
      result.current.removeStreams([]);
    });

    expect(result.current.streams).toEqual(initialStreams);
  });

  it('should handle fetch with empty results', async () => {
    const mockResponse = {
      results: [],
      count: 0,
    };

    api.getStreams.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useStreamsStore());

    await act(async () => {
      await result.current.fetchStreams();
    });

    expect(result.current.streams).toEqual([]);
    expect(result.current.count).toBe(0);
  });
});
