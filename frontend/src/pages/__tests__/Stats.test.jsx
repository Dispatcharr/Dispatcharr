// src/pages/__tests__/Stats.test.jsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from '@testing-library/react';
import StatsPage from '../Stats';
import useStreamProfilesStore from '../../store/streamProfiles';
import useLocalStorage from '../../hooks/useLocalStorage';
import useChannelsStore from '../../store/channels';
import useLogosStore from '../../store/logos';
import {
  fetchActiveChannelStats,
  getCurrentPrograms,
  getClientStats,
  getCombinedConnections,
  getStatsByChannelId,
  getVODStats,
  stopChannel,
  stopClient,
  stopVODClient,
} from '../../utils/pages/StatsUtils.js';

// Mock dependencies
vi.mock('../../store/channels');
vi.mock('../../store/logos');
vi.mock('../../store/streamProfiles');
vi.mock('../../hooks/useLocalStorage');

vi.mock('../../components/SystemEvents', () => ({
  default: () => <div data-testid="system-events">SystemEvents</div>,
}));

vi.mock('../../components/ErrorBoundary.jsx', () => ({
  default: ({ children }) => <div data-testid="error-boundary">{children}</div>,
}));

vi.mock('../../components/cards/VodConnectionCard.jsx', () => ({
  default: ({ vodContent, stopVODClient }) => (
    <div data-testid={`vod-connection-card-${vodContent.content_uuid}`}>
      VODConnectionCard - {vodContent.content_uuid}
      {vodContent.connections?.map((conn) => (
        <button
          key={conn.client_id}
          data-testid={`stop-vod-client-${conn.client_id}`}
          onClick={() => stopVODClient(conn.client_id)}
        >
          Stop VOD Client
        </button>
      ))}
    </div>
  ),
}));

vi.mock('../../components/cards/StreamConnectionCard.jsx', () => ({
  default: ({ channel }) => (
    <div data-testid={`stream-connection-card-${channel.uuid}`}>
      StreamConnectionCard - {channel.uuid}
    </div>
  ),
}));

