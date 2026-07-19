import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/logos', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/tables/LogosTableUtils.js', () => ({
  cleanupUnusedLogos: vi.fn(),
  deleteLogo: vi.fn(),
  deleteLogos: vi.fn(),
  generateUsageLabel: vi.fn((names, count) => `${count} channel${count !== 1 ? 's' : ''}`),
  getFilteredLogos: vi.fn(),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../forms/Logo', () => ({
  default: ({ isOpen, onClose, logo, onSuccess }) =>
    isOpen ? (
      <div data-testid="logo-form">
        <span data-testid="logo-form-name">{logo?.name ?? 'new'}</span>
        <button data-testid="logo-form-close" onClick={onClose}>
          Close
        </button>
        <button
          data-testid="logo-form-success-update"
          onClick={() =>
            onSuccess({ type: 'update', logo: { id: 1, name: 'Updated', url: '/x.png', channel_count: 0 } })
          }
        >
          Success Update
        </button>
        <button
          data-testid="logo-form-success-create"
          onClick={() =>
            onSuccess({ type: 'create', logo: { id: 99, name: 'New', url: '/n.png', channel_count: 0 } })
          }
        >
          Success Create
        </button>
        <button data-testid="logo-form-success-null" onClick={() => onSuccess(null)}>
          Success Null
        </button>
        <button
          data-testid="logo-form-success-no-logo"
          onClick={() => onSuccess({ type: 'update', logo: null })}
        >
          Success No Logo
        </button>
      </div>
    ) : null,
}));

