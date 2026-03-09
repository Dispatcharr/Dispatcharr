/**
 * Tests for the EPG preview fetch logic used in Channel.jsx.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

vi.mock('../../../api', () => ({
  default: {
    getCurrentProgramForEpg: vi.fn(),
  },
}));

import API from '../../../api';
import { useEpgPreview } from '../Channel';

describe('Channel EPG preview hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not call API when epg_data_id is empty', () => {
    const { result } = renderHook(() => useEpgPreview(''));
    expect(API.getCurrentProgramForEpg).not.toHaveBeenCalled();
    expect(result.current.isLoadingProgram).toBe(false);
    expect(result.current.hasFetchedProgram).toBe(false);
    expect(result.current.currentProgram).toBeNull();
  });

  it('does not call API when epg_data_id is "0"', () => {
    renderHook(() => useEpgPreview('0'));
    expect(API.getCurrentProgramForEpg).not.toHaveBeenCalled();
  });

  it('calls API when epg_data_id is set', async () => {
    const program = { title: 'Live News', epg_data_id: 10 };
    API.getCurrentProgramForEpg.mockResolvedValue(program);

    const { result } = renderHook(() => useEpgPreview(10));

    await waitFor(() => {
      expect(API.getCurrentProgramForEpg).toHaveBeenCalledWith(10);
      expect(result.current.currentProgram).toEqual(program);
      expect(result.current.isLoadingProgram).toBe(false);
      expect(result.current.hasFetchedProgram).toBe(true);
    });
  });

  it('shows loading state while API call is in flight', () => {
    API.getCurrentProgramForEpg.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useEpgPreview(10));

    expect(result.current.isLoadingProgram).toBe(true);
    expect(result.current.hasFetchedProgram).toBe(false);
  });

  it('shows null program after successful fetch with null response', async () => {
    API.getCurrentProgramForEpg.mockResolvedValue(null);

    const { result } = renderHook(() => useEpgPreview(10));

    await waitFor(() => {
      expect(result.current.currentProgram).toBeNull();
      expect(result.current.hasFetchedProgram).toBe(true);
    });
  });

  it('retries when response has parsing=true', async () => {
    vi.useFakeTimers();

    let callCount = 0;
    API.getCurrentProgramForEpg.mockImplementation(() => {
      callCount++;
      if (callCount === 1) return Promise.resolve({ parsing: true });
      return Promise.resolve({ title: 'Parsed Show', epg_data_id: 10 });
    });

    const { result } = renderHook(() => useEpgPreview(10));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(callCount).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });

    expect(callCount).toBe(2);
    expect(result.current.currentProgram).toEqual({
      title: 'Parsed Show',
      epg_data_id: 10,
    });
    expect(result.current.isLoadingProgram).toBe(false);
    expect(result.current.hasFetchedProgram).toBe(true);
  });

  it('retries on API error and eventually gives up', async () => {
    vi.useFakeTimers();
    vi.spyOn(console, 'error').mockImplementation(() => {});

    // Fail twice, then succeed
    let callCount = 0;
    API.getCurrentProgramForEpg.mockImplementation(() => {
      callCount++;
      if (callCount <= 2) return Promise.reject(new Error('Network error'));
      return Promise.resolve({ title: 'Recovered Show', epg_data_id: 10 });
    });

    const { result } = renderHook(() => useEpgPreview(10));

    // First call fails immediately
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(callCount).toBe(1);

    // Advance past first retry delay (3s)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(callCount).toBe(2);

    // Advance past second retry delay (4.5s)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4600);
    });
    expect(callCount).toBe(3);
    expect(result.current.currentProgram).toEqual({
      title: 'Recovered Show',
      epg_data_id: 10,
    });
    expect(result.current.isLoadingProgram).toBe(false);
    expect(result.current.hasFetchedProgram).toBe(true);
  });

  it('sets null program after exhausting all retries on error', async () => {
    vi.useFakeTimers();
    vi.spyOn(console, 'error').mockImplementation(() => {});

    API.getCurrentProgramForEpg.mockRejectedValue(new Error('Persistent error'));

    const { result } = renderHook(() => useEpgPreview(10));

    // Advance through all 6 attempts (0..5) with increasing delays:
    // 3s, 4.5s, 6.75s, 10.125s, 15s (capped)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0); // attempt 0
    });
    for (const delay of [3000, 4500, 6750, 10125, 15000]) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(delay + 100);
      });
    }

    expect(result.current.currentProgram).toBeNull();
    expect(result.current.isLoadingProgram).toBe(false);
    expect(result.current.hasFetchedProgram).toBe(true);
  });

  it('cancels fetch on unmount (no state update after unmount)', async () => {
    let resolvePromise;
    API.getCurrentProgramForEpg.mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve;
      })
    );

    const { unmount, result } = renderHook(() => useEpgPreview(10));

    expect(result.current.isLoadingProgram).toBe(true);

    unmount();

    await act(async () => {
      resolvePromise({ title: 'Late Show', epg_data_id: 10 });
    });
  });

  it('changing epg_data_id cancels previous fetch and starts new one', async () => {
    let resolve1;
    const promise1 = new Promise((r) => {
      resolve1 = r;
    });

    API.getCurrentProgramForEpg
      .mockReturnValueOnce(promise1)
      .mockResolvedValueOnce({ title: 'New Show', epg_data_id: 20 });

    const { result, rerender } = renderHook(({ id }) => useEpgPreview(id), {
      initialProps: { id: 10 },
    });

    expect(result.current.isLoadingProgram).toBe(true);

    rerender({ id: 20 });

    await waitFor(() => {
      expect(result.current.currentProgram).toEqual({
        title: 'New Show',
        epg_data_id: 20,
      });
    });

    await act(async () => {
      resolve1({ title: 'Old Show', epg_data_id: 10 });
    });

    expect(result.current.currentProgram).toEqual({
      title: 'New Show',
      epg_data_id: 20,
    });
  });
});
