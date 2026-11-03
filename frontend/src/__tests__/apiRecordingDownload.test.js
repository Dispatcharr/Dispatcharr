import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { getToken } = vi.hoisted(() => ({ getToken: vi.fn() }));

vi.mock('../store/auth', () => ({
  default: { getState: () => ({ getToken }) },
}));
vi.mock('../store/channels', () => ({ default: vi.fn() }));
vi.mock('../store/logos', () => ({ default: vi.fn() }));
vi.mock('../store/userAgents', () => ({ default: vi.fn() }));
vi.mock('../store/serverGroups', () => ({ default: vi.fn() }));
vi.mock('../store/playlists', () => ({ default: vi.fn() }));
vi.mock('../store/epgs', () => ({ default: vi.fn() }));
vi.mock('../store/streams', () => ({ default: vi.fn() }));
vi.mock('../store/streamProfiles', () => ({ default: vi.fn() }));
vi.mock('../store/outputProfiles', () => ({ default: vi.fn() }));
vi.mock('../store/settings', () => ({ default: vi.fn() }));
vi.mock('../store/channelsTable', () => ({ default: vi.fn() }));
vi.mock('../store/streamsTable', () => ({ default: vi.fn() }));
vi.mock('../store/users', () => ({ default: vi.fn() }));
vi.mock('../store/connect', () => ({ default: vi.fn() }));
vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}));
vi.mock('../utils', () => ({
  default: { all: vi.fn() },
  formatApiError: vi.fn(() => 'error'),
}));

import API from '../api';
import { notifications } from '@mantine/notifications';

describe('recording download', () => {
  let link;

  beforeEach(() => {
    vi.clearAllMocks();
    link = null;
    getToken.mockResolvedValue('fresh-token+/=&');
    vi.stubGlobal('fetch', vi.fn());
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(
      function () {
        link = this;
      }
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it.each([false, true])(
    'downloads the existing file endpoint on the same origin with DEV=%s',
    async (dev) => {
      vi.stubEnv('DEV', dev);

      await API.downloadRecording(67, 'Test Show.mkv');

      const url = new URL(link.href);
      expect(url.origin).toBe(window.location.origin);
      expect(url.pathname).toBe('/api/channels/recordings/67/file/');
      expect(url.searchParams.get('token')).toBe('fresh-token+/=&');
      expect(link.download).toBe('Test Show.mkv');
      expect(fetch).not.toHaveBeenCalled();
      expect(link.isConnected).toBe(false);
    }
  );

  it('obtains a fresh token for each download', async () => {
    await API.downloadRecording(67, 'Test Show.mkv');
    getToken.mockResolvedValue('refreshed-token');

    await API.downloadRecording(67, 'Test Show.mkv');

    expect(getToken).toHaveBeenCalledTimes(2);
    expect(new URL(link.href).searchParams.get('token')).toBe(
      'refreshed-token'
    );
  });

  it('supplies a fallback filename', async () => {
    await API.downloadRecording(67);

    expect(link.download).toBe('recording');
  });

  it('reports token refresh failures without starting a download', async () => {
    const error = new Error('Token refresh failed');
    getToken.mockRejectedValue(error);

    await expect(API.downloadRecording(67)).rejects.toThrow(error);

    expect(link).toBeNull();
    expect(notifications.show).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Failed to download recording: error',
        color: 'red',
      })
    );
  });

  it('does not start an unauthenticated download', async () => {
    getToken.mockResolvedValue(null);

    await expect(API.downloadRecording(67)).rejects.toThrow(
      'Authentication required'
    );

    expect(link).toBeNull();
    expect(notifications.show).toHaveBeenCalled();
  });
});
