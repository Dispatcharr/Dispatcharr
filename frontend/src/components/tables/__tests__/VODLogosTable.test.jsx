import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/vodLogos', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => ['default', vi.fn()]),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../ConfirmationDialog', () => ({
  default: ({ opened, onClose, onConfirm, title, loading, confirmLabel, cancelLabel }) =>
    opened ? (
      <div data-testid="confirm-dialog">
        <span data-testid="confirm-title">{title}</span>
        <button
          data-testid="confirm-ok"
          onClick={() => onConfirm(false)}
          disabled={loading}
        >
          {confirmLabel}
        </button>
        <button data-testid="confirm-cancel" onClick={onClose}>
          {cancelLabel}
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
    <button
      data-testid="action-icon"
      data-color={color}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, leftSection, disabled, loading }) => (
    <button
      data-testid="button"
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={String(!!loading)}
    >
      {leftSection}
      {children}
    </button>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Checkbox: ({ checked, indeterminate, onChange }) => (
    <input
      type="checkbox"
      data-testid="checkbox"
      checked={!!checked}
      data-indeterminate={String(!!indeterminate)}
      onChange={onChange}
    />
  ),
  Group: ({ children, style }) => (
    <div style={style}>{children}</div>
  ),
  Image: ({ src, alt, fallbackSrc }) => (
    <img src={src} alt={alt} data-fallback={fallbackSrc} />
  ),
  LoadingOverlay: ({ visible }) =>
    visible ? <div data-testid="loading-overlay" /> : null,
  NativeSelect: ({ value, data, onChange }) => (
    <select data-testid="page-size-select" value={value} onChange={onChange}>
      {(data || []).map((d) => (
        <option key={d} value={d}>
          {d}
        </option>
      ))}
    </select>
  ),
  Pagination: ({ total, value, onChange }) => (
    <div data-testid="pagination">
      <button
        data-testid="pagination-prev"
        onClick={() => onChange(value - 1)}
        disabled={value <= 1}
      >
        Prev
      </button>
      <span data-testid="pagination-page">{value}</span>
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
  Select: ({ value, onChange, data }) => (
    <select
      data-testid="usage-filter"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {(data || []).map((d) => (
        <option key={d.value} value={d.value}>
          {d.label}
        </option>
      ))}
    </select>
  ),
  Stack: ({ children, style }) => <div style={style}>{children}</div>,
  Text: ({ children, style, name }) => (
    <span data-testid="text" data-name={name} style={style}>
      {children}
    </span>
  ),
  TextInput: ({ value, onChange, placeholder }) => (
    <input
      data-testid="name-filter"
      value={value}
      onChange={onChange}
      placeholder={placeholder}
    />
  ),
  Tooltip: ({ children, label }) => (
    <div data-tooltip={label}>{children}</div>
  ),
  useMantineTheme: vi.fn(() => ({
    tailwind: {
      red: { 6: '#dc2626' },
    },
  })),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ExternalLink: () => <svg data-testid="icon-external-link" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  Trash: () => <svg data-testid="icon-trash" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useVODLogosStore from '../../../store/vodLogos';
import { useTable } from '../CustomTable';
import { showNotification } from '../../../utils/notificationUtils.js';
import VODLogosTable from '../VODLogosTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeLogo = (overrides = {}) => ({
  id: 1,
  name: 'Test Logo',
  url: 'http://example.com/logo.png',
  cache_url: '/cache/logo.png',
  movie_count: 0,
  series_count: 0,
  item_names: [],
  ...overrides,
});

let capturedTableOptions = null;

const setupMocks = ({
  logos = [makeLogo()],
  totalCount = 1,
  isLoading = false,
  unusedCount = 0,
} = {}) => {
  const fetchVODLogos = vi.fn().mockResolvedValue(undefined);
  const deleteVODLogo = vi.fn().mockResolvedValue(undefined);
  const deleteVODLogos = vi.fn().mockResolvedValue(undefined);
  const cleanupUnusedVODLogos = vi.fn().mockResolvedValue({ deleted_count: 3 });
  const getUnusedLogosCount = vi.fn().mockResolvedValue(unusedCount);

  vi.mocked(useVODLogosStore).mockReturnValue({
    logos,
    totalCount,
    isLoading,
    fetchVODLogos,
    deleteVODLogo,
    deleteVODLogos,
    cleanupUnusedVODLogos,
    getUnusedLogosCount,
  });

  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return {
      getRowModel: () => ({ rows: [] }),
      getHeaderGroups: () => [],
      setSelectedTableIds: vi.fn(),
    };
  });

  return {
    fetchVODLogos,
    deleteVODLogo,
    deleteVODLogos,
    cleanupUnusedVODLogos,
    getUnusedLogosCount,
  };
};

