import { create } from 'zustand';
import api from '../api';
import useSettingsStore from './settings';
import useChannelsStore from './channels';
import usePlaylistsStore from './playlists';
import useEPGsStore from './epgs';
import useStreamProfilesStore from './streamProfiles';
import useUserAgentsStore from './userAgents';
import useUsersStore from './users';
import API from '../api';
import { USER_LEVELS } from '../constants';

const decodeToken = (token) => {
  if (!token) return null;
  const payload = token.split('.')[1];
  const decodedPayload = JSON.parse(atob(payload));
  return decodedPayload.exp;
};

const isTokenExpired = (expirationTime) => {
  const now = Math.floor(Date.now() / 1000);
  return now >= expirationTime;
};

const useAuthStore = create((set, get) => ({
  isAuthenticated: false,
  isInitialized: false,
  needsSuperuser: false,
  user: {
    username: '',
    email: '',
    user_level: '',
  },
  isLoading: false,
  error: null,

  setUser: (user) => set({ user }),

  initData: async () => {
    const user = await API.me();
    if (user.user_level <= USER_LEVELS.STREAMER) {
      throw new Error('Unauthorized');
    }

    set({ user, isAuthenticated: true });

    // Ensure settings are loaded first
    await useSettingsStore.getState().fetchSettings();

    try {
      // Only after settings are loaded, fetch the essential data
      await Promise.all([
        useChannelsStore.getState().fetchChannels(),
        useChannelsStore.getState().fetchChannelGroups(),
        useChannelsStore.getState().fetchChannelProfiles(),
        usePlaylistsStore.getState().fetchPlaylists(),
        useEPGsStore.getState().fetchEPGs(),
        useEPGsStore.getState().fetchEPGData(),
        useStreamProfilesStore.getState().fetchProfiles(),
        useUserAgentsStore.getState().fetchUserAgents(),
      ]);

      if (user.user_level >= USER_LEVELS.ADMIN) {
        await Promise.all([useUsersStore.getState().fetchUsers()]);
      }

      // Note: Logos are loaded after the Channels page tables finish loading
      // This is handled by the tables themselves signaling completion
    } catch (error) {
      console.error('Error initializing data:', error);
    }
  },

  accessToken: localStorage.getItem('accessToken') || null,
  refreshToken: localStorage.getItem('refreshToken') || null,
  tokenExpiration: localStorage.getItem('tokenExpiration') || null,
  superuserExists: true,

  setIsAuthenticated: (isAuthenticated) => set({ isAuthenticated }),

  setSuperuserExists: (superuserExists) => set({ superuserExists }),

  getToken: async () => {
    const tokenExpiration = localStorage.getItem('tokenExpiration');
    let accessToken = null;
    if (isTokenExpired(tokenExpiration)) {
      accessToken = await get().getRefreshToken();
    } else {
      accessToken = localStorage.getItem('accessToken');
    }

    return accessToken;
  },

  // Action to login
  login: async ({ username, password }) => {
    try {
      const response = await api.login(username, password);
      if (response.access) {
        const expiration = decodeToken(response.access);
        set({
          accessToken: response.access,
          refreshToken: response.refresh,
          tokenExpiration: expiration, // 1 hour from now
        });
        // Store in localStorage
        localStorage.setItem('accessToken', response.access);
        localStorage.setItem('refreshToken', response.refresh);
        localStorage.setItem('tokenExpiration', expiration);

        // Don't start background loading here - let it happen after app initialization
      }
    } catch (error) {
      console.error('Login failed:', error);
    }
  },

  // Action to refresh the token
  getRefreshToken: async () => {
    const refreshToken = localStorage.getItem('refreshToken');
    if (!refreshToken) return false; // Add explicit return here

    try {
      const data = await api.refreshToken(refreshToken);
      if (data && data.access) {
        set({
          accessToken: data.access,
          tokenExpiration: decodeToken(data.access),
          isAuthenticated: true,
        });
        localStorage.setItem('accessToken', data.access);
        localStorage.setItem('tokenExpiration', decodeToken(data.access));

        return data.access;
      }
      return false; // Add explicit return for when data.access is not available
    } catch (error) {
      console.error('Token refresh failed:', error);
      await get().logout();
      return false; // Add explicit return after error
    }
  },

  // Action to logout
  logout: async () => {
    // Call backend logout endpoint to log the event
    try {
      await API.logout();
    } catch (error) {
      // Continue with logout even if API call fails
      console.error('Logout API call failed:', error);
    }

    set({
      accessToken: null,
      refreshToken: null,
      tokenExpiration: null,
      isAuthenticated: false,
      user: null,
    });
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('tokenExpiration');
  },

  initializeAuth: async () => {
    const refreshToken = localStorage.getItem('refreshToken') || null;

    if (refreshToken) {
      const loggedIn = await get().getRefreshToken();
      if (loggedIn) {
        return true;
      }
    }

    return false;
  },
}));

export default useAuthStore;
