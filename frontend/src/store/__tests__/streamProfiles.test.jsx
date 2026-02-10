import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useStreamProfilesStore from '../streamProfiles';
import api from '../../api';

vi.mock('../../api');

describe('useStreamProfilesStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStreamProfilesStore.setState({
      profiles: [],
      isLoading: false,
      error: null,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useStreamProfilesStore());

    expect(result.current.profiles).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should fetch profiles successfully', async () => {
    const mockProfiles = [
      { id: 1, name: 'Profile 1', bitrate: 5000 },
      { id: 2, name: 'Profile 2', bitrate: 8000 },
    ];

    api.getStreamProfiles.mockResolvedValue(mockProfiles);

    const { result } = renderHook(() => useStreamProfilesStore());

    await act(async () => {
      await result.current.fetchProfiles();
    });

    expect(api.getStreamProfiles).toHaveBeenCalled();
    expect(result.current.profiles).toEqual(mockProfiles);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should handle fetch profiles error', async () => {
    const mockError = new Error('Network error');
    api.getStreamProfiles.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useStreamProfilesStore());

    await act(async () => {
      await result.current.fetchProfiles();
    });

    expect(result.current.error).toBe('Failed to load profiles.');
    expect(result.current.isLoading).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch profiles:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should set loading state during fetch', async () => {
    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    api.getStreamProfiles.mockReturnValue(promise);

    const { result } = renderHook(() => useStreamProfilesStore());

    act(() => {
      result.current.fetchProfiles();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBe(null);

    await act(async () => {
      resolvePromise([]);
      await promise;
    });

    expect(result.current.isLoading).toBe(false);
  });

  it('should add stream profile', () => {
    useStreamProfilesStore.setState({
      profiles: [{ id: 1, name: 'Profile 1', bitrate: 5000 }],
    });

    const { result } = renderHook(() => useStreamProfilesStore());
    const newProfile = { id: 2, name: 'Profile 2', bitrate: 8000 };

    act(() => {
      result.current.addStreamProfile(newProfile);
    });

    expect(result.current.profiles).toEqual([
      { id: 1, name: 'Profile 1', bitrate: 5000 },
      { id: 2, name: 'Profile 2', bitrate: 8000 },
    ]);
  });

  it('should add stream profile to empty profiles', () => {
    const { result } = renderHook(() => useStreamProfilesStore());
    const newProfile = { id: 1, name: 'Profile 1', bitrate: 5000 };

    act(() => {
      result.current.addStreamProfile(newProfile);
    });

    expect(result.current.profiles).toEqual([newProfile]);
  });

  it('should update stream profile', () => {
    useStreamProfilesStore.setState({
      profiles: [
        { id: 1, name: 'Profile 1', bitrate: 5000 },
        { id: 2, name: 'Profile 2', bitrate: 8000 },
      ],
    });

    const { result } = renderHook(() => useStreamProfilesStore());
    const updatedProfile = { id: 1, name: 'Updated Profile', bitrate: 10000 };

    act(() => {
      result.current.updateStreamProfile(updatedProfile);
    });

    expect(result.current.profiles).toEqual([
      { id: 1, name: 'Updated Profile', bitrate: 10000 },
      { id: 2, name: 'Profile 2', bitrate: 8000 },
    ]);
  });

  it('should not modify other profiles when updating', () => {
    useStreamProfilesStore.setState({
      profiles: [
        { id: 1, name: 'Profile 1', bitrate: 5000 },
        { id: 2, name: 'Profile 2', bitrate: 8000 },
      ],
    });

    const { result } = renderHook(() => useStreamProfilesStore());
    const updatedProfile = { id: 1, name: 'Updated Profile', bitrate: 10000 };

    act(() => {
      result.current.updateStreamProfile(updatedProfile);
    });

    expect(result.current.profiles[1]).toEqual({
      id: 2,
      name: 'Profile 2',
      bitrate: 8000,
    });
  });

  it('should not modify profiles when updating non-existent profile', () => {
    const initialProfiles = [
      { id: 1, name: 'Profile 1', bitrate: 5000 },
      { id: 2, name: 'Profile 2', bitrate: 8000 },
    ];

    useStreamProfilesStore.setState({
      profiles: initialProfiles,
    });

    const { result } = renderHook(() => useStreamProfilesStore());
    const nonExistentProfile = {
      id: 999,
      name: 'Non-existent',
      bitrate: 10000,
    };

    act(() => {
      result.current.updateStreamProfile(nonExistentProfile);
    });

    expect(result.current.profiles).toEqual(initialProfiles);
  });

  it('should remove single stream profile', () => {
    useStreamProfilesStore.setState({
      profiles: [
        { id: 1, name: 'Profile 1', bitrate: 5000 },
        { id: 2, name: 'Profile 2', bitrate: 8000 },
        { id: 3, name: 'Profile 3', bitrate: 10000 },
      ],
    });

    const { result } = renderHook(() => useStreamProfilesStore());

    act(() => {
      result.current.removeStreamProfiles([2]);
    });

    expect(result.current.profiles).toEqual([
      { id: 1, name: 'Profile 1', bitrate: 5000 },
      { id: 3, name: 'Profile 3', bitrate: 10000 },
    ]);
  });

  it('should remove multiple stream profiles', () => {
    useStreamProfilesStore.setState({
      profiles: [
        { id: 1, name: 'Profile 1', bitrate: 5000 },
        { id: 2, name: 'Profile 2', bitrate: 8000 },
        { id: 3, name: 'Profile 3', bitrate: 10000 },
      ],
    });

    const { result } = renderHook(() => useStreamProfilesStore());

    act(() => {
      result.current.removeStreamProfiles([1, 3]);
    });

    expect(result.current.profiles).toEqual([
      { id: 2, name: 'Profile 2', bitrate: 8000 },
    ]);
  });

  it('should handle removing non-existent profiles', () => {
    const initialProfiles = [
      { id: 1, name: 'Profile 1', bitrate: 5000 },
      { id: 2, name: 'Profile 2', bitrate: 8000 },
    ];

    useStreamProfilesStore.setState({
      profiles: initialProfiles,
    });

    const { result } = renderHook(() => useStreamProfilesStore());

    act(() => {
      result.current.removeStreamProfiles([999]);
    });

    expect(result.current.profiles).toEqual(initialProfiles);
  });

  it('should handle removing from empty profiles', () => {
    const { result } = renderHook(() => useStreamProfilesStore());

    act(() => {
      result.current.removeStreamProfiles([1, 2]);
    });

    expect(result.current.profiles).toEqual([]);
  });

  it('should handle empty array when removing profiles', () => {
    const initialProfiles = [{ id: 1, name: 'Profile 1', bitrate: 5000 }];

    useStreamProfilesStore.setState({
      profiles: initialProfiles,
    });

    const { result } = renderHook(() => useStreamProfilesStore());

    act(() => {
      result.current.removeStreamProfiles([]);
    });

    expect(result.current.profiles).toEqual(initialProfiles);
  });
});
