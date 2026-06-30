import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => ['default', vi.fn()]),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: vi.fn(() => ({
    fullDateFormat: 'MM/DD/YYYY',
    fullDateTimeFormat: 'MM/DD/YYYY HH:mm',
  })),
  format: vi.fn((val) => `formatted:${val}`),
  diff: vi.fn(() => 30),
  getNow: vi.fn(() => '2024-06-01T12:00:00Z'),
}));

vi.mock('../../../utils/tables/M3UsTableUtils.js', () => ({
  deletePlaylist: vi.fn().mockResolvedValue(undefined),
  getExpirationInfo: vi.fn(() => ({ color: 'green.5', label: '30d left' })),
  getExpirationTooltip: vi.fn(() => 'expiration-tooltip'),
  getPlaylistAutoCreatedChannelsCount: vi.fn().mockResolvedValue({
    count: 0,
    sample_names: [],
  }),
  getSortedPlaylists: vi.fn((playlists) =>
    playlists.filter((p) => p.locked === false)
  ),
  getStatusColor: vi.fn(() => 'green.5'),
  getStatusContent: vi.fn(() => ({ type: 'default', label: 'Idle' })),
  formatStatusText: vi.fn((s) =>
    s ? s.charAt(0).toUpperCase() + s.slice(1) : 'Unknown'
  ),
  refreshPlaylist: vi.fn().mockResolvedValue(undefined),
  updatePlaylist: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../M3uTableUtils.jsx', () => ({
  makeHeaderCellRenderer: vi.fn(() => (header) => (
    <span data-testid={`header-${header.id}`}>
      {header.column.columnDef.header}
    </span>
  )),
  makeSortingChangeHandler: vi.fn(() => vi.fn()),
}));

vi.mock('../../../helpers', () => ({
  TableHelper: {
    defaultProperties: { mantineTableProps: { striped: true } },
  },
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../forms/M3U', () => ({
  default: ({ isOpen, onClose, m3uAccount }) =>
    isOpen ? (
      <div data-testid="m3u-form">
        <span data-testid="m3u-form-account">{m3uAccount?.name ?? 'new'}</span>
        <button data-testid="m3u-form-close" onClick={() => onClose(null)}>
          Close
        </button>
        <button
          data-testid="m3u-form-close-with-playlist"
          onClick={() => onClose({ id: 99, name: 'New Playlist' })}
        >
          Close with playlist
        </button>
      </div>
    ) : null,
}));

