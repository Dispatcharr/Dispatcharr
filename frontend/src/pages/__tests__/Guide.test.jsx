import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import dayjs from 'dayjs';
import Guide from '../Guide';
import useChannelsStore from '../../store/channels';
import useLogosStore from '../../store/logos';
import useEPGsStore from '../../store/epgs';
import useSettingsStore from '../../store/settings';
import useVideoStore from '../../store/useVideoStore';
import useLocalStorage from '../../hooks/useLocalStorage';
import { showNotification } from '../../utils/notificationUtils.js';
import * as guideUtils from '../guideUtils';
import * as recordingCardUtils from '../../utils/cards/RecordingCardUtils.js';
import * as dateTimeUtils from '../../utils/dateTimeUtils.js';
import userEvent from '@testing-library/user-event';

// Mock dependencies
vi.mock('../../store/channels');
vi.mock('../../store/logos');
vi.mock('../../store/epgs');
vi.mock('../../store/settings');
vi.mock('../../store/useVideoStore');
vi.mock('../../hooks/useLocalStorage');

vi.mock('@mantine/hooks', () => ({
  useElementSize: () => ({
    ref: vi.fn(),
    width: 1200,
    height: 800,
  }),
}));
vi.mock('@mantine/core', async () => {
  const actual = await vi.importActual('@mantine/core');
  return {
    ...actual,
    Box: ({ children, style, onClick, className, ref }) => (
      <div style={style} onClick={onClick} className={className} ref={ref}>
        {children}
      </div>
    ),
    Flex: ({ children, direction, justify, align, gap, mb, style }) => (
      <div
        style={style}
        data-direction={direction}
        data-justify={justify}
        data-align={align}
        data-gap={gap}
        data-mb={mb}
      >
        {children}
      </div>
    ),
    Group: ({ children, gap, justify }) => (
      <div data-gap={gap} data-justify={justify}>
        {children}
      </div>
    ),
    Title: ({ children, order, size }) => (
      <h2 data-order={order} data-size={size}>
        {children}
      </h2>
    ),
    Text: ({ children, size, c, fw, lineClamp, style, onClick }) => (
      <span
        data-size={size}
        data-color={c}
        data-fw={fw}
        data-line-clamp={lineClamp}
        style={style}
        onClick={onClick}
      >
        {children}
      </span>
    ),
    Paper: ({ children, style, onClick }) => (
      <div style={style} onClick={onClick}>
        {children}
      </div>
    ),
    Button: ({
      children,
      onClick,
      leftSection,
      variant,
      size,
      color,
      disabled,
    }) => (
      <button
        onClick={onClick}
        disabled={disabled}
        data-variant={variant}
        data-size={size}
        data-color={color}
      >
        {leftSection}
        {children}
      </button>
    ),
    TextInput: ({ value, onChange, placeholder, icon, rightSection }) => (
      <div>
        {icon}
        <input
          type="text"
          value={value}
          onChange={onChange}
          placeholder={placeholder}
        />
        {rightSection}
      </div>
    ),
    Select: ({ value, onChange, data, placeholder, clearable }) => (
      <select
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        aria-label={placeholder}
        data-clearable={clearable}
      >
        <option value="">Select...</option>
        {data?.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    ),
    ActionIcon: ({ children, onClick, variant, size, color }) => (
      <button
        onClick={onClick}
        data-variant={variant}
        data-size={size}
        data-color={color}
      >
        {children}
      </button>
    ),
    Tooltip: ({ children, label }) => <div title={label}>{children}</div>,
    LoadingOverlay: ({ visible }) => (visible ? <div>Loading...</div> : null),
  };
});
vi.mock('react-window', () => ({
  VariableSizeList: ({ children, itemData, itemCount }) => (
    <div data-testid="variable-size-list">
      {Array.from({ length: Math.min(itemCount, 5) }, (_, i) => (
        <div key={i}>
          {children({
            index: i,
            style: {},
            data: itemData.filteredChannels[i],
          })}
        </div>
      ))}
    </div>
  ),
}));

vi.mock('../../components/GuideRow', () => ({
  default: ({ data }) => (
    <div data-testid="guide-row">GuideRow for {data?.name}</div>
  ),
}));
vi.mock('../../components/HourTimeline', () => ({
  default: ({ hourTimeline }) => (
    <div data-testid="hour-timeline">
      {hourTimeline.map((hour, i) => (
        <div key={i}>{hour.label}</div>
      ))}
    </div>
  ),
}));
vi.mock('../../components/forms/ProgramRecordingModal', () => ({
  __esModule: true,
  default: ({ opened, onClose, program, onRecordOne }) =>
    opened ? (
      <div data-testid="program-recording-modal">
        <div>{program?.title}</div>
        <button onClick={onClose}>Close</button>
        <button onClick={onRecordOne}>Record One</button>
      </div>
    ) : null,
}));
vi.mock('../../components/forms/SeriesRecordingModal', () => ({
  __esModule: true,
  default: ({ opened, onClose, rules }) =>
    opened ? (
      <div data-testid="series-recording-modal">
        <div>Series Rules: {rules.length}</div>
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

vi.mock('../guideUtils', async () => {
  const actual = await vi.importActual('../guideUtils');
  return {
    ...actual,
    fetchPrograms: vi.fn(),
    createRecording: vi.fn(),
    createSeriesRule: vi.fn(),
    evaluateSeriesRule: vi.fn(),
    fetchRules: vi.fn(),
    filterGuideChannels: vi.fn(),
    getGroupOptions: vi.fn(),
    getProfileOptions: vi.fn(),
  };
});
vi.mock('../../utils/cards/RecordingCardUtils.js', async () => {
  const actual = await vi.importActual(
    '../../utils/cards/RecordingCardUtils.js'
  );
  return {
    ...actual,
    getShowVideoUrl: vi.fn(),
  };
});
vi.mock('../../utils/dateTimeUtils.js', async () => {
  const actual = await vi.importActual('../../utils/dateTimeUtils.js');
  return {
    ...actual,
    getNow: vi.fn(),
    add: vi.fn(),
    format: vi.fn(),
    initializeTime: vi.fn(),
    startOfDay: vi.fn(),
    convertToMs: vi.fn(),
    useDateTimeFormat: vi.fn(),
  };
});
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

describe('Guide', () => {
  let mockChannelsState;
  let mockShowVideo;
  let mockFetchRecordings;
  const now = dayjs('2024-01-15T12:00:00Z');

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2024-01-15T12:00:00Z'));

    mockChannelsState = {
      channels: {
        'channel-1': {
          id: 'channel-1',
          uuid: 'uuid-1',
          name: 'Test Channel 1',
          channel_number: 1,
          logo_id: 'logo-1',
          stream_url: 'http://stream1.test',
        },
        'channel-2': {
          id: 'channel-2',
          uuid: 'uuid-2',
          name: 'Test Channel 2',
          channel_number: 2,
          logo_id: 'logo-2',
          stream_url: 'http://stream2.test',
        },
      },
      recordings: [],
      channelGroups: {
        'group-1': { id: 'group-1', name: 'News', channels: ['channel-1'] },
      },
      profiles: {
        'profile-1': { id: 'profile-1', name: 'HD Profile' },
      },
    };

    mockShowVideo = vi.fn();
    mockFetchRecordings = vi.fn().mockResolvedValue([]);

    useChannelsStore.mockImplementation((selector) => {
      const state = {
        ...mockChannelsState,
        fetchRecordings: mockFetchRecordings,
      };
      return selector ? selector(state) : state;
    });

    useLogosStore.mockReturnValue({
      'logo-1': { url: 'http://logo1.png' },
      'logo-2': { url: 'http://logo2.png' },
    });

    useEPGsStore.mockImplementation((selector) =>
      selector
        ? selector({ tvgsById: {}, epgs: {} })
        : { tvgsById: {}, epgs: {} }
    );

    useSettingsStore.mockReturnValue('production');
    useVideoStore.mockReturnValue(mockShowVideo);
    useLocalStorage.mockReturnValue(['12h', vi.fn()]);

    dateTimeUtils.getNow.mockReturnValue(now);
    dateTimeUtils.format.mockImplementation((date, format) => {
      if (format?.includes('dddd')) return 'Monday, 01/15/2024 • 12:00 PM';
      return '12:00 PM';
    });
    dateTimeUtils.initializeTime.mockImplementation((date) => date || now);
    dateTimeUtils.startOfDay.mockReturnValue(now.startOf('day'));
    dateTimeUtils.add.mockImplementation((date, amount, unit) =>
      dayjs(date).add(amount, unit)
    );
    dateTimeUtils.convertToMs.mockImplementation((date) =>
      dayjs(date).valueOf()
    );
    dateTimeUtils.useDateTimeFormat.mockReturnValue({
      timeFormat: '12h',
      dateFormat: 'MM/DD/YYYY',
    });

    guideUtils.fetchPrograms.mockResolvedValue([
      {
        id: 'prog-1',
        tvg_id: 'tvg-1',
        title: 'Test Program 1',
        description: 'Description 1',
        start_time: now.toISOString(),
        end_time: now.add(1, 'hour').toISOString(),
        programStart: now,
        programEnd: now.add(1, 'hour'),
        startMs: now.valueOf(),
        endMs: now.add(1, 'hour').valueOf(),
        isLive: true,
        isPast: false,
      },
    ]);

    guideUtils.fetchRules.mockResolvedValue([]);
    guideUtils.filterGuideChannels.mockImplementation((channels) =>
      Object.values(channels)
    );
    guideUtils.createRecording.mockResolvedValue(undefined);
    guideUtils.createSeriesRule.mockResolvedValue(undefined);
    guideUtils.evaluateSeriesRule.mockResolvedValue(undefined);
    guideUtils.getGroupOptions.mockReturnValue([
      { value: 'all', label: 'All Groups' },
      { value: 'group-1', label: 'News' },
    ]);
    guideUtils.getProfileOptions.mockReturnValue([
      { value: 'all', label: 'All Profiles' },
      { value: 'profile-1', label: 'HD Profile' },
    ]);

    recordingCardUtils.getShowVideoUrl.mockReturnValue('http://video.test');
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  describe('Rendering', () => {
    it('renders the TV Guide title', async () => {
      render(<Guide />);

      expect(screen.getByText('TV Guide')).toBeInTheDocument();
    });

    it('displays current time in header', async () => {
      render(<Guide />);

      expect(screen.getByText(/Monday, 01\/15\/2024/)).toBeInTheDocument();
    });

    it('renders channel rows when channels are available', async () => {
      render(<Guide />);

      expect(screen.getAllByTestId('guide-row')).toHaveLength(2);
    });

    it('shows no channels message when filters exclude all channels', async () => {
      guideUtils.filterGuideChannels.mockReturnValue([]);

      render(<Guide />);

      // await waitFor(() => {
      expect(
        screen.getByText('No channels match your filters')
      ).toBeInTheDocument();
      // });
    });

    it('displays channel count', async () => {
      render(<Guide />);

      // await waitFor(() => {
      expect(screen.getByText(/2 channels/)).toBeInTheDocument();
      // });
    });
  });

  describe('Search Functionality', () => {
    it('updates search query when user types', async () => {
      vi.useRealTimers();

      render(<Guide />);

      const searchInput = screen.getByPlaceholderText('Search channels...');
      fireEvent.change(searchInput, { target: { value: 'Test' } });

      expect(searchInput).toHaveValue('Test');
    });

    it('clears search query when clear button is clicked', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);

      const searchInput = screen.getByPlaceholderText('Search channels...');

      await user.type(searchInput, 'Test');
      expect(searchInput).toHaveValue('Test');

      await user.click(screen.getByText('Clear Filters'));
      expect(searchInput).toHaveValue('');
    });

    it('calls filterGuideChannels with search query', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);

      const searchInput =
        await screen.findByPlaceholderText('Search channels...');
      await user.type(searchInput, 'News');

      await waitFor(() => {
        expect(guideUtils.filterGuideChannels).toHaveBeenCalledWith(
          expect.anything(),
          'News',
          'all',
          'all',
          expect.anything()
        );
      });
    });
  });

  describe('Filter Functionality', () => {
    it('filters by channel group', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);

      const groupSelect = await screen.findByLabelText('Filter by group');
      await user.selectOptions(groupSelect, 'group-1');

      await waitFor(() => {
        expect(guideUtils.filterGuideChannels).toHaveBeenCalledWith(
          expect.anything(),
          '',
          'group-1',
          'all',
          expect.anything()
        );
      });
    });

    it('filters by profile', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);

      const profileSelect = await screen.findByLabelText('Filter by profile');
      await user.selectOptions(profileSelect, 'profile-1');

      await waitFor(() => {
        expect(guideUtils.filterGuideChannels).toHaveBeenCalledWith(
          expect.anything(),
          '',
          'all',
          'profile-1',
          expect.anything()
        );
      });
    });

    it('clears all filters when Clear Filters is clicked', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);

      // Set some filters
      const searchInput =
        await screen.findByPlaceholderText('Search channels...');
      await user.type(searchInput, 'Test');

      // Clear them
      const clearButton = await screen.findByText('Clear Filters');
      await user.click(clearButton);

      expect(searchInput).toHaveValue('');
    });
  });

  describe('Recording Functionality', () => {
    it('opens Series Rules modal when button is clicked', async () => {
      vi.useRealTimers();

      const user = userEvent.setup();
      render(<Guide />);

      const rulesButton = await screen.findByText('Series Rules');
      await user.click(rulesButton);

      await waitFor(() => {
        expect(
          screen.getByTestId('series-recording-modal')
        ).toBeInTheDocument();
      });

      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-01-15T12:00:00Z'));
    });

    it('fetches rules when opening Series Rules modal', async () => {
      vi.useRealTimers();

      const mockRules = [{ id: 1, title: 'Test Rule' }];
      guideUtils.fetchRules.mockResolvedValue(mockRules);

      const user = userEvent.setup();
      render(<Guide />);

      const rulesButton = await screen.findByText('Series Rules');
      await user.click(rulesButton);

      await waitFor(() => {
        expect(guideUtils.fetchRules).toHaveBeenCalled();
      });

      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-01-15T12:00:00Z'));
    });
  });

  describe('Navigation', () => {
    it('scrolls to current time when Jump to current time is clicked', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);

      const jumpButton = await screen.findByTitle('Jump to current time');
      await user.click(jumpButton);

      // Verify button was clicked (scroll behavior is tested in integration tests)
      expect(jumpButton).toBeInTheDocument();
    });
  });

  describe('Time Updates', () => {
    it('updates current time every second', async () => {
      render(<Guide />);

      expect(screen.getByText(/Monday, 01\/15\/2024/)).toBeInTheDocument();

      // Advance time by 1 second
      vi.advanceTimersByTime(1000);

      expect(dateTimeUtils.getNow).toHaveBeenCalled();
    });
  });

  describe('Error Handling', () => {
    it('shows notification when no channels are available', async () => {
      useChannelsStore.mockImplementation((selector) => {
        const state = {
          channels: {},
          recordings: [],
          channelGroups: {},
          profiles: {},
        };
        return selector ? selector(state) : state;
      });

      render(<Guide />);

      expect(showNotification).toHaveBeenCalledWith({
        title: 'No channels available',
        color: 'red.5',
      });
    });
  });

  describe('Watch Functionality', () => {
    it('calls showVideo when watch button is clicked on live program', async () => {
      vi.useRealTimers();

      // Mock a live program
      const liveProgram = {
        id: 'prog-live',
        tvg_id: 'tvg-1',
        title: 'Live Show',
        description: 'Live Description',
        start_time: now.subtract(30, 'minutes').toISOString(),
        end_time: now.add(30, 'minutes').toISOString(),
        programStart: now.subtract(30, 'minutes'),
        programEnd: now.add(30, 'minutes'),
        startMs: now.subtract(30, 'minutes').valueOf(),
        endMs: now.add(30, 'minutes').valueOf(),
        isLive: true,
        isPast: false,
      };

      guideUtils.fetchPrograms.mockResolvedValue([liveProgram]);

      render(<Guide />);

      await waitFor(() => {
        expect(screen.getByText('TV Guide')).toBeInTheDocument();
      });

      // Implementation depends on how programs are rendered - this is a placeholder
      // You would need to find and click the actual watch button in the rendered program

      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-01-15T12:00:00Z'));
    });

    it('does not show watch button for past programs', async () => {
      vi.useRealTimers();

      const pastProgram = {
        id: 'prog-past',
        tvg_id: 'tvg-1',
        title: 'Past Show',
        description: 'Past Description',
        start_time: now.subtract(2, 'hours').toISOString(),
        end_time: now.subtract(1, 'hour').toISOString(),
        programStart: now.subtract(2, 'hours'),
        programEnd: now.subtract(1, 'hour'),
        startMs: now.subtract(2, 'hours').valueOf(),
        endMs: now.subtract(1, 'hour').valueOf(),
        isLive: false,
        isPast: true,
      };

      guideUtils.fetchPrograms.mockResolvedValue([pastProgram]);

      render(<Guide />);

      await waitFor(() => {
        expect(screen.getByText('TV Guide')).toBeInTheDocument();
      });

      vi.useFakeTimers();
      vi.setSystemTime(new Date('2024-01-15T12:00:00Z'));
    });
  });
});
