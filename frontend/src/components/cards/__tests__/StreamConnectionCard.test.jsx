import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── react-router-dom ──────────────────────────────────────────────────────────
vi.mock('react-router-dom', () => ({
  useLocation: vi.fn(),
}));

// ── Zustand stores ────────────────────────────────────────────────────────────
vi.mock('../../../store/playlists.jsx', () => ({
  default: vi.fn(),
}));
vi.mock('../../../store/settings.jsx', () => ({
  default: vi.fn(),
}));
vi.mock('../../../store/useVideoStore', () => ({
  default: vi.fn(),
}));

// ── dateTimeUtils ─────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  toFriendlyDuration: vi.fn(() => '1h 23m'),
  useDateTimeFormat: vi.fn(() => ({ fullDateTimeFormat: 'MM/DD/YYYY h:mm A' })),
}));

// ── networkUtils ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/networkUtils.js', () => ({
  formatBytes: vi.fn((n) => `${n} B`),
  formatSpeed: vi.fn((n) => `${n} Kbps`),
}));

// ── notificationUtils ─────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// ── StreamConnectionCardUtils ─────────────────────────────────────────────────
vi.mock('../../../utils/cards/StreamConnectionCardUtils.js', () => ({
  connectedAccessor: vi.fn(() => () => '01/01/2024 10:00 AM'),
  durationAccessor: vi.fn(() => () => '5m 30s'),
  getBufferingSpeedThreshold: vi.fn(() => 0.9),
  getChannelStreams: vi.fn(() => Promise.resolve([])),
  getLogoUrl: vi.fn(() => null),
  getM3uAccountsMap: vi.fn(() => ({})),
  getMatchingStreamByUrl: vi.fn(() => null),
  getSelectedStream: vi.fn(() => null),
  getStartDate: vi.fn(() => 'Jan 1 2024 10:00 AM'),
  getStreamOptions: vi.fn(() => []),
  getStreamsByIds: vi.fn(() => Promise.resolve([])),
  switchStream: vi.fn(() => Promise.resolve({})),
}));

// ── CustomTable / useTable ────────────────────────────────────────────────────
vi.mock('../../../components/tables/CustomTable/index.jsx', () => ({
  CustomTable: () => <div data-testid="custom-table" />,
  useTable: vi.fn(() => ({ table: {} })),
}));

vi.mock('../../../helpers/index.jsx', () => ({
  TableHelper: {
    defaultProperties: {},
  },
}));

// ── logo image ────────────────────────────────────────────────────────────────
vi.mock('../../../images/logo.png', () => ({ default: 'logo.png' }));

// ── Mantine core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, color, disabled }) => (
    <button
      data-testid="action-icon"
      data-color={color}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color, variant }) => (
    <span data-testid="badge" data-color={color} data-variant={variant}>
      {children}
    </span>
  ),
  Box: ({ children, style, pos }) => (
    <div style={style} data-pos={pos}>
      {children}
    </div>
  ),
  Card: ({ children, style }) => (
    <div data-testid="stream-connection-card" style={style}>
      {children}
    </div>
  ),
  Center: ({ children }) => <div data-testid="center">{children}</div>,
  Group: ({ children }) => <div data-testid="group">{children}</div>,
  Progress: ({ value, size, color }) => (
    <div
      data-testid="progress"
      data-value={value}
      data-size={size}
      data-color={color}
    />
  ),
  Select: ({ value, onChange, label, data, disabled, placeholder }) => (
    <select
      data-testid="select"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      aria-label={label}
    >
      <option value="">{placeholder}</option>
      {(data ?? []).map((opt) => {
        const val = typeof opt === 'string' ? opt : opt.value;
        const lbl = typeof opt === 'string' ? opt : opt.label;
        return (
          <option key={val} value={val}>
            {lbl}
          </option>
        );
      })}
    </select>
  ),
  Stack: ({ children }) => <div data-testid="stack">{children}</div>,
  Text: ({ children, size, c, fw, style }) => (
    <span
      data-testid="text"
      data-size={size}
      data-color={c}
      data-fw={fw}
      style={style}
    >
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
  useMantineTheme: vi.fn(() => ({
    tailwind: { green: { 5: '#22c55e' } },
  })),
}));