// Mock Mantine components
vi.mock('@mantine/core', () => ({
  Box: ({ children, ...props }) => <div {...props}>{children}</div>,
  Button: ({ children, onClick, loading, ...props }) => (
    <button onClick={onClick} disabled={loading} {...props}>
      {children}
    </button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  LoadingOverlay: () => <div data-testid="loading-overlay">Loading...</div>,
  Text: ({ children }) => <span>{children}</span>,
  Title: ({ children }) => <h3>{children}</h3>,
  NumberInput: ({ value, onChange, min, max, ...props }) => (
    <input
      data-testid="refresh-interval-input"
      type="number"
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      min={min}
      max={max}
      {...props}
    />
  ),
}));

//mock stats utils
vi.mock('../../utils/pages/StatsUtils', () => {
  return {
    fetchActiveChannelStats: vi.fn(),
    getVODStats: vi.fn(),
    getCurrentPrograms: vi.fn(),
    getClientStats: vi.fn(),
    getCombinedConnections: vi.fn(),
    getStatsByChannelId: vi.fn(),
    stopChannel: vi.fn(),
    stopClient: vi.fn(),
    stopVODClient: vi.fn(),
  };
});

describe('StatsPage', () => {
  const mockChannels = [
    { id: 1, uuid: 'channel-1', name: 'Channel 1' },
    { id: 2, uuid: 'channel-2', name: 'Channel 2' },
  ];

  const mockChannelsByUUID = {
    'channel-1': mockChannels[0],
    'channel-2': mockChannels[1],
  };

  const mockStreamProfiles = [{ id: 1, name: 'Profile 1' }];

  const mockLogos = {
    'logo-1': 'logo-url-1',
  };

  const mockChannelStats = {
    channels: [
      { channel_id: 1, uuid: 'channel-1', connections: 2 },
      { channel_id: 2, uuid: 'channel-2', connections: 1 },
    ],
  };

  const mockVODStats = {
    vod_connections: [
      {
        content_uuid: 'vod-1',
        connections: [{ client_id: 'client-1', ip: '192.168.1.1' }],
      },
    ],
  };

  const mockProcessedChannelHistory = {
    1: { id: 1, uuid: 'channel-1', connections: 2 },
    2: { id: 2, uuid: 'channel-2', connections: 1 },
  };

  const mockClients = [
    { id: 'client-1', channel_id: 1 },
    { id: 'client-2', channel_id: 1 },
    { id: 'client-3', channel_id: 2 },
  ];

  const mockCombinedConnections = [
    { id: 1, type: 'stream', data: { id: 1, uuid: 'channel-1' } },
    { id: 2, type: 'stream', data: { id: 2, uuid: 'channel-2' } },
    {
      id: 3,
      type: 'vod',
      data: { content_uuid: 'vod-1', connections: [{ client_id: 'client-1' }] },
    },
  ];

  let mockSetChannelStats;
  let mockSetRefreshInterval;

  beforeEach(() => {
    vi.clearAllMocks();

    mockSetChannelStats = vi.fn();
    mockSetRefreshInterval = vi.fn();

    // Setup store mocks
    useChannelsStore.mockImplementation((selector) => {
      const state = {
        channels: mockChannels,
        channelsByUUID: mockChannelsByUUID,
        stats: { channels: mockChannelStats.channels },
        setChannelStats: mockSetChannelStats,
      };
      return selector ? selector(state) : state;
    });

    useStreamProfilesStore.mockImplementation((selector) => {
      const state = {
        profiles: mockStreamProfiles,
      };
      return selector ? selector(state) : state;
    });

    useLogosStore.mockImplementation((selector) => {
      const state = {
        logos: mockLogos,
      };
      return selector ? selector(state) : state;
    });

    useLocalStorage.mockReturnValue([5, mockSetRefreshInterval]);

    // Setup API mocks
    fetchActiveChannelStats.mockResolvedValue(mockChannelStats);
    getVODStats.mockResolvedValue(mockVODStats);
    getCurrentPrograms.mockResolvedValue({});
    getStatsByChannelId.mockReturnValue(mockProcessedChannelHistory);
    getClientStats.mockReturnValue(mockClients);
    getCombinedConnections.mockReturnValue(mockCombinedConnections);
    stopVODClient.mockResolvedValue({});

    delete window.location;
    window.location = { pathname: '/stats' };
  });

  describe('Initial Rendering', () => {
    it('renders the page title', async () => {
      render(<StatsPage />);
      await screen.findByText('Active Connections');
    });

    it('fetches initial stats on mount', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(fetchActiveChannelStats).toHaveBeenCalledTimes(2);
        expect(getVODStats).toHaveBeenCalledTimes(2);
      });
    });

    it('displays connection counts', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(screen.getByText(/2 streams/)).toBeInTheDocument();
        expect(screen.getByText(/1 VOD connection/)).toBeInTheDocument();
      });
    });

    it('renders SystemEvents component', async () => {
      render(<StatsPage />);
      await screen.findByTestId('system-events');
    });
  });

  describe('Refresh Interval Controls', () => {
    it('displays default refresh interval', () => {
      render(<StatsPage />);

      waitFor(() => {
        const input = screen.getByTestId('refresh-interval-input');
        expect(input).toHaveValue(5);
      });
    });

    it('updates refresh interval when input changes', async () => {
      render(<StatsPage />);

      const input = screen.getByTestId('refresh-interval-input');
      fireEvent.change(input, { target: { value: '10' } });

      await waitFor(() => {
        expect(mockSetRefreshInterval).toHaveBeenCalledWith(10);
      });
    });

    it('displays polling active message when interval > 0', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(screen.getByText(/Refreshing every 5s/)).toBeInTheDocument();
      });
    });

    it('displays disabled message when interval is 0', async () => {
      useLocalStorage.mockReturnValue([0, mockSetRefreshInterval]);
      render(<StatsPage />);

      await screen.findByText('Refreshing disabled');
    });
  });

  describe('Auto-refresh Polling', () => {
    it('sets up polling interval for stats', async () => {
      vi.useFakeTimers();

      render(<StatsPage />);

      expect(fetchActiveChannelStats).toHaveBeenCalledTimes(2);
      expect(getVODStats).toHaveBeenCalledTimes(2);

      // Advance timers by 5 seconds
      await act(async () => {
        vi.advanceTimersByTime(5000);
      });

      expect(fetchActiveChannelStats).toHaveBeenCalledTimes(3);
      expect(getVODStats).toHaveBeenCalledTimes(3);

      vi.useRealTimers();
    });

    it('does not poll when interval is 0', async () => {
      vi.useFakeTimers();

      useLocalStorage.mockReturnValue([0, mockSetRefreshInterval]);
      render(<StatsPage />);

      expect(fetchActiveChannelStats).toHaveBeenCalledTimes(1);

      await act(async () => {
        vi.advanceTimersByTime(10000);
      });

      expect(fetchActiveChannelStats).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });

    it('clears interval on unmount', async () => {
      vi.useFakeTimers();

      const { unmount } = render(<StatsPage />);

      expect(fetchActiveChannelStats).toHaveBeenCalledTimes(2);

      unmount();

      await act(async () => {
        vi.advanceTimersByTime(5000);
      });

      // Should not fetch again after unmount
      expect(fetchActiveChannelStats).toHaveBeenCalledTimes(2);

      vi.useRealTimers();
    });
  });

  describe('Manual Refresh', () => {
    it('refreshes stats when Refresh Now button is clicked', async () => {
      render(<StatsPage />);

      expect(fetchActiveChannelStats).toHaveBeenCalledTimes(2);

      const refreshButton = screen.getByText('Refresh Now');
      fireEvent.click(refreshButton);

      await waitFor(() => {
        expect(fetchActiveChannelStats).toHaveBeenCalledTimes(3);
        expect(getVODStats).toHaveBeenCalledTimes(3);
      });
    });
  });

  describe('Connection Display', () => {
    it('renders stream connection cards', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(
          screen.getByTestId('stream-connection-card-channel-1')
        ).toBeInTheDocument();
        expect(
          screen.getByTestId('stream-connection-card-channel-2')
        ).toBeInTheDocument();
      });
    });

    it('renders VOD connection cards', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(
          screen.getByTestId('vod-connection-card-vod-1')
        ).toBeInTheDocument();
      });
    });

    it('displays empty state when no connections', async () => {
      getCombinedConnections.mockReturnValue([]);
      render(<StatsPage />);

      await waitFor(() => {
        expect(screen.getByText('No active connections')).toBeInTheDocument();
      });
    });
  });

  describe('VOD Client Management', () => {
    it('stops VOD client when stop button is clicked', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(
          screen.getByTestId('stop-vod-client-client-1')
        ).toBeInTheDocument();
      });

      const stopButton = screen.getByTestId('stop-vod-client-client-1');
      fireEvent.click(stopButton);

      await waitFor(() => {
        expect(stopVODClient).toHaveBeenCalledWith('client-1');
      });
    });

    it('refreshes VOD stats after stopping client', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(getVODStats).toHaveBeenCalledTimes(2);
      });

      const stopButton = await screen.findByTestId('stop-vod-client-client-1');
      fireEvent.click(stopButton);

      await waitFor(() => {
        expect(getVODStats).toHaveBeenCalledTimes(3);
      });
    });
  });

  describe('Stats Processing', () => {
    it('processes channel stats correctly', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(getStatsByChannelId).toHaveBeenCalledWith(
          mockChannelStats,
          expect.any(Object),
          mockChannelsByUUID,
          mockChannels,
          mockStreamProfiles
        );
      });
    });

    it('updates clients based on processed stats', async () => {
      render(<StatsPage />);

      await waitFor(() => {
        expect(getClientStats).toHaveBeenCalledWith(
          mockProcessedChannelHistory
        );
      });
    });
  });

  describe('Error Handling', () => {
    it('handles fetchActiveChannelStats error gracefully', async () => {
      const consoleError = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      fetchActiveChannelStats.mockRejectedValue(new Error('API Error'));

      render(<StatsPage />);

      await waitFor(() => {
        expect(consoleError).toHaveBeenCalledWith(
          'Error fetching channel stats:',
          expect.any(Error)
        );
      });

      consoleError.mockRestore();
    });

    it('handles getVODStats error gracefully', async () => {
      const consoleError = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      getVODStats.mockRejectedValue(new Error('VOD API Error'));

      render(<StatsPage />);

      await waitFor(() => {
        expect(consoleError).toHaveBeenCalledWith(
          'Error fetching VOD stats:',
          expect.any(Error)
        );
      });

      consoleError.mockRestore();
    });
  });

  describe('Connection Count Display', () => {
    it('displays singular form for 1 stream', async () => {
      getCombinedConnections.mockReturnValue([
        { id: 1, type: 'stream', data: { id: 1, uuid: 'channel-1' } },
      ]);
      getStatsByChannelId.mockReturnValue({ 1: { id: 1, uuid: 'channel-1' } });

      render(<StatsPage />);

      await waitFor(() => {
        expect(screen.getByText(/1 stream/)).toBeInTheDocument();
      });
    });

    it('displays plural form for multiple VOD connections', async () => {
      const multiVODStats = {
        vod_connections: [
          { content_uuid: 'vod-1', connections: [{ client_id: 'c1' }] },
          { content_uuid: 'vod-2', connections: [{ client_id: 'c2' }] },
        ],
      };
      getVODStats.mockResolvedValue(multiVODStats);

      render(<StatsPage />);

      await waitFor(() => {
        expect(screen.getByText(/2 VOD connections/)).toBeInTheDocument();
      });
    });
  });
});
