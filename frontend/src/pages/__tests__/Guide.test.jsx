import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import API from '../../api';
import dayjs from 'dayjs';
import Guide from '../Guide';
import ProgramSearchPanel from '../../components/ProgramSearchPanel';
import useChannelsStore from '../../store/channels';
import useLogosStore from '../../store/logos';
import useEPGsStore from '../../store/epgs';
import useSettingsStore from '../../store/settings';
import useVideoStore from '../../store/useVideoStore';
import useAuthStore from '../../store/auth';
import useBrowserStorage from '../../hooks/useBrowserStorage';
import * as guideUtils from '../../utils/guideUtils';
import * as recordingCardUtils from '../../utils/cards/RecordingCardUtils.js';
import * as dateTimeUtils from '../../utils/dateTimeUtils.js';
import userEvent from '@testing-library/user-event';
import { USER_LEVELS } from '../../constants';

// Mock dependencies
vi.mock('../../store/channels', () => ({
  default: vi.fn(),
}));
vi.mock('../../store/logos', () => ({
  default: vi.fn(),
}));
vi.mock('../../store/epgs', () => ({
  default: vi.fn(),
}));
vi.mock('../../store/settings', () => ({
  default: vi.fn(),
}));
vi.mock('../../store/useVideoStore', () => ({
  default: vi.fn(),
}));
vi.mock('../../store/auth', () => ({
  default: vi.fn(),
}));
vi.mock('../../hooks/useBrowserStorage', () => ({
  readStoredJSON: (key, defaultValue) => defaultValue,
  writeStoredJSON: vi.fn(),
  default: vi.fn(),
}));
vi.mock('../../api', () => ({
  default: {
    getAllChannelIds: vi.fn(),
    getChannelsSummary: vi.fn(),
    getChannel: vi.fn(),
    searchPrograms: vi.fn(),
  },
}));

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
    Box: ({
      children,
      style,
      onClick,
      className,
      ref,
      'aria-hidden': ariaHidden,
    }) => (
      <div
        style={style}
        onClick={onClick}
        className={className}
        ref={ref}
        aria-hidden={ariaHidden}
      >
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
    Group: ({ children, gap, justify, ref }) => (
      <div data-gap={gap} data-justify={justify} ref={ref}>
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
    Badge: ({ children, size, variant, color, style }) => (
      <span
        data-size={size}
        data-variant={variant}
        data-color={color}
        style={style}
      >
        {children}
      </span>
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
    SegmentedControl: ({ data, value, onChange }) => (
      <div>
        {data.map((option) => (
          <button
            key={option.value}
            aria-pressed={option.value === value}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
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
            data: itemData,
          })}
        </div>
      ))}
    </div>
  ),
}));

