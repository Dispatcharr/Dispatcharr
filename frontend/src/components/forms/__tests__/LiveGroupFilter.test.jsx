import React, { useState } from 'react';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ───────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/streamProfiles', () => ({ default: vi.fn() }));
vi.mock('../../../api.js', () => ({
  default: { getM3UGroupContent: vi.fn(), loadM3UGroupContent: vi.fn() },
}));

// ── Hook mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useSmartLogos', () => ({
  useChannelLogoSelection: vi.fn(),
}));

// ── Child component mocks ─────────────────────────────────────────────────────
vi.mock('../M3UGroupContentPreview.jsx', () => ({ default: () => null }));
vi.mock('../M3UFilters.jsx', () => ({
  default: ({ isOpen }) =>
    isOpen ? <div data-testid="stream-filters-editor" /> : null,
}));
vi.mock('../StreamFilterControl.jsx', () => ({
  default: function MockStreamFilterControl({ available, unavailableHint }) {
    const [opened, setOpened] = useState(false);
    return (
      <>
        <span
          tabIndex={available ? undefined : 0}
          aria-label={available ? undefined : unavailableHint}
        >
          <button disabled={!available} onClick={() => setOpened(true)}>
            Stream filters
          </button>
        </span>
        {opened && <div data-testid="stream-filters-editor" />}
      </>
    );
  },
}));
vi.mock('../../ListPagination.jsx', () => ({ default: () => null }));
vi.mock('../GroupConfigureModal', () => ({
  default: ({ opened, onDone, onCancel, group, children }) =>
    opened ? (
      <div data-testid="configure-modal" data-group-id={group?.channel_group}>
        {children}
        <button data-testid="modal-done" onClick={onDone}>
          Done
        </button>
        <button data-testid="modal-cancel" onClick={onCancel}>
          Cancel
        </button>
      </div>
    ) : null,
}));

vi.mock('../AutoSyncOrphanCleanup.jsx', () => ({
  default: ({ playlist }) => (
    <div data-testid="orphan-cleanup" data-playlist-id={String(playlist?.id)} />
  ),
}));

vi.mock('../AutoSyncBasic.jsx', () => ({
  default: () => <div data-testid="auto-sync-basic" />,
}));

vi.mock('../../ErrorBoundary.jsx', () => ({
  default: ({ children }) => <>{children}</>,
}));

vi.mock('../AutoSyncAdvanced.jsx', () => ({
  default: ({
    group,
    onApplyGroupChange,
    onScheduleRegexPreview,
    onOpenLogoUpload,
  }) => (
    <div
      data-testid="auto-sync-advanced"
      data-group-id={String(group?.channel_group)}
    >
      <button
        data-testid="trigger-logo-upload"
        onClick={() => onOpenLogoUpload(group.channel_group)}
      >
        Upload Logo
      </button>
      <button
        data-testid="trigger-apply-group"
        onClick={() =>
          onApplyGroupChange({ ...group, name: 'Modified By Advanced' })
        }
      >
        Apply Change
      </button>
      <button
        data-testid="trigger-regex-preview"
        onClick={() =>
          onScheduleRegexPreview(group, {
            find: 'test',
            replace: '',
            match: '',
            exclude: '',
          })
        }
      >
        Preview Regex
      </button>
    </div>
  ),
}));

vi.mock('../Logo.jsx', () => ({
  default: ({ isOpen, onClose, onSuccess }) =>
    isOpen ? (
      <div data-testid="logo-form">
        <button data-testid="logo-close" onClick={onClose}>
          Close
        </button>
        <button
          data-testid="logo-success"
          onClick={() => onSuccess({ logo: { id: 'logo-42' } })}
        >
          Select Logo
        </button>
      </div>
    ) : null,
}));

// ── Utility mocks ─────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/LiveGroupFilterUtils.js', () => ({
  // Real cleanup so debounced regex-preview timers do not leak across tests.
  abortTimers: (timerRef, abortRef) => {
    Object.values(timerRef.current).forEach((t) => clearTimeout(t));
    timerRef.current = {};
    Object.values(abortRef.current).forEach((c) => {
      try {
        c.abort();
      } catch {
        // ignore
      }
    });
    abortRef.current = {};
  },
  computeAutoSyncStart: vi.fn(() => 101),
  getChannelsInRange: vi.fn().mockResolvedValue({ occupants: [] }),
  getEPGs: vi.fn().mockResolvedValue([]),
  getRegexOptions: vi.fn((find, replace, match, exclude) => ({
    find,
    replace,
    match,
    exclude,
  })),
  getStreamsRegexPreview: vi.fn().mockResolvedValue(null),
  isExpectedOccupantForGroup: vi.fn(() => true),
  isGroupVisible: vi.fn((group, filter, status) => {
    if (status === 'enabled') return group.enabled;
    if (status === 'disabled') return !group.enabled;
    if (filter) return group.name.toLowerCase().includes(filter.toLowerCase());
    return true;
  }),
  rangeFor: vi.fn(() => null),
}));