vi.mock('../../ConfirmationDialog', () => ({
  default: ({
    opened,
    onClose,
    onConfirm,
    title,
    message,
    confirmLabel,
    cancelLabel,
    loading,
    showDeleteFileOption,
  }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="confirm-title">{title}</div>
        <div data-testid="confirm-message">
          {typeof message === 'string' ? message : 'rich-message'}
        </div>
        <button data-testid="confirm-cancel" onClick={onClose} disabled={loading}>
          {cancelLabel}
        </button>
        <button
          data-testid="confirm-ok"
          onClick={() => onConfirm(false)}
          disabled={loading}
        >
          {confirmLabel}
        </button>
        {showDeleteFileOption && (
          <button
            data-testid="confirm-ok-with-files"
            onClick={() => onConfirm(true)}
            disabled={loading}
          >
            Also Delete Files
          </button>
        )}
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
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, leftSection, disabled, loading, color, variant }) => (
    <button
      data-testid="button"
      onClick={onClick}
      disabled={disabled || loading}
      data-color={color}
      data-variant={variant}
    >
      {leftSection}
      {children}
    </button>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Checkbox: ({ checked, onChange, label, disabled }) => (
    <label>
      <input
        data-testid="checkbox"
        type="checkbox"
        checked={checked ?? false}
        onChange={onChange}
        disabled={disabled}
        readOnly={!onChange}
      />
      {label}
    </label>
  ),
  Group: ({ children, style }) => <div style={style}>{children}</div>,
  Image: ({ src, alt, fallbackSrc, style, onMouseEnter, onMouseLeave }) => (
    <img
      src={src}
      alt={alt}
      data-fallback={fallbackSrc}
      style={style}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    />
  ),
  LoadingOverlay: ({ visible }) => (visible ? <div data-testid="loading-overlay" /> : null),
  NativeSelect: ({ value, data, onChange, style }) => (
    <select data-testid="native-select" value={value} onChange={onChange} style={style}>
      {data.map((d) => (
        <option key={d} value={d}>
          {d}
        </option>
      ))}
    </select>
  ),
  Pagination: ({ total, value, onChange, style }) => (
    <div data-testid="pagination" style={style}>
      <button
        data-testid="pagination-prev"
        onClick={() => onChange(value - 1)}
        disabled={value <= 1}
      >
        Prev
      </button>
      <span data-testid="pagination-current">{value}</span>
      <button
        data-testid="pagination-next"
        onClick={() => onChange(value + 1)}
        disabled={value >= total}
      >
        Next
      </button>
    </div>
  ),
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Select: ({ value, onChange, data, style }) => (
    <select
      data-testid="usage-select"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={style}
    >
      {data.map((d) => (
        <option key={d.value} value={d.value}>
          {d.label}
        </option>
      ))}
    </select>
  ),
  Stack: ({ children, style }) => <div style={style}>{children}</div>,
  Text: ({ children, size, c, style }) => (
    <span data-size={size} data-color={c} style={style}>
      {children}
    </span>
  ),
  TextInput: ({ value, onChange, placeholder, style }) => (
    <input
      data-testid="name-filter-input"
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      style={style}
    />
  ),
  Tooltip: ({ children }) => <div>{children}</div>,
  useMantineTheme: vi.fn(() => ({
    tailwind: {
      yellow: { 3: '#fbbf24' },
      red: { 6: '#dc2626' },
      green: { 5: '#22c55e' },
    },
  })),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ExternalLink: () => <svg data-testid="icon-external-link" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
  Trash: () => <svg data-testid="icon-trash" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useLogosStore from '../../../store/logos';
import useWarningsStore from '../../../store/warnings';
import useLocalStorage from '../../../hooks/useLocalStorage';
import { showNotification } from '../../../utils/notificationUtils.js';
import * as LogosTableUtils from '../../../utils/tables/LogosTableUtils.js';
import { useTable } from '../CustomTable';
import LogosTable from '../LogosTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeLogo = (overrides = {}) => ({
  id: 1,
  name: 'Test Logo',
  url: 'http://example.com/logo.png',
  cache_url: '/cached/logo.png',
  channel_count: 0,
  channel_names: [],
  is_used: false,
  ...overrides,
});

let capturedTableOptions = null;

const setupMocks = ({
  logos = { 1: makeLogo() },
  storeLoading = false,
  tableSize = 'default',
} = {}) => {
  const mockFetchAllLogos = vi.fn().mockResolvedValue(undefined);
  const mockUpdateLogo = vi.fn();
  const mockAddLogo = vi.fn();

  vi.mocked(useLogosStore).mockImplementation((sel) => {
    const state = {
      logos,
      fetchAllLogos: mockFetchAllLogos,
      updateLogo: mockUpdateLogo,
      addLogo: mockAddLogo,
      isLoading: storeLoading,
    };
    return typeof sel === 'function' ? sel(state) : state;
  });

  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({ suppressWarning: vi.fn(), isWarningSuppressed: vi.fn(() => false) })
  );

  vi.mocked(useLocalStorage).mockImplementation((key, defaultVal) => {
    if (key === 'table-size') return [tableSize, vi.fn()];
    if (key === 'logos-page-size') return [25, vi.fn()];
    return [defaultVal, vi.fn()];
  });

  vi.mocked(LogosTableUtils.getFilteredLogos).mockReturnValue(Object.values(logos));

  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return {
      getRowModel: () => ({ rows: [] }),
      getHeaderGroups: () => [],
      setSelectedTableIds: vi.fn(),
    };
  });

  return { mockFetchAllLogos, mockUpdateLogo, mockAddLogo };
};

// ── Column helpers ─────────────────────────────────────────────────────────────
const getActionsCell = (logo) => {
  const col = capturedTableOptions.columns.find((c) => c.id === 'actions');
  return col.cell({ row: { id: logo.id, original: logo } });
};

const getSelectCell = (logo) => {
  const col = capturedTableOptions.columns.find((c) => c.id === 'select');
  return col.cell({ row: { id: logo.id, original: logo } });
};

