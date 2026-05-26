import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVideoStore.jsx', () => ({
  default: Object.assign(vi.fn(), {
    getState: vi.fn(() => ({ showVideo: vi.fn() })),
  }),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  format: vi.fn(),
  isAfter: vi.fn(),
  isBefore: vi.fn(),
  useDateTimeFormat: vi.fn(),
  useTimeHelpers: vi.fn(),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/cards/RecordingCardUtils.js', () => ({
  deleteRecordingById: vi.fn(),
  getChannelLogoUrl: vi.fn(),
  getPosterUrl: vi.fn(),
  getRecordingUrl: vi.fn(),
  getSeasonLabel: vi.fn(),
  getShowVideoUrl: vi.fn(),
  runComSkip: vi.fn(),
}));

vi.mock('../../../utils/forms/RecordingDetailsModalUtils.js', () => ({
  getChannel: vi.fn(),
  getRating: vi.fn(),
  getStatRows: vi.fn(),
  getUpcomingEpisodes: vi.fn(),
  refreshArtwork: vi.fn(),
  updateRecordingMetadata: vi.fn(),
}));

vi.mock('../../../images/logo.png', () => ({ default: 'default-logo.png' }));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Check: () => <svg data-testid="icon-check" />,
  Pencil: () => <svg data-testid="icon-pencil" />,
  RefreshCcw: () => <svg data-testid="icon-refresh" />,
  X: () => <svg data-testid="icon-x" />,
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled }) => (
    <button data-testid="action-icon" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>{children}</span>
  ),
  Button: ({ children, onClick, disabled, loading, size, variant, color }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-size={size}
      data-variant={variant}
      data-color={color}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Card: ({ children, onClick, style }) => (
    <div data-testid="card" onClick={onClick} style={style}>{children}</div>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Image: ({ src, alt, fallbackSrc }) => (
    <img src={src} alt={alt} data-fallback={fallbackSrc} />
  ),
  Modal: ({ children, opened, onClose, title, size }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>×</button>
        {children}
      </div>
    ) : null,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, c, fw, style }) => (
    <span data-size={size} data-color={c} data-fw={fw} style={style}>{children}</span>
  ),
  Textarea: ({ label, value, onChange, placeholder, ...props }) => (
    <div>
      <label>{label}</label>
      <textarea
        data-testid={`textarea-${label ?? placeholder ?? 'unknown'}`}
        value={value ?? ''}
        onChange={onChange}
        {...props}
      />
    </div>
  ),
  TextInput: ({ label, value, onChange, placeholder, ...props }) => (
    <div>
      <label />
      <input
        data-testid={`textinput-${label ?? placeholder ?? 'unknown'}`}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        style={props.style}
      />
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import RecordingDetailsModal from '../RecordingDetailsModal';
import useChannelsStore from '../../../store/channels.jsx';
import useVideoStore from '../../../store/useVideoStore.jsx';
import {
  format,
  isAfter,
  isBefore,
  useDateTimeFormat,
  useTimeHelpers,
} from '../../../utils/dateTimeUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import * as RecordingCardUtils from '../../../utils/cards/RecordingCardUtils.js';
import * as RecordingDetailsModalUtils from '../../../utils/forms/RecordingDetailsModalUtils.js';
import dayjs from 'dayjs';

// ── Helpers ────────────────────────────────────────────────────────────────────
const PAST = '2020-01-01T10:00:00Z';
const FUTURE = '2099-01-01T10:00:00Z';
const NOW = '2024-06-01T12:00:00Z';

const makeMoment = (isoString) => {
  const d = dayjs(isoString);
  return {
    isAfter: (other) => d.isAfter(other?._d ?? other),
    isBefore: (other) => d.isBefore(other?._d ?? other),
    format: vi.fn((fmt) => d.format(fmt)),
    _d: d.toDate(),
  };
};

const makeRecording = (overrides = {}) => ({
  id: 'rec-1',
  channel: 'ch-1',
  start_time: PAST,
  end_time: PAST,
  _group_count: 1,
  custom_properties: {
    status: 'completed',
    file_url: '/recordings/test.ts',
    program: {
      title: 'Test Show',
      description: 'A test description',
      sub_title: 'Pilot',
    },
    ...overrides.custom_properties,
  },
  ...overrides,
});

const makeChannel = () => ({ id: 'ch-1', name: 'HBO', channel_number: 501 });

const mockShowVideo = vi.fn();

const setupMocks = ({ recording = makeRecording(), now = NOW } = {}) => {
  const nowMoment = makeMoment(now);
  const startMoment = makeMoment(recording.start_time);
  const endMoment = makeMoment(recording.end_time);

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

  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ recordings: [recording] })
  );

  mockShowVideo.mockReset();
  vi.mocked(useVideoStore).mockImplementation((sel) =>
    sel({ showVideo: mockShowVideo })
  );
  useVideoStore.getState = vi.fn(() => ({ showVideo: mockShowVideo }));

  vi.mocked(RecordingCardUtils.getPosterUrl).mockReturnValue('/poster.jpg');
  vi.mocked(RecordingCardUtils.getChannelLogoUrl).mockReturnValue('/logo.png');
  vi.mocked(RecordingCardUtils.getRecordingUrl).mockReturnValue('/recordings/test.ts');
  vi.mocked(RecordingCardUtils.getSeasonLabel).mockReturnValue('');
  vi.mocked(RecordingCardUtils.getShowVideoUrl).mockReturnValue('/live/ch-1');

  vi.mocked(RecordingDetailsModalUtils.getRating).mockReturnValue(null);
  vi.mocked(RecordingDetailsModalUtils.getStatRows).mockReturnValue([]);
  vi.mocked(RecordingDetailsModalUtils.getUpcomingEpisodes).mockReturnValue([]);
  vi.mocked(RecordingDetailsModalUtils.getChannel).mockResolvedValue(null);
};