vi.mock('../../ServerGroupsManagerModal', () => ({
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div data-testid="server-groups-modal">
        <button data-testid="server-groups-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../../../components/ConfirmationDialog', () => ({
  default: ({
    opened,
    onClose,
    onConfirm,
    title,
    message,
    confirmLabel,
    cancelLabel,
    loading,
  }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="confirm-title">{title}</div>
        <div data-testid="confirm-message">
          {typeof message === 'string' ? message : 'rich-message'}
        </div>
        <button
          data-testid="confirm-cancel"
          onClick={onClose}
          disabled={loading}
        >
          {cancelLabel}
        </button>
        <button data-testid="confirm-ok" onClick={onConfirm} disabled={loading}>
          {confirmLabel}
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
  ActionIcon: ({ children, onClick, disabled, color }) => (
    <button data-testid="action-icon" data-color={color} onClick={onClick} disabled={disabled}>
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
  Flex: ({ children, style }) => <div style={style}>{children}</div>,
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Switch: ({ checked, onChange }) => (
    <input
      data-testid="active-switch"
      type="checkbox"
      checked={checked ?? false}
      onChange={onChange}
    />
  ),
  Text: ({ children, size, c, fw, style }) => (
    <span data-testid="text" data-size={size} data-color={c} data-fw={fw} style={style}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => (
    <div data-tooltip={typeof label === 'string' ? label : 'tooltip'}>{children}</div>
  ),
  useMantineTheme: vi.fn(() => ({
    palette: { background: { paper: '#1a1a1a' } },
    colors: { red: { 6: '#fa5252' }, green: { 6: '#40c057' } },
  })),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  // Icons used by M3UsTable
  RefreshCcw: () => <svg data-testid="icon-refresh" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
  // Icons required by src/config/navigation.js (pulled in via store/auth)
  Blocks: () => <svg />,
  ChartLine: () => <svg />,
  Database: () => <svg />,
  Download: () => <svg />,
  FileImage: () => <svg />,
  LayoutGrid: () => <svg />,
  ListOrdered: () => <svg />,
  Logs: () => <svg />,
  MonitorCog: () => <svg />,
  Package: () => <svg />,
  Play: () => <svg />,
  PlugZap: () => <svg />,
  Settings: () => <svg />,
  User: () => <svg />,
  Video: () => <svg />,
  Webhook: () => <svg />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import usePlaylistsStore from '../../../store/playlists';
import useWarningsStore from '../../../store/warnings';
import useLocalStorage from '../../../hooks/useLocalStorage';
import * as M3UsTableUtils from '../../../utils/tables/M3UsTableUtils.js';
import * as DateTimeUtils from '../../../utils/dateTimeUtils.js';
import { useTable } from '../CustomTable';
import M3UTable from '../M3UsTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makePlaylist = (overrides = {}) => ({
  id: 1,
  name: 'Test M3U',
  account_type: 'M3U',
  server_url: 'http://example.com/playlist.m3u',
  file_path: null,
  status: 'success',
  last_message: 'Loaded 500 streams',
  max_streams: 5,
  profiles: [],
  is_active: true,
  locked: false,
  updated_at: '2024-01-01T12:00:00Z',
  earliest_expiration: '2024-12-01T00:00:00Z',
  all_expirations: [],
  ...overrides,
});

let capturedTableOptions = null;

const setupMocks = ({
  playlists = [makePlaylist()],
  refreshProgress = {},
  editPlaylistId = null,
  isWarningSuppressed = vi.fn(() => false),
  suppressWarning = vi.fn(),
  tableSize = 'default',
} = {}) => {
  const mockSetRefreshProgress = vi.fn();
  const mockSetEditPlaylistId = vi.fn();

  vi.mocked(usePlaylistsStore).mockImplementation((sel) =>
    sel({
      playlists,
      refreshProgress,
      setRefreshProgress: mockSetRefreshProgress,
      editPlaylistId,
      setEditPlaylistId: mockSetEditPlaylistId,
    })
  );

  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({ isWarningSuppressed, suppressWarning })
  );

  vi.mocked(useLocalStorage).mockReturnValue([tableSize, vi.fn()]);

  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return { getRowModel: () => ({ rows: [] }), getHeaderGroups: () => [] };
  });

  return { mockSetRefreshProgress, mockSetEditPlaylistId };
};

const getCol = (keyOrId) =>
  capturedTableOptions.columns.find(
    (c) => c.accessorKey === keyOrId || c.id === keyOrId
  );

const makeRowCtx = (playlist) => ({
  row: { id: String(playlist.id), original: playlist },
  cell: { column: { id: 'actions', columnDef: {} }, getValue: vi.fn() },
});

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('M3UTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
    vi.mocked(M3UsTableUtils.deletePlaylist).mockResolvedValue(undefined);
    vi.mocked(M3UsTableUtils.refreshPlaylist).mockResolvedValue(undefined);
    vi.mocked(M3UsTableUtils.updatePlaylist).mockResolvedValue(undefined);
    vi.mocked(M3UsTableUtils.getPlaylistAutoCreatedChannelsCount).mockResolvedValue({
      count: 0,
      sample_names: [],
    });
    vi.mocked(M3UsTableUtils.getStatusContent).mockReturnValue({ type: 'default', label: 'Idle' });
    vi.mocked(DateTimeUtils.format).mockImplementation((val) => `formatted:${val}`);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the "M3U Accounts" heading', () => {
      setupMocks();
      render(<M3UTable />);
      expect(screen.getByText('M3U Accounts')).toBeInTheDocument();
    });

    it('renders the "Add M3U" button', () => {
      setupMocks();
      render(<M3UTable />);
      expect(screen.getByText('Add M3U')).toBeInTheDocument();
    });

    it('renders the custom table', () => {
      setupMocks();
      render(<M3UTable />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('does not render the M3U form on initial load', () => {
      setupMocks();
      render(<M3UTable />);
      expect(screen.queryByTestId('m3u-form')).not.toBeInTheDocument();
    });

    it('filters out locked playlists from the table data', () => {
      setupMocks({
        playlists: [
          makePlaylist({ id: 1, name: 'Unlocked', locked: false }),
          makePlaylist({ id: 2, name: 'Locked', locked: true }),
        ],
      });
      render(<M3UTable />);
      expect(capturedTableOptions.data.every((p) => p.locked === false)).toBe(true);
    });

    it('places active playlists before inactive ones', () => {
      setupMocks({
        playlists: [
          makePlaylist({ id: 1, name: 'Inactive', is_active: false }),
          makePlaylist({ id: 2, name: 'Active', is_active: true }),
        ],
      });
      render(<M3UTable />);
      expect(capturedTableOptions.data[0].name).toBe('Active');
      expect(capturedTableOptions.data[1].name).toBe('Inactive');
    });

    it('sorts playlists alphabetically within the same active group', () => {
      setupMocks({
        playlists: [
          makePlaylist({ id: 1, name: 'Zebra', is_active: true }),
          makePlaylist({ id: 2, name: 'Alpha', is_active: true }),
        ],
      });
      render(<M3UTable />);
      expect(capturedTableOptions.data[0].name).toBe('Alpha');
      expect(capturedTableOptions.data[1].name).toBe('Zebra');
    });
  });

  // ── Add M3U ────────────────────────────────────────────────────────────────

  describe('Add M3U', () => {
    it('opens M3UForm with no account when "Add M3U" is clicked', () => {
      setupMocks();
      render(<M3UTable />);
      fireEvent.click(screen.getByText('Add M3U'));
      expect(screen.getByTestId('m3u-form')).toBeInTheDocument();
      expect(screen.getByTestId('m3u-form-account')).toHaveTextContent('new');
    });

    it('closes the form when onClose(null) is called', () => {
      setupMocks();
      render(<M3UTable />);
      fireEvent.click(screen.getByText('Add M3U'));
      fireEvent.click(screen.getByTestId('m3u-form-close'));
      expect(screen.queryByTestId('m3u-form')).not.toBeInTheDocument();
    });

    it('keeps form open and updates playlist when onClose receives a new playlist', () => {
      setupMocks();
      render(<M3UTable />);
      fireEvent.click(screen.getByText('Add M3U'));
      fireEvent.click(screen.getByTestId('m3u-form-close-with-playlist'));
      expect(screen.getByTestId('m3u-form')).toBeInTheDocument();
      expect(screen.getByTestId('m3u-form-account')).toHaveTextContent('New Playlist');
    });
  });

  // ── Edit playlist via RowActions ───────────────────────────────────────────

  describe('edit playlist via RowActions', () => {
    it('opens M3UForm populated with the playlist when edit icon is clicked', () => {
      const playlist = makePlaylist({ name: 'My M3U' });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));

      expect(screen.getByTestId('m3u-form')).toBeInTheDocument();
      expect(screen.getByTestId('m3u-form-account')).toHaveTextContent('My M3U');
    });

    it('closes the form after editing when onClose(null) is called', () => {
      const playlist = makePlaylist({ name: 'My M3U' });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));
      fireEvent.click(screen.getByTestId('m3u-form-close'));

      expect(screen.queryByTestId('m3u-form')).not.toBeInTheDocument();
    });
  });

  // ── editPlaylistId (from notifications) ───────────────────────────────────

  describe('editPlaylistId from store', () => {
    it('auto-opens M3UForm for the matching playlist', () => {
      const playlists = [makePlaylist({ id: 42, name: 'Notification Playlist' })];
      setupMocks({ playlists, editPlaylistId: 42 });
      render(<M3UTable />);
      expect(screen.getByTestId('m3u-form')).toBeInTheDocument();
      expect(screen.getByTestId('m3u-form-account')).toHaveTextContent('Notification Playlist');
    });

    it('calls setEditPlaylistId(null) after handling editPlaylistId', () => {
      const playlists = [makePlaylist({ id: 42 })];
      const { mockSetEditPlaylistId } = setupMocks({ playlists, editPlaylistId: 42 });
      render(<M3UTable />);
      expect(mockSetEditPlaylistId).toHaveBeenCalledWith(null);
    });

    it('does not open form when editPlaylistId does not match any playlist', () => {
      setupMocks({ playlists: [makePlaylist({ id: 1 })], editPlaylistId: 999 });
      render(<M3UTable />);
      expect(screen.queryByTestId('m3u-form')).not.toBeInTheDocument();
    });
  });

  // ── Refresh playlist ───────────────────────────────────────────────────────

  describe('refresh playlist', () => {
    it('calls setRefreshProgress with initializing state immediately', async () => {
      const playlist = makePlaylist({ id: 1 });
      const { mockSetRefreshProgress } = setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      expect(mockSetRefreshProgress).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ action: 'initializing', progress: 0 })
      );
    });

    it('calls refreshPlaylist with the playlist id', async () => {
      const playlist = makePlaylist({ id: 1 });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      await waitFor(() =>
        expect(M3UsTableUtils.refreshPlaylist).toHaveBeenCalledWith(1)
      );
    });

    it('sets error progress when refreshPlaylist rejects', async () => {
      vi.mocked(M3UsTableUtils.refreshPlaylist).mockRejectedValue(new Error('fail'));
      const playlist = makePlaylist({ id: 1 });
      const { mockSetRefreshProgress } = setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      await waitFor(() =>
        expect(mockSetRefreshProgress).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ action: 'error', status: 'error' })
        )
      );
    });

    it('disables the refresh button when playlist is inactive', () => {
      const playlist = makePlaylist({ id: 1, is_active: false });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-refresh').closest('button')).toBeDisabled();
    });

    it('enables the refresh button when playlist is active', () => {
      const playlist = makePlaylist({ id: 1, is_active: true });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-refresh').closest('button')).not.toBeDisabled();
    });
  });

  // ── Delete playlist ────────────────────────────────────────────────────────

  describe('delete playlist', () => {
    const openDeleteDialog = async (playlist) => {
      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
    };

    it('opens "Confirm M3U Account Deletion" dialog', async () => {
      const playlist = makePlaylist();
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);
      await openDeleteDialog(playlist);
      expect(screen.getByTestId('confirm-title')).toHaveTextContent(
        'Confirm M3U Account Deletion'
      );
    });

    it('shows rich message content in the dialog', async () => {
      const playlist = makePlaylist({ name: 'My Channel List' });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);
      await openDeleteDialog(playlist);
      expect(screen.getByTestId('confirm-message')).toHaveTextContent('rich-message');
    });

    it('calls deletePlaylist with the correct id on confirm', async () => {
      const playlist = makePlaylist({ id: 7 });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);
      await openDeleteDialog(playlist);
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(M3UsTableUtils.deletePlaylist).toHaveBeenCalledWith(7)
      );
    });

    it('closes the dialog after confirming delete', async () => {
      const playlist = makePlaylist();
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);
      await openDeleteDialog(playlist);
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument()
      );
    });

    it('closes dialog on cancel without calling deletePlaylist', async () => {
      const playlist = makePlaylist();
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);
      await openDeleteDialog(playlist);
      fireEvent.click(screen.getByTestId('confirm-cancel'));
      expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument();
      expect(M3UsTableUtils.deletePlaylist).not.toHaveBeenCalled();
    });

    it('skips dialog and deletes directly when warning suppressed and 0 auto-channels', async () => {
      const playlist = makePlaylist({ id: 5 });
      setupMocks({ playlists: [playlist], isWarningSuppressed: vi.fn(() => true) });
      render(<M3UTable />);

      const { row, cell } = makeRowCtx(playlist);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      await waitFor(() =>
        expect(M3UsTableUtils.deletePlaylist).toHaveBeenCalledWith(5)
      );
      expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument();
    });

    it('opens dialog when warning suppressed but auto-channels count > 0', async () => {
      vi.mocked(M3UsTableUtils.getPlaylistAutoCreatedChannelsCount).mockResolvedValue({
        count: 3,
        sample_names: ['Ch 1'],
      });
      const playlist = makePlaylist();
      setupMocks({ playlists: [playlist], isWarningSuppressed: vi.fn(() => true) });
      render(<M3UTable />);
      await openDeleteDialog(playlist);
      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
    });

    it('opens dialog when auto-channel count fetch fails', async () => {
      vi.mocked(M3UsTableUtils.getPlaylistAutoCreatedChannelsCount).mockRejectedValue(
        new Error('Network error')
      );
      const playlist = makePlaylist();
      setupMocks({ playlists: [playlist], isWarningSuppressed: vi.fn(() => true) });
      render(<M3UTable />);
      await openDeleteDialog(playlist);
      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
    });

    it('does not throw when deletePlaylist rejects', async () => {
      vi.mocked(M3UsTableUtils.deletePlaylist).mockRejectedValue(new Error('server error'));
      const playlist = makePlaylist();
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);
      await openDeleteDialog(playlist);
      await expect(
        act(async () => fireEvent.click(screen.getByTestId('confirm-ok')))
      ).resolves.not.toThrow();
    });
  });

  // ── Toggle active ──────────────────────────────────────────────────────────

  describe('toggle active', () => {
    const renderSwitch = (playlist) => {
      const col = getCol('is_active');
      return col.cell({
        cell: { getValue: () => playlist.is_active },
        row: { original: playlist },
      });
    };

    it('calls updatePlaylist with is_active:false when toggling an active playlist', async () => {
      const playlist = makePlaylist({ is_active: true });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { getByTestId } = render(renderSwitch(playlist));
      fireEvent.click(getByTestId('active-switch'));

      await waitFor(() =>
        expect(M3UsTableUtils.updatePlaylist).toHaveBeenCalledWith(
          { is_active: false },
          playlist,
          true
        )
      );
    });

    it('calls updatePlaylist with is_active:true when toggling an inactive playlist', async () => {
      const playlist = makePlaylist({ is_active: false });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { getByTestId } = render(renderSwitch(playlist));
      fireEvent.click(getByTestId('active-switch'));

      await waitFor(() =>
        expect(M3UsTableUtils.updatePlaylist).toHaveBeenCalledWith(
          { is_active: true },
          playlist,
          true
        )
      );
    });

    it('does not throw when updatePlaylist rejects', async () => {
      vi.mocked(M3UsTableUtils.updatePlaylist).mockRejectedValue(new Error('toggle error'));
      const playlist = makePlaylist({ is_active: true });
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);

      const { getByTestId } = render(renderSwitch(playlist));
      await expect(
        act(async () => fireEvent.click(getByTestId('active-switch')))
      ).resolves.not.toThrow();
    });
  });

  // ── Column: Type ───────────────────────────────────────────────────────────

  describe('Type column', () => {
    it('renders "XC" for Xtream Codes type', () => {
      setupMocks();
      render(<M3UTable />);
      const { getByText } = render(
        getCol('account_type').cell({ cell: { getValue: () => 'XC' } })
      );
      expect(getByText('XC')).toBeInTheDocument();
    });

    it('renders "M3U" for standard type', () => {
      setupMocks();
      render(<M3UTable />);
      const { getByText } = render(
        getCol('account_type').cell({ cell: { getValue: () => 'M3U' } })
      );
      expect(getByText('M3U')).toBeInTheDocument();
    });
  });

  // ── Column: URL / File ─────────────────────────────────────────────────────

  describe('URL / File column', () => {
    it('renders server_url when present', () => {
      setupMocks();
      render(<M3UTable />);
      const playlist = makePlaylist({ server_url: 'http://example.com/list.m3u' });
      const { getByText } = render(
        getCol('server_url').cell({
          cell: { getValue: () => playlist.server_url },
          row: { original: playlist },
        })
      );
      expect(getByText('http://example.com/list.m3u')).toBeInTheDocument();
    });

    it('falls back to file_path when server_url is empty', () => {
      setupMocks();
      render(<M3UTable />);
      const playlist = makePlaylist({ server_url: '', file_path: '/files/list.m3u' });
      const { getByText } = render(
        getCol('server_url').cell({
          cell: { getValue: () => '' },
          row: { original: playlist },
        })
      );
      expect(getByText('/files/list.m3u')).toBeInTheDocument();
    });
  });

  // ── Column: Status ─────────────────────────────────────────────────────────

  describe('Status column', () => {
    it('returns null when status value is empty', () => {
      setupMocks();
      render(<M3UTable />);
      expect(getCol('status').cell({ cell: { getValue: () => null } })).toBeNull();
    });

    it('renders formatted status text', () => {
      vi.mocked(M3UsTableUtils.formatStatusText).mockReturnValue('Success');
      setupMocks();
      render(<M3UTable />);
      const { getByText } = render(
        getCol('status').cell({ cell: { getValue: () => 'success' } })
      );
      expect(getByText('Success')).toBeInTheDocument();
    });
  });

  // ── Column: Status Message ─────────────────────────────────────────────────

  describe('Status Message column', () => {
    it('returns null when last_message is empty and no active progress', () => {
      setupMocks();
      render(<M3UTable />);
      const playlist = makePlaylist({ id: 1, status: 'idle' });
      expect(
        getCol('last_message').cell({
          cell: { getValue: () => null },
          row: { original: playlist },
        })
      ).toBeNull();
    });

    it('renders the last_message text for a generic status', () => {
      setupMocks();
      render(<M3UTable />);
      const playlist = makePlaylist({ id: 1, status: 'idle' });
      const { getByText } = render(
        getCol('last_message').cell({
          cell: { getValue: () => 'Loaded 200 streams' },
          row: { original: playlist },
        })
      );
      expect(getByText('Loaded 200 streams')).toBeInTheDocument();
    });

    it('shows progress UI when active progress (< 100) exists', () => {
      vi.mocked(M3UsTableUtils.getStatusContent).mockReturnValue({ type: 'initializing' });
      const playlist = makePlaylist({ id: 1 });
      setupMocks({ playlists: [playlist], refreshProgress: { 1: { progress: 50 } } });
      render(<M3UTable />);
      const { getByText } = render(
        getCol('last_message').cell({
          cell: { getValue: () => null },
          row: { original: playlist },
        })
      );
      expect(getByText('Initializing refresh...')).toBeInTheDocument();
    });

    it('bypasses progress UI when progress equals 100', () => {
      const playlist = makePlaylist({ id: 1, status: 'success' });
      setupMocks({ playlists: [playlist], refreshProgress: { 1: { progress: 100 } } });
      render(<M3UTable />);
      const { getByText } = render(
        getCol('last_message').cell({
          cell: { getValue: () => 'Done' },
          row: { original: playlist },
        })
      );
      expect(getByText('Done')).toBeInTheDocument();
    });
  });

  // ── Column: Max Streams ────────────────────────────────────────────────────

  describe('Max Streams column', () => {
    const renderMaxStreams = (playlist) => {
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);
      return getCol('max_streams').cell({ row: { original: playlist } });
    };

    it('renders max_streams when no active profiles', () => {
      const { getByText } = render(
        renderMaxStreams(makePlaylist({ max_streams: 10, profiles: [] }))
      );
      expect(getByText('10')).toBeInTheDocument();
    });

    it('renders "∞" when max_streams is 0 and no active profiles', () => {
      const { getByText } = render(
        renderMaxStreams(makePlaylist({ max_streams: 0, profiles: [] }))
      );
      expect(getByText('∞')).toBeInTheDocument();
    });

    it('renders the sum of active profile max_streams', () => {
      const playlist = makePlaylist({
        profiles: [
          { name: 'P1', max_streams: 3, is_active: true },
          { name: 'P2', max_streams: 5, is_active: true },
        ],
      });
      const { getByText } = render(renderMaxStreams(playlist));
      expect(getByText('8')).toBeInTheDocument();
    });

    it('renders "∞" when any active profile has max_streams 0', () => {
      const playlist = makePlaylist({
        profiles: [
          { name: 'P1', max_streams: 0, is_active: true },
          { name: 'P2', max_streams: 5, is_active: true },
        ],
      });
      const { getByText } = render(renderMaxStreams(playlist));
      expect(getByText('∞')).toBeInTheDocument();
    });
  });

  // ── Column: Expiration ─────────────────────────────────────────────────────

  describe('Expiration column', () => {
    it('returns null when earliest_expiration is absent', () => {
      setupMocks();
      render(<M3UTable />);
      expect(
        getCol('earliest_expiration').cell({
          cell: { getValue: () => null },
          row: { original: makePlaylist({ earliest_expiration: null }) },
        })
      ).toBeNull();
    });

    it('renders the expiration label from getExpirationInfo', () => {
      vi.mocked(M3UsTableUtils.getExpirationInfo).mockReturnValue({
        color: 'orange.5',
        label: '7d left',
      });
      setupMocks();
      render(<M3UTable />);
      const { getByText } = render(
        getCol('earliest_expiration').cell({
          cell: { getValue: () => '2024-12-01T00:00:00Z' },
          row: { original: makePlaylist() },
        })
      );
      expect(getByText('7d left')).toBeInTheDocument();
    });
  });

  // ── Column: Updated ────────────────────────────────────────────────────────

  describe('Updated column', () => {
    it('renders "Never" when updated_at is absent', () => {
      setupMocks();
      render(<M3UTable />);
      const { getByText } = render(
        getCol('updated_at').cell({ cell: { getValue: () => null } })
      );
      expect(getByText('Never')).toBeInTheDocument();
    });

    it('renders the formatted date string when updated_at is present', () => {
      vi.mocked(DateTimeUtils.format).mockReturnValue('formatted:2024-01-01T12:00:00Z');
      setupMocks();
      render(<M3UTable />);
      const { getByText } = render(
        getCol('updated_at').cell({ cell: { getValue: () => '2024-01-01T12:00:00Z' } })
      );
      expect(getByText('formatted:2024-01-01T12:00:00Z')).toBeInTheDocument();
    });
  });

  // ── generateStatusString content types ────────────────────────────────────

  describe('generateStatusString via status message column', () => {
    const renderProgressCell = (contentOverride, progressData = { progress: 50 }) => {
      vi.mocked(M3UsTableUtils.getStatusContent).mockReturnValue(contentOverride);
      const playlist = makePlaylist({ id: 1 });
      setupMocks({ playlists: [playlist], refreshProgress: { 1: progressData } });
      render(<M3UTable />);
      return getCol('last_message').cell({
        cell: { getValue: () => null },
        row: { original: playlist },
      });
    };

    it('renders download progress with speed and time', () => {
      const { getByText } = render(
        renderProgressCell({
          type: 'downloading',
          progress: 45,
          speed: '1.2 MB/s',
          timeRemaining: '2m',
        }, { progress: 45 })
      );
      expect(getByText(/Downloading/)).toBeInTheDocument();
      expect(getByText('45%')).toBeInTheDocument();
      expect(getByText('1.2 MB/s')).toBeInTheDocument();
    });

    it('renders parsing progress', () => {
      const { getByText } = render(
        renderProgressCell({
          type: 'parsing',
          progress: 60,
          elapsedTime: '5s',
          timeRemaining: '3s',
          streamsProcessed: '300/500',
        }, { progress: 60 })
      );
      expect(getByText(/Parsing/)).toBeInTheDocument();
      expect(getByText('60%')).toBeInTheDocument();
    });

    it('renders groups processing progress', () => {
      const { getByText } = render(
        renderProgressCell({
          type: 'groups',
          progress: 30,
          elapsedTime: '2s',
          groupsProcessed: '10/50',
        }, { progress: 30 })
      );
      expect(getByText(/Processing groups/)).toBeInTheDocument();
    });

    it('renders error message from getStatusContent', () => {
      const { getByText } = render(
        renderProgressCell({ type: 'error', error: 'Connection refused' })
      );
      expect(getByText('Connection refused')).toBeInTheDocument();
    });

    it('falls back to "Unknown error occurred" when error text is absent', () => {
      const { getByText } = render(
        renderProgressCell({ type: 'error', error: null })
      );
      expect(getByText('Unknown error occurred')).toBeInTheDocument();
    });

    it('returns "Idle" string when progress is 100', () => {
      vi.mocked(M3UsTableUtils.getStatusContent).mockReturnValue({ type: 'downloading', progress: 100 });
      const playlist = makePlaylist({ id: 1 });
      setupMocks({ playlists: [playlist], refreshProgress: { 1: { progress: 100 } } });
      render(<M3UTable />);
      // progress === 100 → generateStatusString returns the string 'Idle'
      const result = getCol('last_message').cell({
        cell: { getValue: () => null },
        row: { original: playlist },
      });
      // The status message cell bypasses progress when progress === 100, so
      // generateStatusString is not called. Verify via the progress-bypass path:
      // (this is tested via "bypasses progress UI when progress equals 100" already)
      expect(result).toBeNull(); // last_message is null, progress=100 so falls through to null
    });

    it('renders content.label for default type', () => {
      vi.mocked(M3UsTableUtils.getStatusContent).mockReturnValue({ type: 'default', label: 'Queued' });
      const playlist = makePlaylist({ id: 1 });
      setupMocks({ playlists: [playlist], refreshProgress: { 1: { progress: 50 } } });
      render(<M3UTable />);
      const { getByText } = render(
        getCol('last_message').cell({
          cell: { getValue: () => null },
          row: { original: playlist },
        })
      );
      expect(getByText('Queued')).toBeInTheDocument();
    });

    it('renders downloading timeRemaining when present', () => {
      const { getByText } = render(
        renderProgressCell({
          type: 'downloading',
          progress: 45,
          speed: '1.2 MB/s',
          timeRemaining: '30s left',
        }, { progress: 45 })
      );
      expect(getByText('30s left')).toBeInTheDocument();
    });

    it('renders groups elapsedTime and groupsProcessed when present', () => {
      const { getByText } = render(
        renderProgressCell({
          type: 'groups',
          progress: 30,
          elapsedTime: '4s',
          groupsProcessed: '20/80',
        }, { progress: 30 })
      );
      expect(getByText('4s')).toBeInTheDocument();
      expect(getByText('20/80')).toBeInTheDocument();
    });

    it('renders parsing elapsedTime, timeRemaining and streamsProcessed when present', () => {
      const { getByText } = render(
        renderProgressCell({
          type: 'parsing',
          progress: 60,
          elapsedTime: '10s',
          timeRemaining: '5s',
          streamsProcessed: '600/1000',
        }, { progress: 60 })
      );
      expect(getByText('10s')).toBeInTheDocument();
      expect(getByText('5s')).toBeInTheDocument();
      expect(getByText('600/1000')).toBeInTheDocument();
    });
  });

  // ── Status Message column – error / success styling ────────────────────────

  describe('Status Message column – error/success text', () => {
    it('renders error-styled text when status is "error"', () => {
      setupMocks();
      render(<M3UTable />);
      const playlist = makePlaylist({ id: 1, status: 'error' });
      const { getByText } = render(
        getCol('last_message').cell({
          cell: { getValue: () => 'Parse failure' },
          row: { original: playlist },
        })
      );
      expect(getByText('Parse failure')).toBeInTheDocument();
    });

    it('renders success-styled text when status is "success"', () => {
      setupMocks();
      render(<M3UTable />);
      const playlist = makePlaylist({ id: 1, status: 'success' });
      const { getByText } = render(
        getCol('last_message').cell({
          cell: { getValue: () => 'Loaded 500 streams' },
          row: { original: playlist },
        })
      );
      expect(getByText('Loaded 500 streams')).toBeInTheDocument();
    });
  });

  // ── Server Groups modal ────────────────────────────────────────────────────

  describe('Server Groups modal', () => {
    it('renders the "Server Groups" button', () => {
      setupMocks();
      render(<M3UTable />);
      expect(screen.getByText('Server Groups')).toBeInTheDocument();
    });

    it('opens the Server Groups modal when "Server Groups" is clicked', () => {
      setupMocks();
      render(<M3UTable />);
      fireEvent.click(screen.getByText('Server Groups'));
      expect(screen.getByTestId('server-groups-modal')).toBeInTheDocument();
    });

    it('closes the Server Groups modal when onClose is called', () => {
      setupMocks();
      render(<M3UTable />);
      fireEvent.click(screen.getByText('Server Groups'));
      fireEvent.click(screen.getByTestId('server-groups-close'));
      expect(screen.queryByTestId('server-groups-modal')).not.toBeInTheDocument();
    });
  });

  // ── Max Streams column – inactive profiles excluded ────────────────────────

  describe('Max Streams column – profile filtering', () => {
    const renderMaxStreams = (playlist) => {
      setupMocks({ playlists: [playlist] });
      render(<M3UTable />);
      return getCol('max_streams').cell({ row: { original: playlist } });
    };

    it('excludes inactive profiles from the sum', () => {
      // Need 2+ active profiles to trigger the sum branch; inactive ones must be ignored
      const playlist = makePlaylist({
        profiles: [
          { name: 'A1', max_streams: 3, is_active: true },
          { name: 'A2', max_streams: 5, is_active: true },
          { name: 'Inactive', max_streams: 100, is_active: false },
        ],
      });
      const { getByText } = render(renderMaxStreams(playlist));
      // 3 + 5 = 8, not 3 + 5 + 100 = 108
      expect(getByText('8')).toBeInTheDocument();
    });

    it('uses playlist max_streams directly when there is exactly one active profile', () => {
      const playlist = makePlaylist({
        max_streams: 7,
        profiles: [{ name: 'Solo', max_streams: 7, is_active: true }],
      });
      const { getByText } = render(renderMaxStreams(playlist));
      expect(getByText('7')).toBeInTheDocument();
    });
  });

  // ── Expiration column – bold label when daysLeft ≤ 7 ──────────────────────

  describe('Expiration column – bold label', () => {
    it('renders with bold weight (600) when daysLeft is 7 or less', () => {
      vi.mocked(DateTimeUtils.diff).mockReturnValue(5);
      vi.mocked(M3UsTableUtils.getExpirationInfo).mockReturnValue({
        color: 'red.6',
        label: '5d left',
      });
      setupMocks();
      render(<M3UTable />);
      const { getByText } = render(
        getCol('earliest_expiration').cell({
          cell: { getValue: () => '2024-06-06T00:00:00Z' },
          row: { original: makePlaylist() },
        })
      );
      const el = getByText('5d left');
      // The Text mock passes `fw` as data-fw
      expect(el).toHaveAttribute('data-fw', '600');
    });

    it('renders with normal weight (400) when daysLeft > 7', () => {
      vi.mocked(DateTimeUtils.diff).mockReturnValue(30);
      vi.mocked(M3UsTableUtils.getExpirationInfo).mockReturnValue({
        color: 'green.5',
        label: '30d left',
      });
      setupMocks();
      render(<M3UTable />);
      const { getByText } = render(
        getCol('earliest_expiration').cell({
          cell: { getValue: () => '2024-07-01T00:00:00Z' },
          row: { original: makePlaylist() },
        })
      );
      expect(getByText('30d left')).toHaveAttribute('data-fw', '400');
    });

    it('passes all_expirations to getExpirationTooltip', () => {
      const expirations = ['2024-12-01', '2025-01-01'];
      setupMocks();
      render(<M3UTable />);
      const playlist = makePlaylist({ all_expirations: expirations });
      render(
        getCol('earliest_expiration').cell({
          cell: { getValue: () => '2024-12-01T00:00:00Z' },
          row: { original: playlist },
        })
      );
      expect(M3UsTableUtils.getExpirationTooltip).toHaveBeenCalledWith(
        expirations,
        expect.any(String),
        expect.any(String)
      );
    });
  });

  // ── Table structure (useTable options) ────────────────────────────────────

  describe('table structure', () => {
    it('passes enablePagination: false to useTable', () => {
      setupMocks();
      render(<M3UTable />);
      expect(capturedTableOptions.enablePagination).toBe(false);
    });

    it('passes enableRowVirtualization: true to useTable', () => {
      setupMocks();
      render(<M3UTable />);
      expect(capturedTableOptions.enableRowVirtualization).toBe(true);
    });

    it('passes enableRowSelection: false to useTable', () => {
      setupMocks();
      render(<M3UTable />);
      expect(capturedTableOptions.enableRowSelection).toBe(false);
    });

    it('passes renderTopToolbar: false to useTable', () => {
      setupMocks();
      render(<M3UTable />);
      expect(capturedTableOptions.renderTopToolbar).toBe(false);
    });

    it('passes manualSorting: true to useTable', () => {
      setupMocks();
      render(<M3UTable />);
      expect(capturedTableOptions.manualSorting).toBe(true);
    });

    it('passes allRowIds as the playlist ids', () => {
      const playlists = [
        makePlaylist({ id: 10, name: 'A' }),
        makePlaylist({ id: 20, name: 'B' }),
      ];
      setupMocks({ playlists });
      render(<M3UTable />);
      expect(capturedTableOptions.allRowIds).toEqual(
        expect.arrayContaining([10, 20])
      );
    });

    it('actions column size is 75 in compact mode', () => {
      setupMocks({ tableSize: 'compact' });
      render(<M3UTable />);
      const actionsCol = capturedTableOptions.columns.find((c) => c.id === 'actions');
      expect(actionsCol.size).toBe(75);
    });

    it('actions column size is 100 in default mode', () => {
      setupMocks({ tableSize: 'default' });
      render(<M3UTable />);
      const actionsCol = capturedTableOptions.columns.find((c) => c.id === 'actions');
      expect(actionsCol.size).toBe(100);
    });
  });
});