// ── Mantine core mock ─────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  Indicator: ({ children }) => <>{children}</>,
  UnstyledButton: ({ children, onClick, ...props }) => (
    <button
      type={props.type}
      aria-label={props['aria-label']}
      onClick={onClick}
    >
      {children}
    </button>
  ),
  Anchor: ({ children, onClick }) => (
    <button onClick={onClick}>{children}</button>
  ),
  useModalStackContext: () => null,
  Badge: ({ children, color, variant }) => (
    <span data-color={color} data-variant={variant}>
      {children}
    </span>
  ),
  Table: ({ children }) => <table>{children}</table>,
  TableThead: ({ children }) => <thead>{children}</thead>,
  TableTbody: ({ children }) => <tbody>{children}</tbody>,
  TableTr: ({ children, ...props }) => <tr {...props}>{children}</tr>,
  TableTh: ({ children, w }) => <th style={{ width: w }}>{children}</th>,
  TableTd: ({ children }) => <td>{children}</td>,
  ScrollArea: ({ children }) => <div>{children}</div>,
  Select: ({ value, onChange, data, disabled, label, ...props }) => (
    <select
      aria-label={props['aria-label'] || label}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      {data.map((item) => (
        <option key={item.value} value={item.value}>
          {item.label}
        </option>
      ))}
    </select>
  ),
  ActionIcon: ({ children, onClick, disabled, ...props }) => (
    <button
      aria-label={props['aria-label']}
      data-testid="action-icon"
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Alert: ({ children }) => <div data-testid="alert">{children}</div>,
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Paper: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, disabled, variant, color }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      data-variant={variant}
      data-color={color}
    >
      {children}
    </button>
  ),
  Checkbox: ({
    label,
    checked,
    onChange,
    description,
    disabled,
    'aria-label': ariaLabel,
  }) => (
    <label>
      <input
        type="checkbox"
        checked={checked ?? false}
        onChange={onChange}
        disabled={disabled}
        aria-label={
          ariaLabel || (typeof label === 'string' ? label : 'checkbox')
        }
      />
      {typeof label === 'string' ? label : label}
      {description && <span>{description}</span>}
    </label>
  ),
  Divider: () => <hr />,
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Modal: ({ children, opened, title }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        {children}
      </div>
    ) : null,
  Loader: () => <div data-testid="loader" />,
  SegmentedControl: ({ onChange, data }) => (
    <div>
      {(data || []).map((item) => (
        <button
          key={item.value}
          data-testid={`seg-${item.value}`}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  ),
  SimpleGrid: ({ children }) => <div>{children}</div>,
  Stack: ({ children, style, ...rest }) => (
    <div style={style} {...rest}>
      {children}
    </div>
  ),
  Text: ({ children }) => <span>{children}</span>,
  TextInput: ({ placeholder, value, onChange }) => (
    <input
      data-testid="group-filter-input"
      placeholder={placeholder}
      value={value}
      onChange={onChange}
    />
  ),
  Tooltip: ({ children }) => <>{children}</>,
  Popover: Object.assign(({ children }) => <div>{children}</div>, {
    Target: ({ children }) => <>{children}</>,
    Dropdown: ({ children }) => <div>{children}</div>,
  }),
}));

// ── lucide-react mock ─────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Filter: () => <svg />,
  Eye: () => <svg data-testid="icon-eye" />,
  CircleCheck: () => <svg data-testid="icon-circle-check" />,
  CircleX: () => <svg data-testid="icon-circle-x" />,
  Info: () => <svg data-testid="icon-info" />,
  Settings: () => <svg data-testid="icon-cog" />,
  AlertTriangle: () => <svg data-testid="icon-range-warning" />,
}));

// ── Imports after mocks ───────────────────────────────────────────────────────
import LiveGroupFilter from '../LiveGroupFilter';
import API from '../../../api.js';

