import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useSettingsStore from '../settings';
import api from '../../api';

vi.mock('../../api');

describe('useSettingsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({
      settings: {},
      environment: {
        public_ip: '',
        country_code: '',
        country_name: '',
        env_mode: 'prod',
      },
      isLoading: false,
      error: null,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useSettingsStore());

    expect(result.current.settings).toEqual({});
    expect(result.current.environment).toEqual({
      public_ip: '',
      country_code: '',
      country_name: '',
      env_mode: 'prod',
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should fetch settings successfully', async () => {
    const mockSettings = [
      { key: 'setting1', value: 'value1' },
      { key: 'setting2', value: 'value2' },
    ];
    const mockEnv = {
      public_ip: '192.168.1.1',
      country_code: 'US',
      country_name: 'United States',
      env_mode: 'dev',
    };

    api.getSettings.mockResolvedValue(mockSettings);
    api.getEnvironmentSettings.mockResolvedValue(mockEnv);

    const { result } = renderHook(() => useSettingsStore());

    await act(async () => {
      await result.current.fetchSettings();
    });

    expect(api.getSettings).toHaveBeenCalled();
    expect(api.getEnvironmentSettings).toHaveBeenCalled();
    expect(result.current.settings).toEqual({
      setting1: { key: 'setting1', value: 'value1' },
      setting2: { key: 'setting2', value: 'value2' },
    });
    expect(result.current.environment).toEqual(mockEnv);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should handle null environment response', async () => {
    const mockSettings = [{ key: 'setting1', value: 'value1' }];

    api.getSettings.mockResolvedValue(mockSettings);
    api.getEnvironmentSettings.mockResolvedValue(null);

    const { result } = renderHook(() => useSettingsStore());

    await act(async () => {
      await result.current.fetchSettings();
    });

    expect(result.current.environment).toEqual({
      public_ip: '',
      country_code: '',
      country_name: '',
      env_mode: 'prod',
    });
  });

  it('should handle fetch settings error', async () => {
    const mockError = new Error('Network error');
    api.getSettings.mockRejectedValue(mockError);

    const { result } = renderHook(() => useSettingsStore());

    await act(async () => {
      await result.current.fetchSettings();
    });

    expect(result.current.error).toBe('Failed to load settings.');
    expect(result.current.isLoading).toBe(false);
  });

  it('should set loading state during fetch', async () => {
    let resolveSettingsPromise;
    let resolveEnvPromise;
    const settingsPromise = new Promise((resolve) => {
      resolveSettingsPromise = resolve;
    });
    const envPromise = new Promise((resolve) => {
      resolveEnvPromise = resolve;
    });

    api.getSettings.mockReturnValue(settingsPromise);
    api.getEnvironmentSettings.mockReturnValue(envPromise);

    const { result } = renderHook(() => useSettingsStore());

    act(() => {
      result.current.fetchSettings();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBe(null);

    await act(async () => {
      resolveSettingsPromise([]);
      resolveEnvPromise({});
      await settingsPromise;
      await envPromise;
    });

    expect(result.current.isLoading).toBe(false);
  });

  it('should update setting', () => {
    useSettingsStore.setState({
      settings: {
        setting1: { key: 'setting1', value: 'old_value' },
        setting2: { key: 'setting2', value: 'value2' },
      },
    });

    const { result } = renderHook(() => useSettingsStore());

    act(() => {
      result.current.updateSetting({ key: 'setting1', value: 'new_value' });
    });

    expect(result.current.settings).toEqual({
      setting1: { key: 'setting1', value: 'new_value' },
      setting2: { key: 'setting2', value: 'value2' },
    });
  });

  it('should add new setting when updating non-existent key', () => {
    useSettingsStore.setState({
      settings: {
        setting1: { key: 'setting1', value: 'value1' },
      },
    });

    const { result } = renderHook(() => useSettingsStore());

    act(() => {
      result.current.updateSetting({ key: 'setting2', value: 'new_value' });
    });

    expect(result.current.settings).toEqual({
      setting1: { key: 'setting1', value: 'value1' },
      setting2: { key: 'setting2', value: 'new_value' },
    });
  });

  it('should not modify other settings when updating', () => {
    useSettingsStore.setState({
      settings: {
        setting1: { key: 'setting1', value: 'value1' },
        setting2: { key: 'setting2', value: 'value2' },
      },
    });

    const { result } = renderHook(() => useSettingsStore());

    act(() => {
      result.current.updateSetting({ key: 'setting1', value: 'updated' });
    });

    expect(result.current.settings.setting2).toEqual({ key: 'setting2', value: 'value2' });
  });

  it('should handle empty settings array', async () => {
    api.getSettings.mockResolvedValue([]);
    api.getEnvironmentSettings.mockResolvedValue({});

    const { result } = renderHook(() => useSettingsStore());

    await act(async () => {
      await result.current.fetchSettings();
    });

    expect(result.current.settings).toEqual({});
  });
});
