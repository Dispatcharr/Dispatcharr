import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../../store/channelsTable', () => ({ default: vi.fn() }));

// ── @dnd-kit/sortable ─────────────────────────────────────────────────────────
vi.mock('@dnd-kit/sortable', () => ({
  useSortable: vi.fn(() => ({
    attributes: { role: 'button' },
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  })),
}));

// ── @dnd-kit/utilities ────────────────────────────────────────────────────────
vi.mock('@dnd-kit/utilities', () => ({
  CSS: {
    Transform: {
      toString: vi.fn(() => ''),
    },
  },
}));

// ── @mantine/core ─────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Box: ({ children, className, style, onClick, onMouseDown, ...rest }) => (
    <div
      className={className}
      style={style}
      onClick={onClick}
      onMouseDown={onMouseDown}
      {...rest}
    >
      {children}
    </div>
  ),
  Flex: ({ children, align, style }) => (
    <div data-align={align} style={style}>
      {children}
    </div>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  GripVertical: ({ size, opacity }) => (
    <svg data-testid="grip-vertical" data-size={size} data-opacity={opacity} />
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useChannelsTableStore from '../../../../store/channelsTable';
import { useSortable } from '@dnd-kit/sortable';
import CustomTableBody from '../CustomTableBody';

// ── Helpers ────────────────────────────────────────────────────────────────────

const makeCell = (id, columnId, grow = false, maxSize = null) => ({
  id: `${id}-${columnId}`,
  column: {
    id: columnId,
    columnDef: {
      grow,
      ...(maxSize && { maxSize }),
    },
  },
});

const makeRow = (id, cells = [], originalId = null) => ({
  id: `row-${id}`,
  original: { id: originalId ?? id },
  getVisibleCells: () => cells,
});

const defaultProps = (overrides = {}) => {
  const row1 = makeRow(1, [makeCell(1, 'name'), makeCell(1, 'actions')]);
  const row2 = makeRow(2, [makeCell(2, 'name'), makeCell(2, 'actions')]);

  return {
    getRowModel: vi.fn(() => ({ rows: [row1, row2] })),
    expandedRowIds: [],
    expandedRowRenderer: vi.fn(() => <div data-testid="expanded-row" />),
    renderBodyCell: vi.fn(({ cell }) => (
      <span data-testid={`cell-${cell.id}`}>{cell.id}</span>
    )),
    getRowStyles: null,
    tableCellProps: null,
    enableDragDrop: false,
    selectedTableIdsSet: null,
    handleRowClickRef: null,
    ...overrides,
  };
};

const setupMocks = ({ isUnlocked = false } = {}) => {
  vi.mocked(useChannelsTableStore).mockImplementation((sel) =>
    sel({ isUnlocked })
  );
};

describe('CustomTableBody', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders a tbody container', () => {
      render(<CustomTableBody {...defaultProps()} />);
      expect(document.querySelector('.tbody')).toBeInTheDocument();
    });

    it('renders a row for each entry in getRowModel', () => {
      render(<CustomTableBody {...defaultProps()} />);
      expect(document.querySelectorAll('.tr')).toHaveLength(2);
    });

    it('renders no rows when getRowModel returns empty', () => {
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [] })),
      });
      render(<CustomTableBody {...props} />);
      expect(document.querySelectorAll('.tr')).toHaveLength(0);
    });

    it('applies tr-even class to even-indexed rows', () => {
      render(<CustomTableBody {...defaultProps()} />);
      const rows = document.querySelectorAll('.tr');
      expect(rows[0].classList.contains('tr-even')).toBe(true);
    });

    it('applies tr-odd class to odd-indexed rows', () => {
      render(<CustomTableBody {...defaultProps()} />);
      const rows = document.querySelectorAll('.tr');
      expect(rows[1].classList.contains('tr-odd')).toBe(true);
    });

    it('calls renderBodyCell for each visible cell', () => {
      const renderBodyCell = vi.fn(({ cell }) => <span>{cell.id}</span>);
      render(<CustomTableBody {...defaultProps({ renderBodyCell })} />);
      // 2 rows × 2 cells each = 4 calls
      expect(renderBodyCell).toHaveBeenCalledTimes(4);
    });

    it('renders td containers for each visible cell', () => {
      render(<CustomTableBody {...defaultProps()} />);
      expect(document.querySelectorAll('.td')).toHaveLength(4);
    });
  });

  // ── Row styles ─────────────────────────────────────────────────────────────

  describe('row styles', () => {
    it('applies custom className from getRowStyles', () => {
      const getRowStyles = vi.fn(() => ({ className: 'custom-row-class' }));
      render(<CustomTableBody {...defaultProps({ getRowStyles })} />);
      expect(document.querySelector('.custom-row-class')).toBeInTheDocument();
    });
  });

  // ── Row click ──────────────────────────────────────────────────────────────

  describe('row click', () => {
    it('calls handleRowClickRef.current with row id when row is clicked', () => {
      const handleRowClick = vi.fn();
      const handleRowClickRef = { current: handleRowClick };
      const row = makeRow(1, [makeCell(1, 'name')], 42);
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [row] })),
        handleRowClickRef,
      });
      render(<CustomTableBody {...props} />);
      fireEvent.click(document.querySelector('.tr'));
      expect(handleRowClick).toHaveBeenCalledWith(42, expect.any(Object));
    });

    it('does not throw when handleRowClickRef is null', () => {
      render(
        <CustomTableBody {...defaultProps({ handleRowClickRef: null })} />
      );
      expect(() =>
        fireEvent.click(document.querySelector('.tr'))
      ).not.toThrow();
    });

    it('prevents default on mousedown with shift key', () => {
      render(<CustomTableBody {...defaultProps()} />);
      const tr = document.querySelector('.tr');
      const event = new MouseEvent('mousedown', {
        shiftKey: true,
        bubbles: true,
      });
      const preventDefaultSpy = vi.spyOn(event, 'preventDefault');
      tr.dispatchEvent(event);
      expect(preventDefaultSpy).toHaveBeenCalled();
    });
  });

  // ── Expanded rows ──────────────────────────────────────────────────────────

  describe('expanded rows', () => {
    it('renders expanded row content when row is in expandedRowIds', () => {
      const row = makeRow(1, [makeCell(1, 'name')], 1);
      const expandedRowRenderer = vi.fn(() => (
        <div data-testid="expanded-content">Expanded!</div>
      ));
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [row] })),
        expandedRowIds: [1],
        expandedRowRenderer,
      });
      render(<CustomTableBody {...props} />);
      expect(screen.getByTestId('expanded-content')).toBeInTheDocument();
    });

    it('does not render expanded row content when row is not expanded', () => {
      const row = makeRow(1, [makeCell(1, 'name')], 1);
      const expandedRowRenderer = vi.fn(() => (
        <div data-testid="expanded-content">Expanded!</div>
      ));
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [row] })),
        expandedRowIds: [],
        expandedRowRenderer,
      });
      render(<CustomTableBody {...props} />);
      expect(screen.queryByTestId('expanded-content')).not.toBeInTheDocument();
    });

    it('calls expandedRowRenderer with the row when expanded', () => {
      const row = makeRow(1, [makeCell(1, 'name')], 1);
      const expandedRowRenderer = vi.fn(() => <div />);
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [row] })),
        expandedRowIds: [1],
        expandedRowRenderer,
      });
      render(<CustomTableBody {...props} />);
      expect(expandedRowRenderer).toHaveBeenCalledWith({ row });
    });
  });

  // ── Drag and drop ──────────────────────────────────────────────────────────

  describe('drag and drop', () => {
    it('does not render grip handle when enableDragDrop is false', () => {
      render(<CustomTableBody {...defaultProps({ enableDragDrop: false })} />);
      expect(screen.queryByTestId('grip-vertical')).not.toBeInTheDocument();
    });

    it('does not render grip handle when enableDragDrop is true but table is locked', () => {
      setupMocks({ isUnlocked: false });
      render(<CustomTableBody {...defaultProps({ enableDragDrop: true })} />);
      expect(screen.queryByTestId('grip-vertical')).not.toBeInTheDocument();
    });

    it('renders grip handle when enableDragDrop is true and table is unlocked', () => {
      setupMocks({ isUnlocked: true });
      vi.mocked(useSortable).mockReturnValue({
        attributes: { role: 'button' },
        listeners: {},
        setNodeRef: vi.fn(),
        transform: null,
        transition: null,
        isDragging: false,
      });
      const row = makeRow(1, [makeCell(1, 'name')], 1);
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [row] })),
        enableDragDrop: true,
      });
      render(<CustomTableBody {...props} />);
      expect(screen.getByTestId('grip-vertical')).toBeInTheDocument();
    });

    it('calls useSortable with row id', () => {
      const row = makeRow('abc', [makeCell(1, 'name')], 1);
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [row] })),
      });
      render(<CustomTableBody {...props} />);
      expect(useSortable).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'row-abc' })
      );
    });

    it('disables useSortable when enableDragDrop is false', () => {
      const row = makeRow(1, [makeCell(1, 'name')], 1);
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [row] })),
        enableDragDrop: false,
      });
      render(<CustomTableBody {...props} />);
      expect(useSortable).toHaveBeenCalledWith(
        expect.objectContaining({ disabled: true })
      );
    });
  });

  // ── Memoization comparator ─────────────────────────────────────────────────

  describe('MemoizedTableRow comparator', () => {
    it('does not re-render when row.original reference is unchanged', () => {
      const renderBodyCell = vi.fn(({ cell }) => <span>{cell.id}</span>);
      const original = { id: 1 };
      const row = { id: 'row-1', original, getVisibleCells: () => [] };
      const props = defaultProps({
        getRowModel: vi.fn(() => ({ rows: [row] })),
        renderBodyCell,
      });
      const { rerender } = render(<CustomTableBody {...props} />);
      const callCount = renderBodyCell.mock.calls.length;

      // Rerender with same original reference
      rerender(<CustomTableBody {...props} />);
      expect(renderBodyCell.mock.calls.length).toBe(callCount);
    });
  });
});
