import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVideoStore', () => ({ default: vi.fn() }));
vi.mock('../../../store/channelsTable', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));
vi.mock('../../../store/streamsTable', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => [{}, vi.fn()]),
}));

// ── Router mock ────────────────────────────────────────────────────────────────
vi.mock('react-router-dom', () => ({
  useNavigate: vi.fn(() => vi.fn()),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils', () => ({
  copyToClipboard: vi.fn().mockResolvedValue(undefined),
  useDebounce: vi.fn((value) => value),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/components/FloatingVideoUtils.js', () => ({
  buildLiveStreamUrl: vi.fn((path) => path),
}));

vi.mock('../../../utils/forms/ChannelUtils.js', () => ({
  requeryChannels: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../../utils/tables/StreamsTableUtils.js', () => ({
  addStreamsToChannel: vi.fn().mockResolvedValue(undefined),
  appendFetchPageParams: vi.fn(),
  createChannelFromStream: vi.fn().mockResolvedValue(undefined),
  createChannelsFromStreamsAsync: vi.fn().mockResolvedValue({ task_id: 'task-1', stream_count: 1 }),
  deleteStream: vi.fn().mockResolvedValue(undefined),
  deleteStreams: vi.fn().mockResolvedValue(undefined),
  getAllStreamIds: vi.fn().mockResolvedValue([]),
  getChannelNumberValue: vi.fn((mode) => mode === 'provider' ? null : 1),
  getChannelProfileIds: vi.fn((profileIds) => profileIds),
  getFilterParams: vi.fn(() => new URLSearchParams()),
  getStatsTooltip: vi.fn(() => ({ compactDisplay: '1080p', tooltipContent: '1920x1080' })),
  getStreamFilterOptions: vi.fn().mockResolvedValue({ groups: [], m3u_accounts: [] }),
  getStreams: vi.fn().mockResolvedValue([]),
  queryStreamsTable: vi.fn().mockResolvedValue({ count: 5, results: [] }),
  requeryStreams: vi.fn().mockResolvedValue(undefined),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../forms/Stream', () => ({
  default: ({ isOpen, onClose, stream }) =>
    isOpen ? (
      <div data-testid="stream-form">
        <span data-testid="form-stream-name">{stream?.name ?? 'new'}</span>
        <button data-testid="form-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../../ConfirmationDialog', () => ({
  default: ({ opened, onClose, onConfirm, title, message, confirmLabel, cancelLabel, loading }) =>
    opened ? (
      <div data-testid="confirm-dialog">
        <span data-testid="confirm-title">{title}</span>
        <span data-testid="confirm-message">{typeof message === 'string' ? message : 'message'}</span>
        <button data-testid="confirm-ok" onClick={onConfirm} disabled={loading}>
          {confirmLabel}
        </button>
        <button data-testid="confirm-cancel" onClick={onClose}>
          {cancelLabel}
        </button>
      </div>
    ) : null,
}));

vi.mock('../../modals/CreateChannelModal', () => ({
  default: ({ opened, onClose, onConfirm }) =>
    opened ? (
      <div data-testid="create-channel-modal">
        <button data-testid="create-channel-confirm" onClick={onConfirm}>
          Confirm
        </button>
        <button data-testid="create-channel-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../CustomTable', () => ({
  CustomTable: () => <div data-testid="custom-table" />,
  useTable: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled }) => (
    <button data-testid="action-icon" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, leftSection, disabled, loading }) => (
    <button data-testid="button" onClick={onClick} disabled={disabled || loading}>
      {leftSection}
      {children}
    </button>
  ),
  Card: ({ children, style }) => (
    <div data-testid="card" style={style}>{children}</div>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Divider: ({ label }) => <hr data-label={label} />,
  Flex: ({ children, style }) => (
    <div style={style}>{children}</div>
  ),
  Group: ({ children, style }) => <div style={style}>{children}</div>,
  LoadingOverlay: ({ visible }) => visible ? <div data-testid="loading-overlay" /> : null,
  Menu: Object.assign(
    ({ children }) => <div data-testid="menu">{children}</div>,
    {
      Target: ({ children }) => <div>{children}</div>,
      Dropdown: ({ children }) => <div>{children}</div>,
      Label: ({ children }) => <div data-testid="menu-label">{children}</div>,
      Item: ({ children, onClick, leftSection }) => (
        <button data-testid="menu-item" onClick={onClick}>
          {leftSection}
          {children}
        </button>
      ),
      Divider: () => <hr />,
    }
  ),
  MenuDivider: () => <hr />,
  MenuDropdown: ({ children }) => <div>{children}</div>,
  MenuItem: ({ children, onClick, leftSection }) => (
    <button data-testid="menu-item" onClick={onClick}>
      {leftSection}
      {children}
    </button>
  ),
  MenuLabel: ({ children }) => <div data-testid="menu-label">{children}</div>,
  MenuTarget: ({ children }) => <div>{children}</div>,
  MultiSelect: ({ onChange, value, data }) => (
    <select data-testid="multi-select" onChange={(e) => onChange && onChange([e.target.value])} value={value}>
      {(data || []).map((d) => (
        <option key={d.value ?? d} value={d.value ?? d}>{d.label ?? d}</option>
      ))}
    </select>
  ),
  NativeSelect: ({ onChange, value, data }) => (
    <select data-testid="native-select" onChange={onChange} value={value}>
      {(data || []).map((d) => (
        <option key={d} value={d}>{d}</option>
      ))}
    </select>
  ),
  Pagination: ({ total, value, onChange }) => (
    <div data-testid="pagination">
      <button data-testid="page-prev" onClick={() => onChange && onChange(value - 1)} disabled={value <= 1}>
        Prev
      </button>
      <span data-testid="page-current">{value}</span>
      <button data-testid="page-next" onClick={() => onChange && onChange(value + 1)} disabled={value >= total}>
        Next
      </button>
    </div>
  ),
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Stack: ({ children, style }) => <div style={style}>{children}</div>,
  Text: ({ children, style }) => (
    <span data-testid="text" style={style}>{children}</span>
  ),
  TextInput: ({ onChange, value, placeholder }) => (
    <input
      data-testid="text-input"
      onChange={onChange}
      value={value ?? ''}
      placeholder={placeholder}
    />
  ),
  Title: ({ children, style }) => <h3 style={style}>{children}</h3>,
  Tooltip: ({ children, label }) => (
    <div data-tooltip={label}>{children}</div>
  ),
  UnstyledButton: ({ children, onClick }) => (
    <button data-testid="unstyled-button" onClick={onClick}>{children}</button>
  ),
  useMantineTheme: vi.fn(() => ({
    tailwind: { blue: { 6: '#3b82f6' }, green: { 5: '#22c55e' }, yellow: { 3: '#fde047' } },
    palette: { background: { paper: '#1a1a1a' } },
    colors: {},
  })),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ArrowDownWideNarrow: () => <svg data-testid="icon-arrow-down" />,
  ArrowUpDown: () => <svg data-testid="icon-arrow-up-down" />,
  ArrowUpNarrowWide: () => <svg data-testid="icon-arrow-up" />,
  Copy: () => <svg data-testid="icon-copy" />,
  EllipsisVertical: () => <svg data-testid="icon-ellipsis" />,
  Eye: () => <svg data-testid="icon-eye" />,
  EyeOff: () => <svg data-testid="icon-eye-off" />,
  Filter: () => <svg data-testid="icon-filter" />,
  ListPlus: () => <svg data-testid="icon-list-plus" />,
  RotateCcw: () => <svg data-testid="icon-rotate-ccw" />,
  Search: () => <svg data-testid="icon-search" />,
  Square: () => <svg data-testid="icon-square" />,
  SquareCheck: () => <svg data-testid="icon-square-check" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import usePlaylistsStore from '../../../store/playlists';
import useChannelsStore from '../../../store/channels';
import useSettingsStore from '../../../store/settings';
import useVideoStore from '../../../store/useVideoStore';
import useChannelsTableStore from '../../../store/channelsTable';
import useWarningsStore from '../../../store/warnings';
import useStreamsTableStore from '../../../store/streamsTable';
import useLocalStorage from '../../../hooks/useLocalStorage';
import { useNavigate } from 'react-router-dom';
import { useTable } from '../CustomTable';
import * as StreamsTableUtils from '../../../utils/tables/StreamsTableUtils.js';
import StreamsTable from '../StreamsTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeStream = (overrides = {}) => ({
  id: 1,
  name: 'Test Stream',
  url: 'http://example.com/stream',
  stream_hash: 'abc123',
  channel_group: 'group-1',
  m3u_account: 10,
  tvg_id: 'tvg-1',
  stream_stats: null,
  is_custom: true,
  is_stale: false,
  ...overrides,
});

let capturedTableOptions = null;

const DEFAULT_PAGINATION = { pageIndex: 0, pageSize: 50 };
const DEFAULT_SORTING = [{ id: 'name', desc: false }];

const setupMocks = ({
  streams = [makeStream()],
  pageCount = 1,
  totalCount = 1,
  allQueryIds = [1],
  pagination = DEFAULT_PAGINATION,
  sorting = DEFAULT_SORTING,
  selectedStreamIds = [],
  playlists = [{ id: 10, name: 'My M3U' }],
  channelGroups = { 'group-1': { name: 'Sports' } },
  expandedChannelId = null,
  selectedChannelIds = [],
  channelProfiles = {},
  isWarningSuppressed = vi.fn(() => false),
  suppressWarning = vi.fn(),
  envMode = 'production',
  showVideo = vi.fn(),
  isVisible = false,
  tableSize = null,
} = {}) => {
  vi.mocked(useStreamsTableStore).mockImplementation((sel) =>
    sel({
      streams,
      pageCount,
      totalCount,
      allQueryIds,
      pagination,
      sorting,
      selectedStreamIds,
      setAllQueryIds: vi.fn(),
      setPagination: vi.fn(),
      setSorting: vi.fn(),
      setSelectedStreamIds: vi.fn(),
    })
  );

  vi.mocked(usePlaylistsStore).mockImplementation((sel) =>
    sel({ playlists, fetchPlaylists: vi.fn(), isLoading: false })
  );

  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({
      channelGroups,
      fetchChannelGroups: vi.fn(),
      profiles: channelProfiles,
      selectedProfileId: '0',
    })
  );

  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ environment: { env_mode: envMode } })
  );

  vi.mocked(useVideoStore).mockImplementation((sel) =>
    sel({ showVideo, isVisible })
  );

  vi.mocked(useChannelsTableStore).mockImplementation((sel) =>
    sel({
      expandedChannelId,
      selectedChannelIds,
      channels: [],
    })
  );

  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({ suppressWarning, isWarningSuppressed })
  );

  // useLocalStorage: first call is column-sizing, second is column-visibility
  vi.mocked(useLocalStorage)
    .mockReturnValueOnce([{}, vi.fn()])    // streams-table-column-sizing
    .mockReturnValueOnce([tableSize, vi.fn()]); // streams-table-column-visibility

  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return {
      getRowModel: () => ({ rows: [] }),
      getHeaderGroups: () => [],
      setSelectedTableIds: vi.fn(),
      tableSize: tableSize ?? 'default',
    };
  });
};

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('StreamsTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;

    vi.mocked(StreamsTableUtils.queryStreamsTable).mockResolvedValue({ count: 5, results: [] });
    vi.mocked(StreamsTableUtils.getAllStreamIds).mockResolvedValue([]);
    vi.mocked(StreamsTableUtils.getStreamFilterOptions).mockResolvedValue({
      groups: [],
      m3u_accounts: [],
    });
    vi.mocked(StreamsTableUtils.deleteStream).mockResolvedValue(undefined);
    vi.mocked(StreamsTableUtils.deleteStreams).mockResolvedValue(undefined);
    vi.mocked(StreamsTableUtils.addStreamsToChannel).mockResolvedValue(undefined);
    vi.mocked(StreamsTableUtils.requeryStreams).mockResolvedValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the "Streams" heading', () => {
      setupMocks();
      render(<StreamsTable />);
      expect(screen.getByText('Streams')).toBeInTheDocument();
    });

    it('renders the "Create Stream" button', () => {
      setupMocks();
      render(<StreamsTable />);
      expect(screen.getByText('Create Stream')).toBeInTheDocument();
    });

    it('renders the "Delete" button', () => {
      setupMocks();
      render(<StreamsTable />);
      expect(screen.getByText('Delete')).toBeInTheDocument();
    });

    it('renders the "Add to Channel" button', () => {
      setupMocks();
      render(<StreamsTable />);
      expect(screen.getByText('Add to Channel')).toBeInTheDocument();
    });

    it('renders "Create Channel (0)" button when no streams are selected', () => {
      setupMocks({ selectedStreamIds: [] });
      render(<StreamsTable />);
      expect(screen.getByText('Create Channel (0)')).toBeInTheDocument();
    });

    it('renders "Create Channels (N)" button when multiple streams are selected', () => {
      setupMocks({ selectedStreamIds: [1, 2] });
      render(<StreamsTable />);
      expect(screen.getByText('Create Channels (2)')).toBeInTheDocument();
    });

    it('does not render the stream form on initial load', () => {
      setupMocks();
      render(<StreamsTable />);
      expect(screen.queryByTestId('stream-form')).not.toBeInTheDocument();
    });

    it('shows getting-started card when totalCount is 0', async () => {
      vi.mocked(StreamsTableUtils.queryStreamsTable).mockResolvedValue({ count: 0, results: [] });
      setupMocks({ totalCount: 0, streams: [] });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(screen.getByText('Getting started')).toBeInTheDocument();
      });
    });

    it('renders the custom table when totalCount > 0', async () => {
      setupMocks({ totalCount: 5, streams: [makeStream()] });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(screen.getByTestId('custom-table')).toBeInTheDocument();
      });
    });

    it('loading overlay is not visible after data finishes loading', async () => {
      setupMocks({ totalCount: 5, streams: [makeStream()] });
      render(<StreamsTable />);
      // After the initial fetch resolves, the overlay is hidden
      await waitFor(() => {
        expect(screen.queryByTestId('loading-overlay')).not.toBeInTheDocument();
      });
    });
  });

  // ── Stream form (Create/Edit) ──────────────────────────────────────────────

  describe('Create Stream modal', () => {
    it('opens the stream form with no stream when "Create Stream" is clicked', () => {
      setupMocks();
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Create Stream'));
      expect(screen.getByTestId('stream-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-stream-name')).toHaveTextContent('new');
    });

    it('closes the stream form when onClose is called', async () => {
      setupMocks();
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Create Stream'));
      fireEvent.click(screen.getByTestId('form-close'));
      await waitFor(() => {
        expect(screen.queryByTestId('stream-form')).not.toBeInTheDocument();
      });
    });

    it('calls requeryStreams after form is closed', async () => {
      setupMocks();
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Create Stream'));
      fireEvent.click(screen.getByTestId('form-close'));
      await waitFor(() => {
        expect(StreamsTableUtils.requeryStreams).toHaveBeenCalled();
      });
    });
  });

  // ── Delete button state ────────────────────────────────────────────────────

  describe('"Delete" button', () => {
    it('is disabled when no streams are selected', () => {
      setupMocks({ selectedStreamIds: [] });
      render(<StreamsTable />);
      const deleteBtn = screen.getByText('Delete').closest('button');
      expect(deleteBtn).toBeDisabled();
    });

    it('is enabled when streams are selected', () => {
      setupMocks({ selectedStreamIds: [1] });
      render(<StreamsTable />);
      const deleteBtn = screen.getByText('Delete').closest('button');
      expect(deleteBtn).not.toBeDisabled();
    });
  });

  // ── "Add to Channel" button state ──────────────────────────────────────────

  describe('"Add to Channel" button', () => {
    it('is disabled when no streams are selected', () => {
      setupMocks({ selectedStreamIds: [] });
      render(<StreamsTable />);
      const btn = screen.getByText('Add to Channel').closest('button');
      expect(btn).toBeDisabled();
    });

    it('is disabled when streams selected but no target channel', () => {
      setupMocks({ selectedStreamIds: [1], expandedChannelId: null, selectedChannelIds: [] });
      render(<StreamsTable />);
      const btn = screen.getByText('Add to Channel').closest('button');
      expect(btn).toBeDisabled();
    });

    it('is enabled when streams selected and target channel exists', () => {
      setupMocks({
        selectedStreamIds: [1],
        expandedChannelId: 42,
      });
      render(<StreamsTable />);
      const btn = screen.getByText('Add to Channel').closest('button');
      expect(btn).not.toBeDisabled();
    });
  });

  // ── Single delete confirmation dialog ─────────────────────────────────────

  describe('single stream delete', () => {
    it('opens ConfirmationDialog when delete is clicked and warning is not suppressed', () => {
      setupMocks({
        selectedStreamIds: [1],
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Delete'));
      expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
      expect(screen.getByTestId('confirm-title')).toHaveTextContent('Confirm Bulk Stream Deletion');
    });

    it('calls deleteStreams when delete is confirmed', async () => {
      setupMocks({
        selectedStreamIds: [1],
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Delete'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => {
        expect(StreamsTableUtils.deleteStreams).toHaveBeenCalled();
      });
    });

    it('closes the dialog after confirming delete', async () => {
      setupMocks({
        selectedStreamIds: [1],
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Delete'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => {
        expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
      });
    });

    it('closes the dialog on Cancel', () => {
      setupMocks({
        selectedStreamIds: [1],
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Delete'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    it('skips the dialog and calls deleteStreams directly when warning is suppressed', async () => {
      setupMocks({
        selectedStreamIds: [1, 2],
        isWarningSuppressed: vi.fn(() => true),
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Delete'));
      await waitFor(() => {
        expect(StreamsTableUtils.deleteStreams).toHaveBeenCalled();
        expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
      });
    });
  });

  // ── "Create Channel" button and modal ─────────────────────────────────────

  describe('Create Channel modal', () => {
    it('opens CreateChannelModal when "Create Channel" is clicked with 1+ streams selected and warning not suppressed', () => {
      setupMocks({
        selectedStreamIds: [1, 2],
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Create Channels (2)'));
      expect(screen.getByTestId('create-channel-modal')).toBeInTheDocument();
    });

    it('closes CreateChannelModal when Close is clicked', () => {
      setupMocks({
        selectedStreamIds: [1, 2],
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Create Channels (2)'));
      fireEvent.click(screen.getByTestId('create-channel-close'));
      expect(screen.queryByTestId('create-channel-modal')).not.toBeInTheDocument();
    });

    it('calls createChannelsFromStreamsAsync when modal is confirmed', async () => {
      setupMocks({
        selectedStreamIds: [1, 2],
        isWarningSuppressed: vi.fn(() => false),
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Create Channels (2)'));
      fireEvent.click(screen.getByTestId('create-channel-confirm'));
      await waitFor(() => {
        expect(StreamsTableUtils.createChannelsFromStreamsAsync).toHaveBeenCalled();
      });
    });

    it('"Create Channel" button is disabled when no streams selected', () => {
      setupMocks({ selectedStreamIds: [] });
      render(<StreamsTable />);
      const btn = screen.getByText('Create Channel (0)').closest('button');
      expect(btn).toBeDisabled();
    });
  });

  // ── Getting started card navigation ───────────────────────────────────────

  describe('getting started card', () => {
    const renderEmpty = async () => {
      vi.mocked(StreamsTableUtils.queryStreamsTable).mockResolvedValue({ count: 0, results: [] });
      setupMocks({ totalCount: 0, streams: [] });
      render(<StreamsTable />);
      await waitFor(() => screen.getByText('Getting started'));
    };

    it('shows "Add M3U" button', async () => {
      await renderEmpty();
      expect(screen.getByText('Add M3U')).toBeInTheDocument();
    });

    it('shows "Add Individual Stream" button', async () => {
      await renderEmpty();
      expect(screen.getByText('Add Individual Stream')).toBeInTheDocument();
    });

    it('navigates to /sources when "Add M3U" is clicked', async () => {
      const mockNavigate = vi.fn();
      vi.mocked(useNavigate).mockReturnValue(mockNavigate);
      await renderEmpty();
      fireEvent.click(screen.getByText('Add M3U'));
      expect(mockNavigate).toHaveBeenCalledWith('/sources');
    });

    it('opens stream form when "Add Individual Stream" is clicked', async () => {
      await renderEmpty();
      fireEvent.click(screen.getByText('Add Individual Stream'));
      expect(screen.getByTestId('stream-form')).toBeInTheDocument();
    });
  });

  // ── Pagination ─────────────────────────────────────────────────────────────

  describe('pagination', () => {
    it('renders pagination controls when totalCount > 0', async () => {
      setupMocks({ totalCount: 5, streams: [makeStream()] });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(screen.getByTestId('pagination')).toBeInTheDocument();
      });
    });

    it('renders current page number', async () => {
      setupMocks({ totalCount: 5, streams: [makeStream()], pagination: { pageIndex: 0, pageSize: 50 } });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(screen.getByTestId('page-current')).toHaveTextContent('1');
      });
    });

    it('renders native select for page size', async () => {
      setupMocks({ totalCount: 5, streams: [makeStream()] });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(screen.getByTestId('native-select')).toBeInTheDocument();
      });
    });
  });

  // ── Column visibility (Table Settings menu) ────────────────────────────────

  describe('column visibility toggle menu', () => {
    it('renders "Toggle Columns" label in the settings menu', () => {
      setupMocks({ totalCount: 5, streams: [makeStream()] });
      render(<StreamsTable />);
      // Menu label is always rendered even in collapsed state due to mock
      expect(screen.getByText('Toggle Columns')).toBeInTheDocument();
    });

    it('renders all column toggle menu items', () => {
      setupMocks({ totalCount: 5, streams: [makeStream()] });
      render(<StreamsTable />);
      expect(screen.getByText('Name')).toBeInTheDocument();
      expect(screen.getByText('Group')).toBeInTheDocument();
      expect(screen.getByText('M3U')).toBeInTheDocument();
      expect(screen.getByText('TVG-ID')).toBeInTheDocument();
      expect(screen.getByText('Stats')).toBeInTheDocument();
    });
  });

  // ── useTable integration ───────────────────────────────────────────────────

  describe('useTable integration', () => {
    it('passes stream data to useTable', async () => {
      const streams = [makeStream({ id: 1 }), makeStream({ id: 2 })];
      setupMocks({ streams, totalCount: 2 });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(capturedTableOptions.data).toHaveLength(2);
      });
    });

    it('passes manualPagination: true to useTable', async () => {
      setupMocks({ totalCount: 5, streams: [makeStream()] });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(capturedTableOptions.manualPagination).toBe(true);
      });
    });

    it('passes manualSorting: true to useTable', async () => {
      setupMocks({ totalCount: 5, streams: [makeStream()] });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(capturedTableOptions.manualSorting).toBe(true);
      });
    });

    it('passes pagination state to useTable', async () => {
      const pagination = { pageIndex: 2, pageSize: 25 };
      setupMocks({ totalCount: 5, streams: [makeStream()], pagination });
      render(<StreamsTable />);
      await waitFor(() => {
        expect(capturedTableOptions.state.pagination).toEqual(pagination);
      });
    });
  });

  // ── Initial data fetch ─────────────────────────────────────────────────────

  describe('initial data fetch', () => {
    it('calls queryStreamsTable on mount', async () => {
      setupMocks();
      render(<StreamsTable />);
      await waitFor(() => {
        expect(StreamsTableUtils.queryStreamsTable).toHaveBeenCalled();
      });
    });

    it('calls getAllStreamIds on mount', async () => {
      setupMocks();
      render(<StreamsTable />);
      await waitFor(() => {
        expect(StreamsTableUtils.getAllStreamIds).toHaveBeenCalled();
      });
    });

    it('calls getStreamFilterOptions on mount', async () => {
      setupMocks();
      render(<StreamsTable />);
      await waitFor(() => {
        expect(StreamsTableUtils.getStreamFilterOptions).toHaveBeenCalled();
      });
    });

    it('calls onReady callback once data is loaded', async () => {
      setupMocks();
      const onReady = vi.fn();
      render(<StreamsTable onReady={onReady} />);
      await waitFor(() => {
        expect(onReady).toHaveBeenCalledTimes(1);
      });
    });
  });

  // ── "Add to Channel" action ────────────────────────────────────────────────

  describe('"Add to Channel" action', () => {
    it('calls addStreamsToChannel with selected streams', async () => {
      const stream = makeStream({ id: 5 });
      setupMocks({
        streams: [stream],
        selectedStreamIds: [5],
        expandedChannelId: 42,
      });
      render(<StreamsTable />);
      fireEvent.click(screen.getByText('Add to Channel'));
      await waitFor(() => {
        expect(StreamsTableUtils.addStreamsToChannel).toHaveBeenCalledWith(
          42,
          undefined,
          expect.arrayContaining([expect.objectContaining({ id: 5 })])
        );
      });
    });
  });

  // ── handleWatchStream ──────────────────────────────────────────────────────

  describe('handleWatchStream (via row actions)', () => {
    it('calls buildLiveStreamUrl and showVideo via the actions cell renderer', async () => {
      const mockShowVideo = vi.fn();
      setupMocks({ totalCount: 5, streams: [makeStream()], showVideo: mockShowVideo });
      render(<StreamsTable />);
      await waitFor(() => expect(capturedTableOptions).not.toBeNull());

      const actionsCell = capturedTableOptions.bodyCellRenderFns?.actions;
      expect(actionsCell).toBeDefined();

      // Render the actions cell to get the StreamRowActions component
      const row = {
        original: makeStream({ stream_hash: 'hash-abc', name: 'My Stream' }),
      };
      const cell = { column: { id: 'actions' } };

      // The actions renderer returns a StreamRowActions element; find Preview Stream button
      const { getByText } = render(actionsCell({ cell, row }));
      fireEvent.click(getByText('Preview Stream'));
      expect(mockShowVideo).toHaveBeenCalled();
    });
  });
});