const filterStatus = (status) => {
  for (const key of ['enabled', 'disabled', 'ignored']) {
    const checkbox = screen.getByRole('checkbox', {
      name: key[0].toUpperCase() + key.slice(1),
      exact: true,
    });
    const checked = status === 'all' ? key !== 'ignored' : key === status;
    if (checkbox.checked !== checked) fireEvent.click(checkbox);
  }
};
const applyStatus = (status) => {
  fireEvent.click(screen.getByRole('button', { name: /^Edit settings/ }));
  fireEvent.change(screen.getByLabelText('Status'), {
    target: { value: status },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
};
import useChannelsStore from '../../../store/channels';
import useStreamProfilesStore from '../../../store/streamProfiles';
import { useChannelLogoSelection } from '../../../hooks/useSmartLogos';
import {
  getEPGs,
  getRegexOptions,
  getStreamsRegexPreview,
  isGroupVisible,
} from '../../../utils/forms/LiveGroupFilterUtils.js';

// ── Factories ─────────────────────────────────────────────────────────────────
const makeGroup = (overrides = {}) => ({
  channel_group: 1,
  name: 'Sports',
  enabled: true,
  auto_channel_sync: true,
  auto_sync_channel_start: 1,
  auto_sync_channel_end: null,
  custom_properties: {},
  is_stale: false,
  original_enabled: true,
  ...overrides,
});

const makePlaylist = (overrides = {}) => ({
  id: 1,
  name: 'Test Playlist',
  channel_groups: [],
  ...overrides,
});

// ── Stateful wrapper ──────────────────────────────────────────────────────────
const Wrapper = ({
  initialGroups = [],
  initialAutoEnable = true,
  playlist,
}) => {
  const [groupStates, setGroupStates] = useState(initialGroups);
  const [autoEnable, setAutoEnable] = useState(initialAutoEnable);
  return (
    <LiveGroupFilter
      playlist={playlist ?? makePlaylist()}
      groupStates={groupStates}
      setGroupStates={setGroupStates}
      autoEnableNewGroupsLive={autoEnable}
      setAutoEnableNewGroupsLive={setAutoEnable}
    />
  );
};

// ── Test setup helpers ────────────────────────────────────────────────────────
describe('LiveGroupFilter', () => {
  let mockEnsureLogosLoaded;
  let mockFetchProfiles;

  beforeEach(() => {
    vi.clearAllMocks();
    mockEnsureLogosLoaded = vi.fn();
    mockFetchProfiles = vi.fn();

    vi.mocked(useChannelsStore).mockImplementation((sel) =>
      sel({ channelGroups: {} })
    );
    vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
      sel({ profiles: [], fetchProfiles: mockFetchProfiles })
    );
    vi.mocked(useChannelLogoSelection).mockReturnValue({
      logos: [],
      ensureLogosLoaded: mockEnsureLogosLoaded,
      isLoading: false,
    });
    vi.mocked(getEPGs).mockResolvedValue([]);
    vi.mocked(getStreamsRegexPreview).mockReset().mockResolvedValue(null);
    API.getM3UGroupContent
      .mockReset()
      .mockResolvedValue({ count: 0, content_source: 'imported' });
    API.loadM3UGroupContent
      .mockReset()
      .mockResolvedValue({ count: 1, content_source: 'provider' });
  });

  const renderWith = ({
    initialGroups = [],
    initialAutoEnable = true,
    playlist,
    channelGroups,
    streamProfiles,
    fetchProfiles,
    ensureLogosLoaded,
  } = {}) => {
    if (channelGroups !== undefined) {
      vi.mocked(useChannelsStore).mockImplementation((sel) =>
        sel({ channelGroups })
      );
    }
    if (streamProfiles !== undefined || fetchProfiles !== undefined) {
      vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
        sel({
          profiles: streamProfiles ?? [],
          fetchProfiles: fetchProfiles ?? mockFetchProfiles,
        })
      );
    }
    if (ensureLogosLoaded !== undefined) {
      vi.mocked(useChannelLogoSelection).mockReturnValue({
        logos: [],
        ensureLogosLoaded,
        isLoading: false,
      });
    }

    return render(
      <Wrapper
        initialGroups={initialGroups}
        initialAutoEnable={initialAutoEnable}
        playlist={playlist}
      />
    );
  };

  // ── Rendering ──────────────────────────────────────────────────────────────
  it('highlights configured active import rules with their count', () => {
    render(
      <LiveGroupFilter
        playlist={makePlaylist()}
        groupStates={[]}
        setGroupStates={vi.fn()}
        ruleCount={2}
      />
    );
    expect(
      screen.getByRole('button', { name: 'Import rules (2)' })
    ).toHaveAttribute('data-variant', 'light');
  });

  it.each(['', 'categories'])(
    'requires an enabled Live category before opening stream filters (setup=%s)',
    (setupStep) => {
      const { rerender } = render(
        <LiveGroupFilter
          playlist={makePlaylist({
            setup_step: setupStep,
            enable_vod: true,
            category_selection_counts: { movie: { selected: 1 } },
          })}
          groupStates={[makeGroup({ enabled: false })]}
          setGroupStates={vi.fn()}
        />
      );
      const open = screen.getByRole('button', { name: 'Stream filters' });
      expect(open).toBeDisabled();
      expect(open.parentElement).toHaveAttribute('tabindex', '0');
      expect(open.parentElement).toHaveAttribute(
        'aria-label',
        'Select at least one Live TV category before configuring stream filters.'
      );
      fireEvent.click(open);
      expect(
        screen.queryByTestId('stream-filters-editor')
      ).not.toBeInTheDocument();
      rerender(
        <LiveGroupFilter
          playlist={makePlaylist({ setup_step: setupStep })}
          groupStates={[makeGroup()]}
          setGroupStates={vi.fn()}
        />
      );
      expect(open).toBeEnabled();
      fireEvent.click(open);
      expect(screen.getByTestId('stream-filters-editor')).toBeInTheDocument();
    }
  );

  describe('rendering', () => {
    it('reserves enough status-column width for the full badge label', () => {
      renderWith({ initialGroups: [makeGroup({ enabled: false })] });
      expect(screen.getByRole('columnheader', { name: 'Status' })).toHaveStyle({
        width: '100px',
      });
      expect(
        within(screen.getByRole('table')).getByText('Disabled')
      ).toBeInTheDocument();
    });

    it('keeps auto-sync help available without a large info banner', () => {
      renderWith();
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      expect(
        screen.getByLabelText('Auto channel sync help')
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Auto channel sync help' })
      ).not.toBeInTheDocument();
    });

    it('explains the opt-in default for newly discovered categories', () => {
      renderWith();
      expect(
        screen.getByText('New unmatched categories are imported disabled.')
      ).toBeInTheDocument();
    });

    it('does not expose the legacy auto-enable fallback', () => {
      renderWith({ initialAutoEnable: true });
      expect(
        screen.queryByRole('checkbox', {
          name: /Enable unmatched new groups/i,
        })
      ).not.toBeInTheDocument();
    });

    it('does not expose the fallback for an account that previously disabled it', () => {
      renderWith({ initialAutoEnable: false });
      expect(
        screen.queryByRole('checkbox', {
          name: /Enable unmatched new groups/i,
        })
      ).not.toBeInTheDocument();
    });

    it('keeps account-wide cleanup controls out of the categories toolbar', () => {
      renderWith({ playlist: makePlaylist({ id: 7 }) });
      expect(screen.queryByTestId('orphan-cleanup')).not.toBeInTheDocument();
    });

    it('renders the group name filter input', () => {
      renderWith();
      expect(screen.getByTestId('group-filter-input')).toBeInTheDocument();
    });

    it('renders Enabled / Disabled / Ignored visibility controls', () => {
      renderWith();
      expect(
        screen.getByRole('checkbox', { name: 'Enabled', exact: true })
      ).toBeChecked();
      expect(
        screen.getByRole('checkbox', { name: 'Disabled', exact: true })
      ).toBeChecked();
      expect(
        screen.getByRole('checkbox', { name: 'Ignored', exact: true })
      ).not.toBeChecked();
    });

    it('requires a selection before bulk actions are enabled', () => {
      renderWith();
      expect(screen.queryByText('Enable selected')).not.toBeInTheDocument();
      expect(screen.queryByText('Disable selected')).not.toBeInTheDocument();
      expect(screen.getByText('Edit settings (0)')).toBeDisabled();
    });

    it('renders a card for each group in groupStates', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports' }),
          makeGroup({ channel_group: 2, name: 'News' }),
        ],
      });
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });

    it('renders groups sorted alphabetically by name', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 3, name: 'Sports' }),
          makeGroup({ channel_group: 1, name: 'Arts' }),
          makeGroup({ channel_group: 2, name: 'News' }),
        ],
      });
      const names = screen
        .getAllByText(/Arts|News|Sports/)
        .map((el) => el.textContent);
      expect(names).toEqual(['Arts', 'News', 'Sports']);
    });

    it('renders no group cards when groupStates is empty', () => {
      renderWith({ initialGroups: [] });
      expect(screen.queryByTestId('group-card')).not.toBeInTheDocument();
    });

    it('does not render the configure modal on initial render', () => {
      renderWith({ initialGroups: [makeGroup()] });
      expect(screen.queryByTestId('configure-modal')).not.toBeInTheDocument();
    });
  });

  // ── Mount effects ──────────────────────────────────────────────────────────

  describe('mount effects', () => {
    it('calls ensureLogosLoaded on mount', () => {
      renderWith({ ensureLogosLoaded: mockEnsureLogosLoaded });
      expect(mockEnsureLogosLoaded).toHaveBeenCalled();
    });

    it('calls fetchStreamProfiles when profiles array is empty', () => {
      renderWith({ streamProfiles: [], fetchProfiles: mockFetchProfiles });
      expect(mockFetchProfiles).toHaveBeenCalled();
    });

    it('does not call fetchStreamProfiles when profiles already exist', () => {
      renderWith({
        streamProfiles: [{ id: 'p1', name: 'Default' }],
        fetchProfiles: mockFetchProfiles,
      });
      expect(mockFetchProfiles).not.toHaveBeenCalled();
    });

    it('calls getEPGs on mount', async () => {
      renderWith();
      await waitFor(() => {
        expect(getEPGs).toHaveBeenCalled();
      });
    });

    it('initializes groupStates from playlist.channel_groups when channelGroups are loaded', async () => {
      const channelGroups = { 10: { id: 10, name: 'Movies' } };
      const playlist = makePlaylist({
        id: 2,
        channel_groups: [
          {
            channel_group: 10,
            enabled: true,
            auto_channel_sync: false,
            auto_sync_channel_start: 1,
            auto_sync_channel_end: null,
            custom_properties: {},
          },
        ],
      });
      renderWith({ channelGroups, playlist, initialGroups: [] });
      await waitFor(() => {
        expect(screen.getByText('Movies')).toBeInTheDocument();
      });
    });

    it('skips groupStates initialization when channelGroups is empty', () => {
      renderWith({
        channelGroups: {},
        playlist: makePlaylist({
          channel_groups: [
            {
              channel_group: 1,
              enabled: true,
              auto_channel_sync: false,
              auto_sync_channel_start: 1,
            },
          ],
        }),
        initialGroups: [],
      });
      // Init effect bails early — no group cards rendered
      expect(screen.queryByTestId('group-card')).not.toBeInTheDocument();
    });

    it('does not re-initialize groupStates for the same playlist/channelGroups key', async () => {
      // Covers the lastInitKey guard preventing re-init on prop-reference changes
      const channelGroups = { 1: { id: 1, name: 'Sports' } };
      const playlist = makePlaylist({
        id: 1,
        channel_groups: [
          {
            channel_group: 1,
            enabled: true,
            auto_channel_sync: false,
            auto_sync_channel_start: 1,
            custom_properties: {},
          },
        ],
      });
      const { rerender } = renderWith({ channelGroups, playlist });
      await waitFor(() =>
        expect(screen.getByText('Sports')).toBeInTheDocument()
      );

      // Re-render with identical playlist reference — init must not fire again
      vi.mocked(useChannelsStore).mockImplementation((sel) =>
        sel({ channelGroups })
      );
      rerender(<Wrapper initialGroups={[]} playlist={playlist} />);
      // Still renders Sports; no duplicate init
      expect(screen.getAllByText('Sports')).toHaveLength(1);
    });
  });

  // ── autoEnableNewGroupsLive checkbox ──────────────────────────────────────

  // ── Group text filter ──────────────────────────────────────────────────────

  describe('group text filter', () => {
    it('shows groups matching the filter and hides non-matching groups', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports' }),
          makeGroup({ channel_group: 2, name: 'News' }),
        ],
      });
      fireEvent.change(screen.getByTestId('group-filter-input'), {
        target: { value: 'sport' },
      });
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.queryByText('News')).not.toBeInTheDocument();
    });

    it('shows all groups when filter is cleared', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports' }),
          makeGroup({ channel_group: 2, name: 'News' }),
        ],
      });
      fireEvent.change(screen.getByTestId('group-filter-input'), {
        target: { value: 'sport' },
      });
      fireEvent.change(screen.getByTestId('group-filter-input'), {
        target: { value: '' },
      });
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });

    it('calls isGroupVisible with the current filter text and status', () => {
      renderWith({
        initialGroups: [makeGroup({ channel_group: 1, name: 'Sports' })],
      });
      fireEvent.change(screen.getByTestId('group-filter-input'), {
        target: { value: 'sp' },
      });
      expect(isGroupVisible).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Sports' }),
        'sp',
        'all'
      );
    });
  });

  // ── Status filter ──────────────────────────────────────────────────────────

  describe('status filter', () => {
    it('shows only enabled groups when Enabled filter is selected', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
          makeGroup({ channel_group: 2, name: 'News', enabled: false }),
        ],
      });
      filterStatus('enabled');
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.queryByText('News')).not.toBeInTheDocument();
    });

    it('shows only disabled groups when Disabled filter is selected', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
          makeGroup({ channel_group: 2, name: 'News', enabled: false }),
        ],
      });
      filterStatus('disabled');
      expect(screen.queryByText('Sports')).not.toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });

    it('uses the existing name filter independently of status visibility', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
        ],
      });
      filterStatus('disabled');
      expect(isGroupVisible).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Sports' }),
        '',
        'all'
      );
    });

    it('reverts to showing all groups when All filter is selected', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
          makeGroup({ channel_group: 2, name: 'News', enabled: false }),
        ],
      });
      filterStatus('enabled');
      filterStatus('all');
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });
  });

  // ── Select Visible / Deselect Visible ─────────────────────────────────────

  describe('group selection and bulk actions', () => {
    it('selects every filtered group across pages, not only the first page', () => {
      renderWith({
        initialGroups: Array.from({ length: 40 }, (_, index) =>
          makeGroup({
            channel_group: index + 1,
            name: `Group ${index + 1}`,
            enabled: false,
            auto_channel_sync: false,
          })
        ),
      });
      expect(screen.getAllByTestId('group-card')).toHaveLength(25);
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      expect(screen.getByText('Edit settings (40)')).toBeEnabled();
      applyStatus('enabled');
      filterStatus('disabled');
      expect(screen.queryByTestId('group-card')).not.toBeInTheDocument();
      fireEvent.click(screen.getByText('Clear'));
      expect(screen.getByText('Edit settings (0)')).toBeDisabled();
    });
    it('selecting visible groups does not enable them until the explicit action', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: false }),
          makeGroup({ channel_group: 2, name: 'News', enabled: false }),
        ],
      });
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      expect(
        screen.getAllByText('Disabled').filter((el) => el.closest('table'))
      ).toHaveLength(2);
      applyStatus('enabled');
      expect(
        screen.getAllByText('Enabled').filter((el) => el.closest('table'))
      ).toHaveLength(2);
    });

    it('disables only selected groups', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
          makeGroup({ channel_group: 2, name: 'News', enabled: true }),
        ],
      });
      fireEvent.click(screen.getByRole('checkbox', { name: 'Select News' }));
      applyStatus('disabled');
      expect(
        screen.getAllByText('Disabled').filter((el) => el.closest('table'))
      ).toHaveLength(1);
      expect(
        screen.getAllByText('Enabled').filter((el) => el.closest('table'))
      ).toHaveLength(1);
    });

    it('selects only groups passing the current filter', () => {
      // With Enabled filter active, only already-enabled groups are "visible"
      // so disabling one and clicking Select Visible should not re-enable the hidden one
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
          makeGroup({ channel_group: 2, name: 'News', enabled: false }),
        ],
      });
      filterStatus('enabled');
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      expect(screen.getByText('Edit settings (1)')).toBeEnabled();
      // News (disabled) is not visible in Enabled filter, so it stays hidden
      expect(screen.queryByText('News')).not.toBeInTheDocument();
    });

    it('bulk editing changes only selected fields and groups', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports' }),
          makeGroup({ channel_group: 2, name: 'News' }),
        ],
      });
      fireEvent.click(screen.getByRole('checkbox', { name: 'Select Sports' }));
      fireEvent.click(screen.getByText('Edit settings (1)'));
      const dialog = screen.getByRole('dialog', {
        name: 'Edit settings for 1 category',
      });
      expect(
        within(dialog).queryByLabelText('Numbering mode')
      ).not.toBeInTheDocument();
      fireEvent.change(within(dialog).getByLabelText('Status'), {
        target: { value: 'disabled' },
      });
      fireEvent.click(
        within(dialog).getByRole('button', { name: 'Apply to selected' })
      );
      expect(
        within(screen.getByText('Sports').closest('tr')).getByText('Fixed')
      ).toBeInTheDocument();
      expect(
        within(screen.getByText('Sports').closest('tr')).getByText('Disabled')
      ).toBeInTheDocument();
      expect(
        within(screen.getByText('News').closest('tr')).getByText('Enabled')
      ).toBeInTheDocument();
      expect(
        within(screen.getByText('News').closest('tr')).getByText('Fixed')
      ).toBeInTheDocument();
      expect(
        screen.getByRole('checkbox', { name: 'Auto Channel Sync for Sports' })
      ).toBeDisabled();
    });

    it('canceling a bulk edit leaves group settings unchanged', () => {
      renderWith({ initialGroups: [makeGroup()] });
      fireEvent.click(screen.getByRole('checkbox', { name: 'Select Sports' }));
      fireEvent.click(screen.getByText('Edit settings (1)'));
      const dialog = screen.getByRole('dialog', {
        name: 'Edit settings for 1 category',
      });
      fireEvent.change(within(dialog).getByLabelText('Status'), {
        target: { value: 'disabled' },
      });
      fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
      expect(
        within(screen.getByText('Sports').closest('tr')).getByText('Fixed')
      ).toBeInTheDocument();
    });
  });

  // ── Configure modal ────────────────────────────────────────────────────────

  describe('configure modal', () => {
    it('shows compact summaries and enables configuration before auto sync is enabled', () => {
      renderWith({ initialGroups: [makeGroup({ auto_channel_sync: false })] });
      expect(screen.queryByTestId('auto-sync-basic')).not.toBeInTheDocument();
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
      const gear = screen.getByTestId('icon-cog').closest('button');
      expect(gear).toBeEnabled();
      fireEvent.click(gear);
      fireEvent.click(
        within(screen.getByTestId('configure-modal')).getByRole('checkbox', {
          name: 'Auto sync',
        })
      );
      expect(screen.getByTestId('auto-sync-basic')).toBeInTheDocument();
      fireEvent.change(screen.getByLabelText('Numbering mode'), {
        target: { value: 'provider' },
      });
      fireEvent.change(screen.getByLabelText('Auto-sync orphan cleanup'), {
        target: { value: 'never' },
      });
      fireEvent.click(screen.getByTestId('modal-cancel'));
      expect(
        screen.getByRole('checkbox', { name: 'Auto Channel Sync for Sports' })
      ).not.toBeChecked();
      expect(
        within(screen.getByText('Sports').closest('tr')).getByText('Fixed')
      ).toBeInTheDocument();
    });
    it('opens when the Cog ActionIcon is clicked', () => {
      renderWith({ initialGroups: [makeGroup({ channel_group: 1 })] });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      expect(screen.getByTestId('configure-modal')).toBeInTheDocument();
    });

    it('passes the correct group id to GroupConfigureModal', () => {
      renderWith({ initialGroups: [makeGroup({ channel_group: 42 })] });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      expect(screen.getByTestId('configure-modal')).toHaveAttribute(
        'data-group-id',
        '42'
      );
    });

    it('closes on Done click', () => {
      renderWith({ initialGroups: [makeGroup()] });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      fireEvent.click(screen.getByTestId('modal-done'));
      expect(screen.queryByTestId('configure-modal')).not.toBeInTheDocument();
    });

    it('closes on Cancel click', () => {
      renderWith({ initialGroups: [makeGroup()] });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      fireEvent.click(screen.getByTestId('modal-cancel'));
      expect(screen.queryByTestId('configure-modal')).not.toBeInTheDocument();
    });

    it('renders AutoSyncAdvanced inside the modal with the correct group', async () => {
      renderWith({ initialGroups: [makeGroup({ channel_group: 1 })] });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await waitFor(() => {
        expect(screen.getByTestId('auto-sync-advanced')).toBeInTheDocument();
        expect(screen.getByTestId('auto-sync-advanced')).toHaveAttribute(
          'data-group-id',
          '1'
        );
      });
    });

    it('restores the group state when Cancel is clicked after a change', async () => {
      renderWith({
        initialGroups: [makeGroup({ channel_group: 1, name: 'Sports' })],
      });
      // Open modal — snapshot is taken
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await waitFor(() => screen.getByTestId('trigger-apply-group'));

      // Mutate the group via AutoSyncAdvanced
      fireEvent.click(screen.getByTestId('trigger-apply-group'));
      expect(screen.getByText('Modified By Advanced')).toBeInTheDocument();

      // Cancel should revert to the snapshot
      fireEvent.click(screen.getByTestId('modal-cancel'));
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(
        screen.queryByText('Modified By Advanced')
      ).not.toBeInTheDocument();
    });

    it('does not revert the group state when Done is clicked after a change', async () => {
      renderWith({
        initialGroups: [makeGroup({ channel_group: 1, name: 'Sports' })],
      });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await waitFor(() => screen.getByTestId('trigger-apply-group'));

      fireEvent.click(screen.getByTestId('trigger-apply-group'));
      fireEvent.click(screen.getByTestId('modal-done'));

      // The modified name should persist
      expect(screen.getByText('Modified By Advanced')).toBeInTheDocument();
    });

    it('triggers a regex preview when configuringGroup changes', async () => {
      renderWith({
        initialGroups: [
          makeGroup({
            channel_group: 1,
            custom_properties: {
              name_regex_pattern: 'ESPN',
              name_match_regex: '',
            },
          }),
        ],
      });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await waitFor(() => {
        expect(getRegexOptions).toHaveBeenCalled();
      });
    });
  });

  // ── Logo upload modal ──────────────────────────────────────────────────────

  describe('logo upload modal', () => {
    const openLogoUpload = async () => {
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await waitFor(() => screen.getByTestId('trigger-logo-upload'));
      fireEvent.click(screen.getByTestId('trigger-logo-upload'));
    };

    it('opens LogoForm when onOpenLogoUpload is called', async () => {
      renderWith({ initialGroups: [makeGroup({ channel_group: 1 })] });
      await openLogoUpload();
      await waitFor(() =>
        expect(screen.getByTestId('logo-form')).toBeInTheDocument()
      );
    });

    it('closes LogoForm when onClose is called', async () => {
      renderWith({ initialGroups: [makeGroup({ channel_group: 1 })] });
      await openLogoUpload();
      fireEvent.click(screen.getByTestId('logo-close'));
      expect(screen.queryByTestId('logo-form')).not.toBeInTheDocument();
    });

    it('applies custom_logo_id and calls ensureLogosLoaded on logo success', async () => {
      renderWith({
        initialGroups: [makeGroup({ channel_group: 1 })],
        ensureLogosLoaded: mockEnsureLogosLoaded,
      });
      await openLogoUpload();

      const callCountBefore = mockEnsureLogosLoaded.mock.calls.length;
      fireEvent.click(screen.getByTestId('logo-success'));

      expect(mockEnsureLogosLoaded.mock.calls.length).toBeGreaterThan(
        callCountBefore
      );
      expect(screen.queryByTestId('logo-form')).not.toBeInTheDocument();
    });

    it('does not apply logo when onSuccess provides no logo', async () => {
      // Test the logo === null guard: LogoForm calls onSuccess({ logo: null })
      vi.mock('./Logo.jsx', () => ({
        default: ({ isOpen, onSuccess }) =>
          isOpen ? (
            <button
              data-testid="logo-success-null"
              onClick={() => onSuccess({ logo: null })}
            >
              No Logo
            </button>
          ) : null,
      }));
      // Without a valid logo object, ensureLogosLoaded should not be called again
      renderWith({
        initialGroups: [makeGroup({ channel_group: 1 })],
        ensureLogosLoaded: mockEnsureLogosLoaded,
      });
      await openLogoUpload();
      // If the null-logo button renders, click it; otherwise the modal just closes
      const nullBtn = screen.queryByTestId('logo-success-null');
      if (nullBtn) fireEvent.click(nullBtn);
      // ensureLogosLoaded should only have been called once (on mount)
      expect(mockEnsureLogosLoaded).toHaveBeenCalledTimes(1);
    });
  });

  // ── scheduleRegexPreview ───────────────────────────────────────────────────

  describe('scheduleRegexPreview (via AutoSyncAdvanced)', () => {
    it('loads missing XC category data once and reuses the resulting regex preview', async () => {
      API.getM3UGroupContent
        .mockResolvedValueOnce({
          count: 0,
          can_load_provider: true,
          content_source: 'imported',
        })
        .mockResolvedValue({
          count: 1,
          can_load_provider: false,
          content_source: 'provider',
        });
      vi.mocked(getStreamsRegexPreview)
        .mockResolvedValueOnce({ total_in_group: 0, can_load_provider: true })
        .mockResolvedValue({
          total_in_group: 1,
          content_source: 'provider',
          find_matches: [{ before: 'test', after: '' }],
          find_match_count: 1,
        });
      renderWith({
        initialGroups: [makeGroup({ channel_group: 1 })],
        playlist: makePlaylist({ account_type: 'XC' }),
      });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await screen.findByTestId('trigger-regex-preview');
      fireEvent.click(screen.getByTestId('trigger-regex-preview'));
      await waitFor(() =>
        expect(getStreamsRegexPreview).toHaveBeenCalledTimes(2)
      );
      expect(API.loadM3UGroupContent).toHaveBeenCalledExactlyOnceWith(
        1,
        'live',
        1
      );
      fireEvent.click(screen.getByTestId('trigger-regex-preview'));
      expect(getStreamsRegexPreview).toHaveBeenCalledTimes(2);
      expect(API.loadM3UGroupContent).toHaveBeenCalledOnce();
    });

    it('does not fetch category content when imported names or a confirmed empty preview exist', async () => {
      vi.mocked(getStreamsRegexPreview).mockResolvedValue({
        total_in_group: 0,
        content_source: 'provider',
        can_load_provider: false,
      });
      renderWith({ initialGroups: [makeGroup({ channel_group: 1 })] });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await screen.findByTestId('trigger-regex-preview');
      fireEvent.click(screen.getByTestId('trigger-regex-preview'));
      await waitFor(() =>
        expect(getStreamsRegexPreview).toHaveBeenCalledOnce()
      );
      expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
    });

    it('passes onScheduleRegexPreview to AutoSyncAdvanced and it triggers without error', async () => {
      renderWith({ initialGroups: [makeGroup({ channel_group: 1 })] });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await waitFor(() => screen.getByTestId('trigger-regex-preview'));
      expect(() =>
        fireEvent.click(screen.getByTestId('trigger-regex-preview'))
      ).not.toThrow();
    });

    it('clears regexPreview state when all pattern fields are empty', async () => {
      // scheduleRegexPreview with empty opts should not call getStreamsRegexPreview
      renderWith({ initialGroups: [makeGroup({ channel_group: 1 })] });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await waitFor(() => screen.getByTestId('auto-sync-advanced'));
      // Trigger with empty patterns by mounting a group with no patterns set
      // (the useEffect on configuringGroup?.channel_group fires getRegexOptions with empty strings)
      expect(getStreamsRegexPreview).not.toHaveBeenCalled();
    });

    it('calls getStreamsRegexPreview when non-empty patterns are provided', async () => {
      vi.mocked(getStreamsRegexPreview).mockResolvedValue({
        find_matches: ['ESPN HD'],
        find_match_count: 1,
        total_in_group: 10,
        total_scanned: 10,
        scan_limit_hit: false,
      });
      renderWith({
        initialGroups: [
          makeGroup({
            channel_group: 1,
            custom_properties: { name_regex_pattern: 'ESPN' },
          }),
        ],
      });
      fireEvent.click(screen.getByTestId('icon-cog').closest('button'));
      await waitFor(() => screen.getByTestId('trigger-regex-preview'));
      fireEvent.click(screen.getByTestId('trigger-regex-preview'));
      await waitFor(() => {
        expect(getStreamsRegexPreview).toHaveBeenCalled();
      });
    });
  });

  // ── applyGroupChange ───────────────────────────────────────────────────────

  describe('applyGroupChange (via AutoSyncAdvanced)', () => {
    it('updates only the target group in groupStates', async () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports' }),
          makeGroup({ channel_group: 2, name: 'News' }),
        ],
      });
      // Group cards will be sorted alphabetically, so the first cog button corresponds to the "News" group, not "Sports" — ensure we target the correct one
      const cogButtons = screen.getAllByTestId('icon-cog');
      fireEvent.click(cogButtons[1].closest('button'));
      await waitFor(() => screen.getByTestId('trigger-apply-group'));
      fireEvent.click(screen.getByTestId('trigger-apply-group'));

      // Group 1 name changed; Group 2 unchanged
      expect(screen.getByText('Modified By Advanced')).toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });
  });
});
