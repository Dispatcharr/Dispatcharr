import { create } from 'zustand';
import api from '../api';

const usePlaylistsStore = create((set) => ({
  playlists: [],
  profiles: {},
  refreshProgress: {},
  isLoading: false,
  error: null,

  fetchPlaylists: async () => {
    set({ isLoading: true, error: null });
    try {
      const playlists = await api.getPlaylists();
      set({
        playlists: playlists,
        isLoading: false,
        profiles: playlists.reduce((acc, playlist) => {
          acc[playlist.id] = playlist.profiles;
          return acc;
        }, {}),
      });
    } catch (error) {
      console.error('Failed to fetch playlists:', error);
      set({ error: 'Failed to load playlists.', isLoading: false });
    }
  },

  addPlaylist: (newPlaylist) =>
    set((state) => ({
      playlists: [...state.playlists, newPlaylist],
      profiles: {
        ...state.profiles,
        [newPlaylist.id]: newPlaylist.profiles,
      },
    })),

  updatePlaylist: (playlist) =>
    set((state) => ({
      playlists: state.playlists.map((pl) =>
        pl.id === playlist.id ? playlist : pl
      ),
      profiles: {
        ...state.profiles,
        [playlist.id]: playlist.profiles,
      },
    })),

  updateProfiles: (playlistId, profiles) =>
    set((state) => ({
      profiles: {
        ...state.profiles,
        [playlistId]: profiles,
      },
    })),

  removePlaylists: (playlistIds) =>
    set((state) => ({
      playlists: state.playlists.filter(
        (playlist) => !playlistIds.includes(playlist.id)
      ),
      // @TODO: remove playlist profiles here
    })),

  setRefreshProgress: (id, progress) =>
    set((state) => ({
      refreshProgress: {
        ...state.refreshProgress,
        [id]: progress,
      },
    })),

  removeRefreshProgress: (id) =>
    set((state) => {
      const updatedProgress = { ...state.refreshProgress };
      delete updatedProgress[id];

      return {
        refreshProgress: updatedProgress,
      };
    }),
}));

export default usePlaylistsStore;
