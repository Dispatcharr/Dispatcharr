import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useLogoSelection, useChannelLogoSelection, useLogosById } from '../useSmartLogos';
import useLogosStore from '../../store/logos';

// Mock the logos store
vi.mock('../../store/logos');

describe('useSmartLogos', () => {
  describe('useLogoSelection', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('should initialize with empty state', () => {
      useLogosStore.mockImplementation((selector) => selector({
        logos: {},
        fetchLogos: vi.fn(),
      }));

      const { result } = renderHook(() => useLogoSelection());

      expect(result.current.logos).toEqual({});
      expect(result.current.isLoading).toBe(false);
      expect(result.current.hasLogos).toBe(false);
    });

    it('should load logos when ensureLogosLoaded is called', async () => {
      const mockFetchLogos = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        logos: {},
        fetchLogos: mockFetchLogos,
      }));

      const { result } = renderHook(() => useLogoSelection());

      await act(async () => {
        await result.current.ensureLogosLoaded();
      });

      expect(mockFetchLogos).toHaveBeenCalledTimes(1);
    });

    it('should not reload logos if already loaded', async () => {
      const mockFetchLogos = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        logos: { logo1: { id: 'logo1' } },
        fetchLogos: mockFetchLogos,
      }));

      const { result } = renderHook(() => useLogoSelection());

      await act(async () => {
        await result.current.ensureLogosLoaded();
      });

      await act(async () => {
        await result.current.ensureLogosLoaded();
      });

      expect(mockFetchLogos).toHaveBeenCalledTimes(1);
    });

    it('should handle errors when fetching logos', async () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const mockFetchLogos = vi.fn().mockRejectedValue(new Error('Fetch failed'));
      useLogosStore.mockImplementation((selector) => selector({
        logos: {},
        fetchLogos: mockFetchLogos,
      }));

      const { result } = renderHook(() => useLogoSelection());

      await act(async () => {
        await result.current.ensureLogosLoaded();
      });

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Failed to load logos for selection:',
        expect.any(Error)
      );

      consoleErrorSpy.mockRestore();
    });

    it('should indicate hasLogos when logos are present', () => {
      useLogosStore.mockImplementation((selector) => selector({
        logos: { logo1: { id: 'logo1' }, logo2: { id: 'logo2' } },
        fetchLogos: vi.fn(),
      }));

      const { result } = renderHook(() => useLogoSelection());

      expect(result.current.hasLogos).toBe(true);
    });
  });

  describe('useChannelLogoSelection', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('should initialize with channel logos state', () => {
      useLogosStore.mockImplementation((selector) => selector({
        channelLogos: {},
        hasLoadedChannelLogos: false,
        backgroundLoading: false,
        fetchChannelAssignableLogos: vi.fn(),
      }));

      const { result } = renderHook(() => useChannelLogoSelection());

      expect(result.current.logos).toEqual({});
      expect(result.current.isLoading).toBe(false);
      expect(result.current.hasLogos).toBe(false);
    });

    it('should load channel logos when ensureLogosLoaded is called', async () => {
      const mockFetchChannelLogos = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        channelLogos: {},
        hasLoadedChannelLogos: false,
        backgroundLoading: false,
        fetchChannelAssignableLogos: mockFetchChannelLogos,
      }));

      const { result } = renderHook(() => useChannelLogoSelection());

      await act(async () => {
        await result.current.ensureLogosLoaded();
      });

      expect(mockFetchChannelLogos).toHaveBeenCalledTimes(1);
    });

    it('should not reload if already loaded', async () => {
      const mockFetchChannelLogos = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        channelLogos: { logo1: { id: 'logo1' } },
        hasLoadedChannelLogos: true,
        backgroundLoading: false,
        fetchChannelAssignableLogos: mockFetchChannelLogos,
      }));

      const { result } = renderHook(() => useChannelLogoSelection());

      await act(async () => {
        await result.current.ensureLogosLoaded();
      });

      expect(mockFetchChannelLogos).not.toHaveBeenCalled();
    });

    it('should not load if backgroundLoading is true', async () => {
      const mockFetchChannelLogos = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        channelLogos: {},
        hasLoadedChannelLogos: false,
        backgroundLoading: true,
        fetchChannelAssignableLogos: mockFetchChannelLogos,
      }));

      const { result } = renderHook(() => useChannelLogoSelection());

      await act(async () => {
        await result.current.ensureLogosLoaded();
      });

      expect(mockFetchChannelLogos).not.toHaveBeenCalled();
    });

    it('should handle errors when fetching channel logos', async () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const mockFetchChannelLogos = vi.fn().mockRejectedValue(new Error('Fetch failed'));
      useLogosStore.mockImplementation((selector) => selector({
        channelLogos: {},
        hasLoadedChannelLogos: false,
        backgroundLoading: false,
        fetchChannelAssignableLogos: mockFetchChannelLogos,
      }));

      const { result } = renderHook(() => useChannelLogoSelection());

      await act(async () => {
        await result.current.ensureLogosLoaded();
      });

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Failed to load channel logos:',
        expect.any(Error)
      );

      consoleErrorSpy.mockRestore();
    });
  });

  describe('useLogosById', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('should initialize with empty logos', () => {
      useLogosStore.mockImplementation((selector) => selector({
        logos: {},
        fetchLogosByIds: vi.fn(),
      }));

      const { result } = renderHook(() => useLogosById([]));

      expect(result.current.logos).toEqual({});
      expect(result.current.isLoading).toBe(false);
      expect(result.current.missingLogos).toBe(0);
    });

    it('should fetch missing logos by IDs', async () => {
      const mockFetchLogosByIds = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        logos: {},
        fetchLogosByIds: mockFetchLogosByIds,
      }));

      renderHook(() => useLogosById(['logo1', 'logo2']));

      await waitFor(() => {
        expect(mockFetchLogosByIds).toHaveBeenCalledWith(['logo1', 'logo2']);
      });
    });

    it('should not fetch logos that are already loaded', async () => {
      const mockFetchLogosByIds = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        logos: { logo1: { id: 'logo1' } },
        fetchLogosByIds: mockFetchLogosByIds,
      }));

      renderHook(() => useLogosById(['logo1', 'logo2']));

      await waitFor(() => {
        expect(mockFetchLogosByIds).toHaveBeenCalledWith(['logo2']);
      });
    });

    it('should handle errors when fetching logos by IDs', async () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const mockFetchLogosByIds = vi.fn().mockRejectedValue(new Error('Fetch failed'));
      useLogosStore.mockImplementation((selector) => selector({
        logos: {},
        fetchLogosByIds: mockFetchLogosByIds,
      }));

      renderHook(() => useLogosById(['logo1']));

      await waitFor(() => {
        expect(consoleErrorSpy).toHaveBeenCalledWith(
          'Failed to load logos by IDs:',
          expect.any(Error)
        );
      });

      consoleErrorSpy.mockRestore();
    });

    it('should filter out null/undefined IDs', async () => {
      const mockFetchLogosByIds = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        logos: {},
        fetchLogosByIds: mockFetchLogosByIds,
      }));

      renderHook(() => useLogosById(['logo1', null, undefined, 'logo2']));

      await waitFor(() => {
        expect(mockFetchLogosByIds).toHaveBeenCalledWith(['logo1', 'logo2']);
      });
    });

    it('should not refetch the same IDs multiple times', async () => {
      const mockFetchLogosByIds = vi.fn().mockResolvedValue();
      useLogosStore.mockImplementation((selector) => selector({
        logos: {},
        fetchLogosByIds: mockFetchLogosByIds,
      }));

      const { rerender } = renderHook(() => useLogosById(['logo1']));

      await waitFor(() => {
        expect(mockFetchLogosByIds).toHaveBeenCalledTimes(1);
      });

      rerender();

      await waitFor(() => {
        expect(mockFetchLogosByIds).toHaveBeenCalledTimes(1);
      });
    });
  });
});