const defaultProps = () => ({
  opened: true,
  onClose: vi.fn(),
  recording: makeRecording(),
  channel: makeChannel(),
  posterUrl: '/poster.jpg',
  onWatchLive: vi.fn(),
  onWatchRecording: vi.fn(),
  env_mode: 'production',
  onEdit: vi.fn(),
});

// ── Tests ──────────────────────────────────────────────────────────────────────
describe('RecordingDetailsModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
    vi.mocked(RecordingDetailsModalUtils.updateRecordingMetadata).mockResolvedValue(undefined);
    vi.mocked(RecordingDetailsModalUtils.refreshArtwork).mockResolvedValue(undefined);
    vi.mocked(RecordingCardUtils.runComSkip).mockResolvedValue(undefined);
    vi.mocked(RecordingCardUtils.deleteRecordingById).mockResolvedValue(undefined);
  });

  // ── Visibility ───────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when opened is true', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render when opened is false', () => {
      render(<RecordingDetailsModal {...defaultProps()} opened={false} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('returns null when recording is not provided', () => {
      const { container } = render(
        <RecordingDetailsModal {...defaultProps()} recording={null} />
      );
      expect(container.firstChild).toBeNull();
    });

    it('calls onClose when modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<RecordingDetailsModal {...defaultProps()} onClose={onClose} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Content rendering ────────────────────────────────────────────────────────

  describe('content rendering', () => {
    it('renders the recording title', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      expect(screen.getByText(/Test Show/i)).toBeInTheDocument();
    });

    it('renders "Custom Recording" when no program title', () => {
      const recording = makeRecording({
        custom_properties: { status: 'completed', program: {} },
      });
      setupMocks({ recording });
      render(
        <RecordingDetailsModal {...defaultProps()} recording={recording} />
      );
      expect(screen.getByText('Custom Recording')).toBeInTheDocument();
    });

    it('renders the description', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      expect(screen.getByText('A test description')).toBeInTheDocument();
    });

    it('renders the poster image', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      expect(screen.getByAltText('Test Show')).toHaveAttribute('src', '/poster.jpg');
    });

    it('renders the season/episode label when present', () => {
      const seriesRecording = makeRecording({ _group_count: 2 });
      const mockEpisode = makeRecording({ id: 'ep-1', _group_count: 1 });

      vi.mocked(RecordingDetailsModalUtils.getUpcomingEpisodes).mockReturnValue([mockEpisode]);
      vi.mocked(RecordingCardUtils.getSeasonLabel).mockReturnValue('S01E02');

      render(
        <RecordingDetailsModal
          {...defaultProps()}
          recording={seriesRecording}
        />
      );
      expect(screen.getByText('S01E02')).toBeInTheDocument();
    });

    it('renders rating when present', () => {
      vi.mocked(RecordingDetailsModalUtils.getRating).mockReturnValue('TV-MA');
      render(<RecordingDetailsModal {...defaultProps()} />);
      expect(screen.getByText('TV-MA')).toBeInTheDocument();
    });

    it('renders stat rows when available', () => {
      vi.mocked(RecordingDetailsModalUtils.getStatRows).mockReturnValue([
        ['Video Codec', 'H264'],
        ['Audio Codec', 'AAC'],
      ]);
      render(<RecordingDetailsModal {...defaultProps()} />);
      expect(screen.getByText('Stream Stats')).toBeInTheDocument();
      expect(screen.getByText('Video Codec')).toBeInTheDocument();
      expect(screen.getByText('H264')).toBeInTheDocument();
    });
  });

  // ── Watch buttons ────────────────────────────────────────────────────────────

  describe('Watch button', () => {
    it('renders Watch button for completed recording', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      expect(screen.getByText('Watch')).toBeInTheDocument();
    });

    it('calls onWatchRecording when Watch is clicked', () => {
      const onWatchRecording = vi.fn();
      render(
        <RecordingDetailsModal
          {...defaultProps()}
          onWatchRecording={onWatchRecording}
        />
      );
      fireEvent.click(screen.getByText('Watch'));
      expect(onWatchRecording).toHaveBeenCalled();
    });

    it('Watch button is disabled when no file_url', () => {
      const recording = makeRecording({
        custom_properties: {
          status: 'completed',
          program: { title: 'Test Show' },
        },
      });
      setupMocks({ recording });
      render(
        <RecordingDetailsModal {...defaultProps()} recording={recording} />
      );
      expect(screen.getByText('Watch')).toBeDisabled();
    });
  });

  describe('Watch Live button', () => {
    it('renders Watch Live button for in-progress recording', () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: {
          status: 'recording',
          file_url: '/f.ts',
          program: { title: 'Live Show' },
        },
      });
      setupMocks({ recording });
      render(
        <RecordingDetailsModal {...defaultProps()} recording={recording} />
      );
      expect(screen.getByText('Watch Live')).toBeInTheDocument();
    });

    it('calls onWatchLive when Watch Live is clicked', () => {
      const recording = makeRecording({
        start_time: PAST,
        end_time: FUTURE,
        custom_properties: {
          status: 'recording',
          file_url: '/f.ts',
          program: { title: 'Live Show' },
        },
      });
      setupMocks({ recording });
      const onWatchLive = vi.fn();
      render(
        <RecordingDetailsModal
          {...defaultProps()}
          recording={recording}
          onWatchLive={onWatchLive}
        />
      );
      fireEvent.click(screen.getByText('Watch Live'));
      expect(onWatchLive).toHaveBeenCalled();
    });
  });

  // ── Edit button ──────────────────────────────────────────────────────────────

  describe('Edit button', () => {
    it('renders the Edit button', () => {
      const futureRecording = makeRecording({ start_time: FUTURE, end_time: FUTURE });
      setupMocks({ recording: futureRecording });
      render(
        <RecordingDetailsModal
          {...defaultProps()}
          recording={futureRecording}
        />
      );
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    it('calls onEdit when Edit is clicked', () => {
      const futureRecording = makeRecording({ start_time: FUTURE, end_time: FUTURE });
      setupMocks({ recording: futureRecording });
      const onEdit = vi.fn();
      render(
        <RecordingDetailsModal
          {...defaultProps()}
          recording={futureRecording}
          onEdit={onEdit}
        />
      );
      fireEvent.click(screen.getByText('Edit'));
      expect(onEdit).toHaveBeenCalledWith(futureRecording);
    });
  });

  // ── Inline editing ───────────────────────────────────────────────────────────

  describe('inline metadata editing', () => {
    it('shows edit inputs when pencil icon is clicked', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      expect(screen.getByTestId('textinput-Recording title')).toBeInTheDocument();
    });

    it('pre-fills title input with current title', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      expect(screen.getByTestId('textinput-Recording title')).toHaveValue('Test Show');
    });

    it('pre-fills description input with current description', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      expect(screen.getByTestId('textarea-Description (optional)')).toHaveValue('A test description');
    });

    it('cancels editing when X icon is clicked', () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      expect(screen.getByTestId('textinput-Recording title')).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('icon-x').closest('button'));
      expect(screen.queryByTestId('textinput-Recording title')).not.toBeInTheDocument();
    });

    it('calls updateRecordingMetadata with new title and description on save', async () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));

      fireEvent.change(screen.getByTestId('textinput-Recording title'), {
        target: { value: 'New Title' },
      });
      fireEvent.change(screen.getByTestId('textarea-Description (optional)'), {
        target: { value: 'New Description' },
      });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(
          RecordingDetailsModalUtils.updateRecordingMetadata
        ).toHaveBeenCalledWith(makeRecording(), 'New Title', 'New Description');
      });
    });

    it('shows saved title optimistically after save', async () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      fireEvent.change(screen.getByTestId('textinput-Recording title'), {
        target: { value: 'Updated Title' },
      });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(screen.getByText('Updated Title')).toBeInTheDocument();
      });
    });

    it('shows success notification after save', async () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green' })
        );
      });
    });

    it('does not show notification when updateRecordingMetadata throws', async () => {
      vi.mocked(
        RecordingDetailsModalUtils.updateRecordingMetadata
      ).mockRejectedValue(new Error('fail'));
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });

    it('uses "Custom Recording" when title is cleared on save', async () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      fireEvent.change(screen.getByTestId('textinput-Recording title'), {
        target: { value: '' },
      });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(screen.getByText('Custom Recording')).toBeInTheDocument();
      });
    });
  });

  // ── Refresh artwork ──────────────────────────────────────────────────────────

  describe('refresh artwork', () => {
    it('calls refreshArtwork with recording id on click', async () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Refresh artwork'));

      await waitFor(() => {
        expect(RecordingDetailsModalUtils.refreshArtwork).toHaveBeenCalledWith(
          'rec-1'
        );
      });
    });

    it('shows success notification after refreshArtwork', async () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Refresh artwork'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'blue.5' })
        );
      });
    });

    it('does not show notification when refreshArtwork throws', async () => {
      vi.mocked(RecordingDetailsModalUtils.refreshArtwork).mockRejectedValue(
        new Error('fail')
      );
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Refresh artwork'));

      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });
  });

  // ── ComSkip ──────────────────────────────────────────────────────────────────

  describe('run comskip', () => {
    it('calls runComSkip with the recording', async () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Remove commercials'));

      await waitFor(() => {
        expect(RecordingCardUtils.runComSkip).toHaveBeenCalledWith(
          makeRecording()
        );
      });
    });

    it('shows success notification after runComSkip', async () => {
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Remove commercials'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: expect.any(String) })
        );
      });
    });

    it('does not show notification when runComSkip throws', async () => {
      vi.mocked(RecordingCardUtils.runComSkip).mockRejectedValue(
        new Error('fail')
      );
      render(<RecordingDetailsModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Remove commercials'));

      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });

    it('does not show Remove commercials when comskip is completed', () => {
      const recording = makeRecording({
        custom_properties: {
          status: 'completed',
          file_url: '/f.ts',
          comskip: { status: 'completed' },
          program: { title: 'Test Show' },
        },
      });
      setupMocks({ recording });
      render(
        <RecordingDetailsModal {...defaultProps()} recording={recording} />
      );
      expect(screen.queryByText('Remove commercials')).not.toBeInTheDocument();
    });
  });

  // ── Series / episodes ────────────────────────────────────────────────────────

  describe('series group', () => {
    const makeSeriesRecording = () =>
      makeRecording({
        _group_count: 3,
        custom_properties: {
          status: 'scheduled',
          program: { title: 'Series Show', tvg_id: 'series-1' },
        },
        start_time: FUTURE,
        end_time: FUTURE,
      });

    const makeEpisode = (id = 'ep-1') => ({
      id,
      channel: 'ch-1',
      start_time: FUTURE,
      end_time: FUTURE,
      custom_properties: {
        status: 'scheduled',
        program: { title: 'Episode', sub_title: `Sub ${id}` },
      },
    });

    it('renders upcoming episodes list when isSeriesGroup is true', () => {
      const recording = makeSeriesRecording();
      const episode = makeEpisode();
      setupMocks({ recording });
      vi.mocked(RecordingDetailsModalUtils.getUpcomingEpisodes).mockReturnValue(
        [episode]
      );
      render(
        <RecordingDetailsModal {...defaultProps()} recording={recording} />
      );
      expect(screen.getByText('Sub ep-1')).toBeInTheDocument();
    });

    it('shows "No upcoming episodes" when episode list is empty for series', () => {
      const recording = makeSeriesRecording();
      setupMocks({ recording });
      vi.mocked(RecordingDetailsModalUtils.getUpcomingEpisodes).mockReturnValue(
        []
      );
      render(
        <RecordingDetailsModal {...defaultProps()} recording={recording} />
      );
      expect(screen.getByText(/no upcoming episodes/i)).toBeInTheDocument();
    });

    it('opens child modal when an episode card is clicked', async () => {
      const recording = makeSeriesRecording();
      const episode = makeEpisode();
      setupMocks({ recording });
      vi.mocked(RecordingDetailsModalUtils.getUpcomingEpisodes).mockReturnValue(
        [episode]
      );
      render(
        <RecordingDetailsModal {...defaultProps()} recording={recording} />
      );
      const episodeCards = screen.getAllByTestId('card');
      fireEvent.click(episodeCards[episodeCards.length - 1]);
      await waitFor(() => {
        expect(screen.getAllByTestId('modal').length).toBeGreaterThanOrEqual(1);
      });
    });

    it('calls deleteRecordingById when episode remove is clicked', async () => {
      const recording = makeSeriesRecording();
      const episode = makeEpisode();
      setupMocks({ recording });
      vi.mocked(RecordingDetailsModalUtils.getUpcomingEpisodes).mockReturnValue(
        [episode]
      );
      render(
        <RecordingDetailsModal {...defaultProps()} recording={recording} />
      );
      fireEvent.click(screen.getByText('Remove'));
      await waitFor(() => {
        expect(RecordingCardUtils.deleteRecordingById).toHaveBeenCalledWith(
          'ep-1'
        );
      });
    });
  });

  // ── safeRecording merging ────────────────────────────────────────────────────

  describe('safeRecording store merge', () => {
    it('picks updated recording from store while preserving _group_count', () => {
      const original = makeRecording({ _group_count: 3 });
      const storeVersion = {
        ...makeRecording(),
        id: 'rec-1',
        custom_properties: {
          ...makeRecording().custom_properties,
          program: { title: 'Updated Title' },
        },
      };
      vi.mocked(useChannelsStore).mockImplementation((sel) =>
        sel({ recordings: [storeVersion] })
      );
      render(
        <RecordingDetailsModal {...defaultProps()} recording={original} />
      );
      expect(screen.getByText(/Updated Title/i)).toBeInTheDocument();
    });
  });

  // ── Optimistic state reset ───────────────────────────────────────────────────

  describe('optimistic state reset on recording change', () => {
    it('resets saved title when recording id changes', async () => {
      const { rerender } = render(
        <RecordingDetailsModal {...defaultProps()} />
      );
      // Save a new title
      fireEvent.click(screen.getByTestId('icon-pencil').closest('button'));
      fireEvent.change(screen.getByTestId('textinput-Recording title'), {
        target: { value: 'Custom' },
      });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));
      await waitFor(() => expect(screen.getByText('Custom')).toBeInTheDocument());

      // Switch to a different recording
      const newRecording = makeRecording({ id: 'rec-2' });
      setupMocks({ recording: newRecording });
      rerender(
        <RecordingDetailsModal
          {...defaultProps()}
          recording={newRecording}
        />
      );
      expect(screen.getByText(/Test Show/i)).toBeInTheDocument();
    });
  });
});