import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import RecordingCard from '../RecordingCard';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVideoStore.jsx', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: vi.fn(),
  useTimeHelpers: vi.fn(),
  isAfter: vi.fn(),
  isBefore: vi.fn(),
  format: vi.fn(),
}));

vi.mock('../../../utils/cards/RecordingCardUtils.js', () => ({
  deleteRecordingById: vi.fn(),
  deleteSeriesAndRule: vi.fn(),
  extendRecordingById: vi.fn(),
  getChannelLogoUrl: vi.fn(),
  getPosterUrl: vi.fn(),
  getRecordingUrl: vi.fn(),
  getSeasonLabel: vi.fn(),
  getSeriesInfo: vi.fn(),
  getShowVideoUrl: vi.fn(),
  removeRecording: vi.fn(),
  runComSkip: vi.fn(),
  stopRecordingById: vi.fn(),
}));

// ── Mantine notifications ──────────────────────────────────────────────────────
vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  ActionIcon: ({ children, onClick, onMouseDown, color, disabled }) => (
    <button
      data-testid="action-icon"
      data-color={color}
      onClick={onClick}
      onMouseDown={onMouseDown}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Box: ({ children, style, display }) => (
    <div style={style} data-display={display}>
      {children}
    </div>
  ),
  Button: ({ children, onClick, disabled, loading, color, variant }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-color={color}
      data-variant={variant}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Card: ({ children, onClick, style }) => (
    <div data-testid="recording-card" onClick={onClick} style={style}>
      {children}
    </div>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Image: ({ src, alt, fallbackSrc }) => (
    <img src={src} alt={alt} data-fallback={fallbackSrc} />
  ),
  Menu: Object.assign(
    ({ children }) => <div data-testid="menu">{children}</div>,
    {
      Target: ({ children }) => <div>{children}</div>,
      Dropdown: ({ children, onClick }) => (
        <div onClick={onClick}>{children}</div>
      ),
      Label: ({ children }) => <div>{children}</div>,
      Item: ({ children, onClick }) => (
        <button onClick={onClick}>{children}</button>
      ),
    }
  ),
  Modal: ({ children, opened, onClose, title }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, c, fw, title, lineClamp, style }) => (
    <span data-size={size} data-color={c} data-fw={fw} style={style}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ListOrdered: () => <svg data-testid="icon-list-ordered" />,
  AlertTriangle: () => <svg data-testid="icon-alert-triangle" />,
  Plus: () => <svg data-testid="icon-plus" />,
  Square: () => <svg data-testid="icon-square" />,
  SquareX: () => <svg data-testid="icon-square-x" />,
}));

// ── RecordingSynopsis ──────────────────────────────────────────────────────────
vi.mock('../../RecordingSynopsis', () => ({
  default: ({ description, onOpen }) => (
    <div data-testid="recording-synopsis" onClick={onOpen}>
      {description}
    </div>
  ),
}));

// ── default logo ───────────────────────────────────────────────────────────────
vi.mock('../../../images/logo.png', () => ({ default: 'default-logo.png' }));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels.jsx';
import useSettingsStore from '../../../store/settings.jsx';
import useVideoStore from '../../../store/useVideoStore.jsx';
import {
  useDateTimeFormat,
  useTimeHelpers,
  format,
  isAfter,
  isBefore,
} from '../../../utils/dateTimeUtils.js';
import { notifications } from '@mantine/notifications';
import * as RecordingCardUtils from '../../../utils/cards/RecordingCardUtils.js';
import dayjs from 'dayjs';

/** Build a minimal dayjs-like mock with isBefore / isAfter */
const makeMoment = (isoString) => {
  const d = dayjs(isoString);
  return {
    isAfter: (other) => d.isAfter(other?._d ?? other),
    isBefore: (other) => d.isBefore(other?._d ?? other),
    format: vi.fn((fmt) => d.format(fmt)),
    _d: d.toDate(),
  };
};

const PAST = '2020-01-01T10:00:00Z';
const FUTURE = '2099-01-01T10:00:00Z';
const NOW = '2024-06-01T12:00:00Z';