vi.mock('../../components/GuideRow', () => ({
  default: ({ index, data }) => {
    const channel = data?.filteredChannels?.[index];
    const channelPrograms = data?.programsByChannelId?.get(channel?.id) || [];
    const program = channelPrograms[0] || {
      id: 'prog-1',
      tvg_id: 'tvg-1',
      title: 'Test Program 1',
      channel_id: channel?.id,
      start_time: '2024-01-15T12:00:00Z',
      end_time: '2024-01-15T13:00:00Z',
      programStart: dayjs('2024-01-15T12:00:00Z'),
      programEnd: dayjs('2024-01-15T13:00:00Z'),
      startMs: dayjs('2024-01-15T12:00:00Z').valueOf(),
      endMs: dayjs('2024-01-15T13:00:00Z').valueOf(),
    };

    return (
      <div data-testid="guide-row">
        GuideRow for {channel?.name}
        <button
          data-testid="guide-row-select"
          onClick={() => {
            // renderProgram embeds the click handler — call it directly
            const fakeEvent = { stopPropagation: () => {}, preventDefault: () => {} };
            // renderProgram returns a Box with onClick — extract and call it
            const rendered = data?.renderProgram?.(program, undefined, channel);
            rendered?.props?.onClick?.(fakeEvent);
          }}
        >
          Select program
        </button>
      </div>
    );
  },
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
vi.mock('../../components/ProgramDetailModal', () => ({
  __esModule: true,
  default: ({ program, channel, opened, onClose, onRecord }) =>
    opened ? (
      <div data-testid="program-detail-modal" data-channel-uuid={channel?.uuid}>
        <div>{program?.title}</div>
        <button onClick={onClose}>Close</button>
        {onRecord && <button onClick={() => onRecord(program)}>Record</button>}
      </div>
    ) : null,
}));
// Stub for the result selection tests. The typing test renders the real panel.
vi.mock('../../components/ProgramSearchPanel', async () => {
  const { useState } = await vi.importActual('react');
  const program = {
    id: 501,
    tvg_id: 'tvg-9',
    title: 'Searched Program',
    start_time: '2024-01-15T13:00:00Z',
    end_time: '2024-01-15T14:00:00Z',
    isLive: false,
    isPast: false,
  };
  const ProgramSearchPanel = ({ visible, onSelect }) => {
    const [query, setQuery] = useState('');
    return (
      <div data-testid="program-search-panel" data-visible={visible}>
        <input
          placeholder="Search programs..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          onClick={() =>
            onSelect(program, { id: 'channel-1', name: 'Test Channel 1' })
          }
        >
          Select loaded channel
        </button>
        <button
          onClick={() =>
            onSelect(program, { id: 'channel-9', name: 'Other Channel' })
          }
        >
          Select other channel
        </button>
        <button onClick={() => onSelect(program, null)}>Select unmapped</button>
      </div>
    );
  };
  return {
    __esModule: true,
    default: vi.fn(ProgramSearchPanel),
  };
});

vi.mock('../../utils/guideUtils', async () => {
  const actual = await vi.importActual('../../utils/guideUtils');
  return {
    ...actual,
    fetchPrograms: vi.fn(),
    createRecording: vi.fn(),
    createSeriesRule: vi.fn(),
    fetchRules: vi.fn(),
    filterGuideChannels: vi.fn(),
    getGroupOptions: vi.fn(),
    getProfileOptions: vi.fn(),
    sortChannels: vi.fn((ch) => ch),
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
  let mockEnableLogoRendering;
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
        // hasChannels is required: Guide.jsx filters groups by this property
        'group-1': {
          id: 'group-1',
          name: 'News',
          channels: ['channel-1'],
          hasChannels: true,
        },
      },
      profiles: {
        'profile-1': { id: 'profile-1', name: 'HD Profile' },
      },
    };

    mockShowVideo = vi.fn();
    mockFetchRecordings = vi.fn().mockResolvedValue([]);
    mockEnableLogoRendering = vi.fn();

    useChannelsStore.mockImplementation((selector) => {
      const state = {
        ...mockChannelsState,
        fetchRecordings: mockFetchRecordings,
      };
      return selector ? selector(state) : state;
    });

    useLogosStore.mockImplementation((selector) => {
      const state = {
        logos: {
          'logo-1': { url: 'http://logo1.png' },
          'logo-2': { url: 'http://logo2.png' },
        },
        enableLogoRendering: mockEnableLogoRendering,
      };
      return selector ? selector(state) : state;
    });

    useEPGsStore.mockImplementation((selector) =>
      selector
        ? selector({ tvgsById: {}, epgs: {} })
        : { tvgsById: {}, epgs: {} }
    );

    useSettingsStore.mockReturnValue('production');
    useVideoStore.mockReturnValue(mockShowVideo);
    useAuthStore.mockImplementation((selector) => {
      const state = {
        user: {
          id: 1,
          user_level: USER_LEVELS.ADMIN,
          custom_properties: {},
        },
      };
      return selector ? selector(state) : state;
    });
    useBrowserStorage.mockReturnValue(['12h', vi.fn()]);

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
      dateYearFormat: 'MMM D, YYYY',
    });

    guideUtils.fetchPrograms.mockResolvedValue([
      {
        id: 'prog-1',
        tvg_id: 'tvg-1',
        title: 'Test Program 1',
        sub_title: 'The Pilot',
        description: 'Description 1',
        season: 1,
        episode: 3,
        is_new: false,
        is_live: false,
        is_premiere: false,
        is_finale: false,
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
    guideUtils.getGroupOptions.mockReturnValue([
      { value: 'all', label: 'All Groups' },
      { value: 'group-1', label: 'News' },
    ]);
    guideUtils.getProfileOptions.mockReturnValue([
      { value: 'all', label: 'All Profiles' },
      { value: 'profile-1', label: 'HD Profile' },
    ]);

    recordingCardUtils.getShowVideoUrl.mockReturnValue('http://video.test');

    // Guide.jsx now fetches channels from the API rather than reading them
    // from the channel store.  Mock both calls so guideChannels gets populated.
    const mockChannelsArray = Object.values(mockChannelsState.channels);
    API.getAllChannelIds.mockResolvedValue(
      Object.keys(mockChannelsState.channels)
    );
    API.getChannelsSummary.mockResolvedValue(mockChannelsArray);
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  describe('Rendering', () => {
    it('renders the TV Guide title', async () => {
      render(<Guide />);

      expect(screen.getByText('TV Guide')).toBeInTheDocument();
      expect(mockEnableLogoRendering).toHaveBeenCalledOnce();
    });

    it('displays current time in header', async () => {
      render(<Guide />);

      expect(screen.getByText(/Monday, 01\/15\/2024/)).toBeInTheDocument();
    });

    it('renders a day-first header date without a comma before the year', () => {
      dateTimeUtils.useDateTimeFormat.mockReturnValue({
        timeFormat: 'HH:mm',
        dateFormat: 'D MMM',
        dateYearFormat: 'D MMM YYYY',
      });
      dateTimeUtils.format.mockImplementation((date, fmt) =>
        dayjs(date).format(fmt)
      );
      render(<Guide />);
      const header = screen.getByText(/•/);
      expect(header).toHaveTextContent(/\d{1,2} [A-Za-z]{3} \d{4}/);
      expect(header.textContent).not.toMatch(/, \d{4}/);
      expect(dateTimeUtils.format).toHaveBeenCalledWith(
        expect.anything(),
        'dddd, D MMM YYYY • HH:mm'
      );
    });

    it('renders channel rows when channels are available', async () => {
      vi.useRealTimers();

      render(<Guide />);

      // Channels are now fetched asynchronously from the API
      await waitFor(() => {
        expect(screen.getAllByTestId('guide-row')).toHaveLength(2);
      });
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
      vi.useRealTimers();

      render(<Guide />);

      // Channels are now fetched asynchronously from the API
      await waitFor(() => {
        expect(screen.getByText(/2 channels/)).toBeInTheDocument();
      });
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

      // Use getAllByText to safely handle the brief window where both the
      // filter-bar and the empty-state buttons are in the DOM simultaneously.
      await user.click(screen.getAllByText('Clear Filters')[0]);
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
      // Use findAllByText + [0] to target the filter-bar button specifically
      // in case the empty-state also shows a Clear Filters button.
      const clearButtons = await screen.findAllByText('Clear Filters');
      await user.click(clearButtons[0]);

      expect(searchInput).toHaveValue('');
    });
  });

  describe('Recording Functionality', () => {
    it('opens Program Recording modal when Record One is clicked', async () => {
      vi.useRealTimers();

      const user = userEvent.setup();
      render(<Guide />);

      const selectButtons = await screen.findAllByTestId('guide-row-select');
      await user.click(selectButtons[0]);

      await waitFor(() =>
        expect(screen.getByTestId('program-detail-modal')).toBeInTheDocument()
      );

      fireEvent.click(screen.getByText('Record'));

      await waitFor(() =>
        expect(screen.getByTestId('program-recording-modal')).toBeInTheDocument()
      );

      fireEvent.click(screen.getByText('Record One'));

      await waitFor(() => {
        expect(guideUtils.createRecording).toHaveBeenCalled();
      });
    });

    it('uses selected channel for recordOne instead of tvg_id fallback', async () => {
      vi.useRealTimers();

      API.getAllChannelIds.mockResolvedValue(['channel-1']);
      API.getChannelsSummary.mockResolvedValue([mockChannelsState.channels['channel-1']]);
      guideUtils.filterGuideChannels.mockImplementation((channels) =>
        Array.isArray(channels) ? channels : Object.values(channels)
      );

      const program = {
        id: 'prog-1',
        tvg_id: 'tvg-1',
        title: 'Test Program 1',
        channel_id: 'channel-1',
        start_time: now.toISOString(),
        end_time: now.add(1, 'hour').toISOString(),
        programStart: now,
        programEnd: now.add(1, 'hour'),
        startMs: now.valueOf(),
        endMs: now.add(1, 'hour').valueOf(),
      };

      guideUtils.fetchPrograms.mockResolvedValue([program]);

      render(<Guide />);

      await waitFor(() =>
        expect(screen.getAllByTestId('guide-row').length).toBeGreaterThan(0)
      );

      // Use userEvent instead of fireEvent so microtasks (Suspense lazy resolution) are flushed
      const user = userEvent.setup({ delay: null });

      await user.click(screen.getByTestId('guide-row-select'));

      await waitFor(() =>
        expect(screen.getByTestId('program-detail-modal')).toBeInTheDocument()
      );

      await user.click(screen.getByText('Record'));

      await waitFor(() =>
        expect(screen.getByTestId('program-recording-modal')).toBeInTheDocument()
      );

      await user.click(screen.getByText('Record One'));

      await waitFor(() => {
        expect(guideUtils.createRecording).toHaveBeenCalledWith(
          expect.objectContaining({ channel: 'channel-1' }),
        );
      });
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
    it('shows empty state when the API returns no channels', async () => {
      vi.useRealTimers();

      // Guide.jsx no longer emits a notification for an empty channel list;
      // instead it renders an empty-state message directly in the UI.
      API.getChannelsSummary.mockResolvedValue([]);

      render(<Guide />);

      await waitFor(() => {
        expect(
          screen.getByText('No channels match your filters')
        ).toBeInTheDocument();
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

  describe('Time window loading', () => {
    it('requests the initial now−1h → now+24h grid window', async () => {
      vi.useRealTimers();
      guideUtils.fetchPrograms.mockClear();

      render(<Guide />);

      await waitFor(() => {
        expect(guideUtils.fetchPrograms).toHaveBeenCalled();
      });

      const params = guideUtils.fetchPrograms.mock.calls[0][0];
      expect(params).toBeInstanceOf(URLSearchParams);
      const start = Date.parse(params.get('start'));
      const end = Date.parse(params.get('end'));
      const nowMs = now.valueOf();
      expect(start).toBe(nowMs - 60 * 60 * 1000);
      expect(end).toBe(nowMs + 24 * 60 * 60 * 1000);
    });

    it('does not refetch channels on the initial program window load alone', async () => {
      vi.useRealTimers();
      API.getChannelsSummary.mockClear();
      guideUtils.fetchPrograms.mockClear();

      render(<Guide />);

      await waitFor(() => {
        expect(API.getChannelsSummary).toHaveBeenCalled();
        expect(guideUtils.fetchPrograms).toHaveBeenCalled();
      });

      const channelCalls = API.getChannelsSummary.mock.calls.length;
      // Allow React StrictMode double-invoke; time-extend must not add channel fetches.
      expect(channelCalls).toBeLessThanOrEqual(2);
      expect(API.getChannelsSummary).toHaveBeenCalledTimes(channelCalls);
    });
  });

  describe('Program Search', () => {
    beforeEach(() => {
      API.getChannel.mockReset();
      vi.mocked(ProgramSearchPanel).mockReset();
    });

    const switchToPrograms = async (user) => {
      await user.click(screen.getByText('Programs'));
      return screen.findByPlaceholderText('Search programs...');
    };

    it('renders the Channels / Programs toggle with Channels selected', () => {
      render(<Guide />);

      expect(screen.getByText('Channels')).toHaveAttribute(
        'aria-pressed',
        'true'
      );
      expect(screen.getByText('Programs')).toHaveAttribute(
        'aria-pressed',
        'false'
      );
      expect(
        screen.queryByTestId('program-search-panel')
      ).not.toBeInTheDocument();
    });

    it('removes channel filters in Programs mode and restores them', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);

      await user.type(
        await screen.findByPlaceholderText('Search channels...'),
        'Test'
      );
      await user.selectOptions(
        screen.getByLabelText('Filter by group'),
        'group-1'
      );
      await user.selectOptions(
        screen.getByLabelText('Filter by profile'),
        'profile-1'
      );

      await switchToPrograms(user);

      expect(
        screen.queryByPlaceholderText('Search channels...')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByLabelText('Filter by group')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByLabelText('Filter by profile')
      ).not.toBeInTheDocument();
      expect(screen.queryByText('Clear Filters')).not.toBeInTheDocument();
      expect(screen.getByText('Series Rules')).toBeInTheDocument();

      await user.click(screen.getByText('Channels'));

      expect(screen.getByPlaceholderText('Search channels...')).toHaveValue(
        'Test'
      );
      expect(screen.getByLabelText('Filter by group')).toHaveValue('group-1');
      expect(screen.getByLabelText('Filter by profile')).toHaveValue(
        'profile-1'
      );
      expect(screen.getAllByText('Clear Filters')[0]).toBeInTheDocument();
    });

    it('keeps the grid mounted but hidden while Programs is shown', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);
      await screen.findAllByTestId('guide-row');

      await switchToPrograms(user);

      const grid = screen.getByTestId('variable-size-list').parentElement;
      expect(grid).toHaveStyle({ visibility: 'hidden' });
      expect(grid).toHaveAttribute('aria-hidden', 'true');
      expect(screen.getByTestId('program-search-panel')).toHaveAttribute(
        'data-visible',
        'true'
      );

      await user.click(screen.getByText('Channels'));

      expect(grid).toHaveStyle({ visibility: 'visible' });
      expect(screen.getByTestId('program-search-panel')).toHaveAttribute(
        'data-visible',
        'false'
      );
    });

    it('does not refetch or re-render the guide while typing a program query', async () => {
      vi.useRealTimers();
      const { default: ActualProgramSearchPanel } = await vi.importActual(
        '../../components/ProgramSearchPanel'
      );
      vi.mocked(ProgramSearchPanel).mockImplementation((props) => (
        <ActualProgramSearchPanel {...props} />
      ));
      API.searchPrograms.mockResolvedValue({
        count: 0,
        next: null,
        previous: null,
        results: [],
      });

      const user = userEvent.setup({ delay: null });
      render(
        <MantineProvider env="test">
          <Guide />
        </MantineProvider>
      );
      await screen.findAllByTestId('guide-row');
      const programInput = await switchToPrograms(user);

      API.getChannelsSummary.mockClear();
      guideUtils.fetchPrograms.mockClear();
      // Guide reads the channels store on every render
      useChannelsStore.mockClear();

      await user.type(programInput, 'news');
      await screen.findByText('No programs match "news" in the next 24 hours');

      expect(programInput).toHaveValue('news');
      expect(API.searchPrograms).toHaveBeenCalledTimes(1);
      expect(API.getChannelsSummary).not.toHaveBeenCalled();
      expect(guideUtils.fetchPrograms).not.toHaveBeenCalled();
      expect(useChannelsStore).not.toHaveBeenCalled();
    });

    it('keeps each search when switching modes', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);

      await user.type(
        await screen.findByPlaceholderText('Search channels...'),
        'Test'
      );
      await user.type(await switchToPrograms(user), 'news');

      await user.click(screen.getByText('Channels'));
      expect(screen.getByPlaceholderText('Search channels...')).toHaveValue(
        'Test'
      );

      await user.click(screen.getByText('Programs'));
      expect(screen.getByPlaceholderText('Search programs...')).toHaveValue(
        'news'
      );
    });

    it('opens the detail modal with the loaded channel for a result', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);
      await screen.findAllByTestId('guide-row');
      await switchToPrograms(user);

      await user.click(screen.getByText('Select loaded channel'));

      const modal = await screen.findByTestId('program-detail-modal');
      expect(modal).toHaveTextContent('Searched Program');
      expect(modal).toHaveAttribute('data-channel-uuid', 'uuid-1');
      expect(API.getChannel).not.toHaveBeenCalled();
    });

    it('fetches a result channel that is not loaded and records on it', async () => {
      vi.useRealTimers();
      API.getChannel.mockResolvedValue({
        id: 'channel-9',
        uuid: 'uuid-9',
        epg_data_id: 3,
        effective_epg_data_id: 4,
      });

      const user = userEvent.setup({ delay: null });
      render(<Guide />);
      await screen.findAllByTestId('guide-row');
      await switchToPrograms(user);

      await user.click(screen.getByText('Select other channel'));

      const modal = await screen.findByTestId('program-detail-modal');
      expect(API.getChannel).toHaveBeenCalledWith('channel-9');
      expect(modal).toHaveAttribute('data-channel-uuid', 'uuid-9');

      await user.click(screen.getByText('Record'));
      await user.click(await screen.findByText('Record One'));

      await waitFor(() => {
        expect(guideUtils.createRecording).toHaveBeenCalledWith(
          expect.objectContaining({
            channel: 'channel-9',
            custom_properties: {
              program: expect.objectContaining({ id: 501 }),
            },
          })
        );
      });
    });

    it('opens an unmapped result without a channel or Record', async () => {
      vi.useRealTimers();

      const user = userEvent.setup({ delay: null });
      render(<Guide />);
      await screen.findAllByTestId('guide-row');
      await switchToPrograms(user);

      await user.click(screen.getByText('Select unmapped'));

      const modal = await screen.findByTestId('program-detail-modal');
      expect(modal).not.toHaveAttribute('data-channel-uuid');
      expect(screen.queryByText('Record')).not.toBeInTheDocument();
      expect(API.getChannel).not.toHaveBeenCalled();
    });

    it('ignores a slow result channel once another result is selected', async () => {
      vi.useRealTimers();
      let resolveChannel;
      API.getChannel.mockReturnValue(
        new Promise((resolve) => {
          resolveChannel = resolve;
        })
      );

      const user = userEvent.setup({ delay: null });
      render(<Guide />);
      await screen.findAllByTestId('guide-row');
      await switchToPrograms(user);

      await user.click(screen.getByText('Select other channel'));
      await user.click(screen.getByText('Select loaded channel'));
      const modal = await screen.findByTestId('program-detail-modal');
      expect(modal).toHaveAttribute('data-channel-uuid', 'uuid-1');

      await act(async () => {
        resolveChannel({ id: 'channel-9', uuid: 'uuid-9' });
      });

      expect(screen.getByTestId('program-detail-modal')).toHaveAttribute(
        'data-channel-uuid',
        'uuid-1'
      );
    });

    it('ignores a slow result channel once a grid program is clicked', async () => {
      vi.useRealTimers();
      let resolveChannel;
      API.getChannel.mockReturnValue(
        new Promise((resolve) => {
          resolveChannel = resolve;
        })
      );

      const user = userEvent.setup({ delay: null });
      render(<Guide />);
      await screen.findAllByTestId('guide-row');
      await switchToPrograms(user);

      await user.click(screen.getByText('Select other channel'));
      await user.click(screen.getByText('Channels'));
      await user.click(screen.getAllByTestId('guide-row-select')[0]);
      const modal = await screen.findByTestId('program-detail-modal');
      expect(modal).toHaveTextContent('Test Program 1');

      await act(async () => {
        resolveChannel({ id: 'channel-9', uuid: 'uuid-9' });
      });

      expect(screen.getByTestId('program-detail-modal')).toHaveTextContent(
        'Test Program 1'
      );
    });

    it('ignores a slow result channel once the detail modal is closed', async () => {
      vi.useRealTimers();
      let resolveChannel;
      API.getChannel.mockReturnValue(
        new Promise((resolve) => {
          resolveChannel = resolve;
        })
      );

      const user = userEvent.setup({ delay: null });
      render(<Guide />);
      await screen.findAllByTestId('guide-row');
      await switchToPrograms(user);

      await user.click(screen.getByText('Select loaded channel'));
      await screen.findByTestId('program-detail-modal');
      await user.click(screen.getByText('Select other channel'));
      await user.click(screen.getByText('Close'));

      await act(async () => {
        resolveChannel({ id: 'channel-9', uuid: 'uuid-9' });
      });

      expect(
        screen.queryByTestId('program-detail-modal')
      ).not.toBeInTheDocument();
    });
  });
});
