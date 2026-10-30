import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, waitFor, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { BrowserRouter } from 'react-router-dom';
import M3URefreshNotification from '../M3URefreshNotification';
import usePlaylistsStore from '../../store/playlists';
import useStreamsStore from '../../store/streams';
import useChannelsStore from '../../store/channels';
import useEPGsStore from '../../store/epgs';
import useVODStore from '../../store/useVODStore';
import API from '../../api';
import {
  showNotification,
  updateNotification,
  hideNotification,
} from '../../utils/notificationUtils';

// Mock all stores
vi.mock('../../store/playlists', () => ({
  default: vi.fn(),
}));

vi.mock('../../store/streams', () => ({
  default: vi.fn(),
}));

vi.mock('../../store/channels', () => ({
  default: vi.fn(),
}));

vi.mock('../../store/epgs', () => ({
  default: vi.fn(),
}));

vi.mock('../../store/useVODStore', () => ({
  default: vi.fn(),
}));

// Mock API
vi.mock('../../api', () => ({
  default: {
    refreshPlaylist: vi.fn(),
    requeryChannels: vi.fn(),
  },
}));

// Mock notification utility
vi.mock('../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
  updateNotification: vi.fn(),
  hideNotification: vi.fn(),
}));

vi.mock('@mantine/core', async () => {
  return {
    Progress: ({ value }) => <div data-testid="progress" data-value={value} />,
    Stack: ({ children }) => <div>{children}</div>,
    Group: ({ children }) => <div>{children}</div>,
    Button: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
    // Stub for the auto-sync failure-details modal.
    Modal: ({ children, opened, onClose, title }) =>
      opened ? (
        <div data-testid="modal" role="dialog" aria-label={title}>
          <button data-testid="modal-close" onClick={onClose}>
            close
          </button>
          {children}
        </div>
      ) : null,
    ScrollArea: ({ children }) => <div>{children}</div>,
    Text: ({ children }) => <span>{children}</span>,
    Code: ({ children }) => <pre>{children}</pre>,
  };
});

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  ListOrdered: () => <div data-testid="icon-list-ordered" />,
  CircleCheck: () => <div data-testid="circle-check-icon" />,
}));

const renderWithProviders = (component) => {
  return render(<BrowserRouter>{component}</BrowserRouter>);
};

