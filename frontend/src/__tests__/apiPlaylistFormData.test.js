import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  updatePlaylist: vi.fn(),
  updateProfiles: vi.fn(),
}));

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
      updatePlaylist: mocks.updatePlaylist,
      updateProfiles: mocks.updateProfiles,
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
  notifications: { show: vi.fn(), hide: vi.fn() },
}));
vi.mock('../utils', () => ({
  default: { all: vi.fn() },
  formatApiError: vi.fn(() => 'error'),
}));

import API from '../api';
import { notifications } from '@mantine/notifications';
import { formatApiError } from '../utils';
import useScreenshotMode from '../store/useScreenshotMode.js';

describe('profile save results', () => {
  beforeEach(() => vi.clearAllMocks());
  it.each([
    ['add', () => API.addM3UProfile(7, { name: 'Example profile' })],
    [
      'update',
      () => API.updateM3UProfile(7, { id: 71, name: 'Example profile' }),
    ],
  ])('returns the %s result after updating the store', async (_kind, save) => {
    const saved = { id: 71, name: 'Example profile' };
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify(saved),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({ id: 7, profiles: [saved] }),
      });
    expect(await save()).toEqual(saved);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });
  it.each([
    ['add', () => API.addM3UProfile(7, { name: 'Example profile' })],
    [
      'update',
      () => API.updateM3UProfile(7, { id: 71, name: 'Example profile' }),
    ],
  ])(
    'returns no success and notifies once when %s fails',
    async (_kind, save) => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: async () => 'Invalid profile',
      });
      await expect(save()).rejects.toMatchObject({ status: 400 });
      expect(notifications.show).toHaveBeenCalledOnce();
      expect(mocks.updatePlaylist).not.toHaveBeenCalled();
      expect(mocks.updateProfiles).not.toHaveBeenCalled();
    }
  );
});

describe('read-only M3U connection checks', () => {
  beforeEach(() => vi.clearAllMocks());
  it('posts a draft in the body without updating the store or notifying', async () => {
    const values = {
      account_type: 'XC',
      server_url: 'https://example.invalid',
      username: 'example',
      password: 'synthetic',
    };
    const result = { success: false, code: 'http_error', message: 'HTTP 403' };
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify(result),
    });
    expect(await API.checkM3UConnection(values)).toEqual(result);
    const [url, options] = globalThis.fetch.mock.calls[0];
    expect(new URL(url, 'http://example.invalid').pathname).toBe(
      '/api/m3u/accounts/check-connection/'
    );
    expect(url).not.toContain('synthetic');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual(values);
    expect(mocks.updatePlaylist).not.toHaveBeenCalled();
    expect(notifications.show).not.toHaveBeenCalled();
  });
  it('leaves API failures to the confirmation dialog without a duplicate notification', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => 'Unavailable',
    });
    await expect(API.checkM3UConnection({})).rejects.toMatchObject({
      status: 503,
    });
    expect(notifications.show).not.toHaveBeenCalled();
  });
});

