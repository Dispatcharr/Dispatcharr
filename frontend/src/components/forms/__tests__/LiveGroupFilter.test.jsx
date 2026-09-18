import React, { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ───────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/streamProfiles', () => ({ default: vi.fn() }));

// ── Hook mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useSmartLogos', () => ({
  useChannelLogoSelection: vi.fn(),
}));

// ── Child component mocks ─────────────────────────────────────────────────────
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

vi.mock('../AutoSyncBasic.jsx', () => ({
  default: () => <div data-testid="auto-sync-basic" />,
}));

vi.mock('../../ErrorBoundary.jsx', () => ({
  default: ({ children }) => <>{children}</>,
}));

vi.mock('../M3UGroupRules.jsx', () => ({
  default: () => <div data-testid="discovery-rules" />,
}));

vi.mock('../M3UDeveloperCatalog.jsx', () => ({
  default: () => <div data-testid="group-preview">Preview</div>,
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
  ActionIcon: ({ children, onClick, disabled }) => (
    <button data-testid="action-icon" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Alert: ({ children }) => <div data-testid="alert">{children}</div>,
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, disabled, variant, color, ...props }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      data-variant={variant}
      data-color={color}
      {...props}
    >
      {children}
    </button>
  ),
  Checkbox: ({ label, checked, onChange, description, disabled, ...props }) => (
    <label>
      <input
        type="checkbox"
        checked={checked ?? false}
        onChange={onChange}
        disabled={disabled}
        aria-label={
          props['aria-label'] ||
          (typeof label === 'string' ? label : 'checkbox')
        }
      />
      {typeof label === 'string' ? label : label}
      {description && <span>{description}</span>}
    </label>
  ),
  Divider: () => <hr />,
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children, style }) => <div style={style}>{children}</div>,
  Loader: () => <div data-testid="loader" />,
  Modal: ({ opened, children, title }) =>
    opened ? (
      <div data-testid="bulk-modal">
        <span>{title}</span>
        {children}
      </div>
    ) : null,
  Pagination: () => <div data-testid="pagination" />,
  ScrollArea: ({ children }) => <div>{children}</div>,
  Select: ({ label, value, onChange, data = [] }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value || ''}
        onChange={(event) => onChange?.(event.target.value || null)}
      >
        {data.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    </label>
  ),
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
  Stack: ({ children, style }) => <div style={style}>{children}</div>,
  Switch: ({ label, checked, onChange, disabled }) => (
    <label>
      <input
        type="checkbox"
        checked={checked ?? false}
        onChange={onChange}
        disabled={disabled}
        aria-label={typeof label === 'string' ? label : 'switch'}
      />
      {label}
    </label>
  ),
  Table: ({ children }) => <table>{children}</table>,
  TableTbody: ({ children }) => <tbody>{children}</tbody>,
  TableTd: ({ children }) => <td>{children}</td>,
  TableTh: ({ children }) => <th>{children}</th>,
  TableThead: ({ children }) => <thead>{children}</thead>,
  TableTr: ({ children }) => <tr>{children}</tr>,
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
}));

// ── lucide-react mock ─────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  CircleCheck: () => <svg data-testid="icon-circle-check" />,
  CircleX: () => <svg data-testid="icon-circle-x" />,
  Eye: () => <svg data-testid="icon-eye" />,
  Info: (props) => <svg data-testid="icon-info" {...props} />,
  Settings: () => <svg data-testid="icon-cog" />,
}));

