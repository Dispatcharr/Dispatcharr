import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { BrowserRouter } from 'react-router-dom';
import M3URefreshNotification from '../M3URefreshNotification';
import usePlaylistsStore from '../../store/playlists';
import useStreamsStore from '../../store/streams';
import useChannelsStore from '../../store/channels';
import useEPGsStore from '../../store/epgs';
import useVODStore from '../../store/useVODStore';
import API from '../../api';
import { showNotification } from '../../utils/notificationUtils';

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
}));

vi.mock('@mantine/core', async () => {
  return {
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

  describe('Download Progress Notifications', () => {
    it('should show notification when download starts', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'downloading',
          progress: 0,
          status: 'in_progress',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Processing: Test Playlist',
          message: 'Downloading starting...',
          loading: true,
          autoClose: 2000,
          icon: null,
        });
      });
    });

    it('should show notification when download completes', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'downloading',
          progress: 100,
          status: 'completed',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Processing: Test Playlist',
          message: 'Downloading complete!',
          loading: false,
          autoClose: 2000,
          icon: expect.anything(),
        });
      });
    });

    it('should not show notification for intermediate progress', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'downloading',
          progress: 50,
          status: 'in_progress',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });
  });

  describe('Parsing Progress Notifications', () => {
    it('should show notification when parsing starts', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 0,
          status: 'in_progress',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Processing: Test Playlist',
          message: 'Stream parsing starting...',
          loading: true,
          autoClose: 2000,
          icon: null,
        });
      });
    });

    it('should show notification and trigger fetches when parsing completes', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 100,
          status: 'completed',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
        expect(mockStreamsStore.fetchStreams).toHaveBeenCalled();
        expect(API.requeryChannels).toHaveBeenCalled();
        expect(mockChannelsStore.fetchChannelIds).toHaveBeenCalled();
      });
    });
  });

  describe('Group Processing Notifications', () => {
    it('should show notification when processing groups starts', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'processing_groups',
          progress: 0,
          status: 'in_progress',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Processing: Test Playlist',
          message: 'Group parsing starting...',
          loading: true,
          autoClose: 2000,
          icon: null,
        });
      });
    });

    it('should trigger multiple fetches when processing groups completes', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'processing_groups',
          progress: 100,
          status: 'completed',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(mockStreamsStore.fetchStreams).toHaveBeenCalled();
        expect(mockChannelsStore.fetchChannelGroups).toHaveBeenCalled();
        expect(mockEPGsStore.fetchEPGData).toHaveBeenCalled();
        expect(mockPlaylistsStore.fetchPlaylists).toHaveBeenCalled();
      });
    });
  });

  describe('VOD Refresh Notifications', () => {
    it('should show notification when VOD refresh starts', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'vod_refresh',
          progress: 0,
          status: 'in_progress',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Processing: Test Playlist',
          message: 'VOD content refresh starting...',
          loading: true,
          autoClose: 2000,
          icon: null,
        });
      });
    });

    it('should trigger VOD-specific fetches when VOD refresh completes', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'vod_refresh',
          progress: 100,
          status: 'completed',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(mockPlaylistsStore.fetchPlaylists).toHaveBeenCalled();
        expect(mockVODStore.fetchCategories).toHaveBeenCalled();
      });
    });
  });

  describe('Pending Setup Status', () => {
    it('should show setup notification and trigger fetches for pending_setup status', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          status: 'pending_setup',
          message: 'Test setup message',
          progress: 100,
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Setup: Test Playlist',
          message: expect.anything(),
          color: 'orange.5',
          autoClose: 5000,
        });
        expect(mockChannelsStore.fetchChannelGroups).toHaveBeenCalled();
        expect(mockPlaylistsStore.fetchPlaylists).toHaveBeenCalled();
      });
    });

    it('should use default message when no message provided in pending_setup', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          status: 'pending_setup',
          progress: 100,
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });
    });
  });

  describe('Error Handling', () => {
    it('should show error notification when status is error and progress is 100', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          status: 'error',
          progress: 100,
          error: 'Connection timeout',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Processing: Test Playlist',
          message: 'parsing failed: Connection timeout',
          color: 'red',
          autoClose: 5000,
        });
      });
    });

    it('should not show error notification when progress is not 100', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          status: 'error',
          progress: 50,
          error: 'Connection timeout',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });

    it('should use default error message when error field is missing', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'downloading',
          status: 'error',
          progress: 100,
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Processing: Test Playlist',
          message: 'downloading failed: Unknown error',
          color: 'red',
          autoClose: 5000,
        });
      });
    });

    it('should use default action when action field is missing in error', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          status: 'error',
          progress: 100,
          error: 'Test error',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith({
          title: 'M3U Processing: Test Playlist',
          message: 'Processing failed: Test error',
          color: 'red',
          autoClose: 5000,
        });
      });
    });

    it('should not show further notifications after error status', async () => {
      // First update with error
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          status: 'error',
          progress: 100,
          error: 'Test error',
        },
      };

      const { rerender } = renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledTimes(1);
      });

      vi.clearAllMocks();

      // Second update with success
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          status: 'completed',
          progress: 100,
        },
      };

      rerender(
        <BrowserRouter>
          <M3URefreshNotification />
        </BrowserRouter>
      );

      // Should not show notification due to previous error
      expect(showNotification).not.toHaveBeenCalled();
    });
  });

  describe('Playlist Validation', () => {
    it('should not show notification if playlist not found', async () => {
      mockPlaylistsStore.playlists = [];
      mockPlaylistsStore.refreshProgress = {
        999: {
          account: 999,
          action: 'parsing',
          progress: 0,
          status: 'in_progress',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });

    it('should handle multiple playlists correctly', async () => {
      const secondPlaylist = { id: 2, name: 'Second Playlist' };
      mockPlaylistsStore.playlists = [mockPlaylist, secondPlaylist];
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 0,
          status: 'in_progress',
        },
        2: {
          account: 2,
          action: 'downloading',
          progress: 100,
          status: 'completed',
        },
      };

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledTimes(2);
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'M3U Processing: Test Playlist',
          })
        );
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'M3U Processing: Second Playlist',
          })
        );
      });
    });
  });

  describe('Notification Deduplication', () => {
    it('should not show duplicate notification for same status', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 0,
          status: 'in_progress',
        },
      };

      const { rerender } = renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledTimes(1);
      });

      vi.clearAllMocks();

      // Re-render with same data
      rerender(
        <BrowserRouter>
          <M3URefreshNotification />
        </BrowserRouter>
      );

      expect(showNotification).not.toHaveBeenCalled();
    });

    it('should show notification when status changes', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 0,
          status: 'in_progress',
        },
      };

      const { rerender } = renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledTimes(1);
      });

      vi.clearAllMocks();

      // Update with different progress
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 100,
          status: 'completed',
        },
      };

      rerender(
        <BrowserRouter>
          <M3URefreshNotification />
        </BrowserRouter>
      );

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe('State Cleanup', () => {
    it('should reset notification status when playlists change', async () => {
      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 0,
          status: 'in_progress',
        },
      };

      const { rerender } = renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });

      vi.clearAllMocks();

      // Change playlists - remove existing playlist
      mockPlaylistsStore.playlists = [];
      mockPlaylistsStore.refreshProgress = {
        2: {
          account: 2,
          action: 'parsing',
          progress: 0,
          status: 'in_progress',
        },
      };

      rerender(
        <BrowserRouter>
          <M3URefreshNotification />
        </BrowserRouter>
      );

      // Should not show notification because playlist doesn't exist
      expect(showNotification).not.toHaveBeenCalled();
    });

    it('should handle empty playlists array', async () => {
      mockPlaylistsStore.playlists = [];
      mockPlaylistsStore.refreshProgress = {};

      renderWithProviders(<M3URefreshNotification />);

      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });
  });

  describe('Effect Dependencies', () => {
    it('should re-run effect when refreshProgress changes', async () => {
      mockPlaylistsStore.refreshProgress = {};

      const { rerender } = renderWithProviders(<M3URefreshNotification />);

      expect(showNotification).not.toHaveBeenCalled();

      mockPlaylistsStore.refreshProgress = {
        1: {
          account: 1,
          action: 'parsing',
          progress: 0,
          status: 'in_progress',
        },
      };

      rerender(
        <BrowserRouter>
          <M3URefreshNotification />
        </BrowserRouter>
      );

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });
    });

    it('should re-run effect when playlists change', async () => {
      const { rerender } = renderWithProviders(<M3URefreshNotification />);

      const newPlaylist = { id: 2, name: 'New Playlist' };
      mockPlaylistsStore.playlists = [mockPlaylist, newPlaylist];

      rerender(
        <BrowserRouter>
          <M3URefreshNotification />
        </BrowserRouter>
      );
    });
  });

  // The parsing-complete event payload carries auto-sync counts
  // (channels_created/updated/deleted/failed) and a failed_stream_details
  // array. The component surfaces the counts inline in the notification
  // body and exposes a "Click for details" affordance when failures exist.
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
          action: 'downloading',
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
});