describe('account import rule requests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useScreenshotMode.setState({ enabled: false });
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ updated: 1, results: [] }),
    });
  });
  it('checks and previews draft Live selections without requesting an import or saving selections', async () => {
    await API.getM3UStreamFilterAvailability(7, [9, 12]);
    let [url, options] = globalThis.fetch.mock.calls[0];
    expect(url).toContain('/filters/availability/');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ group_ids: [9, 12] });
    globalThis.fetch.mockClear();
    await API.analyzeM3URules(7, 'filters', [{ preview_id: '1' }], {
      groupIds: [9, 12],
    });
    [url, options] = globalThis.fetch.mock.calls[0];
    expect(url).toContain('/filters/preview-draft/');
    expect(JSON.parse(options.body)).toEqual({
      rules: [{ preview_id: '1' }],
      target_id: '1',
      group_ids: [9, 12],
    });
    expect(mocks.updatePlaylist).not.toHaveBeenCalled();
    expect(notifications.show).not.toHaveBeenCalled();
  });
  it.each([
    ['GET', () => API.getM3UEPG(7)],
    ['POST', () => API.createM3UEPG(7)],
  ])(
    'uses the credential-free account EPG endpoint with %s',
    async (method, action) => {
      await action();
      const [url, options] = globalThis.fetch.mock.calls[0];
      expect(new URL(url, 'http://example.invalid').pathname).toBe(
        '/api/m3u/accounts/7/epg/'
      );
      expect(options.method || 'GET').toBe(method);
      expect(options.body).toBeUndefined();
    }
  );
  it.each([
    ['rules', () => API.getM3URules(7, 'group-rules', 'live')],
    ['library', () => API.getMovies()],
  ])(
    'keeps %s API error notifications masked when screenshot mode changes',
    async (_name, request) => {
      const url =
        'https://example.invalid/player_api.php?username=example-user&password=example-secret';
      vi.mocked(formatApiError).mockReturnValueOnce(`Request failed: ${url}`);
      globalThis.fetch.mockResolvedValue({
        ok: false,
        status: 503,
        text: async () => 'Unavailable',
      });
      await expect(request()).rejects.toMatchObject({ status: 503 });
      render(notifications.show.mock.calls[0][0].message);
      expect(
        screen.getByText(new RegExp('example-secret'))
      ).toBeInTheDocument();
      act(() => useScreenshotMode.setState({ enabled: true }));
      expect(
        screen.queryByText(new RegExp('example-secret'))
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(new RegExp('example-user'))
      ).not.toBeInTheDocument();
      expect(screen.getByText(/••••••••/)).toBeInTheDocument();
      act(() => useScreenshotMode.setState({ enabled: false }));
      expect(
        screen.getByText(new RegExp('example-secret'))
      ).toBeInTheDocument();
    }
  );
  it.each([
    ['load', () => API.getM3URules(7, 'group-rules', 'live')],
    [
      'save',
      () => API.saveM3URule(7, 'group-rules', 1, { regex_pattern: '[' }),
    ],
    ['delete', () => API.deleteM3URule(7, 'filters', 1)],
    ['preview', () => API.previewM3URules(7, 'group-rules', [], 1, 1, 50)],
    ['reorder', () => API.reorderM3URules(7, 'group-rules', [1], 'live', [0])],
    ['apply', () => API.saveApplyM3UGroupRules(7, [], 1)],
  ])(
    'already emits exactly one API error notification on %s failure',
    async (_operation, request) => {
      globalThis.fetch.mockResolvedValue({
        ok: false,
        status: 400,
        text: async () =>
          JSON.stringify({ regex_pattern: ['Invalid regular expression.'] }),
      });
      await expect(request()).rejects.toMatchObject({ status: 400 });
      expect(notifications.show).toHaveBeenCalledTimes(1);
      expect(notifications.show).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Error',
          color: 'red',
          autoClose: false,
          id: expect.stringMatching(/^account-rules-7-/),
        })
      );
    }
  );
  it('loads rules from the selected account and content scope', async () => {
    await API.getM3URules(7, 'group-rules', 'movie');
    expect(globalThis.fetch.mock.calls[0][0]).toContain(
      '/api/m3u/accounts/7/group-rules/?scope=movie'
    );
  });
  it('saves edited rows with PATCH, and new rows with POST', async () => {
    await API.saveM3URule(7, 'filters', 2, { regex_pattern: '###' });
    expect(globalThis.fetch.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ regex_pattern: '###' }),
      })
    );
    await API.saveM3URule(7, 'filters', null, { regex_pattern: 'Sport' });
    expect(globalThis.fetch.mock.calls[1][1].method).toBe('POST');
  });
  it('sends the full ordered draft and selected row to the paginated preview', async () => {
    const rules = [{ preview_id: 'new', regex_pattern: 'Sport' }];
    await API.previewM3URules(7, 'group-rules', rules, 'new', 5, 50);
    expect(globalThis.fetch.mock.calls[0][0]).toContain(
      '/preview-draft/?page=5&page_size=50'
    );
    expect(JSON.parse(globalThis.fetch.mock.calls[0][1].body)).toEqual({
      rules,
      target_id: 'new',
    });
  });
  it('uses the same read-only snapshot endpoint for quiet coverage analysis', async () => {
    const rules = [{ preview_id: '1', regex_pattern: 'News' }];
    await API.analyzeM3URules(7, 'group-rules', rules);
    expect(globalThis.fetch.mock.calls[0][0]).toContain(
      '/preview-draft/?page=1&page_size=1'
    );
    expect(JSON.parse(globalThis.fetch.mock.calls[0][1].body)).toEqual({
      rules,
      target_id: '1',
    });
    expect(notifications.show).not.toHaveBeenCalled();
  });
  it('does not toast optional background analysis errors but still rejects them', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => 'Unavailable',
    });
    await expect(
      API.analyzeM3URules(7, 'filters', [{ preview_id: '1' }])
    ).rejects.toThrow();
    expect(notifications.show).not.toHaveBeenCalled();
  });
  it('saves and applies the previewed draft in one request', async () => {
    const rules = [{ preview_id: '2', action: 'enable' }];
    await API.saveApplyM3UGroupRules(7, rules, 2);
    expect(globalThis.fetch.mock.calls[0][0]).toContain(
      '/group-rules/save-apply/'
    );
    expect(JSON.parse(globalThis.fetch.mock.calls[0][1].body)).toEqual({
      rules,
      target_id: '2',
    });
  });
  it('changes only IDs and positions during reordering', async () => {
    await API.reorderM3URules(7, 'group-rules', [2, 1], 'live', [0, 2]);
    expect(JSON.parse(globalThis.fetch.mock.calls[0][1].body)).toEqual({
      ids: [2, 1],
      positions: [0, 2],
      scope: 'live',
    });
  });
  it('encodes the search and exact group in content preview requests', async () => {
    await API.getM3UGroupContent(7, 'series', 9, 2, 25, 'Football & Boxing');
    const query = new URL(globalThis.fetch.mock.calls[0][0], 'http://localhost')
      .searchParams;
    expect(Object.fromEntries(query)).toEqual({
      scope: 'series',
      group_id: '9',
      page: '2',
      page_size: '25',
      search: 'Football & Boxing',
    });
  });
  it('propagates rejected group saves rather than reporting false success', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => 'invalid settings',
    });
    await expect(API.updateM3UGroupSettings(7, [], [])).rejects.toThrow();
  });
  it('publishes authoritative account counts after saving VOD category selections', async () => {
    const saved = {
      id: 7,
      category_selection_counts: {
        live: { selected: 2, total: 3 },
        movie: { selected: 1, total: 4 },
        series: { selected: 0, total: 2 },
      },
    };
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({ message: 'Saved' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify(saved),
      });
    await API.updateM3UGroupSettings(7, [], [{ id: 10, enabled: true }]);
    expect(mocks.updatePlaylist).toHaveBeenCalledExactlyOnceWith(saved);
    expect(
      globalThis.fetch.mock.calls.map(
        ([url]) => new URL(url, 'https://example.invalid').pathname
      )
    ).toEqual(['/api/m3u/accounts/7/group-settings/', '/api/m3u/accounts/7/']);
  });
});

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
      server_url: '',
      file: new Blob(['#EXTM3U'], { type: 'text/plain' }),
    });

    expect(appended).toContainEqual(['hash_key', '']);
    expect(appended).toContainEqual(['server_url', '']);
    expect(appended.some(([key]) => key === 'id')).toBe(false);
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
