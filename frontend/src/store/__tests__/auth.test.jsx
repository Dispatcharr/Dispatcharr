import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useAuthStore from '../auth';
import useSettingsStore from '../settings';
import useChannelsStore from '../channels';
import usePlaylistsStore from '../playlists';
import useEPGsStore from '../epgs';
import useStreamProfilesStore from '../streamProfiles';
import useUserAgentsStore from '../userAgents';
import useUsersStore from '../users';
import API from '../../api';
import { USER_LEVELS } from '../../constants';

// Mock all store dependencies
vi.mock('../settings');
vi.mock('../channels');
vi.mock('../playlists');
vi.mock('../epgs');
vi.mock('../streamProfiles');
vi.mock('../userAgents');
vi.mock('../users');
vi.mock('../../api');

// Mock localStorage
const localStorageMock = (() => {
  let store = {};
  return {
    getItem: vi.fn((key) => store[key] || null),
    setItem: vi.fn((key, value) => {
      store[key] = value.toString();
    }),
    removeItem: vi.fn((key) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
  };
})();

global.localStorage = localStorageMock;

// Helper to create a mock JWT token
const createMockToken = (expiresInSeconds = 3600) => {
  const now = Math.floor(Date.now() / 1000);
  const exp = now + expiresInSeconds;
  const payload = btoa(JSON.stringify({ exp }));
  return `header.${payload}.signature`;
};

describe('useAuthStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();

    // Setup default store mocks
    useSettingsStore.mockImplementation((selector) =>
      selector({
        fetchSettings: vi.fn().mockResolvedValue(),
      })
    );

    useChannelsStore.mockImplementation((selector) =>
      selector({
        fetchChannels: vi.fn().mockResolvedValue(),
        fetchChannelGroups: vi.fn().mockResolvedValue(),
        fetchChannelProfiles: vi.fn().mockResolvedValue(),
      })
    );

    usePlaylistsStore.mockImplementation((selector) =>
      selector({
        fetchPlaylists: vi.fn().mockResolvedValue(),
      })
    );

    useEPGsStore.mockImplementation((selector) =>
      selector({
        fetchEPGs: vi.fn().mockResolvedValue(),
        fetchEPGData: vi.fn().mockResolvedValue(),
      })
    );

    useStreamProfilesStore.mockImplementation((selector) =>
      selector({
        fetchProfiles: vi.fn().mockResolvedValue(),
      })
    );

    useUserAgentsStore.mockImplementation((selector) =>
      selector({
        fetchUserAgents: vi.fn().mockResolvedValue(),
      })
    );

    useUsersStore.mockImplementation((selector) =>
      selector({
        fetchUsers: vi.fn().mockResolvedValue(),
      })
    );
  });

  afterEach(() => {
    // Reset the store state
    const { setState } = useAuthStore;
    if (setState) {
      setState({
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
        accessToken: null,
        refreshToken: null,
        tokenExpiration: null,
        superuserExists: true,
      });
    }
  });

  describe('Initial State', () => {
    it('should initialize with default state', () => {
      const { result } = renderHook(() => useAuthStore());

      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.isInitialized).toBe(false);
      expect(result.current.needsSuperuser).toBe(false);
      expect(result.current.user).toEqual({
        username: '',
        email: '',
        user_level: '',
      });
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.superuserExists).toBe(true);
    });
  });

  describe('login', () => {
    it('should successfully login and store tokens', async () => {
      const mockAccessToken = createMockToken();
      const mockRefreshToken = createMockToken(86400);

      API.login.mockResolvedValue({
        access: mockAccessToken,
        refresh: mockRefreshToken,
      });

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.login({
          username: 'testuser',
          password: 'password',
        });
      });

      expect(API.login).toHaveBeenCalledWith('testuser', 'password');
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'accessToken',
        mockAccessToken
      );
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'refreshToken',
        mockRefreshToken
      );
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'tokenExpiration',
        expect.any(Number)
      );
    });

    it('should handle login failure', async () => {
      API.login.mockRejectedValue(new Error('Invalid credentials'));

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.login({ username: 'testuser', password: 'wrong' });
      });

      expect(API.login).toHaveBeenCalledWith('testuser', 'wrong');
      expect(result.current.isAuthenticated).toBe(false);
      expect(localStorageMock.setItem).not.toHaveBeenCalled();
    });
  });

  describe('getRefreshToken', () => {
    it('should refresh token successfully', async () => {
      const mockNewAccessToken = createMockToken();
      localStorageMock.getItem.mockReturnValue('old-refresh-token');

      API.refreshToken.mockResolvedValue({
        access: mockNewAccessToken,
      });

      const { result } = renderHook(() => useAuthStore());

      let newToken;
      await act(async () => {
        newToken = await result.current.getRefreshToken();
      });

      expect(API.refreshToken).toHaveBeenCalledWith('old-refresh-token');
      expect(newToken).toBe(mockNewAccessToken);
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'accessToken',
        mockNewAccessToken
      );
    });

    it('should return false if no refresh token exists', async () => {
      localStorageMock.getItem.mockReturnValue(null);

      const { result } = renderHook(() => useAuthStore());

      let response;
      await act(async () => {
        response = await result.current.getRefreshToken();
      });

      expect(response).toBe(false);
      expect(API.refreshToken).not.toHaveBeenCalled();
    });

    it('should logout on refresh token failure', async () => {
      localStorageMock.getItem.mockReturnValue('invalid-refresh-token');
      API.refreshToken.mockRejectedValue(new Error('Invalid token'));
      API.logout.mockResolvedValue();

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.getRefreshToken();
      });

      expect(result.current.isAuthenticated).toBe(false);
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('accessToken');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('refreshToken');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith(
        'tokenExpiration'
      );
    });
  });

  describe('getToken', () => {
    it('should return valid access token if not expired', async () => {
      const mockToken = createMockToken(3600);
      const now = Math.floor(Date.now() / 1000);

      localStorageMock.getItem.mockImplementation((key) => {
        if (key === 'tokenExpiration') return (now + 1800).toString();
        if (key === 'accessToken') return mockToken;
        return null;
      });

      const { result } = renderHook(() => useAuthStore());

      let token;
      await act(async () => {
        token = await result.current.getToken();
      });

      expect(token).toBe(mockToken);
    });

    it('should refresh token if expired', async () => {
      const now = Math.floor(Date.now() / 1000);
      const mockNewToken = createMockToken();

      localStorageMock.getItem.mockImplementation((key) => {
        if (key === 'tokenExpiration') return (now - 100).toString();
        if (key === 'refreshToken') return 'refresh-token';
        return null;
      });

      API.refreshToken.mockResolvedValue({
        access: mockNewToken,
      });

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.getToken();
      });

      expect(API.refreshToken).toHaveBeenCalled();
    });
  });

  describe('logout', () => {
    it('should clear tokens and call logout API', async () => {
      API.logout.mockResolvedValue();

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.logout();
      });

      expect(API.logout).toHaveBeenCalled();
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('accessToken');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('refreshToken');
      expect(localStorageMock.removeItem).toHaveBeenCalledWith(
        'tokenExpiration'
      );
    });

    it('should continue logout even if API call fails', async () => {
      API.logout.mockRejectedValue(new Error('API error'));

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.logout();
      });

      expect(result.current.isAuthenticated).toBe(false);
      expect(localStorageMock.removeItem).toHaveBeenCalled();
    });
  });

  describe('initializeAuth', () => {
    it('should initialize auth with valid refresh token', async () => {
      const mockToken = createMockToken();
      localStorageMock.getItem.mockReturnValue('valid-refresh-token');
      API.refreshToken.mockResolvedValue({ access: mockToken });

      const { result } = renderHook(() => useAuthStore());

      let initialized;
      await act(async () => {
        initialized = await result.current.initializeAuth();
      });

      expect(initialized).toBe(true);
    });

    it('should return false if no refresh token exists', async () => {
      localStorageMock.getItem.mockReturnValue(null);

      const { result } = renderHook(() => useAuthStore());

      let initialized;
      await act(async () => {
        initialized = await result.current.initializeAuth();
      });

      expect(initialized).toBe(false);
    });
  });

  describe('initData', () => {
    const fetchSettings = vi.fn().mockResolvedValue();
    const fetchChannels = vi.fn().mockResolvedValue();
    const fetchChannelGroups = vi.fn().mockResolvedValue();
    const fetchChannelProfiles = vi.fn().mockResolvedValue();
    const fetchPlaylists = vi.fn().mockResolvedValue();
    const fetchEPGs = vi.fn().mockResolvedValue();
    const fetchEPGData = vi.fn().mockResolvedValue();
    const fetchProfiles = vi.fn().mockResolvedValue();
    const fetchUserAgents = vi.fn().mockResolvedValue();
    const fetchUsers = vi.fn().mockResolvedValue();

    // Mock getState for each store
    useSettingsStore.getState = () => ({ fetchSettings });
    useChannelsStore.getState = () => ({
      fetchChannels,
      fetchChannelGroups,
      fetchChannelProfiles,
    });
    usePlaylistsStore.getState = () => ({ fetchPlaylists });
    useEPGsStore.getState = () => ({ fetchEPGs, fetchEPGData });
    useStreamProfilesStore.getState = () => ({ fetchProfiles });
    useUserAgentsStore.getState = () => ({ fetchUserAgents });
    useUsersStore.getState = () => ({ fetchUsers });

    it('should initialize data for admin user', async () => {
      const mockUser = {
        username: 'admin',
        email: 'admin@test.com',
        user_level: USER_LEVELS.ADMIN,
      };

      API.me.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.initData();
      });

      expect(API.me).toHaveBeenCalled();
      expect(result.current.user).toEqual(mockUser);
      expect(result.current.isAuthenticated).toBe(true);
      expect(fetchSettings).toHaveBeenCalled();
      expect(fetchChannels).toHaveBeenCalled();
      expect(fetchUsers).toHaveBeenCalled();
    });

    it('should not fetch users for non-admin user', async () => {
      const mockUser = {
        username: 'reseller',
        email: 'reseller@test.com',
        user_level: USER_LEVELS.RESELLER,
      };

      API.me.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.initData();
      });

      expect(fetchUsers).not.toHaveBeenCalled();
    });

    it('should throw error for unauthorized user level', async () => {
      const mockUser = {
        username: 'streamer',
        email: 'streamer@test.com',
        user_level: USER_LEVELS.STREAMER,
      };

      API.me.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuthStore());

      await expect(
        act(async () => {
          await result.current.initData();
        })
      ).rejects.toThrow('Unauthorized');
    });

    it('should handle errors during data initialization', async () => {
      const mockUser = {
        username: 'admin',
        email: 'admin@test.com',
        user_level: USER_LEVELS.ADMIN,
      };

      API.me.mockResolvedValue(mockUser);

      const fetchChannels = vi
        .fn()
        .mockRejectedValue(new Error('Fetch failed'));

      useChannelsStore.getState = vi.fn(() => ({
        fetchChannels,
        fetchChannelGroups: vi.fn().mockResolvedValue(),
        fetchChannelProfiles: vi.fn().mockResolvedValue(),
      }));

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.initData();
      });
    });
  });

  describe('setUser', () => {
    it('should update user state', () => {
      const { result } = renderHook(() => useAuthStore());
      const newUser = {
        username: 'test',
        email: 'test@test.com',
        user_level: USER_LEVELS.ADMIN,
      };

      act(() => {
        result.current.setUser(newUser);
      });

      expect(result.current.user).toEqual(newUser);
    });
  });

  describe('setIsAuthenticated', () => {
    it('should update authentication state', () => {
      const { result } = renderHook(() => useAuthStore());

      act(() => {
        result.current.setIsAuthenticated(true);
      });

      expect(result.current.isAuthenticated).toBe(true);
    });
  });

  describe('setSuperuserExists', () => {
    it('should update superuser exists state', () => {
      const { result } = renderHook(() => useAuthStore());

      act(() => {
        result.current.setSuperuserExists(false);
      });

      expect(result.current.superuserExists).toBe(false);
    });
  });

  describe('getRefreshToken edge cases', () => {
    it('should return false if API response has no access token', async () => {
      localStorageMock.getItem.mockReturnValue('refresh-token');
      API.refreshToken.mockResolvedValue({});

      const { result } = renderHook(() => useAuthStore());

      let response;
      await act(async () => {
        response = await result.current.getRefreshToken();
      });

      expect(response).toBe(false);
    });
  });

  describe('login edge cases', () => {
    it('should not update state if response has no access token', async () => {
      API.login.mockResolvedValue({});

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.login({
          username: 'testuser',
          password: 'password',
        });
      });

      expect(result.current.accessToken).toBeNull();
      expect(localStorageMock.setItem).not.toHaveBeenCalled();
    });
  });

  describe('logout edge cases', () => {
    it('should reset isInitializing flag on logout', async () => {
      useAuthStore.setState({ isInitializing: true });
      API.logout.mockResolvedValue();

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.logout();
      });

      expect(result.current.isInitializing).toBe(false);
    });
  });

  describe('initializeAuth edge cases', () => {
    it('should return false if refresh token API call fails', async () => {
      localStorageMock.getItem.mockReturnValue('refresh-token');
      API.refreshToken.mockRejectedValue(new Error('Token expired'));
      API.logout.mockResolvedValue();

      const { result } = renderHook(() => useAuthStore());

      let initialized;
      await act(async () => {
        initialized = await result.current.initializeAuth();
      });

      expect(initialized).toBe(false);
    });

    it('should return false if refresh returns no access token', async () => {
      localStorageMock.getItem.mockReturnValue('refresh-token');
      API.refreshToken.mockResolvedValue({});

      const { result } = renderHook(() => useAuthStore());

      let initialized;
      await act(async () => {
        initialized = await result.current.initializeAuth();
      });

      expect(initialized).toBe(false);
    });
  });

  describe('initData edge cases', () => {
    it('should skip initialization if already initialized', async () => {
      useAuthStore.setState({ isInitialized: true });

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.initData();
      });

      expect(API.me).not.toHaveBeenCalled();
    });

    it('should skip initialization if already initializing', async () => {
      useAuthStore.setState({ isInitializing: true });

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.initData();
      });

      expect(API.me).not.toHaveBeenCalled();
    });

    it('should set isInitializing to false on error', async () => {
      // Reset state before the test
      useAuthStore.setState({
        isInitializing: false,
        isInitialized: false,
      });

      API.me.mockRejectedValue(new Error('API error'));

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        try {
          await result.current.initData();
        } catch {
          // Expected error
        }
      });

      expect(result.current.isInitializing).toBe(false);
      expect(result.current.isInitialized).toBe(false);
    });

    it('should call fetchChannels in background after initialization', async () => {
      const mockUser = {
        username: 'admin',
        email: 'admin@test.com',
        user_level: USER_LEVELS.ADMIN,
      };

      const fetchChannels = vi.fn().mockResolvedValue();
      useChannelsStore.getState = () => ({
        fetchChannels,
        fetchChannelGroups: vi.fn().mockResolvedValue(),
        fetchChannelProfiles: vi.fn().mockResolvedValue(),
      });

      API.me.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuthStore());

      await act(async () => {
        await result.current.initData();
      });

      // Wait for the background call to complete
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });

      // The background fetchChannels is called synchronously without await
      // so we just need to verify it was called
      expect(fetchChannels).toHaveBeenCalled();
    });
  });
});
