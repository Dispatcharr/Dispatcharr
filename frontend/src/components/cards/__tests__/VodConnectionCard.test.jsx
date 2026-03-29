import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── dateTimeUtils ─────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  convertToSec: vi.fn((val) => (val ? Number(val) : 0)),
  fromNow: vi.fn(() => '5 minutes ago'),
  toFriendlyDuration: vi.fn((secs) => (secs ? `${secs}s` : null)),
  useDateTimeFormat: vi.fn(() => ({ fullDateTimeFormat: 'MM/DD/YYYY h:mm A' })),
}));

// ── VodConnectionCardUtils ────────────────────────────────────────────────────
vi.mock('../../../utils/cards/VodConnectionCardUtils.js', () => ({
  calculateConnectionDuration: vi.fn(() => '5m 30s'),
  calculateConnectionStartTime: vi.fn(() => 'Jan 1 2024 10:00 AM'),
  calculateProgress: vi.fn(() => ({
    totalTime: 0,
    currentTime: 0,
    percentage: 0,
  })),
  formatDuration: vi.fn((secs) => (secs ? `${secs}s` : null)),
  formatTime: vi.fn((secs) => `${secs}s`),
  getEpisodeDisplayTitle: vi.fn(() => 'S01E02 — Pilot'),
  getEpisodeSubtitle: vi.fn(() => ['Test Series', 'Season 1']),
  getMovieDisplayTitle: vi.fn(() => 'Test Movie (2022)'),
  getMovieSubtitle: vi.fn(() => ['120m', 'Action']),
}));

// ── logo ──────────────────────────────────────────────────────────────────────
vi.mock('../../../images/logo.png', () => ({ default: 'default-logo.png' }));

// ── Mantine core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, color, variant }) => (
    <button
      data-testid="action-icon"
      data-color={color}
      data-variant={variant}
      onClick={onClick}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color, variant, size }) => (
    <span
      data-testid="badge"
      data-color={color}
      data-variant={variant}
      data-size={size}
    >
      {children}
    </span>
  ),
  Box: ({ children, style }) => (
    <div data-testid="box" style={style}>
      {children}
    </div>
  ),
  Card: (
    { children, shadow, style } // remove padding, radius, withBorder
  ) => (
    <div data-testid="vod-connection-card" data-shadow={shadow} style={style}>
      {children}
    </div>
  ),
  Center: ({ children }) => <div data-testid="center">{children}</div>,
  Flex: (
    { children, justify } // remove align
  ) => (
    <div data-testid="flex" data-justify={justify}>
      {children}
    </div>
  ),
  Group: (
    { children, justify, onClick, style } // remove gap, align, p
  ) => (
    <div
      data-testid="group"
      data-justify={justify}
      onClick={onClick}
      style={style}
    >
      {children}
    </div>
  ),
  Progress: ({ value, size, color }) => (
    <div
      data-testid="progress"
      data-value={value}
      data-size={size}
      data-color={color}
    />
  ),
  Stack: ({ children, gap, pos, mt }) => (
    <div data-testid="stack" data-gap={gap} data-pos={pos} data-mt={mt}>
      {children}
    </div>
  ),
  Text: (
    { children, size, c, fw, color } // remove ff, ta
  ) => (
    <span
      data-testid="text"
      data-size={size}
      data-c={c}
      data-fw={fw}
      data-color={color}
    >
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => (
    <div data-testid="tooltip" data-label={label}>
      {children}
    </div>
  ),
}));

// ── useUsersStore ─────────────────────────────────────────────────────────────
vi.mock('../../../store/users.jsx', () => ({
  default: vi.fn((selector) => selector({ users: [] })),
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
  // VodConnectionCard-specific icons
  ChevronDown: ({ size, style }) => (
    <svg data-testid="icon-chevron-down" data-size={size} style={style} />
  ),
  HardDriveUpload: () => <svg data-testid="icon-hdd-upload" />,
  SquareX: () => <svg data-testid="icon-square-x" />,
  Timer: () => <svg data-testid="icon-timer" />,
}));

