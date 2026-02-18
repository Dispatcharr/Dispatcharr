import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import DVRPage from '../DVR';
import dayjs from 'dayjs';
import useChannelsStore from '../../store/channels';
import useSettingsStore from '../../store/settings';
import useVideoStore from '../../store/useVideoStore';
import useLocalStorage from '../../hooks/useLocalStorage';
import API from '../../api';
import {
  isAfter,
  isBefore,
  useTimeHelpers,
} from '../../utils/dateTimeUtils.js';
import { categorizeRecordings } from '../../utils/pages/DVRUtils.js';
import {
  getPosterUrl,
  getRecordingUrl,
  getShowVideoUrl,
} from '../../utils/cards/RecordingCardUtils.js';

vi.mock('../../store/channels');
vi.mock('../../store/settings');
vi.mock('../../store/useVideoStore');
vi.mock('../../hooks/useLocalStorage');
vi.mock('../../api');

// Mock Mantine components
vi.mock('@mantine/core', () => ({
  Box: ({ children }) => <div data-testid="box">{children}</div>,
  Container: ({ children }) => <div data-testid="container">{children}</div>,
  Title: ({ children, order }) => <h1 data-order={order}>{children}</h1>,
  Text: ({ children }) => <p>{children}</p>,
  Button: ({ children, onClick, leftSection, loading, ...props }) => (
    <button onClick={onClick} disabled={loading} {...props}>
      {leftSection}
      {children}
    </button>
  ),
  Badge: ({ children }) => <span>{children}</span>,
  SimpleGrid: ({ children }) => <div data-testid="simple-grid">{children}</div>,
  Group: ({ children }) => <div data-testid="group">{children}</div>,
  Stack: ({ children }) => <div data-testid="stack">{children}</div>,
  Divider: () => <hr data-testid="divider" />,
  useMantineTheme: () => ({
    tailwind: {
      green: { 5: '#22c55e' },
      red: { 6: '#dc2626' },
      yellow: { 6: '#ca8a04' },
      gray: { 6: '#52525b' },
    },
  }),
}));

// Mock components
vi.mock('../../components/cards/RecordingCard', () => ({
  default: ({ recording, onOpenDetails, onOpenRecurring }) => (
    <div data-testid={`recording-card-${recording.id}`}>
      <span>{recording.custom_properties?.Title || 'Recording'}</span>
      <button onClick={() => onOpenDetails(recording)}>Open Details</button>
      {recording.custom_properties?.rule && (
        <button onClick={() => onOpenRecurring(recording)}>
          Open Recurring
        </button>
      )}
    </div>
  ),
}));

vi.mock('../../components/forms/RecordingDetailsModal', () => ({
  default: ({
    opened,
    onClose,
    recording,
    onEdit,
    onWatchLive,
    onWatchRecording,
  }) =>
    opened ? (
      <div data-testid="details-modal">
        <div data-testid="modal-title">
          {recording?.custom_properties?.Title}
        </div>
        <button onClick={onClose}>Close Modal</button>
        <button onClick={onEdit}>Edit</button>
        <button onClick={onWatchLive}>Watch Live</button>
        <button onClick={onWatchRecording}>Watch Recording</button>
      </div>
    ) : null,
}));

vi.mock('../../components/forms/RecurringRuleModal', () => ({
  default: ({ opened, onClose, ruleId }) =>
    opened ? (
      <div data-testid="recurring-modal">
        <div>Rule ID: {ruleId}</div>
        <button onClick={onClose}>Close Recurring</button>
      </div>
    ) : null,
}));

vi.mock('../../components/forms/Recording', () => ({
  default: ({ isOpen, onClose, recording }) =>
    isOpen ? (
      <div data-testid="recording-form">
        <div>Recording ID: {recording?.id || 'new'}</div>
        <button onClick={onClose}>Close Form</button>
      </div>
    ) : null,
}));

vi.mock('../../components/ErrorBoundary', () => ({
  default: ({ children }) => <div data-testid="error-boundary">{children}</div>,
}));