/** Factory for a completed (past) recording */
const makeRecording = (overrides = {}) => ({
  id: 'rec-1',
  start_time: PAST,
  end_time: PAST,
  _group_count: 1,
  custom_properties: {
    status: 'completed',
    program: {
      title: 'Test Show',
      sub_title: 'Pilot',
      description: 'A test description',
    },
    file_url: '/recordings/test.ts',
    ...overrides.custom_properties,
  },
  ...overrides,
});

const makeChannel = () => ({
  id: 'ch-1',
  name: 'HBO',
  channel_number: 501,
});

/** Wire up all store/utility mocks with sensible defaults */
const setupMocks = ({
  now = NOW,
  recording = makeRecording(),
  channel = makeChannel(),
} = {}) => {
  const nowMoment = makeMoment(now);
  const startMoment = makeMoment(recording.start_time);
  const endMoment = makeMoment(recording.end_time);

  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ environment: { env_mode: 'production' } })
  );

  const mockShowVideo = vi.fn();
  vi.mocked(useVideoStore).mockImplementation((sel) =>
    sel({ showVideo: mockShowVideo })
  );

  const mockFetchRecordings = vi.fn().mockResolvedValue(undefined);
  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ fetchRecordings: mockFetchRecordings })
  );

  vi.mocked(useTimeHelpers).mockReturnValue({
    toUserTime: (iso) => {
      if (iso === recording.start_time) return startMoment;
      if (iso === recording.end_time) return endMoment;
      return makeMoment(iso);
    },
    userNow: () => nowMoment,
  });

  vi.mocked(useDateTimeFormat).mockReturnValue({
    timeFormat: 'HH:mm',
    dateFormat: 'MM/DD',
  });

  vi.mocked(format).mockImplementation((moment, fmt) => moment.format(fmt));
  vi.mocked(isAfter).mockImplementation((a, b) => a.isAfter(b));
  vi.mocked(isBefore).mockImplementation((a, b) => a.isBefore(b));

  vi.mocked(RecordingCardUtils.getPosterUrl).mockReturnValue('/poster.jpg');
  vi.mocked(RecordingCardUtils.getChannelLogoUrl).mockReturnValue('/logo.png');
  vi.mocked(RecordingCardUtils.getRecordingUrl).mockReturnValue(
    '/recordings/test.ts'
  );
  vi.mocked(RecordingCardUtils.getSeasonLabel).mockReturnValue('');
  vi.mocked(RecordingCardUtils.getSeriesInfo).mockReturnValue({
    seriesId: 's1',
  });
  vi.mocked(RecordingCardUtils.getShowVideoUrl).mockReturnValue('/live/ch-1');

  return { mockShowVideo, mockFetchRecordings };
};

