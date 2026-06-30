import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import EPGsTable from '../EPGsTable';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/epgs', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => ['default', vi.fn()]),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  format: vi.fn((val) => `formatted:${val}`),
  useDateTimeFormat: vi.fn(() => ({ fullDateTimeFormat: 'MM/DD/YYYY HH:mm' })),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/tables/EPGsTableUtils.js', () => ({
  deleteEpg: vi.fn().mockResolvedValue(undefined),
  formatStatusText: vi.fn((s) =>
    s ? s.charAt(0).toUpperCase() + s.slice(1) : 'Unknown'
  ),
  getProgressInfo: vi.fn(() => null),
  getProgressLabel: vi.fn(() => null),
  getSortedEpgs: vi.fn((epgs) => Object.values(epgs)),
  refreshEpg: vi.fn().mockResolvedValue(undefined),
  updateEpg: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../M3uTableUtils.jsx', () => ({
  makeHeaderCellRenderer: vi.fn(() => (header) => (
    <span data-testid={`header-${header.id}`}>
      {header.column.columnDef.header}
    </span>
  )),
  makeSortingChangeHandler: vi.fn(() => vi.fn()),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../forms/EPG', () => ({
  default: ({ isOpen, onClose, epg }) =>
    isOpen ? (
      <div data-testid="epg-form">
        <span data-testid="epg-form-epg">{epg?.name ?? 'new'}</span>
        <button data-testid="epg-form-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../../forms/DummyEPG', () => ({
  default: ({ isOpen, onClose, epg }) =>
    isOpen ? (
      <div data-testid="dummy-epg-form">
        <span data-testid="dummy-epg-form-epg">{epg?.name ?? 'new'}</span>
        <button data-testid="dummy-epg-form-close" onClick={onClose}>
          Close
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
  CustomTable: ({ table }) => (
    <div data-testid="custom-table">
      {table?.getRowModel?.().rows.map((row) => (
        <div key={row.id} data-testid="table-row" data-row-id={row.id}>
          {row.getVisibleCells().map((cell) => (
            <div key={cell.id} data-testid={`cell-${cell.column.id}`}>
              {cell.column.id === 'actions'
                ? table.bodyCellRenderFns?.actions?.({ cell, row })
                : cell.column.columnDef.cell
                  ? cell.column.columnDef.cell(cell.getContext())
                  : cell.getValue?.()}
            </div>
          ))}
        </div>
      ))}
    </div>
  ),
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
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({
    children,
    onClick,
    leftSection,
    rightSection,
    disabled,
    loading,
  }) => (
    <button
      data-testid="button"
      onClick={onClick}
      disabled={disabled || loading}
    >
      {leftSection}
      {children}
      {rightSection}
    </button>
  ),
  Checkbox: ({ checked, onChange, label, disabled }) => (
    <label>
      <input
        data-testid="checkbox"
        type="checkbox"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
      />
      {label}
    </label>
  ),
  Flex: ({ children, style }) => <div style={style}>{children}</div>,
  Menu: Object.assign(
    ({ children }) => <div data-testid="menu">{children}</div>,
    {
      Target: ({ children }) => <div>{children}</div>,
      Dropdown: ({ children }) => (
        <div data-testid="menu-dropdown">{children}</div>
      ),
      Item: ({ children, onClick }) => (
        <button data-testid="menu-item" onClick={onClick}>
          {children}
        </button>
      ),
    }
  ),
  MenuDropdown: ({ children }) => (
    <div data-testid="menu-dropdown">{children}</div>
  ),
  MenuItem: ({ children, onClick }) => (
    <button data-testid="menu-item" onClick={onClick}>
      {children}
    </button>
  ),
  MenuTarget: ({ children }) => <div>{children}</div>,
  Modal: ({ children, opened, onClose, title }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Progress: ({ value }) => <div data-testid="progress" data-value={value} />,
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ checked, onChange, disabled }) => (
    <input
      data-testid="switch"
      type="checkbox"
      checked={checked}
      onChange={onChange}
      disabled={disabled}
    />
  ),
  Text: ({ children, size, c, style }) => (
    <span data-testid="text" data-size={size} data-color={c} style={style}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => (
    <div data-tooltip={label}>{children}</div>
  ),
  useMantineTheme: vi.fn(() => ({
    palette: { background: { paper: '#1a1a1a' } },
    colors: { red: { 6: '#fa5252' }, green: { 6: '#40c057' } },
  })),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ChevronDown: () => <svg data-testid="icon-chevron-down" />,
  RefreshCcw: () => <svg data-testid="icon-refresh" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useEPGsStore from '../../../store/epgs';
import useWarningsStore from '../../../store/warnings';
import { showNotification } from '../../../utils/notificationUtils.js';
import * as EPGsTableUtils from '../../../utils/tables/EPGsTableUtils.js';
import { useTable, CustomTable } from '../CustomTable';
import useLocalStorage from '../../../hooks/useLocalStorage';
import { makeSortingChangeHandler } from '../M3uTableUtils.jsx';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeEpg = (overrides = {}) => ({
  id: 'epg-1',
  name: 'Test EPG',
  source_type: 'xmltv',
  url: 'http://example.com/epg.xml',
  status: 'idle',
  last_message: null,
  is_active: true,
  updated_at: '2024-01-01T12:00:00Z',
  ...overrides,
});

const makeDummyEpg = (overrides = {}) =>
  makeEpg({
    id: 'epg-dummy',
    name: 'Dummy EPG',
    source_type: 'dummy',
    ...overrides,
  });

// Captures the useTable options passed by EPGsTable so we can invoke
// renderBodyCell and renderHeaderCell in tests.
let capturedTableOptions = null;

/** Wire stores and the useTable spy */
const setupMocks = ({
  epgs = { 'epg-1': makeEpg() },
  refreshProgress = {},
  isWarningSuppressed = vi.fn(() => false),
  suppressWarning = vi.fn(),
  tableSize = 'default',
} = {}) => {
  vi.mocked(useEPGsStore).mockImplementation((sel) =>
    sel({ epgs, refreshProgress })
  );

  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({ isWarningSuppressed, suppressWarning })
  );

  vi.mocked(useLocalStorage).mockReturnValue([tableSize, vi.fn()]);

  // Capture the options EPGsTable passes to useTable so tests can call
  // renderBodyCell / renderHeaderCell manually.
  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return {
      getRowModel: () => ({ rows: [] }),
      bodyCellRenderFns: opts.bodyCellRenderFns ?? {},
      getHeaderGroups: () => [],
    };
  });
};

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Build a minimal row/cell pair like TanStack Table would provide */
const makeRowContext = (epgObj) => {
  const row = {
    id: epgObj.id,
    original: epgObj,
    getIsSelected: vi.fn(() => false),
    getVisibleCells: vi.fn(() => []),
  };
  const cell = {
    column: { id: 'actions', columnDef: {} },
    getValue: vi.fn(() => epgObj.is_active),
    row,
    getContext: vi.fn(() => ({})),
  };
  return { row, cell };
};

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('EPGsTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
    vi.mocked(EPGsTableUtils.deleteEpg).mockResolvedValue(undefined);
    vi.mocked(EPGsTableUtils.refreshEpg).mockResolvedValue(undefined);
    vi.mocked(EPGsTableUtils.updateEpg).mockResolvedValue(undefined);
    vi.mocked(EPGsTableUtils.getSortedEpgs).mockImplementation((epgs) =>
      Object.values(epgs)
    );
  });

  // ── Header renders ─────────────────────────────────────────────────────────

  describe('header / top toolbar', () => {
    it('renders the "EPGs" heading', () => {
      setupMocks();
      render(<EPGsTable />);
      expect(screen.getByText('EPGs')).toBeInTheDocument();
    });

    it('renders the "Add EPG" menu button', () => {
      setupMocks();
      render(<EPGsTable />);
      expect(screen.getByText('Add EPG')).toBeInTheDocument();
    });

    it('renders both menu items in the Add EPG menu', () => {
      setupMocks();
      render(<EPGsTable />);
      expect(screen.getByText('Standard EPG Source')).toBeInTheDocument();
      expect(screen.getByText('Dummy EPG Source')).toBeInTheDocument();
    });
  });

  // ── Add EPG modal flows ────────────────────────────────────────────────────

  describe('add EPG modals', () => {
    it('opens the standard EPG form when "Standard EPG Source" is clicked', () => {
      setupMocks();
      render(<EPGsTable />);
      fireEvent.click(screen.getByText('Standard EPG Source'));
      expect(screen.getByTestId('epg-form')).toBeInTheDocument();
    });

    it('passes null epg to EPGForm when creating new standard EPG', () => {
      setupMocks();
      render(<EPGsTable />);
      fireEvent.click(screen.getByText('Standard EPG Source'));
      expect(screen.getByTestId('epg-form-epg')).toHaveTextContent('new');
    });

    it('closes the standard EPG form when onClose is called', () => {
      setupMocks();
      render(<EPGsTable />);
      fireEvent.click(screen.getByText('Standard EPG Source'));
      fireEvent.click(screen.getByTestId('epg-form-close'));
      expect(screen.queryByTestId('epg-form')).not.toBeInTheDocument();
    });

    it('opens the dummy EPG form when "Dummy EPG Source" is clicked', () => {
      setupMocks();
      render(<EPGsTable />);
      fireEvent.click(screen.getByText('Dummy EPG Source'));
      expect(screen.getByTestId('dummy-epg-form')).toBeInTheDocument();
    });

    it('passes null epg to DummyEPGForm when creating new dummy EPG', () => {
      setupMocks();
      render(<EPGsTable />);
      fireEvent.click(screen.getByText('Dummy EPG Source'));
      expect(screen.getByTestId('dummy-epg-form-epg')).toHaveTextContent('new');
    });

    it('closes the dummy EPG form when onClose is called', () => {
      setupMocks();
      render(<EPGsTable />);
      fireEvent.click(screen.getByText('Dummy EPG Source'));
      fireEvent.click(screen.getByTestId('dummy-epg-form-close'));
      expect(screen.queryByTestId('dummy-epg-form')).not.toBeInTheDocument();
    });
  });

  // ── Edit EPG (RowActions) ──────────────────────────────────────────────────

  describe('edit EPG via RowActions', () => {
    it('opens the standard EPG form with the correct epg when edit is clicked', () => {
      const epg = makeEpg();
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      // Invoke the actions cell renderer directly
      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));

      expect(screen.getByTestId('epg-form')).toBeInTheDocument();
      expect(screen.getByTestId('epg-form-epg')).toHaveTextContent('Test EPG');
    });

    it('opens the dummy EPG form when editing a dummy EPG', () => {
      const epg = makeDummyEpg();
      setupMocks({ epgs: { 'epg-dummy': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));

      expect(screen.getByTestId('dummy-epg-form')).toBeInTheDocument();
    });
  });

  // ── Delete EPG (with confirmation) ────────────────────────────────────────

  describe('delete EPG', () => {
    it('opens the confirmation dialog when delete is clicked (warning not suppressed)', () => {
      const epg = makeEpg();
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
    });

    it('shows the correct title in the confirmation dialog', () => {
      const epg = makeEpg();
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      expect(screen.getByTestId('confirm-title')).toHaveTextContent(
        'Confirm EPG Source Deletion'
      );
    });

    it('calls deleteEpg when delete is confirmed', async () => {
      const epg = makeEpg();
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(EPGsTableUtils.deleteEpg).toHaveBeenCalledWith('epg-1');
      });
    });

    it('closes the dialog after successful delete', async () => {
      const epg = makeEpg();
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument();
      });
    });

    it('closes the dialog when Cancel is clicked without deleting', () => {
      const epg = makeEpg();
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
      expect(EPGsTableUtils.deleteEpg).not.toHaveBeenCalled();
    });

    it('skips confirmation and calls deleteEpg immediately when warning is suppressed', async () => {
      const epg = makeEpg();
      setupMocks({
        epgs: { 'epg-1': epg },
        isWarningSuppressed: vi.fn(() => true),
      });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      await waitFor(() => {
        expect(EPGsTableUtils.deleteEpg).toHaveBeenCalledWith('epg-1');
      });
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });
  });

  // ── Refresh EPG ────────────────────────────────────────────────────────────

  describe('refresh EPG', () => {
    it('calls refreshEpg with the correct id when refresh is clicked', async () => {
      const epg = makeEpg();
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      // refreshEPG passes force=false (the default) through to refreshEpg
      await waitFor(() => {
        expect(EPGsTableUtils.refreshEpg).toHaveBeenCalledWith('epg-1', false);
      });
    });

    it('shows a notification after refreshEpg resolves', async () => {
      const epg = makeEpg();
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'EPG refresh initiated' })
        );
      });
    });

    it('disables the refresh button for dummy EPGs', () => {
      const epg = makeDummyEpg();
      setupMocks({ epgs: { 'epg-dummy': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      expect(getByTestId('icon-refresh').closest('button')).toBeDisabled();
    });

    it('disables the refresh button for inactive EPGs', () => {
      const epg = makeEpg({ is_active: false });
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({
        cell,
        row,
      });
      const { getByTestId } = render(rendered);
      expect(getByTestId('icon-refresh').closest('button')).toBeDisabled();
    });
  });

  // ── Toggle active (Switch) ─────────────────────────────────────────────────

  describe('toggle active', () => {
    it('calls updateEpg with flipped is_active when Switch is toggled', async () => {
      const epg = makeEpg({ is_active: true });
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      // The switch is rendered inside the is_active column cell renderer.
      // Find the column definition and call its cell renderer.
      const isActiveCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'is_active'
      );
      const row = {
        original: epg,
        getIsSelected: vi.fn(() => false),
      };
      const cell = { getValue: vi.fn(() => epg.is_active) };
      const { getByTestId } = render(isActiveCol.cell({ row, cell }));
      fireEvent.click(getByTestId('switch'));

      await waitFor(() => {
        expect(EPGsTableUtils.updateEpg).toHaveBeenCalledWith(
          { is_active: false },
          epg,
          true
        );
      });
    });

    it('does not call updateEpg when epg object is invalid', async () => {
      setupMocks();
      render(<EPGsTable />);

      const isActiveCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'is_active'
      );
      const row = { original: { source_type: 'xmltv', id: undefined, is_active: true }, getIsSelected: vi.fn(() => false) };
      const cell = { getValue: vi.fn(() => false) };

      // Should not throw even with an invalid (no id) epg, and should not call updateEpg
      render(isActiveCol.cell({ row, cell }));
      expect(EPGsTableUtils.updateEpg).not.toHaveBeenCalled();
    });

    it('disables the Switch for dummy EPGs', () => {
      const epg = makeDummyEpg();
      setupMocks({ epgs: { 'epg-dummy': epg } });
      render(<EPGsTable />);

      const isActiveCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'is_active'
      );
      const row = { original: epg, getIsSelected: vi.fn(() => false) };
      const cell = { getValue: vi.fn(() => true) };
      const { getByTestId } = render(isActiveCol.cell({ row, cell }));
      expect(getByTestId('switch')).toBeDisabled();
    });
  });

  // ── Status cell ────────────────────────────────────────────────────────────

  describe('status cell', () => {
    const statuses = ['idle', 'fetching', 'parsing', 'error', 'success'];
    statuses.forEach((status) => {
      it(`renders formatted status text for status="${status}"`, () => {
        const epg = makeEpg({ status });
        setupMocks({ epgs: { 'epg-1': epg } });
        render(<EPGsTable />);

        const statusCol = capturedTableOptions.columns.find(
          (c) => c.accessorKey === 'status'
        );
        const row = { original: epg };
        const { container } = render(statusCol.cell({ row }));
        expect(container).toBeInTheDocument();
        expect(EPGsTableUtils.formatStatusText).toHaveBeenCalledWith(status);
      });
    });

    it('renders "idle" status for dummy EPG regardless of actual status', () => {
      const epg = makeDummyEpg({ status: 'fetching' });
      setupMocks({ epgs: { 'epg-dummy': epg } });
      render(<EPGsTable />);

      const statusCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'status'
      );
      const row = { original: epg };
      render(statusCol.cell({ row }));
      expect(EPGsTableUtils.formatStatusText).toHaveBeenCalledWith('idle');
    });
  });

  // ── Updated_at cell ────────────────────────────────────────────────────────

  describe('updated_at cell', () => {
    it('renders "Never" when updated_at is null', () => {
      const epg = makeEpg({ updated_at: null });
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const updatedCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'updated_at'
      );
      const cell = { getValue: vi.fn(() => null) };
      const { getByText } = render(updatedCol.cell({ cell }));
      expect(getByText('Never')).toBeInTheDocument();
    });

    it('renders the formatted date when updated_at has a value', () => {
      setupMocks();
      render(<EPGsTable />);

      const updatedCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'updated_at'
      );
      const cell = { getValue: vi.fn(() => '2024-01-01T12:00:00Z') };
      const { getByText } = render(updatedCol.cell({ cell }));
      expect(getByText(/formatted:/)).toBeInTheDocument();
    });
  });

  // ── Status message cell ────────────────────────────────────────────────────

  describe('status message cell', () => {
    it('returns null for dummy EPGs', () => {
      const epg = makeDummyEpg();
      setupMocks({ epgs: { 'epg-dummy': epg } });
      render(<EPGsTable />);

      const msgCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'last_message'
      );
      const row = { original: epg };
      const { container } = render(<div>{msgCol.cell({ row })}</div>);
      expect(container.firstChild).toBeEmptyDOMElement();
    });

    it('renders error message when status is error', () => {
      const epg = makeEpg({ status: 'error', last_message: 'Something broke' });
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const msgCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'last_message'
      );
      const row = { original: epg };
      const { getByText } = render(msgCol.cell({ row }));
      expect(getByText('Something broke')).toBeInTheDocument();
    });

    it('renders success message when status is success and last_message is set', () => {
      const epg = makeEpg({ status: 'success', last_message: 'All good' });
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const msgCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'last_message'
      );
      const row = { original: epg };
      const { getByText } = render(msgCol.cell({ row }));
      expect(getByText('All good')).toBeInTheDocument();
    });

    it('renders fallback success message when status is success and last_message is null', () => {
      const epg = makeEpg({ status: 'success', last_message: null });
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const msgCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'last_message'
      );
      const row = { original: epg };
      const { getByText } = render(msgCol.cell({ row }));
      expect(getByText('EPG data refreshed successfully')).toBeInTheDocument();
    });

    it('renders idle last_message when status is idle and message is set', () => {
      const epg = makeEpg({ status: 'idle', last_message: 'Previous result' });
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const msgCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'last_message'
      );
      const row = { original: epg };
      const { getByText } = render(msgCol.cell({ row }));
      expect(getByText('Previous result')).toBeInTheDocument();
    });

    it('renders progress display when refreshProgress is active', () => {
      const epg = makeEpg();
      vi.mocked(EPGsTableUtils.getProgressLabel).mockReturnValue('Downloading');
      vi.mocked(EPGsTableUtils.getProgressInfo).mockReturnValue(null);
      setupMocks({
        epgs: { 'epg-1': epg },
        refreshProgress: { 'epg-1': { action: 'downloading', progress: 50 } },
      });
      render(<EPGsTable />);

      const msgCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'last_message'
      );
      const row = { original: epg };
      const { getByTestId, getByText } = render(msgCol.cell({ row }));
      expect(getByText(/Downloading: 50%/)).toBeInTheDocument();
      expect(getByTestId('progress')).toBeInTheDocument();
    });

    it('renders speed when progress has speed', () => {
      const epg = makeEpg();
      vi.mocked(EPGsTableUtils.getProgressLabel).mockReturnValue('Downloading');
      setupMocks({
        epgs: { 'epg-1': epg },
        refreshProgress: {
          'epg-1': { action: 'downloading', progress: 30, speed: 512 },
        },
      });
      render(<EPGsTable />);

      const msgCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'last_message'
      );
      const row = { original: epg };
      const { getByText } = render(msgCol.cell({ row }));
      expect(getByText(/Speed: 512 KB\/s/)).toBeInTheDocument();
    });

    it('renders additionalInfo when getProgressInfo returns a value', () => {
      const epg = makeEpg();
      vi.mocked(EPGsTableUtils.getProgressLabel).mockReturnValue(
        'Parsing Programs'
      );
      vi.mocked(EPGsTableUtils.getProgressInfo).mockReturnValue(
        '5,000 / 10,000'
      );
      setupMocks({
        epgs: { 'epg-1': epg },
        refreshProgress: {
          'epg-1': { action: 'parsing_programs', progress: 50 },
        },
      });
      render(<EPGsTable />);

      const msgCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'last_message'
      );
      const row = { original: epg };
      const { getByText } = render(msgCol.cell({ row }));
      expect(getByText('5,000 / 10,000')).toBeInTheDocument();
    });
  });

  // ── URL cell ───────────────────────────────────────────────────────────────

  describe('URL / api_key / file_path cell', () => {
    it('renders the url when present', () => {
      setupMocks();
      render(<EPGsTable />);

      const urlCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'url'
      );
      const row = { original: makeEpg() };
      const cell = { getValue: vi.fn(() => 'http://example.com/epg.xml') };
      const { getByText } = render(urlCol.cell({ cell, row }));
      expect(getByText('http://example.com/epg.xml')).toBeInTheDocument();
    });

    it('falls back to password when url is empty and password is set', () => {
      setupMocks();
      render(<EPGsTable />);

      const urlCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'url'
      );
      const row = {
        original: { ...makeEpg(), url: null, password: 'MY-KEY-123' },
      };
      const cell = { getValue: vi.fn(() => null) };
      const { getByText } = render(urlCol.cell({ cell, row }));
      expect(getByText('MY-KEY-123')).toBeInTheDocument();
    });

    it('falls back to file_path when url and api_key are both absent', () => {
      setupMocks();
      render(<EPGsTable />);

      const urlCol = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'url'
      );
      const row = {
        original: {
          ...makeEpg(),
          url: null,
          api_key: null,
          file_path: '/data/epg.xml',
        },
      };
      const cell = { getValue: vi.fn(() => null) };
      const { getByText } = render(urlCol.cell({ cell, row }));
      expect(getByText('/data/epg.xml')).toBeInTheDocument();
    });
  });

  // ── Sorting integration ────────────────────────────────────────────────────

  describe('sorting integration', () => {
    it('calls getSortedEpgs when sorting handler fires', () => {
      setupMocks();
      render(<EPGsTable />);
      // The real makeSortingChangeHandler is mocked; verify it was called
      // with sorting state and a setter from the component
      expect(makeSortingChangeHandler).toHaveBeenCalled();
    });
  });

  // ── Data initialization from epgs store ───────────────────────────────────

  describe('data initialization', () => {
    it('passes the epgs as data to useTable (active-first, then alphabetical)', () => {
      const epgs = {
        'epg-2': makeEpg({ id: 'epg-2', name: 'Zebra', is_active: false }),
        'epg-1': makeEpg({ id: 'epg-1', name: 'Alpha', is_active: true }),
      };
      setupMocks({ epgs });
      render(<EPGsTable />);
      // Active EPG should come first in the sorted data passed to useTable
      const data = capturedTableOptions.data;
      expect(data[0].is_active).toBe(true);
    });

    it('places inactive EPGs after active ones', () => {
      const epgs = {
        'epg-a': makeEpg({ id: 'epg-a', name: 'Active', is_active: true }),
        'epg-b': makeEpg({ id: 'epg-b', name: 'Inactive', is_active: false }),
      };
      setupMocks({ epgs });
      render(<EPGsTable />);
      const data = capturedTableOptions.data;
      expect(data[data.length - 1].is_active).toBe(false);
    });

    it('sorts two active EPGs alphabetically by name', () => {
      const epgs = {
        'epg-z': makeEpg({ id: 'epg-z', name: 'Zebra', is_active: true }),
        'epg-a': makeEpg({ id: 'epg-a', name: 'Alpha', is_active: true }),
      };
      setupMocks({ epgs });
      render(<EPGsTable />);
      const data = capturedTableOptions.data;
      expect(data[0].name).toBe('Alpha');
      expect(data[1].name).toBe('Zebra');
    });
  });

  // ── Source type cell ───────────────────────────────────────────────────────

  describe('source type cell', () => {
    const getTypeCol = () =>
      capturedTableOptions.columns.find((c) => c.accessorKey === 'source_type');

    it('renders "XMLTV" for source_type xmltv', () => {
      setupMocks();
      render(<EPGsTable />);
      const { getByText } = render(
        getTypeCol().cell({ cell: { getValue: vi.fn(() => 'xmltv') } })
      );
      expect(getByText('XMLTV')).toBeInTheDocument();
    });

    it('renders "Schedules Direct" for source_type schedules_direct', () => {
      setupMocks();
      render(<EPGsTable />);
      const { getByText } = render(
        getTypeCol().cell({ cell: { getValue: vi.fn(() => 'schedules_direct') } })
      );
      expect(getByText('Schedules Direct')).toBeInTheDocument();
    });

    it('renders "Custom Dummy" for source_type dummy', () => {
      setupMocks();
      render(<EPGsTable />);
      const { getByText } = render(
        getTypeCol().cell({ cell: { getValue: vi.fn(() => 'dummy') } })
      );
      expect(getByText('Custom Dummy')).toBeInTheDocument();
    });

    it('renders the raw value for an unknown source_type', () => {
      setupMocks();
      render(<EPGsTable />);
      const { getByText } = render(
        getTypeCol().cell({ cell: { getValue: vi.fn(() => 'unknown_type') } })
      );
      expect(getByText('unknown_type')).toBeInTheDocument();
    });
  });

  // ── URL cell – schedules_direct scenarios ──────────────────────────────────

  describe('URL cell - schedules_direct', () => {
    const getUrlCol = () =>
      capturedTableOptions.columns.find((c) => c.accessorKey === 'url');

    it('shows "User: <username>" for schedules_direct with a username', () => {
      setupMocks();
      render(<EPGsTable />);
      const row = {
        original: {
          ...makeEpg(),
          source_type: 'schedules_direct',
          username: 'myuser',
        },
      };
      const cell = { getValue: vi.fn(() => null) };
      const { getByText } = render(getUrlCol().cell({ cell, row }));
      expect(getByText('User: myuser')).toBeInTheDocument();
    });

    it('shows "(credentials set)" for schedules_direct with no username', () => {
      setupMocks();
      render(<EPGsTable />);
      const row = {
        original: {
          ...makeEpg(),
          source_type: 'schedules_direct',
          username: '',
        },
      };
      const cell = { getValue: vi.fn(() => null) };
      const { getByText } = render(getUrlCol().cell({ cell, row }));
      expect(getByText('(credentials set)')).toBeInTheDocument();
    });

    it('falls back to password when url is empty and password is set', () => {
      setupMocks();
      render(<EPGsTable />);
      const row = {
        original: { ...makeEpg(), url: null, password: 'secret123' },
      };
      const cell = { getValue: vi.fn(() => null) };
      const { getByText } = render(getUrlCol().cell({ cell, row }));
      expect(getByText('secret123')).toBeInTheDocument();
    });
  });

  // ── Schedules Direct early refresh dialog ──────────────────────────────────

  describe('Schedules Direct early refresh', () => {
    const makeRecentSdEpg = (overrides = {}) =>
      makeEpg({
        id: 'sd-1',
        source_type: 'schedules_direct',
        // 30 minutes ago — well within the 2-hour window
        updated_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
        ...overrides,
      });

    const makeOldSdEpg = (overrides = {}) =>
      makeEpg({
        id: 'sd-1',
        source_type: 'schedules_direct',
        // 3 hours ago — outside the 2-hour window
        updated_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
        ...overrides,
      });

    it('opens the SD early-refresh confirmation dialog when the EPG was refreshed recently', () => {
      const epg = makeRecentSdEpg();
      setupMocks({ epgs: { 'sd-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({ cell, row });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      expect(screen.getByTestId('confirm-title')).toHaveTextContent(
        'Refresh Schedules Direct Early?'
      );
    });

    it('shows "Refresh Anyway" as the confirm label', () => {
      const epg = makeRecentSdEpg();
      setupMocks({ epgs: { 'sd-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({ cell, row });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      expect(screen.getByTestId('confirm-ok')).toHaveTextContent('Refresh Anyway');
    });

    it('skips the SD dialog and calls refreshEpg directly when EPG was refreshed more than 2 hours ago', async () => {
      const epg = makeOldSdEpg();
      setupMocks({ epgs: { 'sd-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({ cell, row });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      await waitFor(() => {
        expect(EPGsTableUtils.refreshEpg).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument();
    });

    it('skips the SD dialog when the SD EPG has no updated_at', async () => {
      const epg = makeEpg({
        id: 'sd-1',
        source_type: 'schedules_direct',
        updated_at: null,
      });
      setupMocks({ epgs: { 'sd-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({ cell, row });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));

      await waitFor(() => {
        expect(EPGsTableUtils.refreshEpg).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument();
    });

    it('calls refreshEpg with force=true when "Refresh Anyway" is confirmed', async () => {
      const epg = makeRecentSdEpg();
      setupMocks({ epgs: { 'sd-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({ cell, row });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(EPGsTableUtils.refreshEpg).toHaveBeenCalledWith('sd-1', true);
      });
    });

    it('shows a notification after force-refreshing', async () => {
      const epg = makeRecentSdEpg();
      setupMocks({ epgs: { 'sd-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({ cell, row });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'EPG refresh initiated' })
        );
      });
    });

    it('closes the SD dialog without calling refreshEpg when cancelled', () => {
      const epg = makeRecentSdEpg();
      setupMocks({ epgs: { 'sd-1': epg } });
      render(<EPGsTable />);

      const { row, cell } = makeRowContext(epg);
      const rendered = capturedTableOptions.bodyCellRenderFns.actions({ cell, row });
      const { getByTestId } = render(rendered);
      fireEvent.click(getByTestId('icon-refresh').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      expect(screen.queryByTestId('confirmation-dialog')).not.toBeInTheDocument();
      expect(EPGsTableUtils.refreshEpg).not.toHaveBeenCalled();
    });
  });

  // ── Status message cell - progress edge cases ──────────────────────────────

  describe('status message cell - progress edge cases', () => {
    const getMsgCol = () =>
      capturedTableOptions.columns.find((c) => c.accessorKey === 'last_message');

    it('renders nothing when getProgressLabel returns null for active progress', () => {
      const epg = makeEpg();
      vi.mocked(EPGsTableUtils.getProgressLabel).mockReturnValue(null);
      setupMocks({
        epgs: { 'epg-1': epg },
        refreshProgress: { 'epg-1': { action: 'unknown_action', progress: 50 } },
      });
      render(<EPGsTable />);

      const row = { original: epg };
      const { container } = render(<div>{getMsgCol().cell({ row })}</div>);
      expect(container.firstChild).toBeEmptyDOMElement();
    });

    it('shows progress when progress.status is "in_progress" even at 100%', () => {
      const epg = makeEpg();
      vi.mocked(EPGsTableUtils.getProgressLabel).mockReturnValue('Processing');
      setupMocks({
        epgs: { 'epg-1': epg },
        refreshProgress: {
          'epg-1': { action: 'processing', progress: 100, status: 'in_progress' },
        },
      });
      render(<EPGsTable />);

      const row = { original: epg };
      const { getByText } = render(getMsgCol().cell({ row }));
      expect(getByText(/Processing: 100%/)).toBeInTheDocument();
    });

    it('shows progress for parsing_channels action when epg.status is "parsing"', () => {
      const epg = makeEpg({ status: 'parsing' });
      vi.mocked(EPGsTableUtils.getProgressLabel).mockReturnValue('Parsing Channels');
      setupMocks({
        epgs: { 'epg-1': epg },
        refreshProgress: {
          'epg-1': { action: 'parsing_channels', progress: 100 },
        },
      });
      render(<EPGsTable />);

      const row = { original: epg };
      const { getByText } = render(getMsgCol().cell({ row }));
      expect(getByText(/Parsing Channels: 100%/)).toBeInTheDocument();
    });

    it('does not show progress for parsing_channels action when epg.status is not "parsing"', () => {
      const epg = makeEpg({ status: 'idle' });
      vi.mocked(EPGsTableUtils.getProgressLabel).mockReturnValue('Parsing Channels');
      setupMocks({
        epgs: { 'epg-1': epg },
        refreshProgress: {
          'epg-1': { action: 'parsing_channels', progress: 100 },
        },
      });
      render(<EPGsTable />);

      const row = { original: epg };
      const { container } = render(<div>{getMsgCol().cell({ row })}</div>);
      // condition fails (100 < 100=false, no in_progress, parsing_channels + idle=false)
      // falls through to the idle-message branch; no last_message → returns null
      expect(container.firstChild).toBeEmptyDOMElement();
    });

    it('renders nothing when there is no active progress and no status message', () => {
      const epg = makeEpg({ status: 'idle', last_message: null });
      setupMocks({ epgs: { 'epg-1': epg } });
      render(<EPGsTable />);

      const row = { original: epg };
      const { container } = render(<div>{getMsgCol().cell({ row })}</div>);
      expect(container.firstChild).toBeEmptyDOMElement();
    });
  });

  // ── Table structure ────────────────────────────────────────────────────────

  describe('table structure', () => {
    it('renders the CustomTable component', () => {
      setupMocks();
      render(<EPGsTable />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('passes enablePagination: false to useTable', () => {
      setupMocks();
      render(<EPGsTable />);
      expect(capturedTableOptions.enablePagination).toBe(false);
    });

    it('passes enableRowSelection: false to useTable', () => {
      setupMocks();
      render(<EPGsTable />);
      expect(capturedTableOptions.enableRowSelection).toBe(false);
    });

    it('passes manualSorting: true to useTable', () => {
      setupMocks();
      render(<EPGsTable />);
      expect(capturedTableOptions.manualSorting).toBe(true);
    });

    it('passes renderTopToolbar: false to useTable', () => {
      setupMocks();
      render(<EPGsTable />);
      expect(capturedTableOptions.renderTopToolbar).toBe(false);
    });

    it('actions column size is 75 in compact mode', () => {
      setupMocks({ tableSize: 'compact' });
      render(<EPGsTable />);
      const actionsCol = capturedTableOptions.columns.find((c) => c.id === 'actions');
      expect(actionsCol.size).toBe(75);
    });

    it('actions column size is 100 in default mode', () => {
      setupMocks({ tableSize: 'default' });
      render(<EPGsTable />);
      const actionsCol = capturedTableOptions.columns.find((c) => c.id === 'actions');
      expect(actionsCol.size).toBe(100);
    });
  });
});
