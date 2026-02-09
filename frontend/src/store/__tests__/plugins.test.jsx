import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { usePluginStore } from '../plugins';
import API from '../../api';

vi.mock('../../api');

describe('usePluginStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    usePluginStore.setState({
      plugins: [],
      loading: false,
      error: null,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => usePluginStore());

    expect(result.current.plugins).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should fetch plugins successfully', async () => {
    const mockPlugins = [
      { key: 'plugin1', name: 'Plugin 1', enabled: true },
      { key: 'plugin2', name: 'Plugin 2', enabled: false },
    ];

    API.getPlugins.mockResolvedValue(mockPlugins);

    const { result } = renderHook(() => usePluginStore());

    await act(async () => {
      await result.current.fetchPlugins();
    });

    expect(API.getPlugins).toHaveBeenCalled();
    expect(result.current.plugins).toEqual(mockPlugins);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should handle fetch plugins with empty response', async () => {
    API.getPlugins.mockResolvedValue(null);

    const { result } = renderHook(() => usePluginStore());

    await act(async () => {
      await result.current.fetchPlugins();
    });

    expect(result.current.plugins).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it('should handle fetch plugins error', async () => {
    const mockError = new Error('Network error');
    API.getPlugins.mockRejectedValue(mockError);

    const { result } = renderHook(() => usePluginStore());

    await act(async () => {
      await result.current.fetchPlugins();
    });

    expect(result.current.error).toEqual(mockError);
    expect(result.current.loading).toBe(false);
  });

  it('should set loading state during fetch', async () => {
    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    API.getPlugins.mockReturnValue(promise);

    const { result } = renderHook(() => usePluginStore());

    // Start the fetch without awaiting
    act(() => {
      result.current.fetchPlugins();
    });

    // Check loading is true synchronously
    expect(result.current.loading).toBe(true);

    // Resolve the promise and wait for state update
    await act(async () => {
      resolvePromise([]);
      await promise;
    });

    expect(result.current.loading).toBe(false);
  });

  it('should update plugin', () => {
    const { result } = renderHook(() => usePluginStore());

    act(() => {
      usePluginStore.setState({
        plugins: [
          { key: 'plugin1', name: 'Plugin 1', enabled: false },
          { key: 'plugin2', name: 'Plugin 2', enabled: false },
        ],
      });
    });

    act(() => {
      result.current.updatePlugin('plugin1', { enabled: true });
    });

    expect(result.current.plugins).toEqual([
      { key: 'plugin1', name: 'Plugin 1', enabled: true },
      { key: 'plugin2', name: 'Plugin 2', enabled: false },
    ]);
  });

  it('should not modify other plugins when updating', () => {
    const { result } = renderHook(() => usePluginStore());

    act(() => {
      usePluginStore.setState({
        plugins: [
          { key: 'plugin1', name: 'Plugin 1', enabled: false },
          { key: 'plugin2', name: 'Plugin 2', enabled: false },
        ],
      });
    });

    act(() => {
      result.current.updatePlugin('plugin1', { name: 'Updated Plugin' });
    });

    expect(result.current.plugins[1]).toEqual({
      key: 'plugin2',
      name: 'Plugin 2',
      enabled: false,
    });
  });

  it('should add plugin', () => {
    const { result } = renderHook(() => usePluginStore());
    const newPlugin = { key: 'plugin1', name: 'New Plugin', enabled: true };

    act(() => {
      result.current.addPlugin(newPlugin);
    });

    expect(result.current.plugins).toEqual([newPlugin]);
  });

  it('should add plugin to existing plugins', () => {
    const { result } = renderHook(() => usePluginStore());
    const existingPlugin = {
      key: 'plugin1',
      name: 'Existing Plugin',
      enabled: true,
    };
    const newPlugin = { key: 'plugin2', name: 'New Plugin', enabled: false };

    act(() => {
      usePluginStore.setState({ plugins: [existingPlugin] });
    });

    act(() => {
      result.current.addPlugin(newPlugin);
    });

    expect(result.current.plugins).toEqual([existingPlugin, newPlugin]);
  });

  it('should remove plugin', () => {
    const { result } = renderHook(() => usePluginStore());

    act(() => {
      usePluginStore.setState({
        plugins: [
          { key: 'plugin1', name: 'Plugin 1', enabled: true },
          { key: 'plugin2', name: 'Plugin 2', enabled: false },
        ],
      });
    });

    act(() => {
      result.current.removePlugin('plugin1');
    });

    expect(result.current.plugins).toEqual([
      { key: 'plugin2', name: 'Plugin 2', enabled: false },
    ]);
  });

  it('should handle removing non-existent plugin', () => {
    const { result } = renderHook(() => usePluginStore());

    act(() => {
      usePluginStore.setState({
        plugins: [{ key: 'plugin1', name: 'Plugin 1', enabled: true }],
      });
    });

    act(() => {
      result.current.removePlugin('nonexistent');
    });

    expect(result.current.plugins).toEqual([
      { key: 'plugin1', name: 'Plugin 1', enabled: true },
    ]);
  });

  it('should invalidate plugins and refetch', async () => {
    const mockPlugins = [{ key: 'plugin1', name: 'Plugin 1', enabled: true }];

    API.getPlugins.mockResolvedValue(mockPlugins);

    const { result } = renderHook(() => usePluginStore());

    act(() => {
      usePluginStore.setState({
        plugins: [{ key: 'old-plugin', name: 'Old Plugin', enabled: false }],
      });
    });

    await act(async () => {
      await result.current.invalidatePlugins();
    });

    expect(result.current.plugins).toEqual(mockPlugins);
    expect(API.getPlugins).toHaveBeenCalled();
  });
});