const getCol = (key) =>
  capturedTableOptions.columns.find(
    (c) => c.accessorKey === key || c.id === key
  );

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('VODLogosTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the name filter input', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(screen.getByTestId('name-filter')).toBeInTheDocument();
    });

    it('renders the usage filter select', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(screen.getByTestId('usage-filter')).toBeInTheDocument();
    });

    it('renders the custom table', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('renders pagination controls', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(screen.getByTestId('pagination')).toBeInTheDocument();
      expect(screen.getByTestId('page-size-select')).toBeInTheDocument();
    });

    it('does not render confirmation dialogs on initial load', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    it('renders "Cleanup Unused" button', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(screen.getByText(/Cleanup Unused/)).toBeInTheDocument();
    });

    it('renders "Delete" button', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(screen.getByText(/^Delete/)).toBeInTheDocument();
    });

    it('shows LoadingOverlay when isLoading is true', () => {
      setupMocks({ isLoading: true });
      render(<VODLogosTable />);
      expect(screen.getByTestId('loading-overlay')).toBeInTheDocument();
    });

    it('does not show LoadingOverlay when isLoading is false', () => {
      setupMocks({ isLoading: false });
      render(<VODLogosTable />);
      expect(screen.queryByTestId('loading-overlay')).not.toBeInTheDocument();
    });

    it('renders pagination string on initial load', () => {
      setupMocks({ totalCount: 50 });
      render(<VODLogosTable />);
      expect(screen.getByText('1 to 25 of 50')).toBeInTheDocument();
    });
  });

  // ── Initial data fetch ─────────────────────────────────────────────────────

  describe('initial data fetch', () => {
    it('calls fetchVODLogos with default params on mount', () => {
      const { fetchVODLogos } = setupMocks();
      render(<VODLogosTable />);
      expect(fetchVODLogos).toHaveBeenCalledWith({
        page: 1,
        page_size: 25,
        name: '',
        usage: undefined,
      });
    });

    it('calls getUnusedLogosCount on mount', () => {
      const { getUnusedLogosCount } = setupMocks();
      render(<VODLogosTable />);
      expect(getUnusedLogosCount).toHaveBeenCalled();
    });

    it('"Cleanup Unused" button shows count and becomes enabled when unusedCount resolves > 0', async () => {
      setupMocks({ unusedCount: 7 });
      render(<VODLogosTable />);
      await waitFor(() => {
        expect(screen.getByText(/Cleanup Unused \(7\)/)).toBeInTheDocument();
        expect(
          screen.getByText(/Cleanup Unused \(7\)/).closest('button')
        ).not.toBeDisabled();
      });
    });
  });

  // ── Name filter ────────────────────────────────────────────────────────────

  describe('name filter', () => {
    it('calls fetchVODLogos with updated name when filter changes', () => {
      const { fetchVODLogos } = setupMocks();
      render(<VODLogosTable />);
      fireEvent.change(screen.getByTestId('name-filter'), {
        target: { value: 'HBO' },
      });
      expect(fetchVODLogos).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'HBO', page: 1 })
      );
    });

    it('passes name: "" when filter is cleared', () => {
      const { fetchVODLogos } = setupMocks();
      render(<VODLogosTable />);
      fireEvent.change(screen.getByTestId('name-filter'), {
        target: { value: 'ESPN' },
      });
      fireEvent.change(screen.getByTestId('name-filter'), {
        target: { value: '' },
      });
      expect(fetchVODLogos).toHaveBeenLastCalledWith(
        expect.objectContaining({ name: '' })
      );
    });
  });

  // ── Usage filter ───────────────────────────────────────────────────────────

  describe('usage filter', () => {
    it('passes usage: undefined when filter is "all"', () => {
      const { fetchVODLogos } = setupMocks();
      render(<VODLogosTable />);
      expect(fetchVODLogos).toHaveBeenCalledWith(
        expect.objectContaining({ usage: undefined })
      );
    });

    it('passes usage: "used" when filter changes to "used"', () => {
      const { fetchVODLogos } = setupMocks();
      render(<VODLogosTable />);
      fireEvent.change(screen.getByTestId('usage-filter'), {
        target: { value: 'used' },
      });
      expect(fetchVODLogos).toHaveBeenCalledWith(
        expect.objectContaining({ usage: 'used' })
      );
    });

    it('passes usage: "unused" when filter changes to "unused"', () => {
      const { fetchVODLogos } = setupMocks();
      render(<VODLogosTable />);
      fireEvent.change(screen.getByTestId('usage-filter'), {
        target: { value: 'unused' },
      });
      expect(fetchVODLogos).toHaveBeenCalledWith(
        expect.objectContaining({ usage: 'unused' })
      );
    });
  });

  // ── "Cleanup Unused" button ────────────────────────────────────────────────

  describe('"Cleanup Unused" button', () => {
    it('is disabled when unusedLogosCount is 0', () => {
      setupMocks({ unusedCount: 0 });
      render(<VODLogosTable />);
      expect(
        screen.getByText(/Cleanup Unused/).closest('button')
      ).toBeDisabled();
    });

    it('opens cleanup dialog when clicked', async () => {
      setupMocks({ unusedCount: 4 });
      render(<VODLogosTable />);
      await waitFor(() =>
        expect(
          screen.getByText(/Cleanup Unused \(4\)/).closest('button')
        ).not.toBeDisabled()
      );
      fireEvent.click(
        screen.getByText(/Cleanup Unused \(4\)/).closest('button')
      );
      expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
      expect(screen.getByTestId('confirm-title')).toHaveTextContent(
        'Cleanup Unused Logos'
      );
    });

    it('calls cleanupUnusedVODLogos when confirmed', async () => {
      const { cleanupUnusedVODLogos } = setupMocks({ unusedCount: 4 });
      render(<VODLogosTable />);
      await waitFor(() =>
        expect(
          screen.getByText(/Cleanup Unused \(4\)/).closest('button')
        ).not.toBeDisabled()
      );
      fireEvent.click(
        screen.getByText(/Cleanup Unused \(4\)/).closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(cleanupUnusedVODLogos).toHaveBeenCalled()
      );
    });

    it('shows success notification after cleanup', async () => {
      setupMocks({ unusedCount: 4 });
      render(<VODLogosTable />);
      await waitFor(() =>
        expect(
          screen.getByText(/Cleanup Unused \(4\)/).closest('button')
        ).not.toBeDisabled()
      );
      fireEvent.click(
        screen.getByText(/Cleanup Unused \(4\)/).closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Success',
            message: 'Cleaned up 3 unused VOD logos',
            color: 'green',
          })
        )
      );
    });

    it('closes cleanup dialog after confirmation', async () => {
      setupMocks({ unusedCount: 4 });
      render(<VODLogosTable />);
      await waitFor(() =>
        expect(
          screen.getByText(/Cleanup Unused \(4\)/).closest('button')
        ).not.toBeDisabled()
      );
      fireEvent.click(
        screen.getByText(/Cleanup Unused \(4\)/).closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
      );
    });

    it('closes cleanup dialog on cancel', async () => {
      setupMocks({ unusedCount: 4 });
      render(<VODLogosTable />);
      await waitFor(() =>
        expect(
          screen.getByText(/Cleanup Unused \(4\)/).closest('button')
        ).not.toBeDisabled()
      );
      fireEvent.click(
        screen.getByText(/Cleanup Unused \(4\)/).closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-cancel'));
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    it('shows error notification when cleanupUnusedVODLogos throws', async () => {
      const { cleanupUnusedVODLogos } = setupMocks({ unusedCount: 4 });
      cleanupUnusedVODLogos.mockRejectedValue(new Error('Server error'));
      render(<VODLogosTable />);
      await waitFor(() =>
        expect(
          screen.getByText(/Cleanup Unused \(4\)/).closest('button')
        ).not.toBeDisabled()
      );
      fireEvent.click(
        screen.getByText(/Cleanup Unused \(4\)/).closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        )
      );
    });
  });

  // ── "Delete selected" button ───────────────────────────────────────────────

  describe('"Delete selected" button', () => {
    it('is disabled when no rows are selected', () => {
      setupMocks();
      render(<VODLogosTable />);
      // Find the Delete button (not the cleanup button)
      const buttons = screen.getAllByTestId('button');
      const deleteBtn = buttons.find((b) => b.textContent.includes('Delete') && !b.textContent.includes('Cleanup'));
      expect(deleteBtn).toBeDisabled();
    });

    it('shows row count in button label when rows are selected', async () => {
      const logo = makeLogo({ id: 5 });
      setupMocks({ logos: [logo] });
      render(<VODLogosTable />);

      // Render row checkbox and click to select
      const selectCol = getCol('select');
      const { getByTestId: getRowCheckbox } = render(
        selectCol.cell({ row: { original: logo } })
      );
      fireEvent.click(getRowCheckbox('checkbox'));

      await waitFor(() =>
        expect(screen.getByText(/Delete \(1\)/)).toBeInTheDocument()
      );
    });

    it('opens delete dialog with "Delete Multiple Logos" title when multiple rows are selected', async () => {
      const logos = [makeLogo({ id: 1 }), makeLogo({ id: 2 })];
      setupMocks({ logos });
      render(<VODLogosTable />);

      // Select all via header checkbox
      const selectCol = getCol('select');
      const { getByTestId: getHeaderCheckbox } = render(
        selectCol.header()
      );
      fireEvent.click(getHeaderCheckbox('checkbox'));

      await waitFor(() =>
        expect(screen.getByText(/Delete \(2\)/)).toBeInTheDocument()
      );
      fireEvent.click(screen.getByText(/Delete \(2\)/).closest('button'));

      expect(screen.getByTestId('confirm-title')).toHaveTextContent(
        'Delete Multiple Logos'
      );
    });

    it('calls deleteVODLogos when bulk delete is confirmed', async () => {
      const logos = [makeLogo({ id: 1 }), makeLogo({ id: 2 })];
      const { deleteVODLogos } = setupMocks({ logos });
      render(<VODLogosTable />);

      const selectCol = getCol('select');
      const { getByTestId: getHeaderCheckbox } = render(selectCol.header());
      fireEvent.click(getHeaderCheckbox('checkbox'));

      await waitFor(() =>
        expect(screen.getByText(/Delete \(2\)/)).toBeInTheDocument()
      );
      fireEvent.click(screen.getByText(/Delete \(2\)/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(deleteVODLogos).toHaveBeenCalledWith([1, 2])
      );
    });

    it('shows success notification with count after bulk delete', async () => {
      const logos = [makeLogo({ id: 1 }), makeLogo({ id: 2 })];
      setupMocks({ logos });
      render(<VODLogosTable />);

      const selectCol = getCol('select');
      const { getByTestId: getHeaderCheckbox } = render(selectCol.header());
      fireEvent.click(getHeaderCheckbox('checkbox'));

      await waitFor(() =>
        expect(screen.getByText(/Delete \(2\)/)).toBeInTheDocument()
      );
      fireEvent.click(screen.getByText(/Delete \(2\)/).closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Success',
            message: '2 VOD logos deleted successfully',
            color: 'green',
          })
        )
      );
    });
  });

  // ── Delete via row actions ─────────────────────────────────────────────────

  describe('delete via row actions', () => {
    it('opens delete dialog when row delete button is clicked', () => {
      const logo = makeLogo({ id: 5 });
      setupMocks({ logos: [logo] });
      render(<VODLogosTable />);

      const { container } = render(
        getCol('actions').cell({ row: { original: logo } })
      );
      fireEvent.click(
        within(container).getByTestId('icon-square-minus').closest('button')
      );

      expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
    });

    it('shows "Delete Logo" title for single row delete', () => {
      const logo = makeLogo({ id: 5 });
      setupMocks({ logos: [logo] });
      render(<VODLogosTable />);

      const { container } = render(
        getCol('actions').cell({ row: { original: logo } })
      );
      fireEvent.click(
        within(container).getByTestId('icon-square-minus').closest('button')
      );

      expect(screen.getByTestId('confirm-title')).toHaveTextContent(
        'Delete Logo'
      );
    });

    it('closes delete dialog on cancel', () => {
      const logo = makeLogo({ id: 5 });
      setupMocks({ logos: [logo] });
      render(<VODLogosTable />);

      const { container } = render(
        getCol('actions').cell({ row: { original: logo } })
      );
      fireEvent.click(
        within(container).getByTestId('icon-square-minus').closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });
  });

  // ── Single delete confirmation ─────────────────────────────────────────────

  describe('single delete confirmation', () => {
    const setupSingleDeleteFlow = () => {
      const logo = makeLogo({ id: 5, name: 'ESPN Logo' });
      const mocks = setupMocks({ logos: [logo] });
      render(<VODLogosTable />);

      const { container } = render(
        getCol('actions').cell({ row: { original: logo } })
      );
      fireEvent.click(
        within(container).getByTestId('icon-square-minus').closest('button')
      );
      return { logo, ...mocks };
    };

    it('calls deleteVODLogo with the logo id when confirmed', async () => {
      const { deleteVODLogo } = setupSingleDeleteFlow();
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => expect(deleteVODLogo).toHaveBeenCalledWith(5));
    });

    it('shows success notification after single delete', async () => {
      setupSingleDeleteFlow();
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Success',
            message: 'VOD logo deleted successfully',
            color: 'green',
          })
        )
      );
    });

    it('closes dialog after single delete', async () => {
      setupSingleDeleteFlow();
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() =>
        expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
      );
    });

    it('shows error notification when deleteVODLogo throws', async () => {
      const logo = makeLogo({ id: 5 });
      const { deleteVODLogo } = setupMocks({ logos: [logo] });
      deleteVODLogo.mockRejectedValue(new Error('Network error'));

      render(<VODLogosTable />);
      const { container } = render(
        getCol('actions').cell({ row: { original: logo } })
      );
      fireEvent.click(
        within(container).getByTestId('icon-square-minus').closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Error',
            message: 'Network error',
            color: 'red',
          })
        )
      );
    });

    it('closes dialog even when deleteVODLogo throws', async () => {
      const logo = makeLogo({ id: 5 });
      const { deleteVODLogo } = setupMocks({ logos: [logo] });
      deleteVODLogo.mockRejectedValue(new Error('Network error'));

      render(<VODLogosTable />);
      const { container } = render(
        getCol('actions').cell({ row: { original: logo } })
      );
      fireEvent.click(
        within(container).getByTestId('icon-square-minus').closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
      );
    });
  });

  // ── Pagination ─────────────────────────────────────────────────────────────

  describe('pagination', () => {
    it('calls fetchVODLogos with page 2 when next page is clicked', () => {
      const { fetchVODLogos } = setupMocks({ totalCount: 100 });
      render(<VODLogosTable />);
      fireEvent.click(screen.getByTestId('pagination-next'));
      expect(fetchVODLogos).toHaveBeenCalledWith(
        expect.objectContaining({ page: 2 })
      );
    });

    it('resets to page 1 when page size changes', () => {
      const { fetchVODLogos } = setupMocks({ totalCount: 200 });
      render(<VODLogosTable />);

      // Go to page 2 first
      fireEvent.click(screen.getByTestId('pagination-next'));
      expect(fetchVODLogos).toHaveBeenCalledWith(
        expect.objectContaining({ page: 2 })
      );

      // Change page size — should reset to page 1
      fireEvent.change(screen.getByTestId('page-size-select'), {
        target: { value: '50' },
      });
      expect(fetchVODLogos).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1, page_size: 50 })
      );
    });

    it('renders correct pagination string based on page and totalCount', () => {
      setupMocks({ totalCount: 75 });
      render(<VODLogosTable />);
      expect(screen.getByText('1 to 25 of 75')).toBeInTheDocument();
    });

    it('passes correct pageCount to useTable', () => {
      setupMocks({ totalCount: 75 });
      render(<VODLogosTable />);
      // ceil(75 / 25) = 3
      expect(capturedTableOptions.pageCount).toBe(3);
    });

    it('updates pagination string after changing page size', () => {
      setupMocks({ totalCount: 75 });
      render(<VODLogosTable />);
      fireEvent.change(screen.getByTestId('page-size-select'), {
        target: { value: '50' },
      });
      expect(screen.getByText('1 to 50 of 75')).toBeInTheDocument();
    });
  });

  // ── Column cell renderers ──────────────────────────────────────────────────

  describe('usage column', () => {
    it('shows "Unused" badge when movie_count and series_count are both 0', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByText } = render(
        getCol('usage').cell({
          row: {
            original: { movie_count: 0, series_count: 0, item_names: [] },
          },
        })
      );
      expect(getByText('Unused')).toBeInTheDocument();
    });

    it('shows movie count label when only movies use the logo', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByText } = render(
        getCol('usage').cell({
          row: {
            original: {
              movie_count: 2,
              series_count: 0,
              item_names: ['Movie A', 'Movie B'],
            },
          },
        })
      );
      expect(getByText('2 movies')).toBeInTheDocument();
    });

    it('uses singular "movie" for exactly 1 movie', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByText } = render(
        getCol('usage').cell({
          row: {
            original: { movie_count: 1, series_count: 0, item_names: ['A'] },
          },
        })
      );
      expect(getByText('1 movie')).toBeInTheDocument();
    });

    it('shows combined item count when both movies and series are used', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByText } = render(
        getCol('usage').cell({
          row: {
            original: {
              movie_count: 2,
              series_count: 1,
              item_names: ['A', 'B', 'C'],
            },
          },
        })
      );
      expect(getByText('3 items')).toBeInTheDocument();
    });

    it('shows series count label when only series use the logo', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByText } = render(
        getCol('usage').cell({
          row: {
            original: {
              movie_count: 0,
              series_count: 3,
              item_names: ['S1', 'S2', 'S3'],
            },
          },
        })
      );
      expect(getByText('3 series')).toBeInTheDocument();
    });
  });

  describe('url column', () => {
    it('renders the URL text', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByText } = render(
        getCol('url').cell({ getValue: () => 'http://example.com/logo.png' })
      );
      expect(getByText('http://example.com/logo.png')).toBeInTheDocument();
    });

    it('shows ExternalLink icon for http URLs', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByTestId } = render(
        getCol('url').cell({ getValue: () => 'http://example.com/logo.png' })
      );
      expect(getByTestId('icon-external-link')).toBeInTheDocument();
    });

    it('hides ExternalLink for non-http (local) URLs', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { queryByTestId } = render(
        getCol('url').cell({ getValue: () => '/data/logos/logo.png' })
      );
      expect(queryByTestId('icon-external-link')).not.toBeInTheDocument();
    });

    it('opens URL in new tab when ExternalLink is clicked', () => {
      const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
      setupMocks();
      render(<VODLogosTable />);
      const { getByTestId } = render(
        getCol('url').cell({ getValue: () => 'http://example.com/logo.png' })
      );
      fireEvent.click(getByTestId('icon-external-link').closest('button'));
      expect(openSpy).toHaveBeenCalledWith(
        'http://example.com/logo.png',
        '_blank'
      );
      openSpy.mockRestore();
    });
  });

  describe('name column', () => {
    it('renders the logo name', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByText } = render(
        getCol('name').cell({ getValue: () => 'ESPN Logo' })
      );
      expect(getByText('ESPN Logo')).toBeInTheDocument();
    });
  });

  describe('cache_url (Preview) column', () => {
    it('renders an img with the correct src and alt', () => {
      setupMocks();
      render(<VODLogosTable />);
      const { getByAltText } = render(
        getCol('cache_url').cell({
          getValue: () => '/cache/espn.png',
          row: { original: { name: 'ESPN Logo' } },
        })
      );
      const img = getByAltText('ESPN Logo');
      expect(img).toHaveAttribute('src', '/cache/espn.png');
    });
  });

  describe('select column', () => {
    it('renders an unchecked header checkbox when nothing is selected', () => {
      const logos = [makeLogo({ id: 1 }), makeLogo({ id: 2 })];
      setupMocks({ logos });
      render(<VODLogosTable />);
      const { getByTestId } = render(getCol('select').header());
      expect(getByTestId('checkbox')).not.toBeChecked();
    });

    it('renders an unchecked row checkbox for an unselected row', () => {
      const logo = makeLogo({ id: 5 });
      setupMocks({ logos: [logo] });
      render(<VODLogosTable />);
      const { getByTestId } = render(
        getCol('select').cell({ row: { original: logo } })
      );
      expect(getByTestId('checkbox')).not.toBeChecked();
    });
  });

  // ── useTable options ───────────────────────────────────────────────────────

  describe('useTable options', () => {
    it('passes enablePagination: false', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(capturedTableOptions.enablePagination).toBe(false);
    });

    it('passes enableRowSelection: true', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(capturedTableOptions.enableRowSelection).toBe(true);
    });

    it('passes manualPagination: true', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(capturedTableOptions.manualPagination).toBe(true);
    });

    it('passes logos as data', () => {
      const logos = [makeLogo({ id: 10 }), makeLogo({ id: 20 })];
      setupMocks({ logos });
      render(<VODLogosTable />);
      expect(capturedTableOptions.data).toEqual(logos);
    });

    it('passes allRowIds derived from logo ids', () => {
      const logos = [makeLogo({ id: 10 }), makeLogo({ id: 20 })];
      setupMocks({ logos });
      render(<VODLogosTable />);
      expect(capturedTableOptions.allRowIds).toEqual([10, 20]);
    });

    it('passes manualSorting: false', () => {
      setupMocks();
      render(<VODLogosTable />);
      expect(capturedTableOptions.manualSorting).toBe(false);
    });
  });
});