describe('M3URefreshNotification', () => {
  let mockPlaylistsStore;
  let mockStreamsStore;
  let mockChannelsStore;
  let mockEPGsStore;
  let mockVODStore;

  const mockPlaylist = {
    id: 1,
    name: 'Test Playlist',
    url: 'https://example.com/playlist.m3u',
  };

  beforeEach(() => {
    vi.clearAllMocks();

    // Setup default store mocks
    mockPlaylistsStore = {
      playlists: [mockPlaylist],
      refreshProgress: {},
      fetchPlaylists: vi.fn(),
      setEditPlaylistId: vi.fn(),
    };

    mockStreamsStore = {
      fetchStreams: vi.fn(),
    };

    mockChannelsStore = {
      fetchChannelGroups: vi.fn(),
      fetchChannelIds: vi.fn(),
    };

    mockEPGsStore = {
      fetchEPGData: vi.fn(),
    };

    mockVODStore = {
      fetchCategories: vi.fn(),
    };

    usePlaylistsStore.mockImplementation((selector) =>
      selector(mockPlaylistsStore)
    );
    useStreamsStore.mockImplementation((selector) =>
      selector(mockStreamsStore)
    );
    useChannelsStore.mockImplementation((selector) =>
      selector(mockChannelsStore)
    );
    useEPGsStore.mockImplementation((selector) => selector(mockEPGsStore));
    useVODStore.mockImplementation((selector) => selector(mockVODStore));
  });

  describe('Rendering', () => {
    it('should render without crashing', () => {
      const { container } = renderWithProviders(<M3URefreshNotification />);
      expect(container).toBeInTheDocument();
    });

    it('should render empty fragment', () => {
      const { container } = renderWithProviders(<M3URefreshNotification />);
      expect(container.firstChild).toBeNull();
    });
  });

  const setProgress = (values, account = 1) => {
    mockPlaylistsStore.refreshProgress = {
      [account]: {
        account,
        action: 'parsing',
        progress: 0,
        status: 'processing',
        ...values,
      },
    };
  };
  const rerenderNotifications = (view) =>
    view.rerender(
      <BrowserRouter>
        <M3URefreshNotification />
      </BrowserRouter>
    );

  describe('Persistent progress notifications', () => {
    it.each([
      'initializing',
      'downloading',
      'parsing',
      'processing_groups',
      'vod_refresh',
    ])('keeps %s visible until the refresh finishes', (action) => {
      setProgress({ action });
      renderWithProviders(<M3URefreshNotification />);
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          loading: true,
          autoClose: false,
          withCloseButton: false,
        })
      );
    });
    it('updates the same notification for intermediate progress and completion', () => {
      setProgress({ action: 'parsing' });
      const view = renderWithProviders(<M3URefreshNotification />);
      setProgress({
        progress: 50,
        streams_processed: 2000,
        elapsed_time: 12,
        time_remaining: 15,
      });
      rerenderNotifications(view);
      expect(showNotification).toHaveBeenCalledTimes(1);
      expect(updateNotification).toHaveBeenCalledWith(
        'm3u-refresh-1-live',
        expect.objectContaining({ loading: true, autoClose: false })
      );
      const message = updateNotification.mock.calls.at(-1)[1].message;
      render(<>{message}</>);
      expect(screen.getByText('Processing streams: 50%')).toBeInTheDocument();
      expect(screen.getByText('Streams: 2000')).toBeInTheDocument();
      setProgress({ progress: 100, status: 'success' });
      rerenderNotifications(view);
      expect(updateNotification).toHaveBeenLastCalledWith(
        'm3u-refresh-1-live',
        expect.objectContaining({
          loading: false,
          color: 'green',
          withCloseButton: true,
        })
      );
      expect(mockStreamsStore.fetchStreams).toHaveBeenCalled();
      expect(API.requeryChannels).toHaveBeenCalled();
      expect(mockChannelsStore.fetchChannelIds).toHaveBeenCalled();
    });
    it('shows VOD phases, elapsed time, estimated remaining time and catalog counts', () => {
      setProgress({
        action: 'vod_refresh',
        phase: 'Processing movies',
        progress: 12,
        items_processed: 2000,
        items_total: 48061,
        elapsed_time: 12,
        time_remaining: 89,
      });
      renderWithProviders(<M3URefreshNotification />);
      render(<>{showNotification.mock.calls[0][0].message}</>);
      expect(screen.getByText('Processing movies: 12%')).toBeInTheDocument();
      expect(
        screen.getByText('Catalog entries: 2,000 / 48,061')
      ).toBeInTheDocument();
      expect(screen.getByText(/Elapsed:/)).toBeInTheDocument();
      expect(screen.getByText(/Remaining/)).toBeInTheDocument();
    });
    it('keeps the Live notification running when only the download phase finishes', () => {
      setProgress({ action: 'downloading', progress: 100 });
      renderWithProviders(<M3URefreshNotification />);
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ loading: true, autoClose: false })
      );
      expect(mockStreamsStore.fetchStreams).not.toHaveBeenCalled();
    });
    it('uses separate stable notification IDs for Live TV and VOD', () => {
      setProgress({});
      const view = renderWithProviders(<M3URefreshNotification />);
      setProgress({ action: 'vod_refresh' });
      rerenderNotifications(view);
      expect(showNotification.mock.calls.map((call) => call[0].id)).toEqual([
        'm3u-refresh-1-live',
        'm3u-refresh-1-vod',
      ]);
    });
    it('deduplicates repeated events and playlist updates', () => {
      setProgress({});
      const view = renderWithProviders(<M3URefreshNotification />);
      mockPlaylistsStore.refreshProgress = {
        ...mockPlaylistsStore.refreshProgress,
      };
      rerenderNotifications(view);
      mockPlaylistsStore.playlists = [...mockPlaylistsStore.playlists];
      rerenderNotifications(view);
      expect(showNotification).toHaveBeenCalledTimes(1);
      expect(updateNotification).not.toHaveBeenCalled();
    });
    it('shows a new notification after the prior completed message has closed', () => {
      setProgress({ progress: 100, status: 'success' });
      const view = renderWithProviders(<M3URefreshNotification />);
      showNotification.mock.calls[0][0].onClose();
      setProgress({});
      rerenderNotifications(view);
      expect(showNotification).toHaveBeenCalledTimes(2);
    });
    it.each(['processing_groups', 'vod_refresh'])(
      'keeps completion fetches for %s',
      (action) => {
        setProgress({ action, progress: 100, status: 'success' });
        renderWithProviders(<M3URefreshNotification />);
        expect(mockPlaylistsStore.fetchPlaylists).toHaveBeenCalled();
        if (action === 'vod_refresh')
          expect(mockVODStore.fetchCategories).toHaveBeenCalled();
        else {
          expect(mockChannelsStore.fetchChannelGroups).toHaveBeenCalled();
          expect(mockEPGsStore.fetchEPGData).toHaveBeenCalled();
        }
      }
    );
    it('ignores progress for unknown or deleted accounts', () => {
      setProgress({}, 999);
      renderWithProviders(<M3URefreshNotification />);
      expect(showNotification).not.toHaveBeenCalled();
    });
    it('removes a deleted account notification without replaying other accounts', () => {
      mockPlaylistsStore.playlists = [mockPlaylist, { id: 2, name: 'Other' }];
      mockPlaylistsStore.refreshProgress = {
        1: { account: 1, action: 'parsing', progress: 5 },
        2: { account: 2, action: 'parsing', progress: 5 },
      };
      const view = renderWithProviders(<M3URefreshNotification />);
      mockPlaylistsStore.playlists = [mockPlaylist];
      rerenderNotifications(view);
      expect(hideNotification).toHaveBeenCalledWith('m3u-refresh-2-live');
      expect(showNotification).toHaveBeenCalledTimes(2);
      expect(updateNotification).not.toHaveBeenCalled();
    });
    it('cleans up its notifications when the authenticated app unmounts', () => {
      setProgress({ action: 'vod_refresh' });
      const view = renderWithProviders(<M3URefreshNotification />);
      view.unmount();
      expect(hideNotification).toHaveBeenCalledWith('m3u-refresh-1-vod');
    });
    it('supports multiple providers without creating duplicate phase notifications', () => {
      mockPlaylistsStore.playlists = [
        mockPlaylist,
        { id: 2, name: 'Second Playlist' },
      ];
      mockPlaylistsStore.refreshProgress = {
        1: { account: 1, action: 'parsing', progress: 5 },
        2: { account: 2, action: 'vod_refresh', progress: 30 },
      };
      renderWithProviders(<M3URefreshNotification />);
      expect(showNotification).toHaveBeenCalledTimes(2);
      expect(showNotification.mock.calls.map((call) => call[0].id)).toEqual([
        'm3u-refresh-1-live',
        'm3u-refresh-2-vod',
      ]);
    });
  });

  describe('Setup and errors', () => {
    it.each([0, 100])(
      'stops the spinner and preserves an error at progress %s',
      (progress) => {
        setProgress({
          status: 'error',
          progress,
          error: 'Provider unavailable',
        });
        renderWithProviders(<M3URefreshNotification />);
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            message: 'Provider unavailable',
            loading: false,
            color: 'red',
            autoClose: false,
            withCloseButton: true,
          })
        );
      }
    );
    it('uses an upstream message when no error field is present', () => {
      setProgress({
        action: 'vod_refresh',
        status: 'error',
        message: 'Upstream timed out',
      });
      renderWithProviders(<M3URefreshNotification />);
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Upstream timed out' })
      );
    });
    it('uses a useful fallback for an empty error', () => {
      setProgress({ status: 'error' });
      renderWithProviders(<M3URefreshNotification />);
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Refresh failed. Please retry.' })
      );
    });
    it('allows a new refresh after an error', () => {
      setProgress({ status: 'error' });
      const view = renderWithProviders(<M3URefreshNotification />);
      setProgress({});
      rerenderNotifications(view);
      expect(updateNotification).toHaveBeenCalledWith(
        'm3u-refresh-1-live',
        expect.objectContaining({ loading: true, autoClose: false })
      );
    });
    it('turns pending setup into the configure/refresh notification', () => {
      setProgress({
        status: 'pending_setup',
        action: 'processing_groups',
        progress: 100,
      });
      renderWithProviders(<M3URefreshNotification />);
      expect(mockChannelsStore.fetchChannelGroups).toHaveBeenCalled();
      expect(mockPlaylistsStore.fetchPlaylists).toHaveBeenCalled();
      const notification = showNotification.mock.calls[0][0];
      expect(notification).toMatchObject({
        title: 'M3U Setup: Test Playlist',
        loading: false,
        autoClose: 5000,
      });
      render(<BrowserRouter>{notification.message}</BrowserRouter>);
      fireEvent.click(screen.getByText('Refresh Now'));
      expect(API.refreshPlaylist).toHaveBeenCalledWith(1);
    });

    it('does not duplicate handoff notifications during guided setup', () => {
      mockPlaylistsStore.playlists = [
        { ...mockPlaylist, setup_step: 'categories' },
      ];
      setProgress({
        status: 'pending_setup',
        action: 'processing_groups',
        progress: 100,
      });
      renderWithProviders(<M3URefreshNotification />);
      expect(mockChannelsStore.fetchChannelGroups).toHaveBeenCalled();
      expect(showNotification).not.toHaveBeenCalled();
    });

    it('keeps provider errors visible during guided setup', () => {
      mockPlaylistsStore.playlists = [{ ...mockPlaylist, setup_step: 'epg' }];
      setProgress({ status: 'error', error: 'Provider request failed' });
      renderWithProviders(<M3URefreshNotification />);
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red', autoClose: false })
      );
    });
  });

  describe('Auto-sync count rendering on parsing complete', () => {
    it('inlines auto-sync summary when counts are present', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 100,
          status: 'success',
          channels_created: 12,
          channels_updated: 3,
          channels_deleted: 1,
          channels_failed: 0,
          failed_stream_details: [],
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });
      // The message arg is JSX; render it and confirm both the
      // base message and the auto-sync summary text appear.
      const call = showNotification.mock.calls.find(
        (c) => typeof c[0]?.message === 'object'
      );
      expect(call).toBeDefined();
      const { container } = render(<>{call[0].message}</>);
      expect(container.textContent).toContain('Stream parsing complete!');
      expect(container.textContent).toContain('12 created');
      expect(container.textContent).toContain('3 updated');
      expect(container.textContent).toContain('1 deleted');
    });

    it('shows "Click for details" button when failures exist', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 100,
          status: 'success',
          channels_created: 5,
          channels_updated: 0,
          channels_deleted: 0,
          channels_failed: 2,
          failed_stream_details: [
            {
              stream_name: 'BadStream1',
              group: 'Sports',
              error: 'Range exhausted',
            },
            {
              stream_name: 'BadStream2',
              group: 'News',
              error: 'Channel number conflict',
            },
          ],
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });
      const call = showNotification.mock.calls.find(
        (c) => typeof c[0]?.message === 'object'
      );
      expect(call).toBeDefined();
      const { container } = render(<>{call[0].message}</>);
      expect(container.textContent).toContain('2 failed');
      expect(container.textContent).toContain('Click for details');
    });

    it('falls back to plain string body when no auto-sync counts arrive', async () => {
      // Older payload shape (or non-parsing actions) get the original
      // simple "X complete!" string body, no JSX wrapping.
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 100,
          status: 'success',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });
      const call = showNotification.mock.calls[0];
      expect(typeof call[0].message).toBe('string');
    });

    it('uses extended autoClose when failures are present', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 100,
          status: 'success',
          channels_created: 1,
          channels_failed: 1,
          failed_stream_details: [{ stream_name: 'X', group: 'Y', error: 'Z' }],
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });
      const call = showNotification.mock.calls[0];
      // 12000ms when failures > 0; 4000ms when summary present but no
      // failures; 2000ms when no auto-sync counts.
      expect(call[0].autoClose).toBe(12000);
    });
  });

  describe('Stream count rendering on parsing complete', () => {
    it('inlines stream summary including marked stale count', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 100,
          status: 'success',
          streams_created: 2,
          streams_updated: 5,
          streams_stale: 18,
          streams_deleted: 3,
          streams_processed: 1200,
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });
      const call = showNotification.mock.calls.find(
        (c) => typeof c[0]?.message === 'object'
      );
      expect(call).toBeDefined();
      const { container } = render(<>{call[0].message}</>);
      expect(container.textContent).toContain('Stream parsing complete!');
      expect(container.textContent).toContain('18 marked stale');
      expect(container.textContent).toContain('3 removed');
      expect(container.textContent).toContain('Total processed: 1200');
    });
  });
});