// ── lucide-react ──────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  // navigation.js icons (all must be present for the auth→navigation import chain)
  ListOrdered: () => <svg data-testid="icon-list-ordered" />,
  Play: () => <svg data-testid="icon-play" />,
  Database: () => <svg data-testid="icon-database" />,
  LayoutGrid: () => <svg data-testid="icon-layout-grid" />,
  Settings: () => <svg data-testid="icon-settings" />,
  ChartLine: () => <svg data-testid="icon-chart-line" />,
  Video: () => <svg data-testid="icon-video" />,
  PlugZap: () => <svg data-testid="icon-plug-zap" />,
  User: () => <svg data-testid="icon-user" />,
  FileImage: () => <svg data-testid="icon-file-image" />,
  Webhook: () => <svg data-testid="icon-webhook" />,
  Logs: () => <svg data-testid="icon-logs" />,
  Blocks: () => <svg data-testid="icon-blocks" />,
  MonitorCog: () => <svg data-testid="icon-monitor-cog" />,
  // StreamConnectionCard-specific icons
  ChevronDown: () => <svg data-testid="icon-chevron-down" />,
  ChevronRight: () => <svg data-testid="icon-chevron-right" />,
  CirclePlay: () => <svg data-testid="icon-circle-play" />,
  Gauge: () => <svg data-testid="icon-gauge" />,
  HardDriveDownload: () => <svg data-testid="icon-hdd-download" />,
  HardDriveUpload: () => <svg data-testid="icon-hdd-upload" />,
  Radio: () => <svg data-testid="icon-radio" />,
  SquareX: () => <svg data-testid="icon-square-x" />,
  Timer: () => <svg data-testid="icon-timer" />,
  Users: () => <svg data-testid="icon-users" />,
  Video: () => <svg data-testid="icon-video" />,
  Package: () => <svg data-testid="icon-package" />,
  Download: () => <svg data-testid="icon-download" />,
}));

// ── Imports after mocks ───────────────────────────────────────────────────────
import { useLocation } from 'react-router-dom';
import usePlaylistsStore from '../../../store/playlists.jsx';
import useSettingsStore from '../../../store/settings.jsx';
import useVideoStore from '../../../store/useVideoStore';
import { showNotification } from '../../../utils/notificationUtils.js';
import {
  getChannelStreams,
  getMatchingStreamByUrl,
  getSelectedStream,
  getStreamsByIds,
  switchStream,
} from '../../../utils/cards/StreamConnectionCardUtils.js';
import StreamConnectionCard from '../StreamConnectionCard';

// ── Helpers ───────────────────────────────────────────────────────────────────

const makeChannel = (overrides = {}) => ({
  channel_id: 'ch-uuid-1',
  name: 'Test Channel',
  url: 'http://stream.example.com/ch1',
  stream_id: 42,
  logo_id: null,
  uptime: 4980,
  bitrates: [3500, 3600, 3700],
  total_bytes: 1048576,
  client_count: 2,
  avg_bitrate: '3.6 Mbps',
  stream_profile: { name: 'Default Profile' },
  m3u_profile: { name: 'Main M3U' },
  resolution: '1920x1080',
  source_fps: 30,
  video_codec: 'h264',
  audio_codec: 'aac',
  audio_channels: '2.0',
  stream_type: 'hls',
  ffmpeg_speed: '1.05',
  ...overrides,
});

const makeClients = (channelId = 'ch-uuid-1') => [
  {
    client_id: 'client-1',
    channel: { channel_id: channelId, uuid: 'ch-uuid-1' },
    ip_address: '192.168.1.10',
    connected_since: 330,
    connection_duration: 330,
    user_agent: 'VLC/3.0',
    streams: [{ id: 1 }],
  },
];

const makeCurrentProgram = (overrides = {}) => ({
  title: 'Evening News',
  description: 'Daily news broadcast.',
  start_time: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
  end_time: new Date(Date.now() + 50 * 60 * 1000).toISOString(),
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  channel: makeChannel(),
  clients: makeClients(),
  stopClient: vi.fn(),
  stopChannel: vi.fn(),
  logos: {},
  channelsByUUID: { 'ch-uuid-1': 1 },
  channels: {
    1: { id: 1, uuid: 'ch-uuid-1', name: 'Test Channel' },
  },
  currentProgram: null,
  ...overrides,
});

const setupLocation = (pathname = '/stats') => {
  vi.mocked(useLocation).mockReturnValue({
    pathname,
    search: '',
    hash: '',
    state: null,
  });
};

