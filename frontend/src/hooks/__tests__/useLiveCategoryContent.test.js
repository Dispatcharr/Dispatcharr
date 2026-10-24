import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import API from '../../api.js';
import useLiveCategoryContent from '../useLiveCategoryContent.js';

vi.mock('../../api.js', () => ({
  default: {
    getM3UGroupContent: vi.fn(),
    loadM3UGroupContent: vi.fn(),
    refreshLivePlaylist: vi.fn(),
  },
}));

const account = { id: 7, account_type: 'XC', updated_at: 'saved-refresh' };
const missing = {
  count: 0,
  content_source: 'imported',
  can_load_provider: true,
};
const preview = { count: 238, content_source: 'provider' };

beforeEach(() => {
  vi.clearAllMocks();
  API.getM3UGroupContent.mockResolvedValue(missing);
  API.loadM3UGroupContent.mockResolvedValue(preview);
});

describe('session-local Live category content', () => {
  it('loads one missing XC category without importing or starting a refresh', async () => {
    const { result } = renderHook(() => useLiveCategoryContent(account));
    await act(() => result.current.ensure(12));
    expect(API.getM3UGroupContent).toHaveBeenCalledExactlyOnceWith(
      7,
      'live',
      12,
      1,
      50,
      ''
    );
    expect(API.loadM3UGroupContent).toHaveBeenCalledExactlyOnceWith(
      7,
      'live',
      12
    );
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
    expect(result.current.summaries[result.current.keyFor(12)]).toMatchObject({
      count: 238,
      source: 'provider',
      loading: false,
    });
  });

  it('shares an in-flight request and then reuses its summary', async () => {
    let resolve;
    API.getM3UGroupContent.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      })
    );
    const { result } = renderHook(() => useLiveCategoryContent(account));
    let first, second;
    act(() => {
      first = result.current.ensure(12);
      second = result.current.ensure(12);
    });
    expect(first).toBe(second);
    await waitFor(() => expect(API.getM3UGroupContent).toHaveBeenCalledOnce());
    await act(async () => {
      resolve(missing);
      await first;
    });
    await act(() => result.current.ensure(12));
    expect(API.getM3UGroupContent).toHaveBeenCalledOnce();
    expect(API.loadM3UGroupContent).toHaveBeenCalledOnce();
  });

  it('uses a previously opened preview immediately without another request', async () => {
    const { result } = renderHook(() => useLiveCategoryContent(account));
    act(() => result.current.remember(12, preview));
    await act(() => result.current.ensure(12));
    expect(API.getM3UGroupContent).not.toHaveBeenCalled();
    expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
    expect(result.current.summaries[result.current.keyFor(12)].count).toBe(238);
  });

  it.each(['STD', undefined])(
    'never starts a playlist fetch for account type %s',
    async (account_type) => {
      const { result } = renderHook(() =>
        useLiveCategoryContent({ ...account, account_type })
      );
      await act(() => result.current.ensure(12));
      expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
      expect(result.current.summaries[result.current.keyFor(12)]).toMatchObject(
        { count: 0, source: 'imported' }
      );
    }
  );

  it.each([
    { count: 42, content_source: 'imported' },
    { count: 0, content_source: 'provider' },
  ])('does not fetch a provider for known content %j', async (content) => {
    API.getM3UGroupContent.mockResolvedValue(content);
    const { result } = renderHook(() => useLiveCategoryContent(account));
    await act(() => result.current.ensure(12));
    await act(() => result.current.ensure(12));
    expect(API.getM3UGroupContent).toHaveBeenCalledOnce();
    expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
  });

  it('clears a failed request so Retry can succeed', async () => {
    API.getM3UGroupContent.mockRejectedValueOnce(
      new Error('synthetic failure')
    );
    const { result } = renderHook(() => useLiveCategoryContent(account));
    await act(async () => {
      await expect(result.current.ensure(12)).rejects.toThrow(
        'synthetic failure'
      );
    });
    expect(result.current.summaries[result.current.keyFor(12)].error).toMatch(
      /Retry/
    );
    await act(() => result.current.ensure(12, true));
    expect(result.current.summaries[result.current.keyFor(12)]).toMatchObject({
      error: null,
      count: 238,
    });
    expect(API.getM3UGroupContent).toHaveBeenCalledTimes(2);
  });

  it('keeps accounts and refresh snapshots separate', async () => {
    const { result, rerender } = renderHook(
      (playlist) => useLiveCategoryContent(playlist),
      { initialProps: account }
    );
    await act(() => result.current.ensure(12));
    rerender({ ...account, id: 8 });
    await act(() => result.current.ensure(12));
    rerender({ ...account, updated_at: 'new-refresh' });
    await act(() => result.current.ensure(12));
    expect(API.getM3UGroupContent).toHaveBeenCalledTimes(3);
  });
});