describe('RecordingCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(RecordingCardUtils.stopRecordingById).mockResolvedValue(
      undefined
    );
    vi.mocked(RecordingCardUtils.deleteRecordingById).mockResolvedValue(
      undefined
    );
    vi.mocked(RecordingCardUtils.deleteSeriesAndRule).mockResolvedValue(
      undefined
    );
    vi.mocked(RecordingCardUtils.extendRecordingById).mockResolvedValue(
      undefined
    );
    vi.mocked(RecordingCardUtils.runComSkip).mockResolvedValue(undefined);
    vi.mocked(RecordingCardUtils.removeRecording).mockReturnValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the recording title', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.getByText('Test Show')).toBeInTheDocument();
    });

    it('renders "Custom Recording" when no program title', () => {
      setupMocks({
        recording: makeRecording({
          custom_properties: { status: 'completed', program: {} },
        }),
      });
      render(
        <RecordingCard
          recording={makeRecording({
            custom_properties: { status: 'completed', program: {} },
          })}
          channel={makeChannel()}
        />
      );
      expect(screen.getByText('Custom Recording')).toBeInTheDocument();
    });

    it('renders channel info', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.getByText('501 • HBO')).toBeInTheDocument();
    });

    it('renders "—" when no channel provided', () => {
      setupMocks({ channel: null });
      render(<RecordingCard recording={makeRecording()} channel={null} />);
      expect(screen.getByText('—')).toBeInTheDocument();
    });

    it('shows description via RecordingSynopsis for non-series completed recording', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.getByTestId('recording-synopsis')).toBeInTheDocument();
      expect(screen.getByText('A test description')).toBeInTheDocument();
    });

    it('shows sub_title when present', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.getByText('Pilot')).toBeInTheDocument();
    });

    it('shows season/episode label when getSeasonLabel returns a value', () => {
      setupMocks();
      vi.mocked(RecordingCardUtils.getSeasonLabel).mockReturnValue('S01E02');
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.getByText('S01E02')).toBeInTheDocument();
    });

    it('renders the poster image', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      const img = screen.getByAltText('Test Show');
      expect(img).toHaveAttribute('src', '/poster.jpg');
    });
  });

  // ── Status badges ──────────────────────────────────────────────────────────

  describe('status badge', () => {
    it('shows "Completed" badge for a completed recording', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.getByText('Completed')).toBeInTheDocument();
    });

    it('shows "Recording" badge for an in-progress recording', () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: {
          status: 'recording',
          program: { title: 'Live Show' },
        },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByText('Recording')).toBeInTheDocument();
    });

    it('shows "Scheduled" badge for an upcoming recording', () => {
      const recording = makeRecording({
        start_time: FUTURE,
        end_time: FUTURE,
        custom_properties: {
          status: 'scheduled',
          program: { title: 'Future Show' },
        },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByText('Scheduled')).toBeInTheDocument();
    });

    it('shows "Interrupted" badge and alert icon for interrupted recording', () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: {
          status: 'interrupted',
          interrupted_reason: 'Disk full',
          program: { title: 'Broken Show' },
        },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByText('Interrupted')).toBeInTheDocument();
      expect(screen.getByTestId('icon-alert-triangle')).toBeInTheDocument();
    });

    it('shows interrupted_reason text when present', () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: {
          status: 'interrupted',
          interrupted_reason: 'Disk full',
          program: { title: 'Broken Show' },
        },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByText('Disk full')).toBeInTheDocument();
    });
  });

  // ── Series group ───────────────────────────────────────────────────────────

  describe('series group', () => {
    const makeSeriesRecording = () => makeRecording({ _group_count: 3 });

    it('shows "Series" badge when _group_count > 1', () => {
      const recording = makeSeriesRecording();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByText('Series')).toBeInTheDocument();
    });

    it('shows "Next of N" text for series group', () => {
      const recording = makeSeriesRecording();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByText('Next of 3')).toBeInTheDocument();
    });

    it('does not show description for series group', () => {
      const recording = makeSeriesRecording();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(
        screen.queryByTestId('recording-synopsis')
      ).not.toBeInTheDocument();
    });
  });

  // ── Recurring rule ─────────────────────────────────────────────────────────

  describe('recurring rule', () => {
    const makeRecurring = () =>
      makeRecording({
        custom_properties: {
          status: 'scheduled',
          rule: { type: 'recurring' },
          program: { title: 'Recurring Show' },
        },
        start_time: FUTURE,
        end_time: FUTURE,
      });

    it('shows "Recurring" badge', () => {
      const recording = makeRecurring();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByText('Recurring')).toBeInTheDocument();
    });

    it('calls onOpenRecurring on card click', () => {
      const recording = makeRecurring();
      setupMocks({ recording });
      const onOpenRecurring = vi.fn();
      render(
        <RecordingCard
          recording={recording}
          channel={makeChannel()}
          onOpenRecurring={onOpenRecurring}
        />
      );
      fireEvent.click(screen.getByTestId('recording-card'));
      expect(onOpenRecurring).toHaveBeenCalledWith(recording, false);
    });

    it('calls onOpenRecurring(recording, true) on delete click for recurring rule', () => {
      const recording = makeRecurring();
      setupMocks({ recording });
      const onOpenRecurring = vi.fn();
      render(
        <RecordingCard
          recording={recording}
          channel={makeChannel()}
          onOpenRecurring={onOpenRecurring}
        />
      );
      // The delete ActionIcon is the last action-icon rendered
      const actionIcons = screen.getAllByTestId('action-icon');
      fireEvent.click(actionIcons[actionIcons.length - 1]);
      expect(onOpenRecurring).toHaveBeenCalledWith(recording, true);
    });
  });

  // ── Card click ─────────────────────────────────────────────────────────────

  describe('card click', () => {
    it('calls onOpenDetails when card is clicked for a normal recording', () => {
      setupMocks();
      const onOpenDetails = vi.fn();
      render(
        <RecordingCard
          recording={makeRecording()}
          channel={makeChannel()}
          onOpenDetails={onOpenDetails}
        />
      );
      fireEvent.click(screen.getByTestId('recording-card'));
      expect(onOpenDetails).toHaveBeenCalledWith(makeRecording());
    });

    it('calls onOpenDetails from RecordingSynopsis onOpen', () => {
      setupMocks();
      const onOpenDetails = vi.fn();
      render(
        <RecordingCard
          recording={makeRecording()}
          channel={makeChannel()}
          onOpenDetails={onOpenDetails}
        />
      );
      fireEvent.click(screen.getByTestId('recording-synopsis'));
      expect(onOpenDetails).toHaveBeenCalledWith(makeRecording());
    });
  });

  // ── Watch actions ──────────────────────────────────────────────────────────

  describe('watch actions', () => {
    it('shows "Watch Live" button during in-progress recording', () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: { status: 'recording', program: { title: 'Live' } },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByText('Watch Live')).toBeInTheDocument();
    });

    it('does not show "Watch Live" for a completed recording', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.queryByText('Watch Live')).not.toBeInTheDocument();
    });

    it('calls showVideo with live params when Watch Live is clicked', () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: { status: 'recording', program: { title: 'Live' } },
      });
      const { mockShowVideo } = setupMocks({ recording });
      const channel = makeChannel();
      render(<RecordingCard recording={recording} channel={channel} />);
      fireEvent.click(screen.getByText('Watch Live'));
      expect(mockShowVideo).toHaveBeenCalledWith(
        '/live/ch-1',
        'live',
        expect.objectContaining({ name: channel.name })
      );
    });

    it('shows "Watch" button for a completed recording', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.getByText('Watch')).toBeInTheDocument();
    });

    it('does not show "Watch" for an upcoming recording', () => {
      const recording = makeRecording({
        start_time: FUTURE,
        end_time: FUTURE,
        custom_properties: {
          status: 'scheduled',
          program: { title: 'Future' },
        },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.queryByText('Watch')).not.toBeInTheDocument();
    });

    it('calls showVideo with vod params when Watch is clicked', () => {
      const { mockShowVideo } = setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      fireEvent.click(screen.getByText('Watch'));
      expect(mockShowVideo).toHaveBeenCalledWith(
        '/recordings/test.ts',
        'vod',
        expect.objectContaining({ name: 'Test Show' })
      );
    });

    it('does not call showVideo when Watch is clicked but no file url', () => {
      const { mockShowVideo } = setupMocks();
      vi.mocked(RecordingCardUtils.getRecordingUrl).mockReturnValue(null);
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      fireEvent.click(screen.getByText('Watch'));
      expect(mockShowVideo).not.toHaveBeenCalled();
    });

    it('Watch Live does nothing when channel is null', () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: { status: 'recording', program: { title: 'Live' } },
      });
      const { mockShowVideo } = setupMocks({ recording, channel: null });
      render(<RecordingCard recording={recording} channel={null} />);
      fireEvent.click(screen.getByText('Watch Live'));
      expect(mockShowVideo).not.toHaveBeenCalled();
    });
  });

  // ── Remove commercials ─────────────────────────────────────────────────────

  describe('"Remove commercials" button', () => {
    it('shows "Remove commercials" for a completed recording without comskip', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      expect(screen.getByText('Remove commercials')).toBeInTheDocument();
    });

    it('does not show "Remove commercials" when comskip is completed', () => {
      const recording = makeRecording({
        custom_properties: {
          status: 'completed',
          comskip: { status: 'completed' },
          program: { title: 'Test Show' },
          file_url: '/test.ts',
        },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.queryByText('Remove commercials')).not.toBeInTheDocument();
    });

    it('does not show "Remove commercials" for upcoming recording', () => {
      const recording = makeRecording({
        start_time: FUTURE,
        end_time: FUTURE,
        custom_properties: {
          status: 'scheduled',
          program: { title: 'Future' },
        },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.queryByText('Remove commercials')).not.toBeInTheDocument();
    });

    it('calls runComSkip and shows notification on success', async () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      fireEvent.click(screen.getByText('Remove commercials'));
      await waitFor(() => {
        expect(RecordingCardUtils.runComSkip).toHaveBeenCalledWith(
          makeRecording()
        );
        expect(notifications.show).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Removing commercials',
            color: 'blue.5',
          })
        );
      });
    });

    it('does not show notification when runComSkip throws', async () => {
      vi.mocked(RecordingCardUtils.runComSkip).mockRejectedValue(
        new Error('fail')
      );
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );
      fireEvent.click(screen.getByText('Remove commercials'));
      await waitFor(() => {
        expect(notifications.show).not.toHaveBeenCalled();
      });
    });
  });

  // ── Extend recording ───────────────────────────────────────────────────────

  describe('extend recording', () => {
    const makeInProgress = () =>
      makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: {
          status: 'recording',
          program: { title: 'Live Show' },
          file_url: '/f.ts',
        },
      });

    it('shows extend menu for in-progress recording', () => {
      const recording = makeInProgress();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      expect(screen.getByTestId('icon-plus')).toBeInTheDocument();
    });

    it('calls extendRecordingById with 15 and shows notification', async () => {
      const recording = makeInProgress();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      fireEvent.click(screen.getByText('+15 minutes'));
      await waitFor(() => {
        expect(RecordingCardUtils.extendRecordingById).toHaveBeenCalledWith(
          'rec-1',
          15
        );
        expect(notifications.show).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Recording extended',
            color: 'teal',
          })
        );
      });
    });

    it('calls extendRecordingById with 30', async () => {
      const recording = makeInProgress();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      fireEvent.click(screen.getByText('+30 minutes'));
      await waitFor(() => {
        expect(RecordingCardUtils.extendRecordingById).toHaveBeenCalledWith(
          'rec-1',
          30
        );
      });
    });

    it('calls extendRecordingById with 60', async () => {
      const recording = makeInProgress();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      fireEvent.click(screen.getByText('+1 hour'));
      await waitFor(() => {
        expect(RecordingCardUtils.extendRecordingById).toHaveBeenCalledWith(
          'rec-1',
          60
        );
      });
    });

    it('shows error notification when extendRecordingById throws', async () => {
      vi.mocked(RecordingCardUtils.extendRecordingById).mockRejectedValue(
        new Error('Network error')
      );
      const recording = makeInProgress();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      fireEvent.click(screen.getByText('+15 minutes'));
      await waitFor(() => {
        expect(notifications.show).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Extension failed', color: 'red' })
        );
      });
    });
  });

  // ── Stop recording ─────────────────────────────────────────────────────────

  describe('stop recording', () => {
    const makeInProgress = () =>
      makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: {
          status: 'recording',
          program: { title: 'Live Show' },
          file_url: '/f.ts',
        },
      });

    it('shows stop modal when stop button is clicked', () => {
      const recording = makeInProgress();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      // Stop ActionIcon has the Square icon
      const stopButton = screen.getByTestId('icon-square').closest('button');
      fireEvent.click(stopButton);

      expect(screen.getByTestId('modal')).toBeInTheDocument();
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Stop Recording'
      );
    });

    it('closes stop modal when Go Back is clicked', () => {
      const recording = makeInProgress();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const stopButton = screen.getByTestId('icon-square').closest('button');
      fireEvent.click(stopButton);
      fireEvent.click(screen.getByText('Go Back'));

      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('calls stopRecordingById and fetchRecordings when Stop Recording is confirmed', async () => {
      const recording = makeInProgress();
      const { mockFetchRecordings } = setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const stopButton = screen.getByTestId('icon-square').closest('button');
      fireEvent.click(stopButton);
      fireEvent.click(screen.getAllByText('Stop Recording')[1]);

      await waitFor(() => {
        expect(RecordingCardUtils.stopRecordingById).toHaveBeenCalledWith(
          'rec-1'
        );
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('closes stop modal after confirming stop', async () => {
      const recording = makeInProgress();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const stopButton = screen.getByTestId('icon-square').closest('button');
      fireEvent.click(stopButton);
      fireEvent.click(screen.getAllByText('Stop Recording')[1]);

      await waitFor(() => {
        expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      });
    });
  });

  // ── Delete recording ───────────────────────────────────────────────────────

  describe('delete recording', () => {
    it('shows delete modal for a completed non-series recording', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);

      expect(screen.getByTestId('modal')).toBeInTheDocument();
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Delete Recording'
      );
    });

    it('shows "Cancel Recording" title for upcoming recording delete', () => {
      const recording = makeRecording({
        start_time: FUTURE,
        end_time: FUTURE,
        custom_properties: {
          status: 'scheduled',
          program: { title: 'Future Show' },
        },
      });
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);

      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Cancel Recording'
      );
    });

    it('calls removeRecording when delete is confirmed', async () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);
      fireEvent.click(screen.getByText('Delete'));

      await waitFor(() => {
        expect(RecordingCardUtils.removeRecording).toHaveBeenCalledWith(
          'rec-1'
        );
      });
    });

    it('closes delete modal after confirming', async () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);
      fireEvent.click(screen.getByText('Delete'));

      await waitFor(() => {
        expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      });
    });

    it('closes delete modal on Go Back click', () => {
      setupMocks();
      render(
        <RecordingCard recording={makeRecording()} channel={makeChannel()} />
      );

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);
      fireEvent.click(screen.getByText('Go Back'));

      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Series cancel modal ────────────────────────────────────────────────────

  describe('series cancel modal', () => {
    const makeSeriesRecording = () =>
      makeRecording({
        _group_count: 3,
        custom_properties: {
          status: 'scheduled',
          program: { title: 'Series Show' },
        },
        start_time: FUTURE,
        end_time: FUTURE,
      });

    it('opens Cancel Series modal for a series group delete click', () => {
      const recording = makeSeriesRecording();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);

      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Cancel Series'
      );
    });

    it('calls deleteRecordingById when "Only this upcoming" is clicked', async () => {
      const recording = makeSeriesRecording();
      const { mockFetchRecordings } = setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);
      fireEvent.click(screen.getByText('Only this upcoming'));

      await waitFor(() => {
        expect(RecordingCardUtils.deleteRecordingById).toHaveBeenCalledWith(
          'rec-1'
        );
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('calls deleteSeriesAndRule when "Entire series + rule" is clicked', async () => {
      const recording = makeSeriesRecording();
      const { mockFetchRecordings } = setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);
      fireEvent.click(screen.getByText('Entire series + rule'));

      await waitFor(() => {
        expect(RecordingCardUtils.deleteSeriesAndRule).toHaveBeenCalled();
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('closes Cancel Series modal after removing upcoming only', async () => {
      const recording = makeSeriesRecording();
      setupMocks({ recording });
      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);
      fireEvent.click(screen.getByText('Only this upcoming'));

      await waitFor(() => {
        expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      });
    });
  });

  describe('error resilience', () => {
    it('does not throw when fetchRecordings rejects after stop', async () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: { status: 'recording', program: { title: 'Live' } },
      });
      const { mockFetchRecordings } = setupMocks({ recording });
      mockFetchRecordings.mockRejectedValue(new Error('network'));

      render(<RecordingCard recording={recording} channel={makeChannel()} />);

      const stopButton = screen.getByTestId('icon-square').closest('button');
      fireEvent.click(stopButton);

      await expect(
        waitFor(() => fireEvent.click(screen.getAllByText('Stop Recording')[1]))
      ).resolves.not.toThrow();
    });

    it('does not throw when fetchRecordings rejects after deleteRecordingById', async () => {
      const recording = makeRecording({
        _group_count: 3,
        start_time: FUTURE,
        end_time: FUTURE,
        custom_properties: {
          status: 'scheduled',
          program: { title: 'Series' },
        },
      });
      const { mockFetchRecordings } = setupMocks({ recording });
      mockFetchRecordings.mockRejectedValue(new Error('network'));

      render(<RecordingCard recording={recording} channel={makeChannel()} />);
      const deleteButton = screen
        .getByTestId('icon-square-x')
        .closest('button');
      fireEvent.click(deleteButton);

      await expect(
        waitFor(() => fireEvent.click(screen.getByText('Only this upcoming')))
      ).resolves.not.toThrow();
    });
  });
});
