import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── DnD Kit ────────────────────────────────────────────────────────────────────
vi.mock('@dnd-kit/core', () => ({
  DndContext: ({ children }) => <div>{children}</div>,
  PointerSensor: class PointerSensor {},
  closestCenter: vi.fn(),
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
}));

vi.mock('@dnd-kit/sortable', () => ({
  SortableContext: ({ children }) => <div>{children}</div>,
  verticalListSortingStrategy: vi.fn(),
}));

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/channelsTable', () => {
  const mock = vi.fn();
  mock.getState = vi.fn(() => ({ selectedChannelIds: [] }));
  mock.setState = vi.fn();
  return { default: mock };
});
vi.mock('../../../store/auth', () => ({ default: vi.fn() }));
vi.mock('../../../store/epgs', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVideoStore', () => ({ default: vi.fn() }));
vi.mock('../../../store/outputProfiles', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => [{}, vi.fn()]),
}));
vi.mock('../../../hooks/useSmartLogos', () => ({
  useChannelLogoSelection: vi.fn(() => ({ ensureLogosLoaded: vi.fn() })),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils', () => ({
  copyToClipboard: vi.fn().mockResolvedValue(undefined),
  useDebounce: vi.fn((val) => val),
}));
vi.mock('../../../utils/forms/ChannelUtils.js', () => ({
  listOverriddenFields: vi.fn(() => []),
  requeryChannels: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('../../../utils/components/FloatingVideoUtils.js', () => ({
  buildLiveStreamUrl: vi.fn((path) => path),
}));
vi.mock('../../../utils/cards/RecordingCardUtils.js', () => ({
  getShowVideoUrl: vi.fn(() => '/proxy/ts/stream/uuid-1'),
}));
vi.mock('../../../utils/tables/ChannelsTableUtils.js', () => ({
  buildEPGUrl: vi.fn(() => 'http://localhost/output/epg'),
  buildFetchParams: vi.fn(() => new URLSearchParams()),
  buildHDHRUrl: vi.fn(() => 'http://localhost/hdhr'),
  buildM3UUrl: vi.fn(() => 'http://localhost/output/m3u'),
  deleteChannel: vi.fn().mockResolvedValue(undefined),
  deleteChannels: vi.fn().mockResolvedValue(undefined),
  epgUrlBase: 'http://localhost/output/epg',
  getAllChannelIds: vi.fn().mockResolvedValue([1, 2]),
  hdhrUrlBase: 'http://localhost/hdhr',
  m3uUrlBase: 'http://localhost/output/m3u',
  queryChannels: vi.fn().mockResolvedValue(undefined),
  reorderChannel: vi.fn().mockResolvedValue(undefined),
  updateProfileChannel: vi.fn().mockResolvedValue(undefined),
  updateProfileChannels: vi.fn().mockResolvedValue(undefined),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../CustomTable', () => ({
  CustomTable: () => <div data-testid="custom-table" />,
  useTable: vi.fn(),
}));
vi.mock('../ChannelsTable/ChannelsTableOnboarding', () => ({
  default: ({ editChannel }) => (
    <div data-testid="onboarding">
      <button data-testid="onboarding-add" onClick={() => editChannel(null, { forceAdd: true })}>
        Add Channel
      </button>
    </div>
  ),
}));
vi.mock('../ChannelsTable/ChannelTableHeader', () => ({
  default: ({
    editChannel,
    deleteChannels,
    showDisabled,
    setShowDisabled,
    showOnlyStreamlessChannels,
    setShowOnlyStreamlessChannels,
    showOnlyStaleChannels,
    setShowOnlyStaleChannels,
    showOnlyOverriddenChannels,
    setShowOnlyOverriddenChannels,
  }) => (
    <div data-testid="channel-table-header">
      <button data-testid="header-add-channel" onClick={() => editChannel(null, { forceAdd: true })}>
        Add Channel
      </button>
      <button data-testid="header-delete-channels" onClick={deleteChannels}>
        Delete Selected
      </button>
      <button
        data-testid="toggle-show-disabled"
        onClick={() => setShowDisabled(!showDisabled)}
      >
        Toggle Disabled
      </button>
      <button
        data-testid="toggle-streamless"
        onClick={() => setShowOnlyStreamlessChannels(!showOnlyStreamlessChannels)}
      >
        Toggle Streamless
      </button>
      <button
        data-testid="toggle-stale"
        onClick={() => setShowOnlyStaleChannels(!showOnlyStaleChannels)}
      >
        Toggle Stale
      </button>
      <button
        data-testid="toggle-overridden"
        onClick={() => setShowOnlyOverriddenChannels(!showOnlyOverriddenChannels)}
      >
        Toggle Overridden
      </button>
    </div>
  ),
}));
vi.mock('../ChannelsTable/EditableCell', () => ({
  EditableEPGCell: () => <span data-testid="editable-epg-cell" />,
  EditableGroupCell: () => <span data-testid="editable-group-cell" />,
  EditableLogoCell: () => <span data-testid="editable-logo-cell" />,
  EditableNumberCell: () => <span data-testid="editable-number-cell" />,
  EditableTextCell: () => <span data-testid="editable-text-cell" />,
}));
vi.mock('../ChannelTableStreams', () => ({
  default: () => <div data-testid="channel-table-streams" />,
}));
vi.mock('../../forms/Channel', () => ({
  default: ({ isOpen, onClose, channel }) =>
    isOpen ? (
      <div data-testid="channel-form">
        <span data-testid="channel-form-name">{channel?.name ?? 'new'}</span>
        <button data-testid="channel-form-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));
vi.mock('../../forms/ChannelBatch', () => ({
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div data-testid="channel-batch-form">
        <button data-testid="batch-form-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));
vi.mock('../../forms/Recording', () => ({
  default: ({ isOpen, onClose, channel }) =>
    isOpen ? (
      <div data-testid="recording-form">
        <span data-testid="recording-form-channel">{channel?.name}</span>
        <button data-testid="recording-form-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));
vi.mock('../../ConfirmationDialog', () => ({
  default: ({ opened, onClose, onConfirm, title, loading, confirmLabel, cancelLabel }) =>
    opened ? (
      <div data-testid="confirm-dialog">
        <span data-testid="confirm-title">{title}</span>
        <button data-testid="confirm-ok" onClick={onConfirm} disabled={loading}>
          {confirmLabel}
        </button>
        <button data-testid="confirm-cancel" onClick={onClose}>
          {cancelLabel}
        </button>
      </div>
    ) : null,
}));
vi.mock('../../LazyLogo', () => ({
  default: ({ alt }) => <img data-testid="lazy-logo" alt={alt} />,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled }) => (
    <button data-testid="action-icon" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Box: ({ children, style, role, 'aria-label': ariaLabel }) => (
    <div style={style} role={role} aria-label={ariaLabel}>
      {children}
    </div>
  ),
  Button: ({ children, onClick, leftSection, disabled, loading }) => (
    <button data-testid="button" onClick={onClick} disabled={disabled || loading}>
      {leftSection}
      {children}
    </button>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Flex: ({ children, style }) => <div style={style}>{children}</div>,
  Group: ({ children, style }) => <div style={style}>{children}</div>,
  Menu: Object.assign(
    ({ children }) => <div data-testid="menu">{children}</div>,
    {
      Target: ({ children }) => <div>{children}</div>,
      Dropdown: ({ children }) => <div>{children}</div>,
      Label: ({ children }) => <div>{children}</div>,
      Item: ({ children, onClick, disabled, leftSection }) => (
        <button data-testid="menu-item" onClick={onClick} disabled={disabled}>
          {leftSection}
          {children}
        </button>
      ),
    }
  ),
  MenuDropdown: ({ children }) => <div>{children}</div>,
  MenuItem: ({ children, onClick, disabled, leftSection }) => (
    <button data-testid="menu-item" onClick={onClick} disabled={disabled}>
      {leftSection}
      {children}
    </button>
  ),
  MenuTarget: ({ children }) => <div>{children}</div>,
  MultiSelect: ({ value, data }) => (
    <select data-testid="multi-select" multiple value={value || []} onChange={() => {}}>
      {(data || []).map((d) => (
        <option key={d.value ?? d} value={d.value ?? d}>{d.label ?? d}</option>
      ))}
    </select>
  ),
  NativeSelect: ({ value, data, onChange }) => (
    <select data-testid="native-select" value={String(value)} onChange={onChange}>
      {(data || []).map((d) => (
        <option key={d} value={d}>{d}</option>
      ))}
    </select>
  ),
  NumberInput: ({ value, onChange }) => (
    <input data-testid="number-input" type="number" value={value} onChange={(e) => onChange(Number(e.target.value))} />
  ),
  Pagination: ({ total, value, onChange }) => (
    <div data-testid="pagination">
      <button data-testid="pagination-prev" onClick={() => onChange(value - 1)} disabled={value <= 1}>Prev</button>
      <span data-testid="pagination-page">{value}</span>
      <button data-testid="pagination-next" onClick={() => onChange(value + 1)} disabled={value >= total}>Next</button>
    </div>
  ),
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Popover: Object.assign(
    ({ children }) => <div data-testid="popover">{children}</div>,
    {
      Target: ({ children }) => <div>{children}</div>,
      Dropdown: ({ children }) => <div data-testid="popover-dropdown">{children}</div>,
    }
  ),
  PopoverDropdown: ({ children, onClick, onMouseDown }) => (
    <div data-testid="popover-dropdown" onClick={onClick} onMouseDown={onMouseDown}>
      {children}
    </div>
  ),
  PopoverTarget: ({ children }) => <div>{children}</div>,
  Select: ({ value, onChange, data, placeholder }) => (
    <select
      data-testid="select"
      value={value || ''}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">{placeholder}</option>
      {(data || []).map((d) => (
        <option key={d.value ?? d} value={d.value ?? d}>{d.label ?? d}</option>
      ))}
    </select>
  ),
  Stack: ({ children, style }) => <div style={style}>{children}</div>,
  Switch: ({ checked, onChange, label, disabled }) => (
    <input
      type="checkbox"
      data-testid="switch"
      checked={!!checked}
      onChange={onChange}
      disabled={disabled}
      aria-label={label}
    />
  ),
  Text: ({ children, style }) => (
    <span data-testid="text" style={style}>{children}</span>
  ),
  TextInput: ({ value, placeholder, onChange, readOnly }) => (
    <input
      data-testid="text-input"
      value={value}
      placeholder={placeholder}
      onChange={onChange || (() => {})}
      readOnly={readOnly}
    />
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
  UnstyledButton: ({ children, onClick }) => (
    <button data-testid="unstyled-button" onClick={onClick}>{children}</button>
  ),
  useMantineTheme: vi.fn(() => ({
    tailwind: { yellow: { 3: '#fde047' }, red: { 6: '#dc2626' }, green: { 5: '#22c55e' } },
    palette: {
      custom: { greenMain: '#22c55e', indigoMain: '#6366f1', greyBorder: '#71717a' },
    },
  })),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ArrowDownWideNarrow: () => <svg data-testid="icon-arrow-down" />,
  ArrowUpDown: () => <svg data-testid="icon-arrow-up-down" />,
  ArrowUpNarrowWide: () => <svg data-testid="icon-arrow-up" />,
  CirclePlay: () => <svg data-testid="icon-circle-play" />,
  Copy: () => <svg data-testid="icon-copy" />,
  EllipsisVertical: () => <svg data-testid="icon-ellipsis" />,
  EyeOff: () => <svg data-testid="icon-eye-off" />,
  Pencil: () => <svg data-testid="icon-pencil" />,
  ScanEye: () => <svg data-testid="icon-scan-eye" />,
  ScreenShare: () => <svg data-testid="icon-screen-share" />,
  Scroll: () => <svg data-testid="icon-scroll" />,
  Search: () => <svg data-testid="icon-search" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
  Tv2: () => <svg data-testid="icon-tv2" />,
}));

// ── CSS import ─────────────────────────────────────────────────────────────────
vi.mock('../table.css', () => ({}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels';
import useChannelsTableStore from '../../../store/channelsTable';
import useAuthStore from '../../../store/auth';
import useEPGsStore from '../../../store/epgs';
import useSettingsStore from '../../../store/settings';
import useVideoStore from '../../../store/useVideoStore';
import useOutputProfilesStore from '../../../store/outputProfiles';
import useWarningsStore from '../../../store/warnings';
import useLocalStorage from '../../../hooks/useLocalStorage';
import { useTable } from '../CustomTable';
import { deleteChannel, deleteChannels, queryChannels, getAllChannelIds } from '../../../utils/tables/ChannelsTableUtils.js';
import { requeryChannels } from '../../../utils/forms/ChannelUtils.js';
import { copyToClipboard } from '../../../utils';
import { buildLiveStreamUrl } from '../../../utils/components/FloatingVideoUtils.js';
import { USER_LEVELS } from '../../../constants';
import ChannelsTable from '../ChannelsTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeChannel = (overrides = {}) => ({
  id: 1,
  uuid: 'uuid-1',
  name: 'Test Channel',
  channel_number: 101,
  effective_channel_number: 101,
  effective_name: 'Test Channel',
  streams: [{ id: 10, is_stale: false }],
  hidden_from_output: false,
  channel_group_id: null,
  logo_id: null,
  epg_data_id: null,
  ...overrides,
});

const makeAdminUser = () => ({ id: 99, user_level: USER_LEVELS.ADMIN });
const makeStandardUser = () => ({ id: 88, user_level: USER_LEVELS.STANDARD });

let capturedTableOptions = null;

const makeDefaultTableInstance = (overrides = {}) => ({
  getRowModel: vi.fn(() => ({ rows: [] })),
  getHeaderGroups: vi.fn(() => []),
  setSelectedTableIds: vi.fn(),
  selectedTableIds: [],
  ...overrides,
});

const setupMocks = ({
  channels = [makeChannel()],
  authUser = makeAdminUser(),
  isWarningSuppressed = vi.fn(() => false),
  suppressWarning = vi.fn(),
  selectedProfileId = '0',
  profiles = { 0: { name: 'Default', channels: new Set() } },
  pageCount = 1,
  totalCount = 1,
  allQueryIds = [1],
  channelGroups = {},
  epgs = {},
  hasUnassignedEPGChannels = false,
  tableOverrides = {},
} = {}) => {
  vi.mocked(useChannelsTableStore).mockImplementation((sel) =>
    sel({
      channels,
      pageCount,
      totalCount,
      allQueryIds,
      pagination: { pageIndex: 0, pageSize: 25 },
      sorting: [],
      hasUnassignedEPGChannels,
      setSelectedChannelIds: vi.fn(),
      setExpandedChannelId: vi.fn(),
      setPagination: vi.fn(),
      setSorting: vi.fn(),
      setAllQueryIds: vi.fn(),
    })
  );
  vi.mocked(useChannelsTableStore).getState.mockReturnValue({
    selectedChannelIds: [],
  });

  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({
      channelIds: channels.map((c) => c.id),
      profiles,
      selectedProfileId,
      channelGroups,
    })
  );

  vi.mocked(useAuthStore).mockImplementation((sel) =>
    sel({ user: authUser })
  );

  vi.mocked(useEPGsStore).mockImplementation((sel) =>
    sel({ epgs, tvgsById: {}, tvgsLoaded: true })
  );

  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ environment: { env_mode: 'production' } })
  );

  vi.mocked(useVideoStore).mockImplementation((sel) =>
    sel({ showVideo: vi.fn() })
  );

  vi.mocked(useOutputProfilesStore).mockImplementation((sel) =>
    sel({ profiles: [] })
  );

  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({ isWarningSuppressed, suppressWarning })
  );

  vi.mocked(useLocalStorage).mockReturnValue([{}, vi.fn()]);

  const tableInstance = makeDefaultTableInstance(tableOverrides);
  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return tableInstance;
  });

  return { tableInstance };
};

const getActionsCol = () =>
  capturedTableOptions.columns.find((c) => c.id === 'actions');

const getCol = (id) =>
  capturedTableOptions.columns.find((c) => c.id === id);

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('ChannelsTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
    vi.mocked(deleteChannel).mockResolvedValue(undefined);
    vi.mocked(deleteChannels).mockResolvedValue(undefined);
    vi.mocked(queryChannels).mockResolvedValue(undefined);
    vi.mocked(getAllChannelIds).mockResolvedValue([1]);
    vi.mocked(requeryChannels).mockResolvedValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders "Channels" heading', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(screen.getByText('Channels')).toBeInTheDocument();
    });

    it('renders ChannelTableHeader', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(screen.getByTestId('channel-table-header')).toBeInTheDocument();
    });

    it('renders CustomTable when channels exist', () => {
      setupMocks({ channels: [makeChannel()] });
      render(<ChannelsTable />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('renders onboarding when channels array is empty and no channelIds', async () => {
      setupMocks({
        channels: [],
        tableOverrides: { getRowModel: () => ({ rows: [] }) },
      });
      vi.mocked(useChannelsStore).mockImplementation((sel) =>
        sel({ channelIds: [], profiles: {}, selectedProfileId: '0', channelGroups: {} })
      );
      render(<ChannelsTable />);
      await waitFor(() => expect(screen.getByTestId('onboarding')).toBeInTheDocument());
    });

    it('renders pagination controls when channels exist', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(screen.getByTestId('pagination')).toBeInTheDocument();
      expect(screen.getByTestId('native-select')).toBeInTheDocument();
    });

    it('does not render confirmation dialog initially', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    it('does not render channel form on initial load', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(screen.queryByTestId('channel-form')).not.toBeInTheDocument();
    });

    it('renders HDHR, M3U, and EPG link buttons', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(screen.getByText('HDHR')).toBeInTheDocument();
      expect(screen.getByText('M3U')).toBeInTheDocument();
      expect(screen.getByText('EPG')).toBeInTheDocument();
    });
  });

  // ── Initial data fetch ─────────────────────────────────────────────────────

  describe('initial data fetch', () => {
    it('calls queryChannels on mount', async () => {
      setupMocks();
      render(<ChannelsTable />);
      await waitFor(() => expect(queryChannels).toHaveBeenCalled());
    });

    it('calls getAllChannelIds on mount', async () => {
      setupMocks();
      render(<ChannelsTable />);
      await waitFor(() => expect(getAllChannelIds).toHaveBeenCalled());
    });

    it('calls onReady after successful fetch when tvgsLoaded is true', async () => {
      setupMocks();
      const onReady = vi.fn();
      render(<ChannelsTable onReady={onReady} />);
      await waitFor(() => expect(onReady).toHaveBeenCalled());
    });
  });

  // ── useTable options ───────────────────────────────────────────────────────

  describe('useTable options', () => {
    it('passes manualPagination: true', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(capturedTableOptions.manualPagination).toBe(true);
    });

    it('passes manualSorting: true', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(capturedTableOptions.manualSorting).toBe(true);
    });

    it('passes manualFiltering: true', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(capturedTableOptions.manualFiltering).toBe(true);
    });

    it('passes enableRowSelection: true', () => {
      setupMocks();
      render(<ChannelsTable />);
      expect(capturedTableOptions.enableRowSelection).toBe(true);
    });

    it('passes channels as data', () => {
      const channels = [makeChannel({ id: 5 })];
      setupMocks({ channels });
      render(<ChannelsTable />);
      expect(capturedTableOptions.data).toBe(channels);
    });
  });

  // ── Add Channel form ───────────────────────────────────────────────────────

  describe('Add Channel form', () => {
    it('opens channel form with no channel when "Add Channel" is clicked in header', () => {
      setupMocks();
      render(<ChannelsTable />);
      fireEvent.click(screen.getByTestId('header-add-channel'));
      expect(screen.getByTestId('channel-form')).toBeInTheDocument();
      expect(screen.getByTestId('channel-form-name')).toHaveTextContent('new');
    });

    it('closes channel form when onClose is called', () => {
      setupMocks();
      render(<ChannelsTable />);
      fireEvent.click(screen.getByTestId('header-add-channel'));
      fireEvent.click(screen.getByTestId('channel-form-close'));
      expect(screen.queryByTestId('channel-form')).not.toBeInTheDocument();
    });

    it('opens channel form with no channel from onboarding', async () => {
      setupMocks({
        channels: [],
        tableOverrides: { getRowModel: () => ({ rows: [] }) },
      });
      vi.mocked(useChannelsStore).mockImplementation((sel) =>
        sel({ channelIds: [], profiles: {}, selectedProfileId: '0', channelGroups: {} })
      );
      render(<ChannelsTable />);
      const addBtn = await screen.findByTestId('onboarding-add');
      fireEvent.click(addBtn);
      expect(screen.getByTestId('channel-form')).toBeInTheDocument();
    });
  });

  // ── ChannelRowActions: edit ────────────────────────────────────────────────

  describe('ChannelRowActions — edit button', () => {
    const renderActionCell = (channel, tableInstance) => {
      const col = getActionsCol();
      return render(
        col.cell({ row: { original: channel }, table: tableInstance })
      );
    };

    it('edit button is disabled for non-admin users', () => {
      const channel = makeChannel();
      const { tableInstance } = setupMocks({ authUser: makeStandardUser() });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      expect(getByTestId('icon-square-pen').closest('button')).toBeDisabled();
    });

    it('edit button is enabled for admin users', () => {
      const channel = makeChannel();
      const { tableInstance } = setupMocks({ authUser: makeAdminUser() });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      expect(getByTestId('icon-square-pen').closest('button')).not.toBeDisabled();
    });

    it('clicking edit button opens channel form populated with the channel', () => {
      const channel = makeChannel({ name: 'HBO' });
      const { tableInstance } = setupMocks();
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));
      expect(screen.getByTestId('channel-form')).toBeInTheDocument();
      expect(screen.getByTestId('channel-form-name')).toHaveTextContent('HBO');
    });
  });

  // ── ChannelRowActions: delete ──────────────────────────────────────────────

  describe('ChannelRowActions — delete button', () => {
    const renderActionCell = (channel, tableInstance) => {
      const col = getActionsCol();
      return render(
        col.cell({ row: { original: channel }, table: tableInstance })
      );
    };

    it('delete button is disabled for non-admin users', () => {
      const channel = makeChannel();
      const { tableInstance } = setupMocks({ authUser: makeStandardUser() });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      expect(getByTestId('icon-square-minus').closest('button')).toBeDisabled();
    });

    it('delete button is enabled for admin users', () => {
      const channel = makeChannel();
      const { tableInstance } = setupMocks({ authUser: makeAdminUser() });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      expect(getByTestId('icon-square-minus').closest('button')).not.toBeDisabled();
    });

    it('opens confirmation dialog when delete is clicked and warning is not suppressed', () => {
      const channel = makeChannel({ id: 5 });
      const { tableInstance } = setupMocks({
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
      expect(screen.getByTestId('confirm-title')).toHaveTextContent(
        'Confirm Channel Deletion'
      );
    });

    it('calls deleteChannel directly when warning is suppressed', async () => {
      const channel = makeChannel({ id: 7 });
      const { tableInstance } = setupMocks({
        isWarningSuppressed: vi.fn(() => true),
      });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      await waitFor(() => expect(deleteChannel).toHaveBeenCalledWith(7));
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    it('calls deleteChannel when confirm dialog is confirmed', async () => {
      const channel = makeChannel({ id: 5 });
      const { tableInstance } = setupMocks({
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => expect(deleteChannel).toHaveBeenCalledWith(5));
    });

    it('calls requeryChannels after deleteChannel succeeds', async () => {
      const channel = makeChannel({ id: 5 });
      const { tableInstance } = setupMocks({
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => expect(requeryChannels).toHaveBeenCalled());
    });

    it('closes dialog after confirming delete', async () => {
      const channel = makeChannel({ id: 5 });
      const { tableInstance } = setupMocks({
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
      );
    });

    it('closes dialog on Cancel', () => {
      const channel = makeChannel({ id: 5 });
      const { tableInstance } = setupMocks({
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<ChannelsTable />);
      const { getByTestId } = renderActionCell(channel, tableInstance);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });
  });

  // ── Bulk delete ────────────────────────────────────────────────────────────

  describe('Bulk delete via ChannelTableHeader', () => {
    it('opens confirmation dialog with "Bulk" in title', () => {
      const channels = [makeChannel({ id: 1 }), makeChannel({ id: 2 })];
      setupMocks({
        channels,
        tableOverrides: {
          getRowModel: vi.fn(() => ({ rows: [] })),
          getHeaderGroups: vi.fn(() => []),
          setSelectedTableIds: vi.fn(),
          selectedTableIds: [1, 2],
        },
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<ChannelsTable />);
      fireEvent.click(screen.getByTestId('header-delete-channels'));
      expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
      expect(screen.getByTestId('confirm-title')).toHaveTextContent(
        'Confirm Bulk Channel Deletion'
      );
    });

    it('calls deleteChannels with selected ids when bulk confirm is clicked', async () => {
      const channels = [makeChannel({ id: 1 }), makeChannel({ id: 2 })];
      setupMocks({
        channels,
        tableOverrides: {
          getRowModel: vi.fn(() => ({ rows: [] })),
          getHeaderGroups: vi.fn(() => []),
          setSelectedTableIds: vi.fn(),
          selectedTableIds: [1, 2],
        },
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<ChannelsTable />);
      fireEvent.click(screen.getByTestId('header-delete-channels'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(deleteChannels).toHaveBeenCalledWith([1, 2])
      );
    });

    it('skips dialog and calls deleteChannels directly when warning is suppressed', async () => {
      const channels = [makeChannel({ id: 1 }), makeChannel({ id: 2 })];
      setupMocks({
        channels,
        tableOverrides: {
          getRowModel: vi.fn(() => ({ rows: [] })),
          getHeaderGroups: vi.fn(() => []),
          setSelectedTableIds: vi.fn(),
          selectedTableIds: [1, 2],
        },
        isWarningSuppressed: vi.fn(() => true),
      });
      render(<ChannelsTable />);
      fireEvent.click(screen.getByTestId('header-delete-channels'));
      await waitFor(() =>
        expect(deleteChannels).toHaveBeenCalledWith([1, 2])
      );
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });
  });

  // ── ChannelRowActions: preview ─────────────────────────────────────────────

  describe('ChannelRowActions — preview button', () => {
    it('calls showVideo when preview button is clicked', () => {
      const channel = makeChannel({ uuid: 'uuid-abc', name: 'ESPN' });
      const showVideoMock = vi.fn();
      const { tableInstance } = setupMocks();
      vi.mocked(useVideoStore).mockImplementation((sel) =>
        sel({ showVideo: showVideoMock })
      );
      vi.mocked(buildLiveStreamUrl).mockReturnValue('/proxy/ts/stream/uuid-abc');
      render(<ChannelsTable />);
      const col = getActionsCol();
      const { getByTestId } = render(
        col.cell({ row: { original: channel }, table: tableInstance })
      );
      fireEvent.click(getByTestId('icon-circle-play').closest('button'));
      expect(showVideoMock).toHaveBeenCalledWith(
        expect.stringContaining('uuid-abc'),
        'live',
        expect.objectContaining({ name: 'ESPN' })
      );
    });
  });

  // ── Recording form ─────────────────────────────────────────────────────────

  describe('Recording form', () => {
    it('opens recording form when Record menu item is clicked', () => {
      const channel = makeChannel({ name: 'CNN', id: 3 });
      const { tableInstance } = setupMocks({ authUser: makeAdminUser() });
      render(<ChannelsTable />);
      const col = getActionsCol();
      const { getAllByTestId } = render(
        col.cell({ row: { original: channel }, table: tableInstance })
      );
      // Record menu item is the second menu-item (after Copy URL)
      const menuItems = getAllByTestId('menu-item');
      const recordItem = menuItems.find((el) => el.textContent.includes('Record'));
      fireEvent.click(recordItem);
      expect(screen.getByTestId('recording-form')).toBeInTheDocument();
      expect(screen.getByTestId('recording-form-channel')).toHaveTextContent('CNN');
    });

    it('closes recording form when onClose is called', () => {
      const channel = makeChannel({ name: 'CNN', id: 3 });
      const { tableInstance } = setupMocks({ authUser: makeAdminUser() });
      render(<ChannelsTable />);
      const col = getActionsCol();
      const { getAllByTestId } = render(
        col.cell({ row: { original: channel }, table: tableInstance })
      );
      const menuItems = getAllByTestId('menu-item');
      const recordItem = menuItems.find((el) => el.textContent.includes('Record'));
      fireEvent.click(recordItem);
      fireEvent.click(screen.getByTestId('recording-form-close'));
      expect(screen.queryByTestId('recording-form')).not.toBeInTheDocument();
    });
  });

  // ── Copy URL ───────────────────────────────────────────────────────────────

  describe('"Copy URL" menu item', () => {
    it('calls copyToClipboard when "Copy URL" is clicked', () => {
      const channel = makeChannel({ uuid: 'uuid-1' });
      const { tableInstance } = setupMocks();
      render(<ChannelsTable />);
      const col = getActionsCol();
      const { getAllByTestId } = render(
        col.cell({ row: { original: channel }, table: tableInstance })
      );
      const menuItems = getAllByTestId('unstyled-button');
      const copyBtn = menuItems.find((el) => el.textContent.includes('Copy URL'));
      fireEvent.click(copyBtn);
      expect(copyToClipboard).toHaveBeenCalled();
    });
  });

  // ── Pagination ─────────────────────────────────────────────────────────────

  describe('pagination', () => {
    it('renders pagination string', () => {
      setupMocks({ totalCount: 50 });
      render(<ChannelsTable />);
      expect(screen.getByText('1 to 25 of 50')).toBeInTheDocument();
    });

    it('clicking next page triggers fetchData with updated page', async () => {
      setupMocks({ totalCount: 100, pageCount: 4 });
      render(<ChannelsTable />);
      fireEvent.click(screen.getByTestId('pagination-next'));
      await waitFor(() => expect(queryChannels).toHaveBeenCalledTimes(2));
    });
  });

  // ── enabled column ─────────────────────────────────────────────────────────

  describe('ChannelEnabledSwitch (enabled column)', () => {
    const renderEnabledCell = (channel) => {
      const col = getCol('enabled');
      const tableInstance = makeDefaultTableInstance({
        getState: () => ({ selectedTableIds: [] }),
      });
      return render(col.cell({ row: { original: channel }, table: tableInstance }));
    };

    it('renders a Switch for the enabled column', () => {
      setupMocks({ selectedProfileId: '0' });
      render(<ChannelsTable />);
      const { container } = renderEnabledCell(makeChannel());
      const { getByTestId } = within(container);
      expect(getByTestId('switch')).toBeInTheDocument();
    });

    it('switch is disabled when selectedProfileId is "0"', () => {
      setupMocks({ selectedProfileId: '0' });
      render(<ChannelsTable />);
      const { container } = renderEnabledCell(makeChannel());
      const { getByTestId } = within(container);
      expect(getByTestId('switch')).toBeDisabled();
    });
  });

  // ── channel_number column ──────────────────────────────────────────────────

  describe('channel_number column', () => {
    it('accessorFn returns effective_channel_number when present', () => {
      setupMocks();
      render(<ChannelsTable />);
      const col = getCol('channel_number');
      const result = col.accessorFn({
        effective_channel_number: 999,
        channel_number: 100,
      });
      expect(result).toBe(999);
    });

    it('accessorFn falls back to channel_number when effective_channel_number is null', () => {
      setupMocks();
      render(<ChannelsTable />);
      const col = getCol('channel_number');
      const result = col.accessorFn({
        effective_channel_number: null,
        channel_number: 42,
      });
      expect(result).toBe(42);
    });
  });

  // ── name column ────────────────────────────────────────────────────────────

  describe('name column', () => {
    it('accessorFn returns effective_name when present', () => {
      setupMocks();
      render(<ChannelsTable />);
      const col = getCol('name');
      const result = col.accessorFn({ effective_name: 'Override Name', name: 'Original' });
      expect(result).toBe('Override Name');
    });

    it('accessorFn falls back to name when effective_name is null', () => {
      setupMocks();
      render(<ChannelsTable />);
      const col = getCol('name');
      const result = col.accessorFn({ effective_name: null, name: 'Original' });
      expect(result).toBe('Original');
    });
  });

  // ── rowClassMap ────────────────────────────────────────────────────────────

  describe('rowClassMap / getRowStyles', () => {
    it('returns no-streams-row class for channels without streams', () => {
      const channel = makeChannel({ id: 10, streams: [] });
      setupMocks({ channels: [channel] });
      render(<ChannelsTable />);
      const { getRowStyles } = capturedTableOptions;
      expect(getRowStyles({ original: channel })).toEqual({
        className: 'no-streams-row',
      });
    });

    it('returns empty object for channels with active streams', () => {
      const channel = makeChannel({
        id: 11,
        streams: [{ id: 20, is_stale: false }],
      });
      setupMocks({ channels: [channel] });
      render(<ChannelsTable />);
      const { getRowStyles } = capturedTableOptions;
      expect(getRowStyles({ original: channel })).toEqual({});
    });

    it('returns stale-streams-row class for channels with stale streams', () => {
      const channel = makeChannel({
        id: 12,
        streams: [{ id: 21, is_stale: true }],
      });
      setupMocks({ channels: [channel] });
      render(<ChannelsTable />);
      const { getRowStyles } = capturedTableOptions;
      expect(getRowStyles({ original: channel })).toMatchObject({
        className: expect.stringMatching(/stale/i),
      });
    });
  });

  // ── expandedRowRenderer ────────────────────────────────────────────────────

  describe('expandedRowRenderer', () => {
    it('renders ChannelTableStreams for the expanded row', () => {
      const channel = makeChannel({ id: 1, streams: [{ id: 10, is_stale: false }] });
      setupMocks({ channels: [channel] });
      render(<ChannelsTable />);
      const { expandedRowRenderer } = capturedTableOptions;
      const { getByTestId } = render(
        expandedRowRenderer({ row: { id: '1', original: channel } })
      );
      expect(getByTestId('channel-table-streams')).toBeInTheDocument();
    });
  });
});
