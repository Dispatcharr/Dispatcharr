import { act, renderHook } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useProviderDetailsPolling from '../useProviderDetailsPolling.jsx';

afterEach(() => vi.useRealTimers());
describe('Provider detail polling', () => {
  it('stops bounded polling with a visible retry state instead of loading forever', async () => {
    vi.useFakeTimers();
    const load = vi.fn(async () => ({
      name: 'Imported',
      refresh_status: 'pending',
    }));
    const view = renderHook(() => {
      const [details, onResult] = useState({ refresh_status: 'pending' });
      const controls = useProviderDetailsPolling({
        opened: true,
        id: 1,
        relationId: 2,
        details,
        load,
        onResult,
      });
      return { details, ...controls };
    });
    for (let i = 0; i < 40; i += 1)
      await act(async () => vi.advanceTimersByTimeAsync(1500));
    expect(view.result.current.details).toEqual({
      name: 'Imported',
      refresh_status: 'failed',
    });
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(load).toHaveBeenCalledTimes(40);
  });
  it('retries failed details explicitly and ignores a retry after closing', async () => {
    let finish;
    const load = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const onResult = vi.fn();
    const props = {
      opened: true,
      id: 1,
      relationId: 2,
      details: { refresh_status: 'failed' },
      load,
      onResult,
    };
    const view = renderHook((p) => useProviderDetailsPolling(p), {
      initialProps: props,
    });
    let retry;
    act(() => {
      retry = view.result.current.retry();
    });
    expect(load).toHaveBeenCalledWith(1, 2, {
      background: true,
      forceRefresh: true,
    });
    expect(view.result.current.retrying).toBe(true);
    view.rerender({ ...props, opened: false });
    await act(async () => {
      finish({ refresh_status: 'pending' });
      await retry;
    });
    expect(onResult).not.toHaveBeenCalled();
    expect(view.result.current.retrying).toBe(false);
  });
  it('keeps imported data immediately available and stops when closed', async () => {
    vi.useFakeTimers();
    const load = vi
      .fn()
      .mockResolvedValue({ refresh_status: 'completed', name: 'Details' });
    const onResult = vi.fn();
    const props = {
      opened: true,
      id: 1,
      relationId: 2,
      details: { refresh_status: 'pending' },
      load,
      onResult,
    };
    const view = renderHook((p) => useProviderDetailsPolling(p), {
      initialProps: props,
    });
    expect(load).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    expect(load).toHaveBeenCalledWith(1, 2, { background: true });
    expect(onResult).toHaveBeenCalledWith({
      refresh_status: 'completed',
      name: 'Details',
    });
    view.rerender({ ...props, opened: false });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(load).toHaveBeenCalledTimes(1);
  });
  it('does not publish stale results after a source change', async () => {
    vi.useFakeTimers();
    let finish;
    const load = vi.fn().mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const onResult = vi.fn();
    const props = {
      opened: true,
      id: 1,
      relationId: 2,
      details: { refresh_status: 'pending' },
      load,
      onResult,
    };
    const view = renderHook((p) => useProviderDetailsPolling(p), {
      initialProps: props,
    });
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    view.rerender({ ...props, relationId: 3, details: null });
    await act(async () => finish({ name: 'Old source' }));
    expect(onResult).not.toHaveBeenCalled();
  });
});