// ── Imports after mocks ───────────────────────────────────────────────────────
import { useDateTimeFormat } from '../../../utils/dateTimeUtils.js';
import {
  calculateProgress,
  getEpisodeDisplayTitle,
  getEpisodeSubtitle,
  getMovieDisplayTitle,
  getMovieSubtitle,
  calculateConnectionDuration,
  calculateConnectionStartTime,
} from '../../../utils/cards/VodConnectionCardUtils.js';
import VodConnectionCard from '../VodConnectionCard';

// ── Helpers ───────────────────────────────────────────────────────────────────

const makeConnection = (overrides = {}) => ({
  client_ip: '192.168.1.100',
  client_id: 'client-abc-123', // needed for stopVODClient
  user_agent: 'Plex/1.0',
  connected_at: '2024-01-01T10:00:00Z',
  duration: 330,
  bytes_sent: 1048576,
  m3u_profile: {
    // M3U profile lives on connection
    account_name: 'Main Account',
    profile_name: 'Main M3U',
  },
  ...overrides,
});

const makeMovieContent = (overrides = {}) => ({
  content_type: 'movie',
  content_name: 'Test Movie',
  content_metadata: {
    logo_url: 'http://example.com/poster.jpg',
    duration_secs: 7200,
    year: 2022,
    rating: 8.5,
    genres: ['Action', 'Drama'],
    resolution: '1920x1080',
    m3u_profile: { name: 'Main M3U' },
  },
  individual_connection: makeConnection(),
  ...overrides,
});

const makeEpisodeContent = (overrides = {}) => ({
  content_type: 'episode',
  content_name: 'Pilot',
  content_metadata: {
    logo_url: 'http://example.com/ep-poster.jpg',
    duration_secs: 2700,
    series_name: 'Test Series',
    season: 1,
    episode: 2,
    m3u_profile: { name: 'Main M3U' },
  },
  individual_connection: makeConnection(),
  ...overrides,
});