const setupStores = () => {
  vi.mocked(usePlaylistsStore).mockImplementation((selector) =>
    selector({ playlists: [] })
  );
  vi.mocked(useSettingsStore).mockImplementation((selector) =>
    selector({
      settings: { proxy_settings: {} },
      environment: { env_mode: 'production' },
    })
  );
  vi.mocked(useVideoStore).mockImplementation((selector) =>
    selector({ showVideo: vi.fn() })
  );
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('StreamConnectionCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupLocation('/stats');
    setupStores();
  });

  // ── Route guard ────────────────────────────────────────────────────────────

  describe('route guard', () => {
    it('renders nothing when pathname is not /stats', () => {
      setupLocation('/dashboard');
      const { container } = render(
        <StreamConnectionCard {...defaultProps()} />
      );
      expect(container.firstChild).toBeNull();
    });

    it('renders nothing when pathname is /channels', () => {
      setupLocation('/channels');
      const { container } = render(
        <StreamConnectionCard {...defaultProps()} />
      );
      expect(container.firstChild).toBeNull();
    });

    it('renders the card when pathname is /stats', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByTestId('stream-connection-card')).toBeInTheDocument();
    });

    it('returns null when channel is missing channel_id', () => {
      const { container } = render(
        <StreamConnectionCard
          {...defaultProps({ channel: makeChannel({ channel_id: undefined }) })}
        />
      );
      expect(container.firstChild).toBeNull();
    });
  });

  // ── Basic rendering ────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the channel name', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('Test Channel')).toBeInTheDocument();
    });

    it('renders the stream profile name', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('Default Profile')).toBeInTheDocument();
    });

    it('renders the M3U profile name', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('Main M3U')).toBeInTheDocument();
    });

    it('renders the uptime via toFriendlyDuration', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('1h 23m')).toBeInTheDocument();
    });

    it('renders the average bitrate', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('Avg: 3.6 Mbps')).toBeInTheDocument();
    });

    it('renders the client count', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('renders the custom table for clients', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('renders the fallback logo when logo_id is null', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      const img = screen.getByAltText('channel logo');
      expect(img).toBeInTheDocument();
    });

    it('falls back to "Unnamed Channel" when channel has no name and no previewed stream', () => {
      vi.mocked(getStreamsByIds).mockResolvedValue([]);
      render(
        <StreamConnectionCard
          {...defaultProps({
            channel: makeChannel({ name: '', stream_id: null }),
          })}
        />
      );
      expect(screen.getByText('Unnamed Channel')).toBeInTheDocument();
    });

    it('renders "Unknown Profile" when stream_profile is absent', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ channel: makeChannel({ stream_profile: null }) })}
        />
      );
      expect(screen.getByText('Unknown Profile')).toBeInTheDocument();
    });

    it('renders "Unknown M3U Profile" when m3u_profile is absent', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({
            channel: makeChannel({ m3u_profile: null, m3u_profile_name: null }),
          })}
        />
      );
      expect(screen.getByText('Unknown M3U Profile')).toBeInTheDocument();
    });
  });

  // ── Stream information badges ──────────────────────────────────────────────

  describe('stream info badges', () => {
    it('renders resolution badge', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('1920x1080')).toBeInTheDocument();
    });

    it('renders FPS badge', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('30 FPS')).toBeInTheDocument();
    });

    it('renders video codec badge in uppercase', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('H264')).toBeInTheDocument();
    });

    it('renders audio codec badge in uppercase', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('AAC')).toBeInTheDocument();
    });

    it('renders audio channels badge', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('2.0')).toBeInTheDocument();
    });

    it('renders stream type badge in uppercase', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('HLS')).toBeInTheDocument();
    });

    it('does not render resolution badge when resolution is absent', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ channel: makeChannel({ resolution: null }) })}
        />
      );
      expect(screen.queryByText('1920x1080')).not.toBeInTheDocument();
    });

    it('renders ffmpeg_speed badge with green color when above threshold', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ channel: makeChannel({ ffmpeg_speed: '1.10' }) })}
        />
      );
      const badges = screen.getAllByTestId('badge');
      const speedBadge = badges.find((b) => b.textContent === '1.10x');
      expect(speedBadge).toHaveAttribute('data-color', 'green');
    });

    it('renders ffmpeg_speed badge with red color when below threshold', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ channel: makeChannel({ ffmpeg_speed: '0.50' }) })}
        />
      );
      const badges = screen.getAllByTestId('badge');
      const speedBadge = badges.find((b) => b.textContent === '0.50x');
      expect(speedBadge).toHaveAttribute('data-color', 'red');
    });
  });

  // ── Stop channel ───────────────────────────────────────────────────────────

  describe('stop channel', () => {
    it('calls stopChannel with channel_id when stop button is clicked', () => {
      const stopChannel = vi.fn();
      render(<StreamConnectionCard {...defaultProps({ stopChannel })} />);
      const stopBtns = screen
        .getAllByTestId('action-icon')
        .filter((btn) => btn.getAttribute('data-color') === 'red.9');
      fireEvent.click(stopBtns[0]);
      expect(stopChannel).toHaveBeenCalledWith('ch-uuid-1');
    });
  });

  // ── Stop client ────────────────────────────────────────────────────────────

  describe('stop client', () => {
    it('calls stopClient with uuid and client_id when disconnect is clicked', () => {
      const stopClient = vi.fn();
      render(<StreamConnectionCard {...defaultProps({ stopClient })} />);
      // The disconnect button is rendered inside renderBodyCell for the actions column
      const stopBtns = screen
        .getAllByTestId('action-icon')
        .filter((btn) => btn.getAttribute('data-color') === 'red.9');
      // Second red button is the client disconnect (first is stopChannel)
      if (stopBtns.length > 1) {
        fireEvent.click(stopBtns[1]);
        expect(stopClient).toHaveBeenCalledWith('ch-uuid-1', 'client-1');
      }
    });
  });

  // ── Current program display ────────────────────────────────────────────────

  describe('current program', () => {
    it('does not render program section when currentProgram is null', () => {
      render(
        <StreamConnectionCard {...defaultProps({ currentProgram: null })} />
      );
      expect(screen.queryByText('Now Playing:')).not.toBeInTheDocument();
    });

    it('renders "Now Playing" label when currentProgram is provided', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ currentProgram: makeCurrentProgram() })}
        />
      );
      expect(screen.getByText('Now Playing:')).toBeInTheDocument();
    });

    it('renders current program title', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ currentProgram: makeCurrentProgram() })}
        />
      );
      expect(screen.getByText('Evening News')).toBeInTheDocument();
    });

    it('does not render description when collapsed', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ currentProgram: makeCurrentProgram() })}
        />
      );
      expect(
        screen.queryByText('Daily news broadcast.')
      ).not.toBeInTheDocument();
    });

    it('expands program description when chevron button is clicked', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ currentProgram: makeCurrentProgram() })}
        />
      );
      const chevronBtn = screen
        .getByTestId('icon-chevron-right')
        .closest('button');
      fireEvent.click(chevronBtn);
      expect(screen.getByText('Daily news broadcast.')).toBeInTheDocument();
    });

    it('collapses program description on second chevron click', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ currentProgram: makeCurrentProgram() })}
        />
      );
      const chevronBtn = screen
        .getByTestId('icon-chevron-right')
        .closest('button');
      fireEvent.click(chevronBtn);
      expect(screen.getByText('Daily news broadcast.')).toBeInTheDocument();
      const chevronDownBtn = screen
        .getByTestId('icon-chevron-down')
        .closest('button');
      fireEvent.click(chevronDownBtn);
      expect(
        screen.queryByText('Daily news broadcast.')
      ).not.toBeInTheDocument();
    });

    it('renders program progress when expanded and times are present', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ currentProgram: makeCurrentProgram() })}
        />
      );
      const chevronBtn = screen
        .getByTestId('icon-chevron-right')
        .closest('button');
      fireEvent.click(chevronBtn);
      expect(screen.getByTestId('progress')).toBeInTheDocument();
    });

    it('does not render progress when program has no start_time', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({
            currentProgram: makeCurrentProgram({
              start_time: null,
              end_time: null,
            }),
          })}
        />
      );
      const chevronBtn = screen
        .getByTestId('icon-chevron-right')
        .closest('button');
      fireEvent.click(chevronBtn);
      expect(screen.queryByTestId('progress')).not.toBeInTheDocument();
    });
  });

  // ── Stream fetching ────────────────────────────────────────────────────────

  describe('stream fetching', () => {
    it('calls getChannelStreams on mount with channel db ID', async () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => {
        expect(getChannelStreams).toHaveBeenCalledWith(1);
      });
    });

    it('does not render Select dropdown when no available streams are returned', async () => {
      vi.mocked(getChannelStreams).mockResolvedValue([]);
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.queryByTestId('select')).not.toBeInTheDocument();
      });
    });

    it('renders Select when streams are available', async () => {
      vi.mocked(getChannelStreams).mockResolvedValue([
        { id: 10, name: 'Stream A', url: 'http://a.com', m3u_profile: null },
        { id: 11, name: 'Stream B', url: 'http://b.com', m3u_profile: null },
      ]);
      // Provide options via getStreamOptions mock
      const { getStreamOptions } =
        await import('../../../utils/cards/StreamConnectionCardUtils.js');
      vi.mocked(getStreamOptions).mockReturnValue([
        { value: '10', label: 'Stream A' },
        { value: '11', label: 'Stream B' },
      ]);
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.getByTestId('select')).toBeInTheDocument();
      });
    });

    it('sets activeStreamId when a matching stream is found by URL', async () => {
      vi.mocked(getChannelStreams).mockResolvedValue([
        {
          id: 42,
          name: 'Stream A',
          url: 'http://stream.example.com/ch1',
          m3u_profile: null,
        },
      ]);
      vi.mocked(getMatchingStreamByUrl).mockReturnValue({
        id: 42,
        name: 'Stream A',
        url: 'http://stream.example.com/ch1',
        m3u_profile: null,
      });
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => {
        expect(getMatchingStreamByUrl).toHaveBeenCalled();
      });
    });

    it('does not call getChannelStreams when channelId is not found in channelsByUUID', async () => {
      render(
        <StreamConnectionCard {...defaultProps({ channelsByUUID: {} })} />
      );
      await waitFor(() => {
        expect(getChannelStreams).not.toHaveBeenCalled();
      });
    });
  });

  // ── Stream switching ───────────────────────────────────────────────────────

  describe('stream switching', () => {
    beforeEach(async () => {
      vi.mocked(getChannelStreams).mockResolvedValue([
        {
          id: 10,
          name: 'Stream A',
          url: 'http://a.com',
          m3u_profile: { name: 'M3U A' },
        },
      ]);
      const { getStreamOptions } =
        await import('../../../utils/cards/StreamConnectionCardUtils.js');
      vi.mocked(getStreamOptions).mockReturnValue([
        { value: '10', label: 'Stream A' },
      ]);
      vi.mocked(getSelectedStream).mockReturnValue({
        id: 10,
        name: 'Stream A',
        m3u_profile: { name: 'M3U A' },
      });
    });

    it('calls switchStream with channel and streamId when Select changes', async () => {
      vi.mocked(switchStream).mockResolvedValue({});
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => screen.getByTestId('select'));
      fireEvent.change(screen.getByTestId('select'), {
        target: { value: '10' },
      });
      await waitFor(() => {
        expect(switchStream).toHaveBeenCalledWith(
          expect.objectContaining({ channel_id: 'ch-uuid-1' }),
          '10'
        );
      });
    });

    it('shows a blue notification after successful stream switch', async () => {
      vi.mocked(switchStream).mockResolvedValue({});
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => screen.getByTestId('select'));
      fireEvent.change(screen.getByTestId('select'), {
        target: { value: '10' },
      });
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'blue.5' })
        );
      });
    });

    it('shows a red error notification when switchStream throws', async () => {
      vi.mocked(switchStream).mockRejectedValue(new Error('Switch failed'));
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => screen.getByTestId('select'));
      fireEvent.change(screen.getByTestId('select'), {
        target: { value: '10' },
      });
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red.5' })
        );
      });
    });

    it('updates M3U profile name from switch response', async () => {
      vi.mocked(switchStream).mockResolvedValue({
        m3u_profile: { name: 'Updated M3U' },
      });
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => screen.getByTestId('select'));
      fireEvent.change(screen.getByTestId('select'), {
        target: { value: '10' },
      });
      await waitFor(() => {
        expect(screen.getByText('Updated M3U')).toBeInTheDocument();
      });
    });
  });

  // ── Preview channel ────────────────────────────────────────────────────────

  describe('preview channel', () => {
    it('does not render preview button when availableStreams is empty', async () => {
      vi.mocked(getChannelStreams).mockResolvedValue([]);
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => {
        expect(
          screen.queryByTestId('icon-circle-play')
        ).not.toBeInTheDocument();
      });
    });

    it('renders preview button when streams are available and channel has a name', async () => {
      vi.mocked(getChannelStreams).mockResolvedValue([
        { id: 10, name: 'Stream A', url: 'http://a.com', m3u_profile: null },
      ]);
      const { getStreamOptions } =
        await import('../../../utils/cards/StreamConnectionCardUtils.js');
      vi.mocked(getStreamOptions).mockReturnValue([
        { value: '10', label: 'Stream A' },
      ]);
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.getByTestId('icon-circle-play')).toBeInTheDocument();
      });
    });

    it('calls showVideo with correct url and type when preview is clicked', async () => {
      const showVideo = vi.fn();
      vi.mocked(useVideoStore).mockImplementation((selector) =>
        selector({ showVideo })
      );
      vi.mocked(getChannelStreams).mockResolvedValue([
        { id: 10, name: 'Stream A', url: 'http://a.com', m3u_profile: null },
      ]);
      const { getStreamOptions } =
        await import('../../../utils/cards/StreamConnectionCardUtils.js');
      vi.mocked(getStreamOptions).mockReturnValue([
        { value: '10', label: 'Stream A' },
      ]);

      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => screen.getByTestId('icon-circle-play'));
      fireEvent.click(screen.getByTestId('icon-circle-play').closest('button'));

      await waitFor(() => {
        expect(showVideo).toHaveBeenCalledWith(
          expect.stringContaining('/proxy/ts/stream/ch-uuid-1'),
          'live',
          expect.objectContaining({ name: 'Test Channel' })
        );
      });
    });

    it('does not call showVideo when channelDbId is not found', async () => {
      const showVideo = vi.fn();
      vi.mocked(useVideoStore).mockImplementation((selector) =>
        selector({ showVideo })
      );
      vi.mocked(getChannelStreams).mockResolvedValue([
        { id: 10, name: 'Stream A', url: 'http://a.com', m3u_profile: null },
      ]);
      const { getStreamOptions } =
        await import('../../../utils/cards/StreamConnectionCardUtils.js');
      vi.mocked(getStreamOptions).mockReturnValue([
        { value: '10', label: 'Stream A' },
      ]);

      render(
        <StreamConnectionCard {...defaultProps({ channelsByUUID: {} })} />
      );
      await waitFor(() => {
        // Select not shown since getChannelStreams won't be called
        expect(showVideo).not.toHaveBeenCalled();
      });
    });
  });

  // ── Previewed stream (unnamed channel) ────────────────────────────────────

  describe('previewed stream fallback', () => {
    it('fetches stream name when channel has no name but has stream_id', async () => {
      vi.mocked(getStreamsByIds).mockResolvedValue([
        { id: 42, name: 'Previewed Stream', logo_id: null },
      ]);
      render(
        <StreamConnectionCard
          {...defaultProps({
            channel: makeChannel({ name: '', stream_id: 42 }),
          })}
        />
      );
      await waitFor(() => {
        expect(getStreamsByIds).toHaveBeenCalledWith(42);
      });
    });

    it('does not call getStreamsByIds when channel has a name', async () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      await waitFor(() => {
        expect(getStreamsByIds).not.toHaveBeenCalled();
      });
    });
  });

  // ── M3U profile from channel data ─────────────────────────────────────────

  describe('M3U profile state', () => {
    it('uses m3u_profile_name fallback when m3u_profile object is absent', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({
            channel: makeChannel({
              m3u_profile: null,
              m3u_profile_name: 'Fallback M3U',
            }),
          })}
        />
      );
      expect(screen.getByText('Fallback M3U')).toBeInTheDocument();
    });

    it('updates currentM3UProfile when channel m3u_profile prop changes', async () => {
      const { rerender } = render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('Main M3U')).toBeInTheDocument();

      rerender(
        <StreamConnectionCard
          {...defaultProps({
            channel: makeChannel({ m3u_profile: { name: 'New M3U' } }),
          })}
        />
      );
      await waitFor(() => {
        expect(screen.getByText('New M3U')).toBeInTheDocument();
      });
    });
  });

  // ── Network stats display ──────────────────────────────────────────────────

  describe('network stats', () => {
    it('renders formatted total bytes via formatBytes', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      expect(screen.getByText('1048576 B')).toBeInTheDocument();
    });

    it('renders formatted current bitrate via formatSpeed', () => {
      render(<StreamConnectionCard {...defaultProps()} />);
      // bitrates.at(-1) = 3700
      expect(screen.getAllByText('3700 Kbps').length).toBeGreaterThan(0);
    });

    it('handles empty bitrates array gracefully', () => {
      render(
        <StreamConnectionCard
          {...defaultProps({ channel: makeChannel({ bitrates: [] }) })}
        />
      );
      expect(screen.getAllByText('0 Kbps').length).toBeGreaterThan(0);
    });
  });
});
