import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../store/auth', () => ({
  default: { getState: () => ({ getToken: () => Promise.resolve('token') }) },
}));
vi.mock('../store/channels', () => ({ default: vi.fn() }));
vi.mock('../store/logos', () => ({ default: vi.fn() }));
vi.mock('../store/userAgents', () => ({ default: vi.fn() }));
vi.mock('../store/serverGroups', () => ({ default: vi.fn() }));
vi.mock('../store/playlists', () => ({
  default: {
    getState: () => ({
      addPlaylist: vi.fn(),
      updatePlaylist: vi.fn(),
    }),
  },
}));
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

describe('playlist FormData hash_key clearing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('sends an empty string for null hash_key when updating with a file', async () => {
    const appended = [];
    const formData = {
      append: (key, value) => {
        appended.push([key, value]);
      },
    };
    vi.stubGlobal(
      'FormData',
      vi.fn(function FormDataMock() {
        return formData;
      })
    );

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ id: 1, name: 'A' })),
    });

    await API.updatePlaylist({
      id: 1,
      name: 'A',
      hash_key: null,
      file: new Blob(['#EXTM3U'], { type: 'text/plain' }),
    });

    expect(appended).toContainEqual(['hash_key', '']);
    vi.unstubAllGlobals();
  });

  it('sends an empty string for null hash_key when creating with a file', async () => {
    const appended = [];
    const formData = {
      append: (key, value) => {
        appended.push([key, value]);
      },
    };
    vi.stubGlobal(
      'FormData',
      vi.fn(function FormDataMock() {
        return formData;
      })
    );

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ id: 2, name: 'B' })),
    });

    await API.addPlaylist({
      name: 'B',
      hash_key: null,
      file: new Blob(['#EXTM3U'], { type: 'text/plain' }),
    });

    expect(appended).toContainEqual(['hash_key', '']);
    vi.unstubAllGlobals();
  });
});
