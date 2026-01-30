import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import usePlaylistsStore from '../playlists';
import api from '../../api';

vi.mock('../../api');

describe('usePlaylistsStore', () => {
  beforeEach(() => {
    const { result } = renderHook(() => usePlaylistsStore());
    act(() => {
      result.current.playlists = [];
      result.current.profiles = {};
      result.current.refreshProgress = {};
      result.current.isLoading = false;
      result.current.error = null;
      result.current.profileSearchPreview = '';
      result.current.profileResult = '';
      result.current.editPlaylistId = null;
    });
    vi.clearAllMocks();
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => usePlaylistsStore());

    expect(result.current.playlists).toEqual([]);
    expect(result.current.profiles).toEqual({});
    expect(result.current.refreshProgress).toEqual({});
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
    expect(result.current.profileSearchPreview).toBe('');
    expect(result.current.profileResult).toBe('');
    expect(result.current.editPlaylistId).toBe(null);
  });

  it('should set edit playlist id', () => {
    const { result } = renderHook(() => usePlaylistsStore());

    act(() => {
      result.current.setEditPlaylistId('playlist1');
    });

    expect(result.current.editPlaylistId).toBe('playlist1');
  });

  it('should fetch playlist successfully', async () => {
    const mockPlaylist = {
      id: 'playlist1',
      name: 'Test Playlist',
      profiles: ['profile1', 'profile2'],
    };

    api.getPlaylist.mockResolvedValue(mockPlaylist);

    const { result } = renderHook(() => usePlaylistsStore());

    act(() => {
      result.current.playlists = [{ id: 'playlist1', name: 'Old Name' }];
    });

    await act(async () => {
      await result.current.fetchPlaylist('playlist1');
    });

    expect(api.getPlaylist).toHaveBeenCalledWith('playlist1');
    expect(result.current.playlists).toEqual([mockPlaylist]);
    expect(result.current.profiles).toEqual({ playlist1: ['profile1', 'profile2'] });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should handle fetch playlist error', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    api.getPlaylist.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => usePlaylistsStore());

    await act(async () => {
      await result.current.fetchPlaylist('playlist1');
    });

    expect(result.current.error).toBe('Failed to load playlists.');
    expect(result.current.isLoading).toBe(false);
    consoleErrorSpy.mockRestore();
  });

  it('should fetch playlists successfully', async () => {
    const mockPlaylists = [
      { id: 'playlist1', name: 'Playlist 1', profiles: ['profile1'] },
      { id: 'playlist2', name: 'Playlist 2', profiles: ['profile2'] },
    ];

    api.getPlaylists.mockResolvedValue(mockPlaylists);

    const { result } = renderHook(() => usePlaylistsStore());

    await act(async () => {
      await result.current.fetchPlaylists();
    });

    expect(api.getPlaylists).toHaveBeenCalled();
    expect(result.current.playlists).toEqual(mockPlaylists);
    expect(result.current.profiles).toEqual({
      playlist1: ['profile1'],
      playlist2: ['profile2'],
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should handle fetch playlists error', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    api.getPlaylists.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => usePlaylistsStore());

    await act(async () => {
      await result.current.fetchPlaylists();
    });

    expect(result.current.error).toBe('Failed to load playlists.');
    expect(result.current.isLoading).toBe(false);
    consoleErrorSpy.mockRestore();
  });

  it('should add playlist', () => {
    const { result } = renderHook(() => usePlaylistsStore());
    const newPlaylist = {
      id: 'playlist1',
      name: 'New Playlist',
      profiles: ['profile1'],
    };

    act(() => {
      result.current.addPlaylist(newPlaylist);
    });

    expect(result.current.playlists).toEqual([newPlaylist]);
    expect(result.current.profiles).toEqual({ playlist1: ['profile1'] });
  });

  it('should update playlist', () => {
    const { result } = renderHook(() => usePlaylistsStore());
    const existingPlaylist = { id: 'playlist1', name: 'Old Name', profiles: ['profile1'] };
    const updatedPlaylist = { id: 'playlist1', name: 'New Name', profiles: ['profile1', 'profile2'] };

    act(() => {
      result.current.playlists = [existingPlaylist];
      result.current.profiles = { playlist1: ['profile1'] };
    });

    act(() => {
      result.current.updatePlaylist(updatedPlaylist);
    });

    expect(result.current.playlists).toEqual([updatedPlaylist]);
    expect(result.current.profiles).toEqual({ playlist1: ['profile1', 'profile2'] });
  });

  it('should update profiles', () => {
    const { result } = renderHook(() => usePlaylistsStore());

    act(() => {
      result.current.profiles = { playlist1: ['profile1'] };
    });

    act(() => {
      result.current.updateProfiles('playlist1', ['profile1', 'profile2', 'profile3']);
    });

    expect(result.current.profiles).toEqual({ playlist1: ['profile1', 'profile2', 'profile3'] });
  });

  it('should remove playlists', () => {
    const { result } = renderHook(() => usePlaylistsStore());

    act(() => {
      result.current.playlists = [
        { id: 'playlist1', name: 'Playlist 1' },
        { id: 'playlist2', name: 'Playlist 2' },
        { id: 'playlist3', name: 'Playlist 3' },
      ];
    });

    act(() => {
      result.current.removePlaylists(['playlist1', 'playlist3']);
    });

    expect(result.current.playlists).toEqual([{ id: 'playlist2', name: 'Playlist 2' }]);
  });

  it('should set refresh progress with two parameters', () => {
    const { result } = renderHook(() => usePlaylistsStore());
    const progressData = { action: 'refreshing', progress: 50 };

    act(() => {
      result.current.setRefreshProgress('account1', progressData);
    });

    expect(result.current.refreshProgress).toEqual({ account1: progressData });
  });

  it('should set refresh progress with WebSocket data', () => {
    const { result } = renderHook(() => usePlaylistsStore());
    const wsData = { account: 'account1', action: 'refreshing', progress: 50 };

    act(() => {
      result.current.setRefreshProgress(wsData);
    });

    expect(result.current.refreshProgress).toEqual({ account1: wsData });
  });

  it('should preserve initializing status until real progress', () => {
    const { result } = renderHook(() => usePlaylistsStore());

    act(() => {
      result.current.refreshProgress = {
        account1: { action: 'initializing', progress: 0 },
      };
    });

    act(() => {
      result.current.setRefreshProgress({ account: 'account1', progress: 0 });
    });

    expect(result.current.refreshProgress.account1.action).toBe('initializing');

    act(() => {
      result.current.setRefreshProgress({ account: 'account1', action: 'refreshing', progress: 25 });
    });

    expect(result.current.refreshProgress.account1.action).toBe('refreshing');
  });

  it('should remove refresh progress', () => {
    const { result } = renderHook(() => usePlaylistsStore());

    act(() => {
      result.current.refreshProgress = {
        account1: { action: 'refreshing', progress: 50 },
        account2: { action: 'refreshing', progress: 75 },
      };
    });

    act(() => {
      result.current.removeRefreshProgress('account1');
    });

    expect(result.current.refreshProgress).toEqual({
      account2: { action: 'refreshing', progress: 75 },
    });
  });

  it('should set profile preview', () => {
    const { result } = renderHook(() => usePlaylistsStore());

    act(() => {
      result.current.setProfilePreview('search text', 'result data');
    });

    expect(result.current.profileSearchPreview).toBe('search text');
    expect(result.current.profileResult).toBe('result data');
  });
});