const getSelectHeader = () => {
  const col = capturedTableOptions.columns.find((c) => c.id === 'select');
  return col.header({ table: {} });
};

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('LogosTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
    vi.mocked(LogosTableUtils.deleteLogo).mockResolvedValue(undefined);
    vi.mocked(LogosTableUtils.deleteLogos).mockResolvedValue(undefined);
    vi.mocked(LogosTableUtils.cleanupUnusedLogos).mockResolvedValue({
      deleted_count: 3,
      local_files_deleted: 0,
    });
    window.open = vi.fn();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the name filter input', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByPlaceholderText('Filter by name...')).toBeInTheDocument();
    });

    it('renders the usage filter select with all options', () => {
      setupMocks();
      render(<LogosTable />);
      const select = screen.getByTestId('usage-select');
      expect(select).toBeInTheDocument();
      expect(select).toHaveValue('all');
    });

    it('renders the "Add Logo" button', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByText('Add Logo')).toBeInTheDocument();
    });

    it('"Delete" button is disabled when no rows are selected', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByText('Delete').closest('button')).toBeDisabled();
    });

    it('"Cleanup Unused" button is disabled when there are no unused logos', () => {
      setupMocks({ logos: { 1: makeLogo({ is_used: true }) } });
      render(<LogosTable />);
      expect(screen.getByText(/Cleanup Unused/).closest('button')).toBeDisabled();
    });

    it('"Cleanup Unused" button shows count and is enabled when unused logos exist', () => {
      setupMocks({
        logos: {
          1: makeLogo({ id: 1, is_used: false }),
          2: makeLogo({ id: 2, name: 'Logo 2', is_used: false }),
        },
      });
      render(<LogosTable />);
      const btn = screen.getByText(/Cleanup Unused/).closest('button');
      expect(btn).not.toBeDisabled();
      expect(btn).toHaveTextContent('(2)');
    });

    it('renders the custom table', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('renders loading overlay when store is loading', () => {
      setupMocks({ storeLoading: true });
      render(<LogosTable />);
      expect(screen.getByTestId('loading-overlay')).toBeInTheDocument();
    });

    it('does not render loading overlay when not loading', () => {
      setupMocks({ storeLoading: false });
      render(<LogosTable />);
      expect(screen.queryByTestId('loading-overlay')).not.toBeInTheDocument();
    });

    it('renders pagination controls', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByTestId('pagination')).toBeInTheDocument();
    });

    it('renders the page size selector', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByTestId('native-select')).toBeInTheDocument();
    });

    it('shows "1 to 1 of 1" pagination string for a single logo', () => {
      setupMocks({ logos: { 1: makeLogo() } });
      render(<LogosTable />);
      expect(screen.getByText('1 to 1 of 1')).toBeInTheDocument();
    });

    it('"Prev" pagination button is disabled on first page', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByTestId('pagination-prev')).toBeDisabled();
    });

    it('"Next" pagination button is disabled when on the only page', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByTestId('pagination-next')).toBeDisabled();
    });
  });

  // ── Add Logo ───────────────────────────────────────────────────────────────

  describe('Add Logo', () => {
    it('opens logo form with no selected logo when "Add Logo" is clicked', () => {
      setupMocks();
      render(<LogosTable />);
      fireEvent.click(screen.getByText('Add Logo'));
      expect(screen.getByTestId('logo-form')).toBeInTheDocument();
      expect(screen.getByTestId('logo-form-name')).toHaveTextContent('new');
    });

    it('closes the logo form when onClose is called', () => {
      setupMocks();
      render(<LogosTable />);
      fireEvent.click(screen.getByText('Add Logo'));
      fireEvent.click(screen.getByTestId('logo-form-close'));
      expect(screen.queryByTestId('logo-form')).not.toBeInTheDocument();
    });
  });

  // ── Edit Logo ──────────────────────────────────────────────────────────────

  describe('Edit Logo', () => {
    it('opens the logo form populated with the logo when edit action is clicked', () => {
      const logo = makeLogo({ name: 'My Logo' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { getByTestId: getActionIcon } = render(getActionsCell(logo));
      fireEvent.click(getActionIcon('icon-square-pen').closest('button'));

      expect(screen.getByTestId('logo-form')).toBeInTheDocument();
      expect(screen.getByTestId('logo-form-name')).toHaveTextContent('My Logo');
    });

    it('closes the logo form when onClose is called after edit', () => {
      const logo = makeLogo();
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { getByTestId: getActionIcon } = render(getActionsCell(logo));
      fireEvent.click(getActionIcon('icon-square-pen').closest('button'));
      fireEvent.click(screen.getByTestId('logo-form-close'));

      expect(screen.queryByTestId('logo-form')).not.toBeInTheDocument();
    });
  });

  // ── onLogoSuccess ──────────────────────────────────────────────────────────

  describe('onLogoSuccess', () => {
    it('calls updateLogo when result type is "update"', () => {
      const { mockUpdateLogo } = setupMocks();
      render(<LogosTable />);
      fireEvent.click(screen.getByText('Add Logo'));
      fireEvent.click(screen.getByTestId('logo-form-success-update'));
      expect(mockUpdateLogo).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1, name: 'Updated' })
      );
    });

    it('calls addLogo when result type is "create"', () => {
      const { mockAddLogo } = setupMocks();
      render(<LogosTable />);
      fireEvent.click(screen.getByText('Add Logo'));
      fireEvent.click(screen.getByTestId('logo-form-success-create'));
      expect(mockAddLogo).toHaveBeenCalledWith(
        expect.objectContaining({ id: 99, name: 'New' })
      );
    });

    it('calls fetchAllLogos when the logo is missing from the result', async () => {
      const { mockFetchAllLogos } = setupMocks();
      render(<LogosTable />);
      fireEvent.click(screen.getByText('Add Logo'));
      fireEvent.click(screen.getByTestId('logo-form-success-no-logo'));
      await waitFor(() => expect(mockFetchAllLogos).toHaveBeenCalled());
    });

    it('does nothing when result is null', () => {
      const { mockUpdateLogo, mockAddLogo, mockFetchAllLogos } = setupMocks();
      render(<LogosTable />);
      fireEvent.click(screen.getByText('Add Logo'));
      fireEvent.click(screen.getByTestId('logo-form-success-null'));
      expect(mockUpdateLogo).not.toHaveBeenCalled();
      expect(mockAddLogo).not.toHaveBeenCalled();
      expect(mockFetchAllLogos).not.toHaveBeenCalled();
    });
  });

  // ── Delete single logo ─────────────────────────────────────────────────────

  describe('Delete single logo', () => {
    it('opens "Delete Logo" confirmation dialog when delete action icon is clicked', () => {
      const logo = makeLogo();
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));

      expect(screen.getByTestId('confirm-title')).toHaveTextContent('Delete Logo');
    });

    it('calls deleteLogo with the logo id on confirm', async () => {
      const logo = makeLogo();
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(LogosTableUtils.deleteLogo).toHaveBeenCalledWith(logo.id, false)
      );
    });

    it('calls fetchAllLogos after a successful delete', async () => {
      const logo = makeLogo();
      const { mockFetchAllLogos } = setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => expect(mockFetchAllLogos).toHaveBeenCalled());
    });

    it('shows a success notification after delete', async () => {
      const logo = makeLogo();
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green', title: 'Success' })
        )
      );
    });

    it('shows an error notification when deleteLogo rejects', async () => {
      vi.mocked(LogosTableUtils.deleteLogo).mockRejectedValue(new Error('fail'));
      const logo = makeLogo();
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        )
      );
    });

    it('closes the dialog after confirming delete', async () => {
      const logo = makeLogo();
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument()
      );
    });

    it('closes the dialog on cancel without calling deleteLogo', () => {
      const logo = makeLogo();
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument();
      expect(LogosTableUtils.deleteLogo).not.toHaveBeenCalled();
    });

    it('shows "Also Delete Files" option for /data/logos URLs', () => {
      const logo = makeLogo({ url: '/data/logos/test.png' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));

      expect(screen.getByTestId('confirm-ok-with-files')).toBeInTheDocument();
    });

    it('does not show "Also Delete Files" option for external URLs', () => {
      const logo = makeLogo({ url: 'http://example.com/logo.png' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));

      expect(screen.queryByTestId('confirm-ok-with-files')).not.toBeInTheDocument();
    });

    it('calls deleteLogo with deleteFile=true when confirmed with file deletion', async () => {
      const logo = makeLogo({ url: '/data/logos/test.png' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { container: actionsContainer } = render(getActionsCell(logo));
      fireEvent.click(within(actionsContainer).getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok-with-files'));

      await waitFor(() =>
        expect(LogosTableUtils.deleteLogo).toHaveBeenCalledWith(logo.id, true)
      );
    });
  });

  // ── Bulk delete ────────────────────────────────────────────────────────────

  describe('Bulk delete', () => {
    it('"Delete" button is disabled when no rows are selected', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByText('Delete').closest('button')).toBeDisabled();
    });

    it('enables "Delete" button and shows count after a row is selected', () => {
      const logo = makeLogo({ id: 1 });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { getByTestId: getCheckbox } = render(getSelectCell(logo));
      fireEvent.click(getCheckbox('checkbox'));

      expect(screen.getByText(/Delete \(1\)/).closest('button')).not.toBeDisabled();
    });

    it('opens "Delete Multiple Logos" dialog after selecting rows and clicking Delete', () => {
      const logo = makeLogo({ id: 1 });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { getByTestId: getCheckbox } = render(getSelectCell(logo));
      fireEvent.click(getCheckbox('checkbox'));
      fireEvent.click(screen.getByText(/Delete \(1\)/));

      expect(screen.getByTestId('confirm-title')).toHaveTextContent('Delete Multiple Logos');
    });

    it('calls deleteLogos with selected ids on confirm', async () => {
      const logo = makeLogo({ id: 1 });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { getByTestId: getCheckbox } = render(getSelectCell(logo));
      fireEvent.click(getCheckbox('checkbox'));
      fireEvent.click(screen.getByText(/Delete \(1\)/));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(LogosTableUtils.deleteLogos).toHaveBeenCalledWith([1], false)
      );
    });

    it('calls fetchAllLogos after bulk delete', async () => {
      const logo = makeLogo({ id: 1 });
      const { mockFetchAllLogos } = setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { getByTestId: getCheckbox } = render(getSelectCell(logo));
      fireEvent.click(getCheckbox('checkbox'));
      fireEvent.click(screen.getByText(/Delete \(1\)/));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => expect(mockFetchAllLogos).toHaveBeenCalled());
    });

    it('shows success notification after bulk delete', async () => {
      const logo = makeLogo({ id: 1 });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { getByTestId: getCheckbox } = render(getSelectCell(logo));
      fireEvent.click(getCheckbox('checkbox'));
      fireEvent.click(screen.getByText(/Delete \(1\)/));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green' })
        )
      );
    });

    it('shows error notification when deleteLogos rejects', async () => {
      vi.mocked(LogosTableUtils.deleteLogos).mockRejectedValue(new Error('fail'));
      const logo = makeLogo({ id: 1 });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const { getByTestId: getCheckbox } = render(getSelectCell(logo));
      fireEvent.click(getCheckbox('checkbox'));
      fireEvent.click(screen.getByText(/Delete \(1\)/));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        )
      );
    });

    it('select-all header checkbox selects all logos', () => {
      const logos = {
        1: makeLogo({ id: 1 }),
        2: makeLogo({ id: 2, name: 'Logo 2' }),
      };
      setupMocks({ logos });
      render(<LogosTable />);

      const { getByTestId: getHeaderCheckbox } = render(getSelectHeader());
      fireEvent.click(getHeaderCheckbox('checkbox'));

      expect(screen.getByText(/Delete \(2\)/).closest('button')).not.toBeDisabled();
    });
  });

  // ── Cleanup unused ─────────────────────────────────────────────────────────

  describe('Cleanup unused', () => {
    const withUnused = () => ({ logos: { 1: makeLogo({ is_used: false }) } });

    it('opens the cleanup confirmation dialog when the button is clicked', () => {
      setupMocks(withUnused());
      render(<LogosTable />);
      fireEvent.click(screen.getByText(/Cleanup Unused/).closest('button'));
      expect(screen.getByTestId('confirm-title')).toHaveTextContent('Cleanup Unused Logos');
    });

    it('calls cleanupUnusedLogos(false) on confirm', async () => {
      setupMocks(withUnused());
      render(<LogosTable />);
      fireEvent.click(screen.getByText(/Cleanup Unused/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(LogosTableUtils.cleanupUnusedLogos).toHaveBeenCalledWith(false)
      );
    });

    it('calls cleanupUnusedLogos(true) when confirmed with file deletion', async () => {
      setupMocks(withUnused());
      render(<LogosTable />);
      fireEvent.click(screen.getByText(/Cleanup Unused/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok-with-files'));
      await waitFor(() =>
        expect(LogosTableUtils.cleanupUnusedLogos).toHaveBeenCalledWith(true)
      );
    });

    it('calls fetchAllLogos after successful cleanup', async () => {
      const { mockFetchAllLogos } = setupMocks(withUnused());
      render(<LogosTable />);
      fireEvent.click(screen.getByText(/Cleanup Unused/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => expect(mockFetchAllLogos).toHaveBeenCalled());
    });

    it('shows "Cleanup Complete" success notification with deleted count', async () => {
      vi.mocked(LogosTableUtils.cleanupUnusedLogos).mockResolvedValue({
        deleted_count: 3,
        local_files_deleted: 0,
      });
      setupMocks(withUnused());
      render(<LogosTable />);
      fireEvent.click(screen.getByText(/Cleanup Unused/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            color: 'green',
            title: 'Cleanup Complete',
            message: expect.stringContaining('3'),
          })
        )
      );
    });

    it('includes local file count in success notification when files were deleted', async () => {
      vi.mocked(LogosTableUtils.cleanupUnusedLogos).mockResolvedValue({
        deleted_count: 5,
        local_files_deleted: 2,
      });
      setupMocks(withUnused());
      render(<LogosTable />);
      fireEvent.click(screen.getByText(/Cleanup Unused/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            message: expect.stringContaining('2 local files'),
          })
        )
      );
    });

    it('shows "Cleanup Failed" error notification when cleanup rejects', async () => {
      vi.mocked(LogosTableUtils.cleanupUnusedLogos).mockRejectedValue(new Error('Server error'));
      setupMocks(withUnused());
      render(<LogosTable />);
      fireEvent.click(screen.getByText(/Cleanup Unused/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red', title: 'Cleanup Failed' })
        )
      );
    });

    it('closes the cleanup dialog on cancel', () => {
      setupMocks(withUnused());
      render(<LogosTable />);
      fireEvent.click(screen.getByText(/Cleanup Unused/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));
      expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument();
    });
  });

  // ── Name filter (debounced) ────────────────────────────────────────────────

  describe('name filter (debounced)', () => {
    it('reflects the typed value in the filter input immediately', () => {
      setupMocks();
      render(<LogosTable />);
      const input = screen.getByPlaceholderText('Filter by name...');
      fireEvent.change(input, { target: { value: 'sports' } });
      expect(input).toHaveValue('sports');
    });

    it('does not pass filter value to getFilteredLogos immediately after typing', () => {
      setupMocks();
      render(<LogosTable />);
      vi.mocked(LogosTableUtils.getFilteredLogos).mockClear();

      fireEvent.change(screen.getByPlaceholderText('Filter by name...'), {
        target: { value: 'sports' },
      });

      expect(LogosTableUtils.getFilteredLogos).not.toHaveBeenCalledWith(
        expect.anything(),
        'sports',
        expect.anything()
      );
    });

    it('passes filter value to getFilteredLogos after the 300ms debounce fires', async () => {
      setupMocks();
      render(<LogosTable />);
      vi.mocked(LogosTableUtils.getFilteredLogos).mockClear();

      fireEvent.change(screen.getByPlaceholderText('Filter by name...'), {
        target: { value: 'sports' },
      });

      await waitFor(
        () =>
          expect(LogosTableUtils.getFilteredLogos).toHaveBeenCalledWith(
            expect.anything(),
            'sports',
            expect.anything()
          ),
        { timeout: 600 }
      );
    });
  });

  // ── Usage filter ───────────────────────────────────────────────────────────

  describe('usage filter', () => {
    it('calls getFilteredLogos with "used" when filter is changed to "Used only"', () => {
      const logos = { 1: makeLogo() };
      setupMocks({ logos });
      render(<LogosTable />);
      vi.mocked(LogosTableUtils.getFilteredLogos).mockClear();

      fireEvent.change(screen.getByTestId('usage-select'), { target: { value: 'used' } });

      expect(LogosTableUtils.getFilteredLogos).toHaveBeenCalledWith(logos, '', 'used');
    });

    it('calls getFilteredLogos with "unused" when filter is changed to "Unused only"', () => {
      const logos = { 1: makeLogo() };
      setupMocks({ logos });
      render(<LogosTable />);
      vi.mocked(LogosTableUtils.getFilteredLogos).mockClear();

      fireEvent.change(screen.getByTestId('usage-select'), { target: { value: 'unused' } });

      expect(LogosTableUtils.getFilteredLogos).toHaveBeenCalledWith(logos, '', 'unused');
    });
  });

  // ── Column cell renderers ──────────────────────────────────────────────────

  describe('column cell renderers', () => {
    it('renders the preview image with cache_url as src and /logo.png as fallback', () => {
      const logo = makeLogo({ cache_url: '/cached/test.png', name: 'My Logo' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const col = capturedTableOptions.columns.find((c) => c.accessorKey === 'cache_url');
      const { getByAltText } = render(
        col.cell({ getValue: () => logo.cache_url, row: { original: logo } })
      );

      expect(getByAltText('My Logo')).toHaveAttribute('src', '/cached/test.png');
      expect(getByAltText('My Logo')).toHaveAttribute('data-fallback', '/logo.png');
    });

    it('renders the logo name in the name column', () => {
      const logo = makeLogo({ name: 'Channel 4 Logo' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const col = capturedTableOptions.columns.find((c) => c.accessorKey === 'name');
      const { getByText } = render(col.cell({ getValue: () => logo.name }));
      expect(getByText('Channel 4 Logo')).toBeInTheDocument();
    });

    it('renders an "Unused" badge when channel_count is 0', () => {
      const logo = makeLogo({ channel_count: 0 });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const col = capturedTableOptions.columns.find((c) => c.accessorKey === 'channel_count');
      const { getByText } = render(col.cell({ getValue: () => 0, row: { original: logo } }));
      expect(getByText('Unused')).toBeInTheDocument();
    });

    it('renders a usage label badge when channel_count is > 0', () => {
      const logo = makeLogo({ channel_count: 2, channel_names: ['Channel: HBO', 'Channel: CNN'] });
      vi.mocked(LogosTableUtils.generateUsageLabel).mockReturnValue('2 channels');
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const col = capturedTableOptions.columns.find((c) => c.accessorKey === 'channel_count');
      const { getByText } = render(col.cell({ getValue: () => 2, row: { original: logo } }));
      expect(getByText('2 channels')).toBeInTheDocument();
    });

    it('renders the URL text in the URL column', () => {
      const logo = makeLogo({ url: 'http://example.com/logo.png' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const col = capturedTableOptions.columns.find((c) => c.accessorKey === 'url');
      const { getByText } = render(col.cell({ getValue: () => logo.url }));
      expect(getByText('http://example.com/logo.png')).toBeInTheDocument();
    });

    it('renders external link icon for http URLs', () => {
      const logo = makeLogo({ url: 'http://example.com/logo.png' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const col = capturedTableOptions.columns.find((c) => c.accessorKey === 'url');
      const { getByTestId } = render(col.cell({ getValue: () => logo.url }));
      expect(getByTestId('icon-external-link')).toBeInTheDocument();
    });

    it('does not render external link icon for non-http URLs', () => {
      const logo = makeLogo({ url: '/data/logos/test.png' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const col = capturedTableOptions.columns.find((c) => c.accessorKey === 'url');
      const { queryByTestId } = render(col.cell({ getValue: () => logo.url }));
      expect(queryByTestId('icon-external-link')).not.toBeInTheDocument();
    });

    it('opens URL in a new tab when external link button is clicked', () => {
      const logo = makeLogo({ url: 'http://example.com/logo.png' });
      setupMocks({ logos: { 1: logo } });
      render(<LogosTable />);

      const col = capturedTableOptions.columns.find((c) => c.accessorKey === 'url');
      const { getByTestId } = render(col.cell({ getValue: () => logo.url }));
      fireEvent.click(getByTestId('icon-external-link').closest('button'));

      expect(window.open).toHaveBeenCalledWith('http://example.com/logo.png', '_blank');
    });
  });

  // ── Pagination controls ────────────────────────────────────────────────────

  describe('pagination controls', () => {
    it('updates pagination when page size is changed', () => {
      setupMocks();
      render(<LogosTable />);
      fireEvent.change(screen.getByTestId('native-select'), { target: { value: '50' } });
      expect(screen.getByTestId('pagination')).toBeInTheDocument();
    });

    it('shows "Page Size" label', () => {
      setupMocks();
      render(<LogosTable />);
      expect(screen.getByText('Page Size')).toBeInTheDocument();
    });
  });
});