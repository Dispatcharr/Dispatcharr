import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import useEPGsStore from '../epgs';
import api from '../../api';

// Mock the api module
vi.mock('../../api');

describe('useEPGsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Reset store state between tests
    useEPGsStore.setState({
      epgs: {},
      tvgs: [],
      tvgsById: {},
      tvgsLoaded: false,
      isLoading: false,
      error: null,
      refreshProgress: {},
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('should initialize with default values', () => {
      const { result } = renderHook(() => useEPGsStore());

      expect(result.current.epgs).toEqual({});
      expect(result.current.tvgs).toEqual([]);
      expect(result.current.tvgsById).toEqual({});
      expect(result.current.tvgsLoaded).toBe(false);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.refreshProgress).toEqual({});
    });
  });

  describe('fetchEPGs', () => {
    it('should fetch and store EPGs successfully', async () => {
      const mockEPGs = [
        { id: 'epg1', name: 'EPG 1', status: 'idle' },
        { id: 'epg2', name: 'EPG 2', status: 'success' },
      ];

      api.getEPGs.mockResolvedValue(mockEPGs);

      const { result } = renderHook(() => useEPGsStore());

      await act(async () => {
        await result.current.fetchEPGs();
      });

      expect(result.current.epgs).toEqual({
        epg1: { id: 'epg1', name: 'EPG 1', status: 'idle' },
        epg2: { id: 'epg2', name: 'EPG 2', status: 'success' },
      });
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(api.getEPGs).toHaveBeenCalledTimes(1);
    });

    it('should set loading state while fetching', async () => {
      api.getEPGs.mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve([]), 100))
      );

      const { result } = renderHook(() => useEPGsStore());

      const fetchPromise = act(async () => {
        await result.current.fetchEPGs();
      });

      // Check loading state immediately after calling
      await waitFor(() => {
        expect(result.current.isLoading).toBe(true);
      });

      await fetchPromise;

      expect(result.current.isLoading).toBe(false);
    });

    it('should handle fetch error', async () => {
      const mockError = new Error('Network error');
      api.getEPGs.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useEPGsStore());

      await act(async () => {
        await result.current.fetchEPGs();
      });

      expect(result.current.error).toBe('Failed to load epgs.');
      expect(result.current.isLoading).toBe(false);
      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to fetch epgs:',
        mockError
      );

      consoleSpy.mockRestore();
    });

    it('should handle empty EPGs array', async () => {
      api.getEPGs.mockResolvedValue([]);

      const { result } = renderHook(() => useEPGsStore());

      await act(async () => {
        await result.current.fetchEPGs();
      });

      expect(result.current.epgs).toEqual({});
      expect(result.current.isLoading).toBe(false);
    });
  });

  describe('fetchEPGData', () => {
    it('should fetch and store TVG data successfully', async () => {
      const mockTVGs = [
        { id: 'tvg1', name: 'TVG 1' },
        { id: 'tvg2', name: 'TVG 2' },
      ];

      api.getEPGData.mockResolvedValue(mockTVGs);

      const { result } = renderHook(() => useEPGsStore());

      await act(async () => {
        await result.current.fetchEPGData();
      });

      expect(result.current.tvgs).toEqual(mockTVGs);
      expect(result.current.tvgsById).toEqual({
        tvg1: { id: 'tvg1', name: 'TVG 1' },
        tvg2: { id: 'tvg2', name: 'TVG 2' },
      });
      expect(result.current.tvgsLoaded).toBe(true);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(api.getEPGData).toHaveBeenCalledTimes(1);
    });

    it('should set loading state while fetching', async () => {
      api.getEPGData.mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve([]), 100))
      );

      const { result } = renderHook(() => useEPGsStore());

      const fetchPromise = act(async () => {
        await result.current.fetchEPGData();
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(true);
      });

      await fetchPromise;

      expect(result.current.isLoading).toBe(false);
    });

    it('should handle fetch error', async () => {
      const mockError = new Error('API error');
      api.getEPGData.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useEPGsStore());

      await act(async () => {
        await result.current.fetchEPGData();
      });

      expect(result.current.error).toBe('Failed to load tvgs.');
      expect(result.current.tvgsLoaded).toBe(true);
      expect(result.current.isLoading).toBe(false);
      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to fetch tvgs:',
        mockError
      );

      consoleSpy.mockRestore();
    });

    it('should handle empty TVG array', async () => {
      api.getEPGData.mockResolvedValue([]);

      const { result } = renderHook(() => useEPGsStore());

      await act(async () => {
        await result.current.fetchEPGData();
      });

      expect(result.current.tvgs).toEqual([]);
      expect(result.current.tvgsById).toEqual({});
      expect(result.current.tvgsLoaded).toBe(true);
    });
  });

  describe('addEPG', () => {
    it('should add new EPG to store', () => {
      const { result } = renderHook(() => useEPGsStore());

      const newEPG = { id: 'epg1', name: 'New EPG', status: 'idle' };

      act(() => {
        result.current.addEPG(newEPG);
      });

      expect(result.current.epgs).toEqual({
        epg1: newEPG,
      });
    });

    it('should add multiple EPGs', () => {
      const { result } = renderHook(() => useEPGsStore());

      const epg1 = { id: 'epg1', name: 'EPG 1', status: 'idle' };
      const epg2 = { id: 'epg2', name: 'EPG 2', status: 'success' };

      act(() => {
        result.current.addEPG(epg1);
        result.current.addEPG(epg2);
      });

      expect(result.current.epgs).toEqual({
        epg1,
        epg2,
      });
    });

    it('should not overwrite existing EPGs', () => {
      const { result } = renderHook(() => useEPGsStore());

      const originalEPG = { id: 'epg1', name: 'Original', status: 'idle' };
      const newEPG = { id: 'epg2', name: 'New', status: 'success' };

      act(() => {
        result.current.addEPG(originalEPG);
        result.current.addEPG(newEPG);
      });

      expect(result.current.epgs).toEqual({
        epg1: originalEPG,
        epg2: newEPG,
      });
    });
  });

  describe('updateEPG', () => {
    it('should update existing EPG', () => {
      const { result } = renderHook(() => useEPGsStore());

      const originalEPG = { id: 'epg1', name: 'Original', status: 'idle' };
      const updatedEPG = { id: 'epg1', name: 'Updated', status: 'success' };

      act(() => {
        result.current.addEPG(originalEPG);
      });

      act(() => {
        result.current.updateEPG(updatedEPG);
      });

      expect(result.current.epgs.epg1).toEqual(updatedEPG);
    });

    it('should add EPG if it does not exist', () => {
      const { result } = renderHook(() => useEPGsStore());

      const newEPG = { id: 'epg1', name: 'New', status: 'idle' };

      act(() => {
        result.current.updateEPG(newEPG);
      });

      expect(result.current.epgs.epg1).toEqual(newEPG);
    });

    it('should not update state when called with invalid epg (null)', () => {
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useEPGsStore());

      const initialEPGs = { epg1: { id: 'epg1', name: 'Test' } };
      act(() => {
        useEPGsStore.setState({ epgs: initialEPGs });
      });

      act(() => {
        result.current.updateEPG(null);
      });

      expect(result.current.epgs).toEqual(initialEPGs);
      expect(consoleSpy).toHaveBeenCalledWith(
        'updateEPG called with invalid epg:',
        null
      );

      consoleSpy.mockRestore();
    });

    it('should not update state when called with invalid epg (missing id)', () => {
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useEPGsStore());

      const initialEPGs = { epg1: { id: 'epg1', name: 'Test' } };
      act(() => {
        useEPGsStore.setState({ epgs: initialEPGs });
      });

      const invalidEPG = { name: 'No ID' };

      act(() => {
        result.current.updateEPG(invalidEPG);
      });

      expect(result.current.epgs).toEqual(initialEPGs);
      expect(consoleSpy).toHaveBeenCalledWith(
        'updateEPG called with invalid epg:',
        invalidEPG
      );

      consoleSpy.mockRestore();
    });

    it('should not update state when called with invalid epg (non-object)', () => {
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useEPGsStore());

      const initialEPGs = { epg1: { id: 'epg1', name: 'Test' } };
      act(() => {
        useEPGsStore.setState({ epgs: initialEPGs });
      });

      act(() => {
        result.current.updateEPG('invalid');
      });

      expect(result.current.epgs).toEqual(initialEPGs);
      expect(consoleSpy).toHaveBeenCalledWith(
        'updateEPG called with invalid epg:',
        'invalid'
      );

      consoleSpy.mockRestore();
    });
  });

  describe('removeEPGs', () => {
    it('should remove single EPG', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        useEPGsStore.setState({
          epgs: {
            epg1: { id: 'epg1', name: 'EPG 1' },
            epg2: { id: 'epg2', name: 'EPG 2' },
          },
        });
      });

      act(() => {
        result.current.removeEPGs(['epg1']);
      });

      expect(result.current.epgs).toEqual({
        epg2: { id: 'epg2', name: 'EPG 2' },
      });
    });

    it('should remove multiple EPGs', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        useEPGsStore.setState({
          epgs: {
            epg1: { id: 'epg1', name: 'EPG 1' },
            epg2: { id: 'epg2', name: 'EPG 2' },
            epg3: { id: 'epg3', name: 'EPG 3' },
          },
        });
      });

      act(() => {
        result.current.removeEPGs(['epg1', 'epg3']);
      });

      expect(result.current.epgs).toEqual({
        epg2: { id: 'epg2', name: 'EPG 2' },
      });
    });

    it('should handle removing non-existent EPG', () => {
      const { result } = renderHook(() => useEPGsStore());

      const initialEPGs = {
        epg1: { id: 'epg1', name: 'EPG 1' },
      };

      act(() => {
        useEPGsStore.setState({ epgs: initialEPGs });
      });

      act(() => {
        result.current.removeEPGs(['nonexistent']);
      });

      expect(result.current.epgs).toEqual(initialEPGs);
    });

    it('should handle empty array', () => {
      const { result } = renderHook(() => useEPGsStore());

      const initialEPGs = {
        epg1: { id: 'epg1', name: 'EPG 1' },
      };

      act(() => {
        useEPGsStore.setState({ epgs: initialEPGs });
      });

      act(() => {
        result.current.removeEPGs([]);
      });

      expect(result.current.epgs).toEqual(initialEPGs);
    });
  });

  describe('updateEPGProgress', () => {
    beforeEach(() => {
      act(() => {
        useEPGsStore.setState({
          epgs: {
            source1: { id: 'source1', status: 'idle', last_message: '' },
          },
        });
      });
    });

    it('should update progress for downloading action', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          action: 'downloading',
          progress: 50,
          speed: '1.5 MB/s',
          elapsed_time: '00:00:30',
          time_remaining: '00:00:30',
        });
      });

      expect(result.current.refreshProgress.source1).toEqual({
        action: 'downloading',
        progress: 50,
        speed: '1.5 MB/s',
        elapsed_time: '00:00:30',
        time_remaining: '00:00:30',
        status: 'in_progress',
      });
      expect(result.current.epgs.source1.status).toBe('fetching');
    });

    it('should update progress for parsing_channels action', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          action: 'parsing_channels',
          progress: 75,
        });
      });

      expect(result.current.epgs.source1.status).toBe('parsing');
    });

    it('should update progress for parsing_programs action', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          action: 'parsing_programs',
          progress: 90,
        });
      });

      expect(result.current.epgs.source1.status).toBe('parsing');
    });

    it('should set status to success when progress is 100', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          action: 'success',
          progress: 100,
        });
      });

      expect(result.current.epgs.source1.status).toBe('success');
    });

    it('should use explicit status from data', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          status: 'error',
          progress: 50,
        });
      });

      expect(result.current.epgs.source1.status).toBe('error');
      expect(result.current.refreshProgress.source1.status).toBe('error');
    });

    it('should set last_message on error status', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          status: 'error',
          error: 'Connection failed',
        });
      });

      expect(result.current.epgs.source1.last_message).toBe(
        'Connection failed'
      );
    });

    it('should use default error message if error is not provided', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          status: 'error',
        });
      });

      expect(result.current.epgs.source1.last_message).toBe('Unknown error');
    });

    it('should not update state when called with invalid data (null)', () => {
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useEPGsStore());

      const initialEPGs = { ...result.current.epgs };
      const initialProgress = { ...result.current.refreshProgress };

      act(() => {
        result.current.updateEPGProgress(null);
      });

      expect(result.current.epgs).toEqual(initialEPGs);
      expect(result.current.refreshProgress).toEqual(initialProgress);
      expect(consoleSpy).toHaveBeenCalledWith(
        'updateEPGProgress called with invalid data:',
        null
      );

      consoleSpy.mockRestore();
    });

    it('should not update state when called with invalid data (missing source)', () => {
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useEPGsStore());

      const initialEPGs = { ...result.current.epgs };
      const initialProgress = { ...result.current.refreshProgress };

      act(() => {
        result.current.updateEPGProgress({ progress: 50 });
      });

      expect(result.current.epgs).toEqual(initialEPGs);
      expect(result.current.refreshProgress).toEqual(initialProgress);
      expect(consoleSpy).toHaveBeenCalledWith(
        'updateEPGProgress called with invalid data:',
        { progress: 50 }
      );

      consoleSpy.mockRestore();
    });

    it('should not update state when source does not exist and no status', () => {
      const { result } = renderHook(() => useEPGsStore());

      const initialEPGs = { ...result.current.epgs };
      const initialProgress = { ...result.current.refreshProgress };

      act(() => {
        result.current.updateEPGProgress({
          source: 'nonexistent',
          progress: 50,
        });
      });

      expect(result.current.epgs).toEqual(initialEPGs);
      expect(result.current.refreshProgress).toEqual(initialProgress);
    });

    it('should update refreshProgress even when source does not exist but status is provided', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        result.current.updateEPGProgress({
          source: 'newSource',
          status: 'success',
          progress: 100,
        });
      });

      expect(result.current.refreshProgress.newSource).toEqual({
        action: undefined,
        progress: 100,
        speed: undefined,
        elapsed_time: undefined,
        time_remaining: undefined,
        status: 'success',
      });
    });

    it('should not update EPG if status and last_message have not changed', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        useEPGsStore.setState({
          epgs: {
            source1: { id: 'source1', status: 'fetching', last_message: '' },
          },
        });
      });

      const epgsBeforeUpdate = result.current.epgs;

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          action: 'downloading',
          progress: 25,
        });
      });

      // EPGs object should be the same reference (not updated)
      expect(result.current.epgs).toBe(epgsBeforeUpdate);
      // But refreshProgress should be updated
      expect(result.current.refreshProgress.source1.progress).toBe(25);
    });

    it('should update EPG if status changed', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        useEPGsStore.setState({
          epgs: {
            source1: { id: 'source1', status: 'idle', last_message: '' },
          },
        });
      });

      const epgsBeforeUpdate = result.current.epgs;

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          action: 'downloading',
          progress: 25,
        });
      });

      // EPGs object should be different (updated) because status changed from 'idle' to 'fetching'
      expect(result.current.epgs).not.toBe(epgsBeforeUpdate);
      expect(result.current.epgs.source1.status).toBe('fetching');
    });

    it('should preserve current EPG status when no status change is detected', () => {
      const { result } = renderHook(() => useEPGsStore());

      act(() => {
        useEPGsStore.setState({
          epgs: {
            source1: {
              id: 'source1',
              status: 'parsing',
              last_message: 'Processing',
            },
          },
        });
      });

      act(() => {
        result.current.updateEPGProgress({
          source: 'source1',
          action: 'parsing_programs',
          progress: 85,
        });
      });

      expect(result.current.epgs.source1.status).toBe('parsing');
      expect(result.current.epgs.source1.last_message).toBe('Processing');
    });
  });
});