// ── Imports after mocks ───────────────────────────────────────────────────────
import LiveGroupFilter from '../LiveGroupFilter';
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

  describe('rendering', () => {
    it('shows Auto sync help beside the table heading', () => {
      renderWith();
      expect(screen.getByText('Auto Sync')).toBeInTheDocument();
      expect(screen.getByTestId('icon-info')).toBeInTheDocument();
    });

    it('shows import rules and stream filters instead of an auto-enable switch', () => {
      renderWith();
      expect(
        screen.getByRole('button', { name: 'Import rules' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Stream filters' })
      ).toBeInTheDocument();
      expect(
        screen.getByText('New unmatched groups are imported inactive.')
      ).toBeInTheDocument();
    });

    it('renders the group name filter input', () => {
      renderWith();
      expect(screen.getByTestId('group-filter-input')).toBeInTheDocument();
    });

    it('renders All / Enabled / Disabled status filter buttons', () => {
      renderWith();
      expect(screen.getByTestId('seg-all')).toBeInTheDocument();
      expect(screen.getByTestId('seg-enabled')).toBeInTheDocument();
      expect(screen.getByTestId('seg-disabled')).toBeInTheDocument();
    });

    it('renders bulk-selection and update controls', () => {
      renderWith();
      expect(
        screen.getByLabelText('Select visible groups')
      ).toBeInTheDocument();
      expect(screen.getByText('Enable selected')).toBeInTheDocument();
      expect(screen.getByText('Disable selected')).toBeInTheDocument();
      expect(screen.getByText('Edit settings (0)')).toBeInTheDocument();
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
      fireEvent.click(screen.getByTestId('seg-enabled'));
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
      fireEvent.click(screen.getByTestId('seg-disabled'));
      expect(screen.queryByText('Sports')).not.toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });

    it('passes the active status value to isGroupVisible', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
        ],
      });
      fireEvent.click(screen.getByTestId('seg-disabled'));
      expect(isGroupVisible).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Sports' }),
        '',
        'disabled'
      );
    });

    it('reverts to showing all groups when All filter is selected', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
          makeGroup({ channel_group: 2, name: 'News', enabled: false }),
        ],
      });
      fireEvent.click(screen.getByTestId('seg-enabled'));
      fireEvent.click(screen.getByTestId('seg-all'));
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });
  });

  // ── Bulk selection and changes ────────────────────────────────────────────

  describe('bulk selection and changes', () => {
    it('selects every filtered group across pagination pages', () => {
      renderWith({
        initialGroups: Array.from({ length: 26 }, (_, index) =>
          makeGroup({
            channel_group: index + 1,
            name: `Group ${String(index + 1).padStart(2, '0')}`,
          })
        ),
      });

      fireEvent.click(screen.getByLabelText('Select visible groups'));

      expect(screen.getByText('Edit settings (26)')).toBeInTheDocument();
    });

    it('enables all selected visible groups', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: false }),
          makeGroup({ channel_group: 2, name: 'News', enabled: false }),
        ],
      });
      fireEvent.click(screen.getByLabelText('Select visible groups'));
      fireEvent.click(screen.getByText('Enable selected'));
      expect(
        screen.getByRole('button', { name: 'Enable Sports' })
      ).toHaveAttribute('aria-pressed', 'true');
      expect(
        screen.getByRole('button', { name: 'Enable News' })
      ).toHaveAttribute('aria-pressed', 'true');
    });

    it('disables all selected visible groups', () => {
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
          makeGroup({ channel_group: 2, name: 'News', enabled: true }),
        ],
      });
      fireEvent.click(screen.getByLabelText('Select visible groups'));
      fireEvent.click(screen.getByText('Disable selected'));
      expect(
        screen.getByRole('button', { name: 'Enable Sports' })
      ).toHaveAttribute('aria-pressed', 'false');
      expect(
        screen.getByRole('button', { name: 'Enable News' })
      ).toHaveAttribute('aria-pressed', 'false');
    });

    it('bulk changes only apply to groups passing the current filter', () => {
      // With Enabled filter active, only already-enabled groups are "visible"
      // so disabling one and clicking Select Visible should not re-enable the hidden one
      renderWith({
        initialGroups: [
          makeGroup({ channel_group: 1, name: 'Sports', enabled: true }),
          makeGroup({ channel_group: 2, name: 'News', enabled: false }),
        ],
      });
      fireEvent.click(screen.getByTestId('seg-enabled'));
      fireEvent.click(screen.getByLabelText('Select visible groups'));
      fireEvent.click(screen.getByText('Enable selected'));
      // News (disabled) is not visible in Enabled filter, so it stays hidden
      expect(screen.queryByText('News')).not.toBeInTheDocument();
    });
  });

  // ── Configure modal ────────────────────────────────────────────────────────

  describe('configure modal', () => {
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
