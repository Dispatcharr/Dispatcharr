import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../api', () => ({
  default: {
    getCurrentProgramForEpg: vi.fn(),
  },
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import API from '../../api';
import { useEpgPreview } from '../useEpgPreview';

// ──────────────────────────────────────────────────────────────────────────────

describe('useEpgPreview', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ── Invalid / empty epgDataId ──────────────────────────────────────────────

  describe('invalid epgDataId', () => {
    it.each([null, undefined, '', '0'])(
      'returns defaults and skips the API call when epgDataId is %s',
      async (id) => {
        const { result } = renderHook(() => useEpgPreview(id));

        await act(async () => {
          await vi.runAllTimersAsync();
        });

        expect(result.current.currentProgram).toBe(null);
        expect(result.current.isLoadingProgram).toBe(false);
        expect(result.current.hasFetchedProgram).toBe(false);
        expect(API.getCurrentProgramForEpg).not.toHaveBeenCalled();
      }
    );
  });

  // ── Initial state ──────────────────────────────────────────────────────────

  describe('initial state with a valid epgDataId', () => {
    it('sets isLoadingProgram true and hasFetchedProgram false immediately', () => {
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue(null);
      const { result } = renderHook(() => useEpgPreview('epg-1'));

      expect(result.current.isLoadingProgram).toBe(true);
      expect(result.current.hasFetchedProgram).toBe(false);
      expect(result.current.currentProgram).toBe(null);
    });
  });

  // ── Successful fetch ───────────────────────────────────────────────────────

  describe('successful fetch', () => {
    it('calls the API with the provided epgDataId', async () => {
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue({ id: 1 });
      renderHook(() => useEpgPreview('epg-42'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(API.getCurrentProgramForEpg).toHaveBeenCalledWith('epg-42');
    });

    it('sets currentProgram to the returned program', async () => {
      const program = { id: 7, title: 'News at Six', channel: 'BBC' };
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue(program);
      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.currentProgram).toEqual(program);
    });

    it('sets isLoadingProgram to false after a successful fetch', async () => {
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue({ id: 1 });
      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.isLoadingProgram).toBe(false);
    });

    it('sets hasFetchedProgram to true after a successful fetch', async () => {
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue({ id: 1 });
      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.hasFetchedProgram).toBe(true);
    });

    it('sets currentProgram to null and completes when API returns null', async () => {
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue(null);
      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.currentProgram).toBe(null);
      expect(result.current.isLoadingProgram).toBe(false);
      expect(result.current.hasFetchedProgram).toBe(true);
    });
  });

  // ── Parsing retry ──────────────────────────────────────────────────────────

  describe('parsing retry', () => {
    it('retries after a delay when program.parsing is true', async () => {
      const parsingProgram = { id: 1, parsing: true };
      const readyProgram = { id: 1, title: 'News', parsing: false };

      vi.mocked(API.getCurrentProgramForEpg)
        .mockResolvedValueOnce(parsingProgram)
        .mockResolvedValueOnce(readyProgram);

      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(API.getCurrentProgramForEpg).toHaveBeenCalledTimes(2);
      expect(result.current.currentProgram).toEqual(readyProgram);
      expect(result.current.hasFetchedProgram).toBe(true);
      expect(result.current.isLoadingProgram).toBe(false);
    });

    it('does not set a still-parsing program as currentProgram', async () => {
      const parsingProgram = { id: 1, parsing: true };
      const readyProgram = { id: 1, title: 'Ready', parsing: false };

      vi.mocked(API.getCurrentProgramForEpg)
        .mockResolvedValueOnce(parsingProgram)
        .mockResolvedValueOnce(readyProgram);

      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.currentProgram).toEqual(readyProgram);
      expect(result.current.currentProgram?.parsing).toBeFalsy();
    });

    it('resolves to null after all retries are exhausted with parsing: true', async () => {
      // Always returns parsing: true — the hook will exhaust retries/deadline
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue({
        id: 1,
        parsing: true,
      });

      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.currentProgram).toBe(null);
      expect(result.current.isLoadingProgram).toBe(false);
      expect(result.current.hasFetchedProgram).toBe(true);
    });
  });

  // ── Error handling ─────────────────────────────────────────────────────────

  describe('error handling', () => {
    it('retries after an API error and sets currentProgram on the next success', async () => {
      const program = { id: 1, title: 'News' };
      vi.mocked(API.getCurrentProgramForEpg)
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce(program);

      vi.spyOn(console, 'error').mockImplementation(() => {});

      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(API.getCurrentProgramForEpg).toHaveBeenCalledTimes(2);
      expect(result.current.currentProgram).toEqual(program);
      expect(result.current.hasFetchedProgram).toBe(true);
    });

    it('resolves to null after all retries are exhausted by persistent errors', async () => {
      vi.mocked(API.getCurrentProgramForEpg).mockRejectedValue(
        new Error('Persistent error')
      );
      vi.spyOn(console, 'error').mockImplementation(() => {});

      const { result } = renderHook(() => useEpgPreview('epg-1'));

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.currentProgram).toBe(null);
      expect(result.current.isLoadingProgram).toBe(false);
      expect(result.current.hasFetchedProgram).toBe(true);
    });
  });

  // ── epgDataId changes ──────────────────────────────────────────────────────

  describe('epgDataId changes', () => {
    it('resets to defaults when epgDataId changes to null', async () => {
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue({
        id: 1,
        title: 'News',
      });

      const { result, rerender } = renderHook(({ id }) => useEpgPreview(id), {
        initialProps: { id: 'epg-1' },
      });

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.currentProgram).not.toBe(null);

      rerender({ id: null });

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.currentProgram).toBe(null);
      expect(result.current.isLoadingProgram).toBe(false);
      expect(result.current.hasFetchedProgram).toBe(false);
    });

    it('resets to defaults when epgDataId changes to "0"', async () => {
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue({
        id: 1,
        title: 'News',
      });

      const { result, rerender } = renderHook(({ id }) => useEpgPreview(id), {
        initialProps: { id: 'epg-1' },
      });

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      rerender({ id: '0' });

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.currentProgram).toBe(null);
      expect(result.current.isLoadingProgram).toBe(false);
      expect(result.current.hasFetchedProgram).toBe(false);
    });

    it('fetches with the new epgDataId when it changes to another valid value', async () => {
      vi.mocked(API.getCurrentProgramForEpg).mockResolvedValue({ id: 1 });

      const { rerender } = renderHook(({ id }) => useEpgPreview(id), {
        initialProps: { id: 'epg-1' },
      });

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      rerender({ id: 'epg-2' });

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(API.getCurrentProgramForEpg).toHaveBeenCalledWith('epg-1');
      expect(API.getCurrentProgramForEpg).toHaveBeenCalledWith('epg-2');
    });
  });

  // ── Cleanup on unmount ─────────────────────────────────────────────────────

  describe('cleanup on unmount', () => {
    it('does not update currentProgram after unmount', async () => {
      let resolveProgram;
      vi.mocked(API.getCurrentProgramForEpg).mockReturnValue(
        new Promise((resolve) => {
          resolveProgram = resolve;
        })
      );

      const { result, unmount } = renderHook(() => useEpgPreview('epg-1'));

      // Unmount before the API call resolves
      unmount();

      // Resolve the pending request
      await act(async () => {
        resolveProgram({ id: 1, title: 'Late News' });
        await vi.runAllTimersAsync();
      });

      // currentProgram should remain null — the cancelled flag prevented the update
      expect(result.current.currentProgram).toBe(null);
    });
  });
});