const makeUnknownContent = (overrides = {}) => ({
  content_type: 'unknown',
  content_name: 'Some Stream',
  content_metadata: {
    logo_url: null,
    duration_secs: null,
    m3u_profile: null,
  },
  individual_connection: makeConnection(),
  ...overrides,
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('VodConnectionCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.mocked(useDateTimeFormat).mockReturnValue({
      fullDateTimeFormat: 'MM/DD/YYYY h:mm A',
    });
    vi.mocked(calculateProgress).mockReturnValue({
      totalTime: 0,
      currentTime: 0,
      percentage: 0,
    });
    vi.mocked(getMovieDisplayTitle).mockReturnValue('Test Movie (2022)');
    vi.mocked(getMovieSubtitle).mockReturnValue(['120m', 'Action']);
    vi.mocked(getEpisodeDisplayTitle).mockReturnValue('S01E02 — Pilot');
    vi.mocked(getEpisodeSubtitle).mockReturnValue(['Test Series', 'Season 1']);
    vi.mocked(calculateConnectionDuration).mockReturnValue('5m 30s');
    vi.mocked(calculateConnectionStartTime).mockReturnValue(
      'Jan 1 2024 10:00 AM'
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ── Basic rendering ────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the card element', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByTestId('vod-connection-card')).toBeInTheDocument();
    });

    it('renders the poster image when logo_url is present', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByRole('img')).toHaveAttribute(
        'src',
        'http://example.com/poster.jpg'
      );
    });

    it('renders the default logo when logo_url is absent', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent({
            content_metadata: { logo_url: null },
          })}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByRole('img')).toHaveAttribute(
        'src',
        'default-logo.png'
      );
    });

    it('renders the stop client button', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByTestId('icon-square-x')).toBeInTheDocument();
    });

    it('renders the client IP in the connection section', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('192.168.1.100')).toBeInTheDocument();
    });

    it('renders "Unknown IP" when client_ip is absent', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent({
            individual_connection: makeConnection({ client_ip: null }),
          })}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('Unknown IP')).toBeInTheDocument();
    });

    it('renders "Hide Details" / "Show Details" toggle text', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('Show Details')).toBeInTheDocument();
    });

    it('does not render client section when no connection is present', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent({
            individual_connection: null,
            connections: null,
          })}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.queryByText('Client:')).not.toBeInTheDocument();
    });
  });

  // ── Movie rendering ────────────────────────────────────────────────────────

  describe('movie content', () => {
    it('calls getMovieDisplayTitle with vodContent', () => {
      const vodContent = makeMovieContent();
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(getMovieDisplayTitle).toHaveBeenCalledWith(vodContent);
    });

    it('renders the movie display title', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('Test Movie (2022)')).toBeInTheDocument();
    });

    it('calls getMovieSubtitle with metadata', () => {
      const vodContent = makeMovieContent();
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(getMovieSubtitle).toHaveBeenCalledWith(
        vodContent.content_metadata
      );
    });

    it('renders the movie subtitle parts', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText(/120m/)).toBeInTheDocument();
      expect(screen.getByText(/Action/)).toBeInTheDocument();
    });

    it('does not call getEpisodeDisplayTitle for a movie', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(getEpisodeDisplayTitle).not.toHaveBeenCalled();
    });
  });

  // ── Episode rendering ──────────────────────────────────────────────────────

  describe('episode content', () => {
    it('calls getEpisodeDisplayTitle with vodContent', () => {
      const vodContent = makeEpisodeContent();
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(getEpisodeDisplayTitle).toHaveBeenCalledWith(
        vodContent.content_metadata
      );
    });

    it('renders the episode display title', () => {
      render(
        <VodConnectionCard
          vodContent={makeEpisodeContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('S01E02 — Pilot')).toBeInTheDocument();
    });

    it('calls getEpisodeSubtitle with metadata', () => {
      const vodContent = makeEpisodeContent();
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(getEpisodeSubtitle).toHaveBeenCalledWith(
        vodContent.content_metadata
      );
    });

    it('renders the episode subtitle parts', () => {
      render(
        <VodConnectionCard
          vodContent={makeEpisodeContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText(/Test Series/)).toBeInTheDocument();
      expect(screen.getByText(/Season 1/)).toBeInTheDocument();
    });

    it('does not call getMovieDisplayTitle for an episode', () => {
      render(
        <VodConnectionCard
          vodContent={makeEpisodeContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(getMovieDisplayTitle).not.toHaveBeenCalled();
    });
  });

  // ── Unknown / fallback content type ───────────────────────────────────────

  describe('unknown content type', () => {
    it('renders content_name as fallback title', () => {
      render(
        <VodConnectionCard
          vodContent={makeUnknownContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('Some Stream')).toBeInTheDocument();
    });

    it('does not call getMovieDisplayTitle or getEpisodeDisplayTitle', () => {
      render(
        <VodConnectionCard
          vodContent={makeUnknownContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(getMovieDisplayTitle).not.toHaveBeenCalled();
      expect(getEpisodeDisplayTitle).not.toHaveBeenCalled();
    });

    it('renders no subtitle when subtitle parts are empty', () => {
      vi.mocked(getMovieSubtitle).mockReturnValue([]);
      vi.mocked(getEpisodeSubtitle).mockReturnValue([]);
      render(
        <VodConnectionCard
          vodContent={makeUnknownContent()}
          stopVODClient={vi.fn()}
        />
      );
      // No " • " separator rendered for empty subtitle
      expect(screen.queryByText(' • ')).not.toBeInTheDocument();
    });
  });

  // ── connections fallback ───────────────────────────────────────────────────

  describe('connection source fallback', () => {
    it('uses individual_connection when present', () => {
      const vodContent = makeMovieContent();
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(screen.getByText('192.168.1.100')).toBeInTheDocument();
    });

    it('falls back to connections[0] when individual_connection is null', () => {
      const connection = makeConnection({ client_ip: '10.0.0.1' });
      const vodContent = makeMovieContent({
        individual_connection: null,
        connections: [connection],
      });
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(screen.getByText('10.0.0.1')).toBeInTheDocument();
    });
  });

  // ── M3U profile ────────────────────────────────────────────────────────────

  describe('M3U profile', () => {
    it('renders M3U profile name when present', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('Main M3U')).toBeInTheDocument();
    });

    it('does not render M3U profile section when absent', () => {
      const vodContent = makeMovieContent({
        individual_connection: makeConnection({ m3u_profile: null }),
      });
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(screen.queryByText('Main M3U')).not.toBeInTheDocument();
    });
  });

  // ── Stop client ────────────────────────────────────────────────────────────

  describe('stop client', () => {
    it('calls stopVODClient with the connection when stop button is clicked', () => {
      const stopVODClient = vi.fn();
      const vodContent = makeMovieContent();
      render(
        <VodConnectionCard
          vodContent={vodContent}
          stopVODClient={stopVODClient}
        />
      );
      fireEvent.click(screen.getByTestId('icon-square-x').closest('button'));
      expect(stopVODClient).toHaveBeenCalledWith('client-abc-123');
    });

    it('calls stopVODClient once per click', () => {
      const stopVODClient = vi.fn();
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={stopVODClient}
        />
      );
      fireEvent.click(screen.getByTestId('icon-square-x').closest('button'));
      fireEvent.click(screen.getByTestId('icon-square-x').closest('button'));
      expect(stopVODClient).toHaveBeenCalledTimes(2);
    });
  });

  // ── Client expand / collapse ───────────────────────────────────────────────

  describe('client expand/collapse', () => {
    it('starts collapsed (Show Details visible)', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('Show Details')).toBeInTheDocument();
      expect(screen.queryByText('Hide Details')).not.toBeInTheDocument();
    });

    it('expands to show client details on header click', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      const header = screen
        .getByText('Show Details')
        .closest('[data-testid="group"]');
      fireEvent.click(header);
      expect(screen.getByText('Hide Details')).toBeInTheDocument();
    });

    it('shows user agent in expanded details', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      const header = screen
        .getByText('Show Details')
        .closest('[data-testid="group"]');
      fireEvent.click(header);
      expect(screen.getByText('Plex/1.0')).toBeInTheDocument();
    });

    it('collapses back when header is clicked again', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      const header = screen
        .getByText('Show Details')
        .closest('[data-testid="group"]');
      fireEvent.click(header);
      fireEvent.click(
        screen.getByText('Hide Details').closest('[data-testid="group"]')
      );
      expect(screen.getByText('Show Details')).toBeInTheDocument();
    });

    it('does not render user agent section when user_agent is "Unknown"', () => {
      const vodContent = makeMovieContent({
        individual_connection: makeConnection({ user_agent: 'Unknown' }),
      });
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      const header = screen
        .getByText('Show Details')
        .closest('[data-testid="group"]');
      fireEvent.click(header);
      expect(screen.queryByText('Unknown')).not.toBeInTheDocument();
    });

    it('does not render user agent section when user_agent is absent', () => {
      const vodContent = makeMovieContent({
        individual_connection: makeConnection({ user_agent: null }),
      });
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      const header = screen
        .getByText('Show Details')
        .closest('[data-testid="group"]');
      fireEvent.click(header);
      // "Plex/1.0" should not appear
      expect(screen.queryByText('Plex/1.0')).not.toBeInTheDocument();
    });

    it('does not render bytes_sent row when bytes_sent is 0', () => {
      const vodContent = makeMovieContent({
        individual_connection: makeConnection({ bytes_sent: 0 }),
      });
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      const header = screen
        .getByText('Show Details')
        .closest('[data-testid="group"]');
      fireEvent.click(header);
      expect(screen.queryByText('Data Sent:')).not.toBeInTheDocument();
    });

    it('does not render duration row when duration is 0', () => {
      const vodContent = makeMovieContent({
        individual_connection: makeConnection({ duration: 0 }),
      });
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      const header = screen
        .getByText('Show Details')
        .closest('[data-testid="group"]');
      fireEvent.click(header);
      expect(screen.queryByText('Watch Duration:')).not.toBeInTheDocument();
    });
  });

  // ── Connection progress ────────────────────────────────────────────────────

  describe('ConnectionProgress', () => {
    it('does not render progress bar when totalTime is 0', () => {
      vi.mocked(calculateProgress).mockReturnValue({
        totalTime: 0,
        currentTime: 0,
        percentage: 0,
      });
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.queryByTestId('progress')).not.toBeInTheDocument();
    });

    it('renders progress bar when totalTime > 0', () => {
      vi.mocked(calculateProgress).mockReturnValue({
        totalTime: 7200,
        currentTime: 3600,
        percentage: 50,
      });
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByTestId('progress')).toBeInTheDocument();
    });

    it('passes correct percentage value to Progress component', () => {
      vi.mocked(calculateProgress).mockReturnValue({
        totalTime: 7200,
        currentTime: 3600,
        percentage: 50,
      });
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByTestId('progress')).toHaveAttribute(
        'data-value',
        '50'
      );
    });

    it('calls calculateProgress with connection and duration_secs', () => {
      const vodContent = makeMovieContent();
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(calculateProgress).toHaveBeenCalledWith(
        vodContent.individual_connection,
        vodContent.content_metadata.duration_secs
      );
    });

    it('does not render ConnectionProgress when no connection', () => {
      render(
        <VodConnectionCard
          vodContent={makeMovieContent({
            individual_connection: null,
            connections: null,
          })}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.queryByTestId('progress')).not.toBeInTheDocument();
    });
  });

  // ── Periodic re-render timer ───────────────────────────────────────────────

  describe('progress update timer', () => {
    it('sets up a 1-second interval to trigger re-renders', () => {
      vi.mocked(calculateProgress).mockReturnValue({
        totalTime: 7200,
        currentTime: 0,
        percentage: 0,
      });
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );

      const callsBefore = vi.mocked(calculateProgress).mock.calls.length;
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      const callsAfter = vi.mocked(calculateProgress).mock.calls.length;

      expect(callsAfter).toBeGreaterThan(callsBefore);
    });

    it('clears the interval on unmount', () => {
      const clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval');
      const { unmount } = render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      unmount();
      expect(clearIntervalSpy).toHaveBeenCalled();
    });
  });

  // ── calculateConnectionDuration / calculateConnectionStartTime ─────────────

  describe('connection duration and start time', () => {
    it('calls calculateConnectionDuration with the connection', () => {
      const vodContent = makeMovieContent();
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(calculateConnectionDuration).toHaveBeenCalledWith(
        vodContent.individual_connection
      );
    });

    it('renders the duration returned by calculateConnectionDuration', () => {
      vi.mocked(calculateConnectionDuration).mockReturnValue('12m 45s');
      render(
        <VodConnectionCard
          vodContent={makeMovieContent()}
          stopVODClient={vi.fn()}
        />
      );
      expect(screen.getByText('12m 45s')).toBeInTheDocument();
    });

    it('calls calculateConnectionStartTime with connection and fullDateTimeFormat', () => {
      const vodContent = makeMovieContent();
      render(
        <VodConnectionCard vodContent={vodContent} stopVODClient={vi.fn()} />
      );
      expect(calculateConnectionStartTime).toHaveBeenCalledWith(
        vodContent.individual_connection,
        'MM/DD/YYYY h:mm A'
      );
    });
  });
});
