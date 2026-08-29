import { beforeEach, describe, expect, it, vi } from 'vitest';

const { channelsTableStore } = vi.hoisted(() => ({
  channelsTableStore: vi.fn(),
}));

channelsTableStore.getState = vi.fn();

vi.mock('../store/auth', () => ({
  default: { getState: () => ({ getToken: () => Promise.resolve('token') }) },
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
vi.mock('../store/channelsTable', () => ({ default: channelsTableStore }));
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

const invalidPageResponse = {
  ok: false,
  status: 404,
  text: () => Promise.resolve(JSON.stringify({ detail: 'Invalid page.' })),
};

const successResponse = (body) => ({
  ok: true,
  json: () => Promise.resolve(body),
});

describe('channel request ordering', () => {
  const setPagination = vi.fn();
  const queryChannels = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    API.channelsRequestVersion = 0;
    API.lastQueryParams = new URLSearchParams();
    channelsTableStore.getState.mockReturnValue({
      pagination: { pageIndex: 1, pageSize: 25 },
      setPagination,
      queryChannels,
      setAllQueryIds: vi.fn(),
    });
  });

  it('does not recover from an invalid page response superseded by queryChannels', async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(invalidPageResponse)
      .mockResolvedValueOnce(successResponse({ results: [], count: 0 }));

    const staleRequest = API.queryChannels(
      new URLSearchParams({ page: '2', page_size: '25' })
    );
    const currentRequest = API.queryChannels(
      new URLSearchParams({ page: '1', page_size: '25' })
    );

    await Promise.all([staleRequest, currentRequest]);

    expect(setPagination).not.toHaveBeenCalled();
    expect(queryChannels).toHaveBeenCalledTimes(1);
  });

  it('does not recover from an invalid page response superseded by requeryChannels', async () => {
    API.lastQueryParams = new URLSearchParams({ page: '2', page_size: '25' });
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(invalidPageResponse)
      .mockResolvedValueOnce(successResponse([]))
      .mockResolvedValueOnce(successResponse({ results: [], count: 0 }));

    const staleRequest = API.requeryChannels();
    const currentRequest = API.queryChannels(
      new URLSearchParams({ page: '1', page_size: '25' })
    );

    await Promise.all([staleRequest, currentRequest]);

    expect(setPagination).not.toHaveBeenCalled();
    expect(queryChannels).toHaveBeenCalledTimes(1);
  });
});
