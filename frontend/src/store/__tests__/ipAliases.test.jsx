import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useIPAliasesStore from '../ipAliases';
import api from '../../api';

vi.mock('../../api');

describe('useIPAliasesStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useIPAliasesStore.setState({
      aliases: [],
      aliasMap: {},
      isLoading: false,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useIPAliasesStore());

    expect(result.current.aliases).toEqual([]);
    expect(result.current.aliasMap).toEqual({});
    expect(result.current.isLoading).toBe(false);
  });

  it('should fetch aliases successfully', async () => {
    const mockAliases = [
      { id: 1, ip_address: '192.168.1.100', alias: "Dad's House" },
      { id: 2, ip_address: '10.0.0.50', alias: 'Work VPN' },
    ];

    api.getIPAliases.mockResolvedValue(mockAliases);

    const { result } = renderHook(() => useIPAliasesStore());

    await act(async () => {
      await result.current.fetchAliases();
    });

    expect(api.getIPAliases).toHaveBeenCalled();
    expect(result.current.aliases).toEqual(mockAliases);
    expect(result.current.aliasMap).toEqual({
      '192.168.1.100': "Dad's House",
      '10.0.0.50': 'Work VPN',
    });
    expect(result.current.isLoading).toBe(false);
  });

  it('should build aliasMap from fetched aliases', async () => {
    const mockAliases = [
      { id: 1, ip_address: '1.2.3.4', alias: 'Alpha' },
      { id: 2, ip_address: '5.6.7.8', alias: 'Beta' },
      { id: 3, ip_address: '9.10.11.12', alias: 'Gamma' },
    ];

    api.getIPAliases.mockResolvedValue(mockAliases);

    const { result } = renderHook(() => useIPAliasesStore());

    await act(async () => {
      await result.current.fetchAliases();
    });

    expect(result.current.aliasMap['1.2.3.4']).toBe('Alpha');
    expect(result.current.aliasMap['5.6.7.8']).toBe('Beta');
    expect(result.current.aliasMap['9.10.11.12']).toBe('Gamma');
  });

  it('should handle fetch error gracefully', async () => {
    api.getIPAliases.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useIPAliasesStore());

    await act(async () => {
      await result.current.fetchAliases();
    });

    expect(result.current.aliases).toEqual([]);
    expect(result.current.aliasMap).toEqual({});
    expect(result.current.isLoading).toBe(false);
  });

  it('should handle fetch with empty results', async () => {
    api.getIPAliases.mockResolvedValue([]);

    const { result } = renderHook(() => useIPAliasesStore());

    await act(async () => {
      await result.current.fetchAliases();
    });

    expect(result.current.aliases).toEqual([]);
    expect(result.current.aliasMap).toEqual({});
  });

  it('should set loading state during fetch', async () => {
    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    api.getIPAliases.mockReturnValue(promise);

    const { result } = renderHook(() => useIPAliasesStore());

    act(() => {
      result.current.fetchAliases();
    });

    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      resolvePromise([]);
      await promise;
    });

    expect(result.current.isLoading).toBe(false);
  });

  it('should create alias and refetch', async () => {
    const newAlias = { id: 1, ip_address: '192.168.1.1', alias: 'Home' };

    api.createIPAlias.mockResolvedValue(newAlias);
    api.getIPAliases.mockResolvedValue([newAlias]);

    const { result } = renderHook(() => useIPAliasesStore());

    await act(async () => {
      await result.current.createAlias({
        ip_address: '192.168.1.1',
        alias: 'Home',
      });
    });

    expect(api.createIPAlias).toHaveBeenCalledWith({
      ip_address: '192.168.1.1',
      alias: 'Home',
    });
    expect(api.getIPAliases).toHaveBeenCalled();
    expect(result.current.aliases).toEqual([newAlias]);
    expect(result.current.aliasMap['192.168.1.1']).toBe('Home');
  });

  it('should update alias and refetch', async () => {
    const updatedAlias = {
      id: 1,
      ip_address: '192.168.1.1',
      alias: 'Home Updated',
    };

    api.updateIPAlias.mockResolvedValue(updatedAlias);
    api.getIPAliases.mockResolvedValue([updatedAlias]);

    const { result } = renderHook(() => useIPAliasesStore());

    await act(async () => {
      await result.current.updateAlias(1, {
        ip_address: '192.168.1.1',
        alias: 'Home Updated',
      });
    });

    expect(api.updateIPAlias).toHaveBeenCalledWith(1, {
      ip_address: '192.168.1.1',
      alias: 'Home Updated',
    });
    expect(api.getIPAliases).toHaveBeenCalled();
    expect(result.current.aliasMap['192.168.1.1']).toBe('Home Updated');
  });

  it('should delete alias and refetch', async () => {
    useIPAliasesStore.setState({
      aliases: [{ id: 1, ip_address: '192.168.1.1', alias: 'Home' }],
      aliasMap: { '192.168.1.1': 'Home' },
    });

    api.deleteIPAlias.mockResolvedValue();
    api.getIPAliases.mockResolvedValue([]);

    const { result } = renderHook(() => useIPAliasesStore());

    await act(async () => {
      await result.current.deleteAlias(1);
    });

    expect(api.deleteIPAlias).toHaveBeenCalledWith(1);
    expect(api.getIPAliases).toHaveBeenCalled();
    expect(result.current.aliases).toEqual([]);
    expect(result.current.aliasMap).toEqual({});
  });

  it('should return alias via getAlias helper', () => {
    useIPAliasesStore.setState({
      aliases: [{ id: 1, ip_address: '10.0.0.1', alias: 'Server' }],
      aliasMap: { '10.0.0.1': 'Server' },
    });

    const { result } = renderHook(() => useIPAliasesStore());

    expect(result.current.getAlias('10.0.0.1')).toBe('Server');
    expect(result.current.getAlias('10.0.0.99')).toBeNull();
  });

  it('should handle non-array response from API', async () => {
    api.getIPAliases.mockResolvedValue(null);

    const { result } = renderHook(() => useIPAliasesStore());

    await act(async () => {
      await result.current.fetchAliases();
    });

    expect(result.current.aliases).toEqual([]);
    expect(result.current.aliasMap).toEqual({});
    expect(result.current.isLoading).toBe(false);
  });
});
