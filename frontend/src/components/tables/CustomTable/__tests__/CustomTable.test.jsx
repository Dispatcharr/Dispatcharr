import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CustomTable from '../CustomTable';

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../CustomTableHeader', () => ({
  default: ({ headerPinned, enableDragDrop }) => (
    <div
      data-testid="custom-table-header"
      data-header-pinned={headerPinned}
      data-enable-drag-drop={enableDragDrop}
    />
  ),
}));

vi.mock('../CustomTableBody', () => ({
  default: ({ enableDragDrop }) => (
    <div
      data-testid="custom-table-body"
      data-enable-drag-drop={enableDragDrop}
    />
  ),
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Box: ({ children, className, style }) => (
    <div data-testid="table-box" className={className} style={style}>
      {children}
    </div>
  ),
}));

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeHeader = (id, size, grow = false, minSize = 50) => ({
  id,
  getSize: () => size,
  column: {
    columnDef: { grow, minSize },
  },
});

const makeTable = (overrides = {}) => {
  const headers = [makeHeader('col1', 100), makeHeader('col2', 200)];

  return {
    tableSize: 'default',
    filters: {},
    allRowIds: [],
    headerCellRenderFns: {},
    selectedTableIds: [],
    tableCellProps: vi.fn(),
    headerPinned: false,
    enableDragDrop: false,
    expandedRowIds: [],
    expandedRowRenderer: null,
    bodyCellRenderFns: {},
    getRowStyles: vi.fn(),
    selectedTableIdsSet: new Set(),
    handleRowClickRef: { current: vi.fn() },
    onSelectAllChange: null,
    renderBodyCell: null,
    getState: () => ({ columnSizing: {} }),
    getHeaderGroups: () => [{ headers }],
    getFlatHeaders: () => headers,
    getRowModel: () => ({ rows: [] }),
    ...overrides,
  };
};

describe('CustomTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders CustomTableHeader and CustomTableBody', () => {
      render(<CustomTable table={makeTable()} />);
      expect(screen.getByTestId('custom-table-header')).toBeInTheDocument();
      expect(screen.getByTestId('custom-table-body')).toBeInTheDocument();
    });

    it('applies default table-size class when tableSize is default', () => {
      render(<CustomTable table={makeTable({ tableSize: 'default' })} />);
      const box = screen.getByTestId('table-box');
      expect(box.className).toContain('table-size-default');
    });

    it('applies compact table-size class when tableSize is compact', () => {
      render(<CustomTable table={makeTable({ tableSize: 'compact' })} />);
      const box = screen.getByTestId('table-box');
      expect(box.className).toContain('table-size-compact');
    });

    it('applies large table-size class when tableSize is large', () => {
      render(<CustomTable table={makeTable({ tableSize: 'large' })} />);
      const box = screen.getByTestId('table-box');
      expect(box.className).toContain('table-size-large');
    });

    it('uses default table size when tableSize is undefined', () => {
      const table = makeTable();
      table.tableSize = undefined;
      render(<CustomTable table={table} />);
      const box = screen.getByTestId('table-box');
      expect(box.className).toContain('table-size-default');
    });
  });

  // ── Min table width ────────────────────────────────────────────────────────

  describe('minTableWidth calculation', () => {
    it('calculates minTableWidth from fixed-width columns', () => {
      const headers = [
        makeHeader('col1', 100, false),
        makeHeader('col2', 200, false),
      ];
      const table = makeTable({
        getHeaderGroups: () => [{ headers }],
        getFlatHeaders: () => headers,
      });
      render(<CustomTable table={table} />);
      const box = screen.getByTestId('table-box');
      expect(box.style.minWidth).toBe('300px');
    });

    it('uses minSize for grow columns instead of full size', () => {
      const headers = [
        makeHeader('col1', 100, false),
        makeHeader('grow-col', 500, true, 80),
      ];
      const table = makeTable({
        getHeaderGroups: () => [{ headers }],
        getFlatHeaders: () => headers,
      });
      render(<CustomTable table={table} />);
      const box = screen.getByTestId('table-box');
      // col1 (100) + grow-col minSize (80) = 180
      expect(box.style.minWidth).toBe('180px');
    });

    it('returns minWidth of 0 when no header groups exist', () => {
      const table = makeTable({
        getHeaderGroups: () => [],
        getFlatHeaders: () => [],
      });
      render(<CustomTable table={table} />);
      const box = screen.getByTestId('table-box');
      expect(box.style.minWidth).toBe('0px');
    });

    it('returns minWidth of 0 when header group has no headers', () => {
      const table = makeTable({
        getHeaderGroups: () => [{ headers: [] }],
        getFlatHeaders: () => [],
      });
      render(<CustomTable table={table} />);
      const box = screen.getByTestId('table-box');
      expect(box.style.minWidth).toBe('0px');
    });
  });

  // ── Column size CSS vars ───────────────────────────────────────────────────

  describe('columnSizeVars', () => {
    it('injects CSS custom properties for fixed-width columns', () => {
      const headers = [
        makeHeader('col1', 120, false),
        makeHeader('col2', 80, false),
      ];
      const table = makeTable({
        getHeaderGroups: () => [{ headers }],
        getFlatHeaders: () => headers,
      });
      render(<CustomTable table={table} />);
      const box = screen.getByTestId('table-box');
      expect(box.style.getPropertyValue('--header-col1-size')).toBe('120px');
      expect(box.style.getPropertyValue('--header-col2-size')).toBe('80px');
    });

    it('does not inject CSS custom properties for grow columns', () => {
      const headers = [
        makeHeader('col1', 100, false),
        makeHeader('grow-col', 500, true, 80),
      ];
      const table = makeTable({
        getHeaderGroups: () => [{ headers }],
        getFlatHeaders: () => headers,
      });
      render(<CustomTable table={table} />);
      const box = screen.getByTestId('table-box');
      expect(box.style.getPropertyValue('--header-grow-col-size')).toBe('');
      expect(box.style.getPropertyValue('--header-col1-size')).toBe('100px');
    });
  });

  // ── Props forwarding ───────────────────────────────────────────────────────

  describe('props forwarding', () => {
    it('passes headerPinned to CustomTableHeader', () => {
      render(<CustomTable table={makeTable({ headerPinned: true })} />);
      const header = screen.getByTestId('custom-table-header');
      expect(header.dataset.headerPinned).toBe('true');
    });

    it('passes enableDragDrop to CustomTableHeader', () => {
      render(<CustomTable table={makeTable({ enableDragDrop: true })} />);
      const header = screen.getByTestId('custom-table-header');
      expect(header.dataset.enableDragDrop).toBe('true');
    });

    it('passes enableDragDrop to CustomTableBody', () => {
      render(<CustomTable table={makeTable({ enableDragDrop: true })} />);
      const body = screen.getByTestId('custom-table-body');
      expect(body.dataset.enableDragDrop).toBe('true');
    });

    it('passes false for enableDragDrop by default', () => {
      render(<CustomTable table={makeTable()} />);
      expect(
        screen.getByTestId('custom-table-header').dataset.enableDragDrop
      ).toBe('false');
      expect(
        screen.getByTestId('custom-table-body').dataset.enableDragDrop
      ).toBe('false');
    });
  });
});
