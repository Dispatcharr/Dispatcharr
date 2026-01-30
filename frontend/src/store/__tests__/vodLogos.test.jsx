import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useVODLogosStore from '../vodLogos';
import api from '../../api';

vi.mock('../../api');

describe('useVODLogosStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useVODLogosStore.setState({
      vodLogos: {},
      logos: [],
      isLoading: false,
      hasLoaded: false,
      error: null,
      totalCount: 0,
      currentPage: 1,
      pageSize: 25,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useVODLogosStore());

    expect(result.current.vodLogos).toEqual({});
    expect(result.current.logos).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.hasLoaded).toBe(false);
    expect(result.current.error).toBe(null);
    expect(result.current.totalCount).toBe(0);
    expect(result.current.currentPage).toBe(1);
    expect(result.current.pageSize).toBe(25);
  });

  it('should set VOD logos with normalized structure', () => {
    const { result } = renderHook(() => useVODLogosStore());
    const mockLogos = [
      { id: 1, name: 'Logo 1', url: 'http://example.com/logo1.png' },
      { id: 2, name: 'Logo 2', url: 'http://example.com/logo2.png' },
    ];

    act(() => {
      result.current.setVODLogos(mockLogos, 2);
    });

    expect(result.current.vodLogos).toEqual({
      1: { id: 1, name: 'Logo 1', url: 'http://example.com/logo1.png' },
      2: { id: 2, name: 'Logo 2', url: 'http://example.com/logo2.png' },
    });
    expect(result.current.totalCount).toBe(2);
    expect(result.current.hasLoaded).toBe(true);
  });

  it('should fetch VOD logos successfully with array response', async () => {
    const mockLogos = [
      { id: 1, name: 'Logo 1', url: 'http://example.com/logo1.png' },
      { id: 2, name: 'Logo 2', url: 'http://example.com/logo2.png' },
    ];

    api.getVODLogos.mockResolvedValue(mockLogos);

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      await result.current.fetchVODLogos();
    });

    expect(api.getVODLogos).toHaveBeenCalled();
    expect(result.current.vodLogos).toEqual({
      1: { id: 1, name: 'Logo 1', url: 'http://example.com/logo1.png' },
      2: { id: 2, name: 'Logo 2', url: 'http://example.com/logo2.png' },
    });
    expect(result.current.logos).toEqual(mockLogos);
    expect(result.current.totalCount).toBe(2);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.hasLoaded).toBe(true);
  });

  it('should fetch VOD logos successfully with paginated response', async () => {
    const mockLogos = [
      { id: 1, name: 'Logo 1', url: 'http://example.com/logo1.png' },
    ];
    const mockResponse = {
      results: mockLogos,
      count: 10,
    };

    api.getVODLogos.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      await result.current.fetchVODLogos({ page: 1, page_size: 25 });
    });

    expect(result.current.vodLogos).toEqual({
      1: { id: 1, name: 'Logo 1', url: 'http://example.com/logo1.png' },
    });
    expect(result.current.logos).toEqual(mockLogos);
    expect(result.current.totalCount).toBe(10);
  });

  it('should handle fetch VOD logos error', async () => {
    const mockError = new Error('Network error');
    api.getVODLogos.mockRejectedValue(mockError);

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      try {
        await result.current.fetchVODLogos();
      } catch (error) {
        // Expected error
      }
    });

    expect(result.current.error).toBe('Failed to load VOD logos.');
    expect(result.current.isLoading).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to fetch VOD logos:', mockError);

    consoleErrorSpy.mockRestore();
  });

  it('should set loading state during fetch', async () => {
    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    api.getVODLogos.mockReturnValue(promise);

    const { result } = renderHook(() => useVODLogosStore());

    act(() => {
      result.current.fetchVODLogos();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBe(null);

    await act(async () => {
      resolvePromise([]);
      await promise;
    });

    expect(result.current.isLoading).toBe(false);
  });

  it('should remove single VOD logo from state', () => {
    useVODLogosStore.setState({
      vodLogos: {
        1: { id: 1, name: 'Logo 1' },
        2: { id: 2, name: 'Logo 2' },
        3: { id: 3, name: 'Logo 3' },
      },
      logos: [
        { id: 1, name: 'Logo 1' },
        { id: 2, name: 'Logo 2' },
        { id: 3, name: 'Logo 3' },
      ],
      totalCount: 3,
    });

    const { result } = renderHook(() => useVODLogosStore());

    act(() => {
      result.current.removeVODLogo(2);
    });

    expect(result.current.vodLogos).toEqual({
      1: { id: 1, name: 'Logo 1' },
      3: { id: 3, name: 'Logo 3' },
    });
    expect(result.current.logos).toEqual([
      { id: 1, name: 'Logo 1' },
      { id: 3, name: 'Logo 3' },
    ]);
    expect(result.current.totalCount).toBe(2);
  });

  it('should remove multiple VOD logos from state using _removeLogosFromState', () => {
    useVODLogosStore.setState({
      vodLogos: {
        1: { id: 1, name: 'Logo 1' },
        2: { id: 2, name: 'Logo 2' },
        3: { id: 3, name: 'Logo 3' },
      },
      logos: [
        { id: 1, name: 'Logo 1' },
        { id: 2, name: 'Logo 2' },
        { id: 3, name: 'Logo 3' },
      ],
      totalCount: 3,
    });

    const { result } = renderHook(() => useVODLogosStore());

    act(() => {
      result.current._removeLogosFromState([1, 3]);
    });

    expect(result.current.vodLogos).toEqual({
      2: { id: 2, name: 'Logo 2' },
    });
    expect(result.current.logos).toEqual([
      { id: 2, name: 'Logo 2' },
    ]);
    expect(result.current.totalCount).toBe(1);
  });

  it('should delete single VOD logo successfully', async () => {
    useVODLogosStore.setState({
      vodLogos: {
        1: { id: 1, name: 'Logo 1' },
        2: { id: 2, name: 'Logo 2' },
      },
      logos: [
        { id: 1, name: 'Logo 1' },
        { id: 2, name: 'Logo 2' },
      ],
      totalCount: 2,
    });

    api.deleteVODLogo.mockResolvedValue({});

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      await result.current.deleteVODLogo(1);
    });

    expect(api.deleteVODLogo).toHaveBeenCalledWith(1);
    expect(result.current.vodLogos).toEqual({
      2: { id: 2, name: 'Logo 2' },
    });
    expect(result.current.logos).toEqual([
      { id: 2, name: 'Logo 2' },
    ]);
    expect(result.current.totalCount).toBe(1);
  });

  it('should handle delete VOD logo error', async () => {
    const mockError = new Error('Delete failed');
    api.deleteVODLogo.mockRejectedValue(mockError);

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      try {
        await result.current.deleteVODLogo(1);
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to delete VOD logo:', mockError);

    consoleErrorSpy.mockRestore();
  });

  it('should delete multiple VOD logos successfully', async () => {
    useVODLogosStore.setState({
      vodLogos: {
        1: { id: 1, name: 'Logo 1' },
        2: { id: 2, name: 'Logo 2' },
        3: { id: 3, name: 'Logo 3' },
      },
      logos: [
        { id: 1, name: 'Logo 1' },
        { id: 2, name: 'Logo 2' },
        { id: 3, name: 'Logo 3' },
      ],
      totalCount: 3,
    });

    api.deleteVODLogos.mockResolvedValue({});

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      await result.current.deleteVODLogos([1, 2]);
    });

    expect(api.deleteVODLogos).toHaveBeenCalledWith([1, 2]);
    expect(result.current.vodLogos).toEqual({
      3: { id: 3, name: 'Logo 3' },
    });
    expect(result.current.logos).toEqual([
      { id: 3, name: 'Logo 3' },
    ]);
    expect(result.current.totalCount).toBe(1);
  });

  it('should handle delete multiple VOD logos error', async () => {
    const mockError = new Error('Bulk delete failed');
    api.deleteVODLogos.mockRejectedValue(mockError);

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      try {
        await result.current.deleteVODLogos([1, 2]);
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to delete VOD logos:', mockError);

    consoleErrorSpy.mockRestore();
  });

  it('should cleanup unused VOD logos and refresh', async () => {
    useVODLogosStore.setState({
      currentPage: 2,
      pageSize: 10,
    });

    const mockCleanupResult = { deleted: 5 };
    const mockRefreshedLogos = [{ id: 1, name: 'Logo 1' }];

    api.cleanupUnusedVODLogos.mockResolvedValue(mockCleanupResult);
    api.getVODLogos.mockResolvedValue(mockRefreshedLogos);

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      const cleanupResult = await result.current.cleanupUnusedVODLogos();
      expect(cleanupResult).toEqual(mockCleanupResult);
    });

    expect(api.cleanupUnusedVODLogos).toHaveBeenCalled();
    expect(api.getVODLogos).toHaveBeenCalledWith({
      page: 2,
      page_size: 10,
    });
    expect(result.current.logos).toEqual(mockRefreshedLogos);
  });

  it('should handle cleanup unused VOD logos error', async () => {
    const mockError = new Error('Cleanup failed');
    api.cleanupUnusedVODLogos.mockRejectedValue(mockError);

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      try {
        await result.current.cleanupUnusedVODLogos();
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to cleanup unused VOD logos:', mockError);

    consoleErrorSpy.mockRestore();
  });

  it('should clear VOD logos', () => {
    useVODLogosStore.setState({
      vodLogos: {
        1: { id: 1, name: 'Logo 1' },
      },
      logos: [{ id: 1, name: 'Logo 1' }],
      hasLoaded: true,
      totalCount: 1,
      error: 'Some error',
    });

    const { result } = renderHook(() => useVODLogosStore());

    act(() => {
      result.current.clearVODLogos();
    });

    expect(result.current.vodLogos).toEqual({});
    expect(result.current.logos).toEqual([]);
    expect(result.current.hasLoaded).toBe(false);
    expect(result.current.totalCount).toBe(0);
    expect(result.current.error).toBe(null);
  });

  it('should handle removing non-existent logo', () => {
    useVODLogosStore.setState({
      vodLogos: {
        1: { id: 1, name: 'Logo 1' },
      },
      logos: [{ id: 1, name: 'Logo 1' }],
      totalCount: 1,
    });

    const { result } = renderHook(() => useVODLogosStore());

    act(() => {
      result.current.removeVODLogo(999);
    });

    expect(result.current.vodLogos).toEqual({
      1: { id: 1, name: 'Logo 1' },
    });
    expect(result.current.logos).toEqual([{ id: 1, name: 'Logo 1' }]);
    expect(result.current.totalCount).toBe(1);
  });

  it('should handle fetch with empty response', async () => {
    api.getVODLogos.mockResolvedValue([]);

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      await result.current.fetchVODLogos();
    });

    expect(result.current.vodLogos).toEqual({});
    expect(result.current.logos).toEqual([]);
    expect(result.current.totalCount).toBe(0);
  });

  it('should not allow totalCount to go below zero', () => {
    useVODLogosStore.setState({
      vodLogos: {
        1: { id: 1, name: 'Logo 1' },
      },
      logos: [{ id: 1, name: 'Logo 1' }],
      totalCount: 1,
    });

    const { result } = renderHook(() => useVODLogosStore());

    act(() => {
      result.current._removeLogosFromState([1, 2, 3]); // Remove more than exist
    });

    expect(result.current.totalCount).toBe(0);
  });

  it('should handle _removeLogosFromState with empty array', () => {
    const initialState = {
      vodLogos: {
        1: { id: 1, name: 'Logo 1' },
      },
      logos: [{ id: 1, name: 'Logo 1' }],
      totalCount: 1,
    };

    useVODLogosStore.setState(initialState);

    const { result } = renderHook(() => useVODLogosStore());

    act(() => {
      result.current._removeLogosFromState([]);
    });

    expect(result.current.vodLogos).toEqual(initialState.vodLogos);
    expect(result.current.logos).toEqual(initialState.logos);
    expect(result.current.totalCount).toBe(1);
  });

  it('should fetch with custom params', async () => {
    const mockLogos = [{ id: 1, name: 'Logo 1' }];
    api.getVODLogos.mockResolvedValue(mockLogos);

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      await result.current.fetchVODLogos({ search: 'test', page: 2 });
    });

    expect(api.getVODLogos).toHaveBeenCalledWith({ search: 'test', page: 2 });
  });

  it('should get unused logos count successfully', async () => {
    const mockResponse = {
      results: [{ id: 1, name: 'Unused Logo' }],
      count: 42,
    };

    api.getVODLogos.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODLogosStore());

    let unusedCount;
    await act(async () => {
      unusedCount = await result.current.getUnusedLogosCount();
    });

    expect(api.getVODLogos).toHaveBeenCalledWith({
      used: 'false',
      page_size: 1,
    });
    expect(unusedCount).toBe(42);
  });

  it('should return 0 when unused logos count response has no count', async () => {
    api.getVODLogos.mockResolvedValue({ results: [] });

    const { result } = renderHook(() => useVODLogosStore());

    let unusedCount;
    await act(async () => {
      unusedCount = await result.current.getUnusedLogosCount();
    });

    expect(unusedCount).toBe(0);
  });

  it('should handle get unused logos count error', async () => {
    const mockError = new Error('Failed to fetch count');
    api.getVODLogos.mockRejectedValue(mockError);

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { result } = renderHook(() => useVODLogosStore());

    await act(async () => {
      try {
        await result.current.getUnusedLogosCount();
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to fetch unused logos count:', mockError);

    consoleErrorSpy.mockRestore();
  });

  it('should update currentPage and pageSize state', () => {
    const { result } = renderHook(() => useVODLogosStore());

    act(() => {
      useVODLogosStore.setState({
        currentPage: 3,
        pageSize: 50,
      });
    });

    expect(result.current.currentPage).toBe(3);
    expect(result.current.pageSize).toBe(50);
  });
});