vi.mock('../../utils/dateTimeUtils.js', async (importActual) => {
  const actual = await importActual();
  return {
    ...actual,
    isBefore: vi.fn(),
    isAfter: vi.fn(),
    useTimeHelpers: vi.fn(),
  };
});
vi.mock('../../utils/cards/RecordingCardUtils.js', () => ({
  getPosterUrl: vi.fn(),
  getRecordingUrl: vi.fn(),
  getShowVideoUrl: vi.fn(),
}));
vi.mock('../../utils/pages/DVRUtils.js', async (importActual) => {
  const actual = await importActual();
  return {
    ...actual,
    categorizeRecordings: vi.fn(),
  };
});

describe('DVRPage', () => {
  const mockShowVideo = vi.fn();
  const mockFetchRecordings = vi.fn();
  const mockFetchChannels = vi.fn();
  const mockFetchRecurringRules = vi.fn();
  const mockRemoveRecording = vi.fn();

  const defaultChannelsState = {
    recordings: [],
    channels: {},
    recurringRules: [],
    fetchRecordings: mockFetchRecordings,
    fetchChannels: mockFetchChannels,
    fetchRecurringRules: mockFetchRecurringRules,
    removeRecording: mockRemoveRecording,
  };

  const defaultSettingsState = {
    settings: {
      system_settings: { value: { time_zone: 'America/New_York' } },
    },
    environment: {
      env_mode: 'production',
    },
  };

  const defaultVideoState = {
    showVideo: mockShowVideo,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    const now = new Date('2024-01-15T12:00:00Z');
    vi.setSystemTime(now);

    // Default: API.getChannel returns null (no channel data loaded by default)
    API.getChannel.mockResolvedValue(null);

    isAfter.mockImplementation((a, b) => new Date(a) > new Date(b));
    isBefore.mockImplementation((a, b) => new Date(a) < new Date(b));
    useTimeHelpers.mockReturnValue({
      toUserTime: (dt) => dayjs(dt).tz('America/New_York').toDate(),
      userNow: () => dayjs().tz('America/New_York').toDate(),
    });

    categorizeRecordings.mockImplementation((recordings, toUserTime, now) => {
      const inProgress = [];
      const upcoming = [];
      const completed = [];
      recordings.forEach((rec) => {
        const start = toUserTime(rec.start_time);
        const end = toUserTime(rec.end_time);
        if (now >= start && now <= end) inProgress.push(rec);
        else if (now < start) upcoming.push(rec);
        else completed.push(rec);
      });
      return { inProgress, upcoming, completed };
    });

    getPosterUrl.mockImplementation((recording) =>
      recording?.id ? `http://poster.url/${recording.id}` : null
    );
    getRecordingUrl.mockImplementation(
      (custom_properties) => custom_properties?.recording_url
    );
    getShowVideoUrl.mockImplementation((channel) => channel?.stream_url);

    useChannelsStore.mockImplementation((selector) => {
      return selector ? selector(defaultChannelsState) : defaultChannelsState;
    });
    useChannelsStore.getState = () => defaultChannelsState;

    useSettingsStore.mockImplementation((selector) => {
      return selector ? selector(defaultSettingsState) : defaultSettingsState;
    });
    useSettingsStore.getState = () => defaultSettingsState;

    useVideoStore.mockImplementation((selector) => {
      return selector ? selector(defaultVideoState) : defaultVideoState;
    });
    useVideoStore.getState = () => defaultVideoState;

    useLocalStorage.mockReturnValue(['America/New_York', vi.fn()]);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.clearAllTimers(); // Clear pending timers
    vi.useRealTimers();
  });

  describe('Initial Render', () => {
    it('renders new recording buttons', () => {
      render(<DVRPage />);

      expect(screen.getByText('New Recording')).toBeInTheDocument();
    });

    it('renders empty state when no recordings', () => {
      render(<DVRPage />);

      expect(screen.getByText('No upcoming recordings.')).toBeInTheDocument();
    });
  });

  describe('Recording Display', () => {
    it('displays recordings grouped by date', () => {
      const now = dayjs('2024-01-15T12:00:00Z');
      const recordings = [
        {
          id: 1,
          channel: 1,
          start_time: now.toISOString(),
          end_time: now.add(1, 'hour').toISOString(),
          custom_properties: { Title: 'Show 1' },
        },
        {
          id: 2,
          channel: 1,
          start_time: now.add(1, 'day').toISOString(),
          end_time: now.add(1, 'day').add(1, 'hour').toISOString(),
          custom_properties: { Title: 'Show 2' },
        },
      ];

      useChannelsStore.mockImplementation((selector) => {
        const state = { ...defaultChannelsState, recordings };
        return selector ? selector(state) : state;
      });

      render(<DVRPage />);

      expect(screen.getByTestId('recording-card-1')).toBeInTheDocument();
      expect(screen.getByTestId('recording-card-2')).toBeInTheDocument();
    });
  });

  describe('New Recording', () => {
    it('opens recording form when new recording button is clicked', async () => {
      render(<DVRPage />);

      const newButton = screen.getByText('New Recording');
      fireEvent.click(newButton);

      expect(screen.getByTestId('recording-form')).toBeInTheDocument();
    });

    it('closes recording form when close is clicked', async () => {
      render(<DVRPage />);

      const newButton = screen.getByText('New Recording');
      fireEvent.click(newButton);

      expect(screen.getByTestId('recording-form')).toBeInTheDocument();

      const closeButton = screen.getByText('Close Form');
      fireEvent.click(closeButton);

      expect(screen.queryByTestId('recording-form')).not.toBeInTheDocument();
    });
  });

  describe('Recording Details Modal', () => {
    const setupRecording = () => {
      const now = dayjs('2024-01-15T12:00:00Z');
      const recording = {
        id: 1,
        channel: 1,
        start_time: now.toISOString(),
        end_time: now.add(1, 'hour').toISOString(),
        custom_properties: { Title: 'Test Show' },
      };

      useChannelsStore.mockImplementation((selector) => {
        const state = {
          ...defaultChannelsState,
          recordings: [recording],
          channels: {
            1: { id: 1, name: 'Channel 1', stream_url: 'http://stream.url' },
          },
        };
        return selector ? selector(state) : state;
      });

      return recording;
    };

    it('opens details modal when recording card is clicked', async () => {
      vi.useRealTimers();

      setupRecording();
      render(<DVRPage />);

      const detailsButton = screen.getByText('Open Details');
      fireEvent.click(detailsButton);

      await screen.findByTestId('details-modal');
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Test Show');
    });

    it('closes details modal when close is clicked', async () => {
      vi.useRealTimers();

      setupRecording();
      render(<DVRPage />);

      const detailsButton = screen.getByText('Open Details');
      fireEvent.click(detailsButton);

      await screen.findByTestId('details-modal');

      const closeButton = screen.getByText('Close Modal');
      fireEvent.click(closeButton);

      expect(screen.queryByTestId('details-modal')).not.toBeInTheDocument();
    });

    it('opens edit form from details modal', async () => {
      vi.useRealTimers();

      setupRecording();
      render(<DVRPage />);

      const detailsButton = screen.getByText('Open Details');
      fireEvent.click(detailsButton);

      await screen.findByTestId('details-modal');

      const editButton = screen.getByText('Edit');
      fireEvent.click(editButton);

      expect(screen.queryByTestId('details-modal')).not.toBeInTheDocument();
      expect(screen.getByTestId('recording-form')).toBeInTheDocument();
    });
  });

  describe('Recurring Rule Modal', () => {
    it('opens recurring rule modal when recording has rule', async () => {
      const now = dayjs('2024-01-15T12:00:00Z');
      const recording = {
        id: 1,
        channel: 1,
        start_time: now.toISOString(),
        end_time: now.add(1, 'hour').toISOString(),
        custom_properties: {
          Title: 'Recurring Show',
          rule: { id: 100 },
        },
      };

      useChannelsStore.mockImplementation((selector) => {
        const state = {
          ...defaultChannelsState,
          recordings: [recording],
          channels: { 1: { id: 1, name: 'Channel 1' } },
        };
        return selector ? selector(state) : state;
      });

      render(<DVRPage />);

      const recurringButton = screen.getByText('Open Recurring');
      fireEvent.click(recurringButton);

      expect(screen.getByTestId('recurring-modal')).toBeInTheDocument();
      expect(screen.getByText('Rule ID: 100')).toBeInTheDocument();
    });

    it('closes recurring modal when close is clicked', async () => {
      const now = dayjs('2024-01-15T12:00:00Z');
      const recording = {
        id: 1,
        channel: 1,
        start_time: now.toISOString(),
        end_time: now.add(1, 'hour').toISOString(),
        custom_properties: {
          Title: 'Recurring Show',
          rule: { id: 100 },
        },
      };

      useChannelsStore.mockImplementation((selector) => {
        const state = {
          ...defaultChannelsState,
          recordings: [recording],
          channels: { 1: { id: 1, name: 'Channel 1' } },
        };
        return selector ? selector(state) : state;
      });

      render(<DVRPage />);

      const recurringButton = screen.getByText('Open Recurring');
      fireEvent.click(recurringButton);

      expect(screen.getByTestId('recurring-modal')).toBeInTheDocument();

      const closeButton = screen.getByText('Close Recurring');
      fireEvent.click(closeButton);

      expect(screen.queryByTestId('recurring-modal')).not.toBeInTheDocument();
    });
  });

  describe('Watch Functionality', () => {
    it('calls showVideo for watch live on in-progress recording', async () => {
      vi.useRealTimers();

      const now = dayjs();
      const recording = {
        id: 1,
        channel: 1,
        start_time: now.subtract(30, 'minutes').toISOString(),
        end_time: now.add(30, 'minutes').toISOString(),
        custom_properties: { Title: 'Live Show' },
      };

      // DVR.jsx now lazy-loads channel data via API.getChannel rather than
      // reading s.channels from the store.  Mock the API so channelsById
      // gets populated before the Watch Live handler runs.
      API.getChannel.mockResolvedValue({
        id: 1,
        name: 'Channel 1',
        stream_url: 'http://stream.url',
      });

      useChannelsStore.mockImplementation((selector) => {
        const state = {
          ...defaultChannelsState,
          recordings: [recording],
        };
        return selector ? selector(state) : state;
      });

      render(<DVRPage />);

      const detailsButton = screen.getByText('Open Details');
      fireEvent.click(detailsButton);

      await screen.findByTestId('details-modal');

      // Wait for channelsById to be populated from the async API call
      await waitFor(() => {
        expect(API.getChannel).toHaveBeenCalledWith(1);
      });

      const watchLiveButton = screen.getByText('Watch Live');
      fireEvent.click(watchLiveButton);

      expect(mockShowVideo).toHaveBeenCalledWith(
        expect.stringContaining('stream.url'),
        'live'
      );
    });

    it('calls showVideo for watch recording on completed recording', async () => {
      vi.useRealTimers();

      const now = dayjs('2024-01-15T12:00:00Z');
      const recording = {
        id: 1,
        channel: 1,
        start_time: now.subtract(2, 'hours').toISOString(),
        end_time: now.subtract(1, 'hour').toISOString(),
        custom_properties: {
          Title: 'Recorded Show',
          recording_url: 'http://recording.url/video.mp4',
        },
      };

      useChannelsStore.mockImplementation((selector) => {
        const state = {
          ...defaultChannelsState,
          recordings: [recording],
          channels: { 1: { id: 1, name: 'Channel 1' } },
        };
        return selector ? selector(state) : state;
      });

      render(<DVRPage />);

      const detailsButton = screen.getByText('Open Details');
      fireEvent.click(detailsButton);

      await screen.findByTestId('details-modal');

      const watchButton = screen.getByText('Watch Recording');
      fireEvent.click(watchButton);

      expect(mockShowVideo).toHaveBeenCalledWith(
        expect.stringContaining('http://recording.url/video.mp4'),
        'vod',
        expect.objectContaining({
          name: 'Recording',
        })
      );
    });

    it('does not call showVideo when recording URL is missing', async () => {
      vi.useRealTimers();

      const now = dayjs('2024-01-15T12:00:00Z');
      const recording = {
        id: 1,
        channel: 1,
        start_time: now.subtract(2, 'hours').toISOString(),
        end_time: now.subtract(1, 'hour').toISOString(),
        custom_properties: { Title: 'No URL Show' },
      };

      useChannelsStore.mockImplementation((selector) => {
        const state = {
          ...defaultChannelsState,
          recordings: [recording],
          channels: { 1: { id: 1, name: 'Channel 1' } },
        };
        return selector ? selector(state) : state;
      });

      render(<DVRPage />);

      const detailsButton = await screen.findByText('Open Details');
      fireEvent.click(detailsButton);

      const modal = await screen.findByTestId('details-modal');
      expect(modal).toBeInTheDocument();

      const watchButton = screen.getByText('Watch Recording');
      fireEvent.click(watchButton);

      expect(mockShowVideo).not.toHaveBeenCalled();
    });
  });
});
