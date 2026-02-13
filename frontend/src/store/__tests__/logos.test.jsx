import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import useLogosStore from '../logos';
import api from '../../api';

// Mock the api module
vi.mock('../../api');

describe('useLogosStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Reset store state between tests
    useLogosStore.setState({
      logos: {},
      channelLogos: {},
      isLoading: false,
      backgroundLoading: false,
      hasLoadedAll: false,
      hasLoadedChannelLogos: false,
      error: null,
      allowLogoRendering: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('should initialize with default values', () => {
      const { result } = renderHook(() => useLogosStore());

      expect(result.current.logos).toEqual({});
      expect(result.current.channelLogos).toEqual({});
      expect(result.current.isLoading).toBe(false);
      expect(result.current.backgroundLoading).toBe(false);
      expect(result.current.hasLoadedAll).toBe(false);
      expect(result.current.hasLoadedChannelLogos).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.allowLogoRendering).toBe(false);
    });
  });

  describe('enableLogoRendering', () => {
    it('should enable logo rendering', () => {
      const { result } = renderHook(() => useLogosStore());

      act(() => {
        result.current.enableLogoRendering();
      });

      expect(result.current.allowLogoRendering).toBe(true);
    });
  });

  describe('addLogo', () => {
    it('should add logo to main logos store', () => {
      const { result } = renderHook(() => useLogosStore());

      const newLogo = {
        id: 'logo1',
        name: 'Logo 1',
        url: 'http://example.com/logo1.png',
      };

      act(() => {
        result.current.addLogo(newLogo);
      });

      expect(result.current.logos).toEqual({
        logo1: newLogo,
      });
    });

    it('should add logo to channelLogos if hasLoadedChannelLogos is true', () => {
      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ hasLoadedChannelLogos: true });
      });

      const newLogo = {
        id: 'logo1',
        name: 'Logo 1',
        url: 'http://example.com/logo1.png',
      };

      act(() => {
        result.current.addLogo(newLogo);
      });

      expect(result.current.logos).toEqual({ logo1: newLogo });
      expect(result.current.channelLogos).toEqual({ logo1: newLogo });
    });

    it('should not add logo to channelLogos if hasLoadedChannelLogos is false', () => {
      const { result } = renderHook(() => useLogosStore());

      const newLogo = {
        id: 'logo1',
        name: 'Logo 1',
        url: 'http://example.com/logo1.png',
      };

      act(() => {
        result.current.addLogo(newLogo);
      });

      expect(result.current.logos).toEqual({ logo1: newLogo });
      expect(result.current.channelLogos).toEqual({});
    });
  });

  describe('updateLogo', () => {
    it('should update logo in main logos store', () => {
      const { result } = renderHook(() => useLogosStore());

      const originalLogo = {
        id: 'logo1',
        name: 'Original',
        url: 'http://example.com/original.png',
      };
      const updatedLogo = {
        id: 'logo1',
        name: 'Updated',
        url: 'http://example.com/updated.png',
      };

      act(() => {
        useLogosStore.setState({ logos: { logo1: originalLogo } });
      });

      act(() => {
        result.current.updateLogo(updatedLogo);
      });

      expect(result.current.logos.logo1).toEqual(updatedLogo);
    });

    it('should update logo in channelLogos if it exists there', () => {
      const { result } = renderHook(() => useLogosStore());

      const originalLogo = {
        id: 'logo1',
        name: 'Original',
        url: 'http://example.com/original.png',
      };
      const updatedLogo = {
        id: 'logo1',
        name: 'Updated',
        url: 'http://example.com/updated.png',
      };

      act(() => {
        useLogosStore.setState({
          logos: { logo1: originalLogo },
          channelLogos: { logo1: originalLogo },
        });
      });

      act(() => {
        result.current.updateLogo(updatedLogo);
      });

      expect(result.current.logos.logo1).toEqual(updatedLogo);
      expect(result.current.channelLogos.logo1).toEqual(updatedLogo);
    });

    it('should not update channelLogos if logo does not exist there', () => {
      const { result } = renderHook(() => useLogosStore());

      const originalLogo = {
        id: 'logo1',
        name: 'Original',
        url: 'http://example.com/original.png',
      };
      const updatedLogo = {
        id: 'logo1',
        name: 'Updated',
        url: 'http://example.com/updated.png',
      };

      act(() => {
        useLogosStore.setState({ logos: { logo1: originalLogo } });
      });

      act(() => {
        result.current.updateLogo(updatedLogo);
      });

      expect(result.current.channelLogos).toEqual({});
    });
  });

  describe('removeLogo', () => {
    it('should remove logo from both stores', () => {
      const { result } = renderHook(() => useLogosStore());

      const logo1 = { id: 'logo1', name: 'Logo 1' };
      const logo2 = { id: 'logo2', name: 'Logo 2' };

      act(() => {
        useLogosStore.setState({
          logos: { logo1, logo2 },
          channelLogos: { logo1, logo2 },
        });
      });

      act(() => {
        result.current.removeLogo('logo1');
      });

      expect(result.current.logos).toEqual({ logo2 });
      expect(result.current.channelLogos).toEqual({ logo2 });
    });

    it('should handle removing non-existent logo', () => {
      const { result } = renderHook(() => useLogosStore());

      const logo1 = { id: 'logo1', name: 'Logo 1' };

      act(() => {
        useLogosStore.setState({ logos: { logo1 } });
      });

      act(() => {
        result.current.removeLogo('nonexistent');
      });

      expect(result.current.logos).toEqual({ logo1 });
    });
  });

  describe('fetchLogos', () => {
    it('should fetch logos successfully with array response', async () => {
      const mockLogos = [
        { id: 'logo1', name: 'Logo 1' },
        { id: 'logo2', name: 'Logo 2' },
      ];

      api.getLogos.mockResolvedValue(mockLogos);

      const { result } = renderHook(() => useLogosStore());

      let response;
      await act(async () => {
        response = await result.current.fetchLogos(100);
      });

      expect(result.current.logos).toEqual({
        logo1: { id: 'logo1', name: 'Logo 1' },
        logo2: { id: 'logo2', name: 'Logo 2' },
      });
      expect(result.current.isLoading).toBe(false);
      expect(api.getLogos).toHaveBeenCalledWith({ page_size: 100 });
      expect(response).toEqual(mockLogos);
    });

    it('should fetch logos successfully with paginated response', async () => {
      const mockResponse = {
        results: [
          { id: 'logo1', name: 'Logo 1' },
          { id: 'logo2', name: 'Logo 2' },
        ],
        count: 2,
      };

      api.getLogos.mockResolvedValue(mockResponse);

      const { result } = renderHook(() => useLogosStore());

      await act(async () => {
        await result.current.fetchLogos(50);
      });

      expect(result.current.logos).toEqual({
        logo1: { id: 'logo1', name: 'Logo 1' },
        logo2: { id: 'logo2', name: 'Logo 2' },
      });
      expect(api.getLogos).toHaveBeenCalledWith({ page_size: 50 });
    });

    it('should handle fetch error', async () => {
      const mockError = new Error('Network error');
      api.getLogos.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      await expect(
        act(async () => {
          await result.current.fetchLogos();
        })
      ).rejects.toThrow('Network error');

      await waitFor(() => {
        expect(result.current.error).toBe('Failed to load logos.');
        expect(result.current.isLoading).toBe(false);
        expect(consoleSpy).toHaveBeenCalledWith(
          'Failed to fetch logos:',
          mockError
        );
      });

      consoleSpy.mockRestore();
    });
  });

  describe('fetchAllLogos', () => {
    it('should fetch all logos successfully', async () => {
      const mockLogos = [
        { id: 'logo1', name: 'Logo 1' },
        { id: 'logo2', name: 'Logo 2' },
      ];

      api.getLogos.mockResolvedValue(mockLogos);

      const { result } = renderHook(() => useLogosStore());

      let response;
      await act(async () => {
        response = await result.current.fetchAllLogos();
      });

      expect(result.current.logos).toEqual({
        logo1: { id: 'logo1', name: 'Logo 1' },
        logo2: { id: 'logo2', name: 'Logo 2' },
      });
      expect(result.current.hasLoadedAll).toBe(true);
      expect(result.current.isLoading).toBe(false);
      expect(api.getLogos).toHaveBeenCalledWith({ no_pagination: 'true' });
      expect(response).toEqual(mockLogos);
    });

    it('should not refetch if already loaded and not forced', async () => {
      const mockLogos = [{ id: 'logo1', name: 'Logo 1' }];

      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({
          logos: { logo1: mockLogos[0] },
          hasLoadedAll: true,
        });
      });

      const response = await act(async () => {
        return await result.current.fetchAllLogos();
      });

      expect(api.getLogos).not.toHaveBeenCalled();
      expect(response).toEqual([mockLogos[0]]);
    });

    it('should refetch if forced', async () => {
      const mockLogos = [{ id: 'logo1', name: 'Logo 1' }];

      api.getLogos.mockResolvedValue(mockLogos);

      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({
          logos: { logo1: mockLogos[0] },
          hasLoadedAll: true,
        });
      });

      await act(async () => {
        await result.current.fetchAllLogos(true);
      });

      expect(api.getLogos).toHaveBeenCalledWith({ no_pagination: 'true' });
    });

    it('should not refetch if already loading', async () => {
      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ isLoading: true });
      });

      const response = await act(async () => {
        return await result.current.fetchAllLogos();
      });

      expect(api.getLogos).not.toHaveBeenCalled();
      expect(response).toEqual([]);
    });

    it('should handle fetch error', async () => {
      const mockError = new Error('API error');
      api.getLogos.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      await expect(
        act(async () => {
          await result.current.fetchAllLogos();
        })
      ).rejects.toThrow('API error');

      await waitFor(() => {
        expect(result.current.error).toBe('Failed to load all logos.');
        expect(result.current.isLoading).toBe(false);
        expect(consoleSpy).toHaveBeenCalledWith(
          'Failed to fetch all logos:',
          mockError
        );
      });

      consoleSpy.mockRestore();
    });
  });

  describe('fetchUsedLogos', () => {
    it('should fetch used logos successfully', async () => {
      const mockResponse = {
        results: [
          { id: 'logo1', name: 'Used Logo 1' },
          { id: 'logo2', name: 'Used Logo 2' },
        ],
      };

      api.getLogos.mockResolvedValue(mockResponse);

      const { result } = renderHook(() => useLogosStore());

      let response;
      await act(async () => {
        response = await result.current.fetchUsedLogos(100);
      });

      expect(result.current.logos).toEqual({
        logo1: { id: 'logo1', name: 'Used Logo 1' },
        logo2: { id: 'logo2', name: 'Used Logo 2' },
      });
      expect(result.current.isLoading).toBe(false);
      expect(api.getLogos).toHaveBeenCalledWith({
        used: 'true',
        page_size: 100,
      });
      expect(response).toEqual(mockResponse);
    });

    it('should merge with existing logos', async () => {
      const existingLogo = { id: 'logo1', name: 'Existing Logo' };
      const newLogo = { id: 'logo2', name: 'New Logo' };

      api.getLogos.mockResolvedValue({ results: [newLogo] });

      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ logos: { logo1: existingLogo } });
      });

      await act(async () => {
        await result.current.fetchUsedLogos();
      });

      expect(result.current.logos).toEqual({
        logo1: existingLogo,
        logo2: newLogo,
      });
    });

    it('should handle fetch error', async () => {
      const mockError = new Error('Fetch error');
      api.getLogos.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      await expect(
        act(async () => {
          await result.current.fetchUsedLogos();
        })
      ).rejects.toThrow('Fetch error');

      await waitFor(() => {
        expect(result.current.error).toBe('Failed to load used logos.');
        expect(consoleSpy).toHaveBeenCalledWith(
          'Failed to fetch used logos:',
          mockError
        );
      });

      consoleSpy.mockRestore();
    });
  });

  describe('fetchChannelAssignableLogos', () => {
    it('should return cached logos if already loaded', async () => {
      const cachedLogos = {
        logo1: { id: 'logo1', name: 'Cached Logo' },
      };

      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({
          channelLogos: cachedLogos,
          hasLoadedChannelLogos: true,
        });
      });

      const response = await act(async () => {
        return await result.current.fetchChannelAssignableLogos();
      });

      expect(api.getLogos).not.toHaveBeenCalled();
      expect(response).toEqual([cachedLogos.logo1]);
    });

    it('should fetch and cache logos if not loaded', async () => {
      const mockLogos = [
        { id: 'logo1', name: 'Logo 1' },
        { id: 'logo2', name: 'Logo 2' },
      ];

      api.getLogos.mockResolvedValue(mockLogos);

      const { result } = renderHook(() => useLogosStore());

      await act(async () => {
        await result.current.fetchChannelAssignableLogos();
      });

      expect(result.current.channelLogos).toEqual({
        logo1: { id: 'logo1', name: 'Logo 1' },
        logo2: { id: 'logo2', name: 'Logo 2' },
      });
      expect(result.current.hasLoadedChannelLogos).toBe(true);
      expect(api.getLogos).toHaveBeenCalledWith({ no_pagination: 'true' });
    });
  });

  describe('fetchLogosByIds', () => {
    it('should fetch missing logos by IDs', async () => {
      const existingLogo = { id: 'logo1', name: 'Existing' };
      const newLogo = { id: 'logo2', name: 'New' };

      api.getLogosByIds.mockResolvedValue([newLogo]);

      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ logos: { logo1: existingLogo } });
      });

      let response;
      await act(async () => {
        response = await result.current.fetchLogosByIds(['logo1', 'logo2']);
      });

      expect(api.getLogosByIds).toHaveBeenCalledWith(['logo2']);
      expect(result.current.logos).toEqual({
        logo1: existingLogo,
        logo2: newLogo,
      });
      expect(response).toEqual([newLogo]);
    });

    it('should return empty array if all logos exist', async () => {
      const logo1 = { id: 'logo1', name: 'Logo 1' };

      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ logos: { logo1 } });
      });

      const response = await act(async () => {
        return await result.current.fetchLogosByIds(['logo1']);
      });

      expect(api.getLogosByIds).not.toHaveBeenCalled();
      expect(response).toEqual([]);
    });

    it('should handle fetch error', async () => {
      const mockError = new Error('Fetch error');
      api.getLogosByIds.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      await expect(
        act(async () => {
          await result.current.fetchLogosByIds(['logo1']);
        })
      ).rejects.toThrow('Fetch error');

      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to fetch logos by IDs:',
        mockError
      );

      consoleSpy.mockRestore();
    });
  });

  describe('fetchLogosInBackground', () => {
    it('should fetch logos in background with pagination', async () => {
      // vi.useRealTimers();

      const page1 = {
        results: [{ id: 'logo1', name: 'Logo 1' }],
        next: 'http://example.com/page2',
      };
      const page2 = {
        results: [{ id: 'logo2', name: 'Logo 2' }],
        next: null,
      };

      api.getLogos.mockResolvedValueOnce(page1).mockResolvedValueOnce(page2);

      const { result } = renderHook(() => useLogosStore());

      await act(async () => {
        await result.current.fetchLogosInBackground();
      });

      expect(result.current.logos).toEqual({
        logo1: { id: 'logo1', name: 'Logo 1' },
        logo2: { id: 'logo2', name: 'Logo 2' },
      });
      expect(result.current.backgroundLoading).toBe(false);
      expect(api.getLogos).toHaveBeenCalledTimes(2);
      expect(api.getLogos).toHaveBeenCalledWith({ page: 1, page_size: 200 });
      expect(api.getLogos).toHaveBeenCalledWith({ page: 2, page_size: 200 });
    });

    it('should handle errors gracefully without throwing', async () => {
      const mockError = new Error('Network error');
      api.getLogos.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      await act(async () => {
        await result.current.fetchLogosInBackground();
      });

      expect(result.current.backgroundLoading).toBe(false);
      expect(consoleSpy).toHaveBeenCalledWith(
        'Background logo loading failed:',
        mockError
      );

      consoleSpy.mockRestore();
    });
  });

  describe('backgroundLoadAllLogos', () => {
    it('should not start if already loading', async () => {
      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ backgroundLoading: true });
      });

      await act(async () => {
        await result.current.backgroundLoadAllLogos();
      });

      expect(api.getLogos).not.toHaveBeenCalled();
    });

    it('should not start if already loaded', async () => {
      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ hasLoadedAll: true });
      });

      await act(async () => {
        await result.current.backgroundLoadAllLogos();
      });

      expect(api.getLogos).not.toHaveBeenCalled();
    });

    it('should load logos in background asynchronously', async () => {
      vi.useFakeTimers();

      const mockLogos = Array.from({ length: 2500 }, (_, i) => ({
        id: `logo${i}`,
        name: `Logo ${i}`,
      }));

      api.getLogos.mockResolvedValue(mockLogos);

      const { result } = renderHook(() => useLogosStore());

      // Start background loading
      result.current.backgroundLoadAllLogos();

      // Advance timers to execute setTimeout
      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.hasLoadedAll).toBe(true);
      expect(result.current.backgroundLoading).toBe(false);
      expect(Object.keys(result.current.logos).length).toBe(2500);

      vi.useRealTimers();
    });

    it('should handle errors gracefully', async () => {
      vi.useFakeTimers();

      const mockError = new Error('Fetch error');
      api.getLogos.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      result.current.backgroundLoadAllLogos();

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.backgroundLoading).toBe(false);
      expect(consoleSpy).toHaveBeenCalledWith(
        'Background all logos loading failed:',
        mockError
      );

      consoleSpy.mockRestore();

      vi.useRealTimers();
    });
  });

  describe('backgroundLoadChannelLogos', () => {
    it('should not start if already loading', async () => {
      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ backgroundLoading: true });
      });

      await act(async () => {
        await result.current.backgroundLoadChannelLogos();
      });

      expect(api.getLogos).not.toHaveBeenCalled();
    });

    it('should not start if already loaded', async () => {
      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ hasLoadedChannelLogos: true });
      });

      await act(async () => {
        await result.current.backgroundLoadChannelLogos();
      });

      expect(api.getLogos).not.toHaveBeenCalled();
    });

    it('should not start if channelLogos already has many items', async () => {
      const channelLogos = Array.from({ length: 150 }, (_, i) => [
        `logo${i}`,
        { id: `logo${i}` },
      ]);
      const channelLogosObj = Object.fromEntries(channelLogos);

      const { result } = renderHook(() => useLogosStore());

      act(() => {
        useLogosStore.setState({ channelLogos: channelLogosObj });
      });

      await act(async () => {
        await result.current.backgroundLoadChannelLogos();
      });

      expect(api.getLogos).not.toHaveBeenCalled();
    });

    it('should load channel logos in background', async () => {
      const mockLogos = [
        { id: 'logo1', name: 'Logo 1' },
        { id: 'logo2', name: 'Logo 2' },
      ];

      api.getLogos.mockResolvedValue(mockLogos);

      const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      await act(async () => {
        await result.current.backgroundLoadChannelLogos();
      });

      expect(result.current.hasLoadedChannelLogos).toBe(true);
      expect(result.current.backgroundLoading).toBe(false);
      expect(Object.keys(result.current.channelLogos).length).toBe(2);
      expect(consoleSpy).toHaveBeenCalledWith(
        'Background loading channel logos...'
      );
      expect(consoleSpy).toHaveBeenCalledWith(
        'Background loaded 2 channel logos'
      );

      consoleSpy.mockRestore();
    });

    it('should handle errors gracefully', async () => {
      const mockError = new Error('Fetch error');
      api.getLogos.mockRejectedValue(mockError);

      const consoleErrorSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const consoleLogSpy = vi
        .spyOn(console, 'log')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      await act(async () => {
        await result.current.backgroundLoadChannelLogos();
      });

      expect(result.current.backgroundLoading).toBe(false);
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Background channel logo loading failed:',
        mockError
      );

      consoleErrorSpy.mockRestore();
      consoleLogSpy.mockRestore();
    });
  });

  describe('startBackgroundLoading', () => {
    it('should start background loading after delay', async () => {
      vi.useFakeTimers();

      const mockLogos = [{ id: 'logo1', name: 'Logo 1' }];
      api.getLogos.mockResolvedValue(mockLogos);

      const { result } = renderHook(() => useLogosStore());

      result.current.startBackgroundLoading();

      // Advance timer by 3 seconds
      await act(async () => {
        vi.advanceTimersByTime(3000);
        await vi.runAllTimersAsync();
      });

      expect(result.current.hasLoadedAll).toBe(true);

      vi.useRealTimers();
    });

    it('should handle errors in background loading', async () => {
      vi.useFakeTimers();

      const mockError = new Error('Background error');
      api.getLogos.mockRejectedValue(mockError);

      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      const { result } = renderHook(() => useLogosStore());

      result.current.startBackgroundLoading();

      await act(async () => {
        vi.advanceTimersByTime(3000);
        await vi.runAllTimersAsync();
      });

      expect(consoleSpy).toHaveBeenCalled();

      consoleSpy.mockRestore();

      vi.useRealTimers();
    });
  });

  describe('helper methods', () => {
    describe('getLogoById', () => {
      it('should return logo if it exists', () => {
        const logo = { id: 'logo1', name: 'Logo 1' };
        const { result } = renderHook(() => useLogosStore());

        act(() => {
          useLogosStore.setState({ logos: { logo1: logo } });
        });

        expect(result.current.getLogoById('logo1')).toEqual(logo);
      });

      it('should return null if logo does not exist', () => {
        const { result } = renderHook(() => useLogosStore());

        expect(result.current.getLogoById('nonexistent')).toBeNull();
      });
    });

    describe('hasLogo', () => {
      it('should return true if logo exists', () => {
        const logo = { id: 'logo1', name: 'Logo 1' };
        const { result } = renderHook(() => useLogosStore());

        act(() => {
          useLogosStore.setState({ logos: { logo1: logo } });
        });

        expect(result.current.hasLogo('logo1')).toBe(true);
      });

      it('should return false if logo does not exist', () => {
        const { result } = renderHook(() => useLogosStore());

        expect(result.current.hasLogo('nonexistent')).toBe(false);
      });
    });

    describe('getLogosCount', () => {
      it('should return correct count of logos', () => {
        const { result } = renderHook(() => useLogosStore());

        act(() => {
          useLogosStore.setState({
            logos: {
              logo1: { id: 'logo1' },
              logo2: { id: 'logo2' },
              logo3: { id: 'logo3' },
            },
          });
        });

        expect(result.current.getLogosCount()).toBe(3);
      });

      it('should return 0 for empty logos', () => {
        const { result } = renderHook(() => useLogosStore());

        expect(result.current.getLogosCount()).toBe(0);
      });
    });

    describe('needsAllLogos', () => {
      it('should return true if hasLoadedAll is false', () => {
        const { result } = renderHook(() => useLogosStore());

        expect(result.current.needsAllLogos()).toBe(true);
      });

      it('should return true if logos is empty', () => {
        const { result } = renderHook(() => useLogosStore());

        act(() => {
          useLogosStore.setState({ hasLoadedAll: true, logos: {} });
        });

        expect(result.current.needsAllLogos()).toBe(true);
      });

      it('should return false if hasLoadedAll is true and logos exist', () => {
        const { result } = renderHook(() => useLogosStore());

        act(() => {
          useLogosStore.setState({
            hasLoadedAll: true,
            logos: { logo1: { id: 'logo1' } },
          });
        });

        expect(result.current.needsAllLogos()).toBe(false);
      });
    });
  });
});
