import React from 'react';
import {
  renderHook,
  act,
  render,
  fireEvent,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── @tanstack/react-table ──────────────────────────────────────────────────────
vi.mock('@tanstack/react-table', () => ({
  getCoreRowModel: vi.fn(() => 'mock-core-row-model'),
  useReactTable: vi.fn(),
  flexRender: vi.fn(() => <span data-testid="flex-rendered" />),
}));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../../hooks/useTablePreferences', () => ({
  default: vi.fn(),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../CustomTable', () => ({
  default: () => <div data-testid="custom-table" />,
}));

vi.mock('../CustomTableHeader', () => ({
  default: () => <div data-testid="custom-table-header" />,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Center: ({ children, style, onClick }) => (
    <div data-testid="center" style={style} onClick={onClick}>
      {children}
    </div>
  ),
  Checkbox: ({ checked, onChange }) => (
    <input
      type="checkbox"
      data-testid="checkbox"
      checked={!!checked}
      onChange={onChange || (() => {})}
    />
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ChevronDown: () => <svg data-testid="icon-chevron-down" />,
  ChevronRight: () => <svg data-testid="icon-chevron-right" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import { useTable } from '../';
import { useReactTable, flexRender } from '@tanstack/react-table';
import useTablePreferences from '../../../../hooks/useTablePreferences';

// ── Helpers ────────────────────────────────────────────────────────────────────
const setupMocks = ({ headerPinned = false, tableSize = 'default' } = {}) => {
  vi.mocked(useReactTable).mockReturnValue({
    getRowModel: vi.fn(() => ({ rows: [] })),
    getHeaderGroups: vi.fn(() => []),
  });
  vi.mocked(useTablePreferences).mockReturnValue({
    headerPinned,
    setHeaderPinned: vi.fn(),
    tableSize,
    setTableSize: vi.fn(),
  });
};

const makeRow = (id) => ({ original: { id } });

const makeCell = (columnId) => ({
  column: { id: columnId, columnDef: {} },
  getContext: () => ({}),
});

const makeClickEvent = (overrides = {}) => ({
  shiftKey: false,
  ctrlKey: false,
  metaKey: false,
  target: { closest: () => null },
  ...overrides,
});

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('useTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    // Clean up any body class/style mutations made by keyboard handlers
    document.body.classList.remove('shift-key-active');
    document.body.style.removeProperty('user-select');
    document.body.style.removeProperty('-webkit-user-select');
    document.body.style.removeProperty('-ms-user-select');
    document.body.style.removeProperty('cursor');
  });

  // ── Initialization ─────────────────────────────────────────────────────────

  describe('initialization', () => {
    it('starts with an empty selectedTableIds array', () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2], columns: [], data: [] })
      );
      expect(result.current.selectedTableIds).toEqual([]);
    });

    it('starts with an empty expandedRowIds array', () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2], columns: [], data: [] })
      );
      expect(result.current.expandedRowIds).toEqual([]);
    });

    it('returns renderBodyCell as a function', () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [], columns: [], data: [] })
      );
      expect(typeof result.current.renderBodyCell).toBe('function');
    });

    it('exposes allRowIds in the returned object', () => {
      setupMocks();
      const allRowIds = [10, 20, 30];
      const { result } = renderHook(() =>
        useTable({ allRowIds, columns: [], data: [] })
      );
      expect(result.current.allRowIds).toEqual(allRowIds);
    });

    it('returns headerPinned and tableSize from useTablePreferences', () => {
      setupMocks({ headerPinned: true, tableSize: 'compact' });
      const { result } = renderHook(() =>
        useTable({ allRowIds: [], columns: [], data: [] })
      );
      expect(result.current.headerPinned).toBe(true);
      expect(result.current.tableSize).toBe('compact');
    });

    it('passes headerCellRenderFns through to the returned object', () => {
      setupMocks();
      const headerCellRenderFns = { name: vi.fn() };
      const { result } = renderHook(() =>
        useTable({ allRowIds: [], columns: [], data: [], headerCellRenderFns })
      );
      expect(result.current.headerCellRenderFns).toBe(headerCellRenderFns);
    });

    it('defaults to an empty bodyCellRenderFns when not provided', () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [], columns: [], data: [] })
      );
      expect(result.current.bodyCellRenderFns).toEqual({});
    });
  });

  describe('paired column sizing', () => {
    const pairedColumnSizing = [
      { id: 'name', size: 200, minSize: 100 },
      { id: 'epg', size: 200, minSize: 120 },
      { id: 'group', size: 200, minSize: 120 },
    ];

    const getSizingUpdater = (nextSizing) => {
      setupMocks();
      const setColumnSizing = vi.fn();
      renderHook(() =>
        useTable({
          allRowIds: [],
          columns: [],
          data: [],
          columnSizing: {},
          setColumnSizing,
          pairedColumnSizing,
          tableId: 'test-table',
        })
      );

      const tableOptions = vi.mocked(useReactTable).mock.calls.at(-1)[0];
      act(() => {
        tableOptions.onColumnSizingChange(nextSizing);
      });
      return setColumnSizing.mock.calls[0][0];
    };

    it('transfers a resize delta only to the adjacent paired column', () => {
      const updateSizing = getSizingUpdater((current) => ({
        ...current,
        name: 250,
      }));

      expect(updateSizing({})).toMatchObject({ name: 250, epg: 150 });
    });

    it('clamps a drag that would cross an adjacent column minimum', () => {
      const updateSizing = getSizingUpdater((current) => ({
        ...current,
        name: 400,
      }));

      expect(updateSizing({})).toEqual({
        name: 280,
        epg: 120,
        group: 200,
      });
    });

    it('measures paired header widths once per drag', () => {
      setupMocks();
      const setColumnSizing = vi.fn();
      const querySpy = vi.spyOn(document, 'querySelector').mockReturnValue({
        getBoundingClientRect: () => ({ width: 200 }),
      });

      renderHook(() =>
        useTable({
          allRowIds: [],
          columns: [],
          data: [],
          columnSizing: {},
          setColumnSizing,
          pairedColumnSizing,
          tableId: 'test-table',
        })
      );

      const tableOptions = vi.mocked(useReactTable).mock.calls.at(-1)[0];
      act(() => {
        tableOptions.onColumnSizingChange((current) => ({
          ...current,
          name: 220,
        }));
      });
      setColumnSizing.mock.calls[0][0]({});

      act(() => {
        tableOptions.onColumnSizingChange((current) => ({
          ...current,
          name: 240,
        }));
      });
      setColumnSizing.mock.calls[1][0]({
        name: 220,
        epg: 180,
        group: 200,
      });

      // Three paired columns measured on the first tick only.
      expect(querySpy).toHaveBeenCalledTimes(3);
      querySpy.mockRestore();
    });
  });

  describe('column resize preview', () => {
    const mountPreviewTable = ({ withTableId = true } = {}) => {
      const tableElement = document.createElement('div');
      tableElement.className = 'divTable';
      if (withTableId) {
        tableElement.setAttribute('data-table-id', 'preview-table');
      }
      tableElement.getBoundingClientRect = () => ({ top: 0, bottom: 100 });

      const header = document.createElement('div');
      header.className = 'thead';
      const headerCell = document.createElement('div');
      headerCell.setAttribute('data-column-id', 'name');
      headerCell.getBoundingClientRect = () => ({ width: 200 });
      const neighborHeaderCell = document.createElement('div');
      neighborHeaderCell.setAttribute('data-column-id', 'epg');
      neighborHeaderCell.getBoundingClientRect = () => ({ width: 200 });
      header.append(headerCell, neighborHeaderCell);

      const body = document.createElement('div');
      body.className = 'tbody';
      const visibleRow = document.createElement('div');
      visibleRow.className = 'native-table-row';
      visibleRow.getBoundingClientRect = () => ({ top: 20, bottom: 60 });
      const hiddenRow = document.createElement('div');
      hiddenRow.className = 'native-table-row';
      hiddenRow.getBoundingClientRect = () => ({ top: 120, bottom: 160 });
      const visibleCell = document.createElement('div');
      visibleCell.setAttribute('data-column-id', 'name');
      const hiddenCell = document.createElement('div');
      hiddenCell.setAttribute('data-column-id', 'name');
      const visibleNeighborCell = document.createElement('div');
      visibleNeighborCell.setAttribute('data-column-id', 'epg');
      visibleRow.append(visibleCell, visibleNeighborCell);
      hiddenRow.append(hiddenCell);
      body.append(visibleRow, hiddenRow);
      tableElement.append(header, body);
      document.body.appendChild(tableElement);

      return {
        tableElement,
        headerCell,
        neighborHeaderCell,
        visibleCell,
        visibleNeighborCell,
        hiddenCell,
      };
    };

    const makePreviewEvent = (tableElement, clientX) => ({
      currentTarget: {
        closest: (selector) => {
          if (selector === '[data-table-id]') {
            return tableElement.hasAttribute('data-table-id')
              ? tableElement
              : null;
          }
          if (selector === '.divTable') {
            return tableElement;
          }
          return null;
        },
      },
      clientX,
      touches: undefined,
      preventDefault: vi.fn(),
    });

    const nameHeader = {
      column: {
        id: 'name',
        columnDef: { minSize: 40, maxSize: 400 },
      },
      getSize: () => 120,
    };

    afterEach(() => {
      document.body.replaceChildren();
    });

    it('previews direct widths only on the header and visible row cells', () => {
      setupMocks();
      const { tableElement, headerCell, visibleCell, hiddenCell } =
        mountPreviewTable();
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [],
          columns: [],
          data: [],
          columnSizing: { name: 120 },
          setColumnSizing: vi.fn(),
          tableId: 'preview-table',
        })
      );

      act(() => {
        result.current.onColumnResizePreview(
          nameHeader,
          makePreviewEvent(tableElement, 100)
        );
        fireEvent.mouseMove(window, { clientX: 140 });
      });

      expect(headerCell.style.width).toBe('160px');
      expect(visibleCell.style.width).toBe('160px');
      expect(hiddenCell.style.width).toBe('');
      expect(tableElement.style.getPropertyValue('--header-name-size')).toBe(
        ''
      );
    });

    it('restores preview styles and scroll position when resizing ends', () => {
      setupMocks();
      const { tableElement, headerCell, visibleCell } = mountPreviewTable();
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [],
          columns: [],
          data: [],
          columnSizing: { name: 120 },
          setColumnSizing: vi.fn(),
          tableId: 'preview-table',
        })
      );
      tableElement.scrollTop = 75;

      act(() => {
        result.current.onColumnResizePreview(
          nameHeader,
          makePreviewEvent(tableElement, 100)
        );
        fireEvent.mouseMove(window, { clientX: 140 });
        tableElement.scrollTop = 0;
        fireEvent.scroll(tableElement);
      });

      expect(tableElement.scrollTop).toBe(75);
      act(() => {
        fireEvent.mouseUp(window);
      });
      expect(headerCell.style.width).toBe('');
      expect(visibleCell.style.width).toBe('');
    });

    it('previews paired columns by updating their direct flex styles', () => {
      setupMocks();
      const {
        tableElement,
        headerCell,
        neighborHeaderCell,
        visibleCell,
        visibleNeighborCell,
      } = mountPreviewTable();
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [],
          columns: [],
          data: [],
          columnSizing: { name: 200, epg: 200 },
          setColumnSizing: vi.fn(),
          pairedColumnSizing: [
            { id: 'name', size: 200, minSize: 100 },
            { id: 'epg', size: 200, minSize: 100 },
          ],
          tableId: 'preview-table',
        })
      );

      act(() => {
        result.current.onColumnResizePreview(
          {
            column: {
              id: 'name',
              columnDef: { flexRatio: true, minSize: 100 },
            },
            getSize: () => 200,
          },
          makePreviewEvent(tableElement, 100)
        );
        fireEvent.mouseMove(window, { clientX: 150 });
      });

      expect(headerCell.style.flex).toBe('250 1 0%');
      expect(visibleCell.style.flex).toBe('250 1 0%');
      expect(neighborHeaderCell.style.flex).toBe('150 1 0%');
      expect(visibleNeighborCell.style.flex).toBe('150 1 0%');
    });

    it('finds a table through its divTable class when no table id is set', () => {
      setupMocks();
      const { tableElement, headerCell } = mountPreviewTable({
        withTableId: false,
      });
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [],
          columns: [],
          data: [],
          columnSizing: { name: 120 },
          setColumnSizing: vi.fn(),
        })
      );

      act(() => {
        result.current.onColumnResizePreview(
          nameHeader,
          makePreviewEvent(tableElement, 100)
        );
        fireEvent.mouseMove(window, { clientX: 140 });
      });

      expect(headerCell.style.width).toBe('160px');
    });
  });

  // ── Keyboard event handling ────────────────────────────────────────────────

  describe('keyboard event handling', () => {
    it('adds shift-key-active class and disables text selection on Shift keydown', () => {
      setupMocks();
      renderHook(() => useTable({ allRowIds: [], columns: [], data: [] }));

      fireEvent.keyDown(window, { key: 'Shift' });

      expect(document.body.classList.contains('shift-key-active')).toBe(true);
      expect(document.body.style.userSelect).toBe('none');
    });

    it('removes shift-key-active class and restores text selection on Shift keyup', () => {
      setupMocks();
      renderHook(() => useTable({ allRowIds: [], columns: [], data: [] }));

      fireEvent.keyDown(window, { key: 'Shift' });
      fireEvent.keyUp(window, { key: 'Shift' });

      expect(document.body.classList.contains('shift-key-active')).toBe(false);
      expect(document.body.style.userSelect).toBe('');
    });

    it('removes shift-key-active class on window blur', () => {
      setupMocks();
      renderHook(() => useTable({ allRowIds: [], columns: [], data: [] }));

      fireEvent.keyDown(window, { key: 'Shift' });
      fireEvent.blur(window);

      expect(document.body.classList.contains('shift-key-active')).toBe(false);
    });

    it('does not add shift-key-active class for non-Shift keydown', () => {
      setupMocks();
      renderHook(() => useTable({ allRowIds: [], columns: [], data: [] }));

      fireEvent.keyDown(window, { key: 'a' });

      expect(document.body.classList.contains('shift-key-active')).toBe(false);
    });
  });

  // ── onSelectAllChange ──────────────────────────────────────────────────────

  describe('onSelectAllChange', () => {
    it('selects all allRowIds when checked', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2, 3], columns: [], data: [] })
      );

      await act(async () => {
        result.current.onSelectAllChange({ target: { checked: true } });
      });

      expect(result.current.selectedTableIds).toEqual([1, 2, 3]);
    });

    it('clears selectedTableIds when unchecked', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2, 3], columns: [], data: [] })
      );

      await act(async () => {
        result.current.onSelectAllChange({ target: { checked: true } });
      });
      await act(async () => {
        result.current.onSelectAllChange({ target: { checked: false } });
      });

      expect(result.current.selectedTableIds).toEqual([]);
    });

    it('calls onRowSelectionChange callback with all ids when selecting all', async () => {
      setupMocks();
      const onRowSelectionChange = vi.fn();
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [1, 2],
          columns: [],
          data: [],
          onRowSelectionChange,
        })
      );

      await act(async () => {
        result.current.onSelectAllChange({ target: { checked: true } });
      });

      expect(onRowSelectionChange).toHaveBeenCalledWith([1, 2]);
    });

    it('calls onRowSelectionChange with empty array when deselecting all', async () => {
      setupMocks();
      const onRowSelectionChange = vi.fn();
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [1, 2],
          columns: [],
          data: [],
          onRowSelectionChange,
        })
      );

      await act(async () => {
        result.current.onSelectAllChange({ target: { checked: true } });
      });
      await act(async () => {
        result.current.onSelectAllChange({ target: { checked: false } });
      });

      expect(onRowSelectionChange).toHaveBeenLastCalledWith([]);
    });
  });

  // ── updateSelectedTableIds ─────────────────────────────────────────────────

  describe('updateSelectedTableIds', () => {
    it('updates selectedTableIds to the given array', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2, 3], columns: [], data: [] })
      );

      await act(async () => {
        result.current.updateSelectedTableIds([2, 3]);
      });

      expect(result.current.selectedTableIds).toEqual([2, 3]);
    });

    it('calls onRowSelectionChange with the new ids', async () => {
      setupMocks();
      const onRowSelectionChange = vi.fn();
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [1, 2, 3],
          columns: [],
          data: [],
          onRowSelectionChange,
        })
      );

      await act(async () => {
        result.current.updateSelectedTableIds([1]);
      });

      expect(onRowSelectionChange).toHaveBeenCalledWith([1]);
    });

    it('does not throw when onRowSelectionChange is not provided', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1], columns: [], data: [] })
      );

      await expect(
        act(async () => result.current.updateSelectedTableIds([1]))
      ).resolves.not.toThrow();
    });
  });

  // ── handleRowClickRef ──────────────────────────────────────────────────────

  describe('handleRowClickRef', () => {
    it('does nothing when the click target is an interactive element', async () => {
      setupMocks();
      const onRowSelectionChange = vi.fn();
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [1],
          columns: [],
          data: [],
          onRowSelectionChange,
        })
      );

      const button = document.createElement('button');
      await act(async () => {
        result.current.handleRowClickRef.current(1, {
          shiftKey: true,
          ctrlKey: false,
          metaKey: false,
          target: {
            closest: (sel) => (sel.includes('button') ? button : null),
          },
        });
      });

      expect(onRowSelectionChange).not.toHaveBeenCalled();
    });

    it('ctrl+click adds an unselected row to selectedTableIds', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2, 3], columns: [], data: [] })
      );

      await act(async () => {
        result.current.handleRowClickRef.current(
          2,
          makeClickEvent({ ctrlKey: true })
        );
      });

      expect(result.current.selectedTableIds).toContain(2);
    });

    it('ctrl+click removes an already-selected row from selectedTableIds', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2, 3], columns: [], data: [] })
      );

      await act(async () => {
        result.current.updateSelectedTableIds([2]);
      });
      await act(async () => {
        result.current.handleRowClickRef.current(
          2,
          makeClickEvent({ ctrlKey: true })
        );
      });

      expect(result.current.selectedTableIds).not.toContain(2);
    });

    it('meta+click adds an unselected row to selectedTableIds', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2, 3], columns: [], data: [] })
      );

      await act(async () => {
        result.current.handleRowClickRef.current(
          3,
          makeClickEvent({ metaKey: true })
        );
      });

      expect(result.current.selectedTableIds).toContain(3);
    });

    it('plain click (no modifier key) does not change selection', async () => {
      setupMocks();
      const onRowSelectionChange = vi.fn();
      const { result } = renderHook(() =>
        useTable({
          allRowIds: [1, 2],
          columns: [],
          data: [],
          onRowSelectionChange,
        })
      );

      await act(async () => {
        result.current.handleRowClickRef.current(1, makeClickEvent());
      });

      expect(onRowSelectionChange).not.toHaveBeenCalled();
    });

    it('shift+click selects the range between lastClickedId and the clicked row', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2, 3, 4, 5], columns: [], data: [] })
      );

      // Ctrl+click row 2 to establish lastClickedId
      await act(async () => {
        result.current.handleRowClickRef.current(
          2,
          makeClickEvent({ ctrlKey: true })
        );
      });
      // Shift+click row 4 to select range [2, 3, 4]
      await act(async () => {
        result.current.handleRowClickRef.current(
          4,
          makeClickEvent({ shiftKey: true })
        );
      });

      expect(result.current.selectedTableIds).toEqual(
        expect.arrayContaining([2, 3, 4])
      );
      expect(result.current.selectedTableIds).toHaveLength(3);
    });

    it('shift+click preserves rows selected outside the shift-click range', async () => {
      setupMocks();
      const { result } = renderHook(() =>
        useTable({ allRowIds: [1, 2, 3, 4, 5], columns: [], data: [] })
      );

      // Pre-select row 1 (will be outside the upcoming range)
      await act(async () => {
        result.current.updateSelectedTableIds([1]);
      });
      // Ctrl+click row 5 to set lastClickedId=5 (also adds 5 to selection)
      await act(async () => {
        result.current.handleRowClickRef.current(
          5,
          makeClickEvent({ ctrlKey: true })
        );
      });
      // Shift+click row 3 → range is [3, 4, 5]; row 1 is preserved
      await act(async () => {
        result.current.handleRowClickRef.current(
          3,
          makeClickEvent({ shiftKey: true })
        );
      });

      expect(result.current.selectedTableIds).toEqual(
        expect.arrayContaining([1, 3, 4, 5])
      );
    });
  });

  // ── renderBodyCell ─────────────────────────────────────────────────────────

  describe('renderBodyCell', () => {
    describe('bodyCellRenderFns override', () => {
      it('calls the custom render fn and renders its output for the matching column id', () => {
        setupMocks();
        const customRenderFn = vi.fn(
          () => <span data-testid="custom-cell" />
        );
        const { result } = renderHook(() =>
          useTable({
            allRowIds: [],
            columns: [],
            data: [],
            bodyCellRenderFns: { 'my-col': customRenderFn },
          })
        );

        const row = makeRow(1);
        const cell = makeCell('my-col');
        const { getByTestId } = render(
          result.current.renderBodyCell({ row, cell })
        );

        expect(customRenderFn).toHaveBeenCalledWith({ row, cell });
        expect(getByTestId('custom-cell')).toBeInTheDocument();
      });
    });

    describe('select column', () => {
      it('renders a Checkbox for the select column', () => {
        setupMocks();
        const { result } = renderHook(() =>
          useTable({ allRowIds: [1], columns: [], data: [] })
        );

        const { getByTestId } = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('select'),
          })
        );

        expect(getByTestId('checkbox')).toBeInTheDocument();
      });

      it('checkbox is unchecked for an unselected row', () => {
        setupMocks();
        const { result } = renderHook(() =>
          useTable({ allRowIds: [1], columns: [], data: [] })
        );

        const { getByTestId } = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('select'),
          })
        );

        expect(getByTestId('checkbox')).not.toBeChecked();
      });

      it('checkbox is checked when the row is pre-selected', async () => {
        setupMocks();
        const { result } = renderHook(() =>
          useTable({ allRowIds: [1], columns: [], data: [] })
        );

        await act(async () => {
          result.current.updateSelectedTableIds([1]);
        });

        const { getByTestId } = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('select'),
          })
        );

        expect(getByTestId('checkbox')).toBeChecked();
      });

      it('checking the checkbox adds the row to selectedTableIds', async () => {
        setupMocks();
        const tableRef = { current: null };

        function TestWrapper() {
          const table = useTable({ allRowIds: [1, 2], columns: [], data: [] });
          tableRef.current = table;
          return table.renderBodyCell({ row: makeRow(1), cell: makeCell('select') });
        }

        const user = userEvent.setup();
        const { getByTestId } = render(<TestWrapper />);

        await user.click(getByTestId('checkbox'));

        expect(tableRef.current.selectedTableIds).toContain(1);
      });

      it('unchecking the checkbox removes the row from selectedTableIds', async () => {
        setupMocks();
        const tableRef = { current: null };

        function TestWrapper() {
          const table = useTable({ allRowIds: [1, 2], columns: [], data: [] });
          tableRef.current = table;
          return table.renderBodyCell({ row: makeRow(1), cell: makeCell('select') });
        }

        const user = userEvent.setup();
        const { getByTestId } = render(<TestWrapper />);

        // Pre-select row 1 so checkbox renders as checked
        await act(async () => {
          tableRef.current.updateSelectedTableIds([1]);
        });

        // Click to uncheck
        await user.click(getByTestId('checkbox'));

        expect(tableRef.current.selectedTableIds).not.toContain(1);
      });

      it('checking a row does not affect other selected rows', async () => {
        setupMocks();
        const tableRef = { current: null };

        function TestWrapper() {
          const table = useTable({ allRowIds: [1, 2, 3], columns: [], data: [] });
          tableRef.current = table;
          return table.renderBodyCell({ row: makeRow(1), cell: makeCell('select') });
        }

        const user = userEvent.setup();
        const { getByTestId } = render(<TestWrapper />);

        // Pre-select rows 2 and 3
        await act(async () => {
          tableRef.current.updateSelectedTableIds([2, 3]);
        });

        // Check row 1
        await user.click(getByTestId('checkbox'));

        expect(tableRef.current.selectedTableIds).toEqual(
          expect.arrayContaining([1, 2, 3])
        );
      });
    });

    describe('expand column', () => {
      it('renders ChevronRight for a non-expanded row', () => {
        setupMocks();
        const { result } = renderHook(() =>
          useTable({ allRowIds: [1], columns: [], data: [] })
        );

        const { getByTestId, queryByTestId } = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('expand'),
          })
        );

        expect(getByTestId('icon-chevron-right')).toBeInTheDocument();
        expect(queryByTestId('icon-chevron-down')).not.toBeInTheDocument();
      });

      it('clicking the expand cell adds the row id to expandedRowIds', async () => {
        setupMocks();
        const { result } = renderHook(() =>
          useTable({ allRowIds: [1], columns: [], data: [] })
        );

        const rendered = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('expand'),
          })
        );

        await act(async () => {
          fireEvent.click(rendered.getByTestId('center'));
        });

        expect(result.current.expandedRowIds).toContain(1);
      });

      it('clicking an already-expanded row clears expandedRowIds', async () => {
        setupMocks();
        const { result } = renderHook(() =>
          useTable({ allRowIds: [1], columns: [], data: [] })
        );

        const rendered1 = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('expand'),
          })
        );
        await act(async () => {
          fireEvent.click(rendered1.getByTestId('center'));
        });
        expect(result.current.expandedRowIds).toEqual([1]);
        rendered1.unmount();

        // Click again to collapse
        const rendered2 = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('expand'),
          })
        );
        await act(async () => {
          fireEvent.click(rendered2.getByTestId('center'));
        });

        expect(result.current.expandedRowIds).toEqual([]);
      });

      it('shows ChevronDown after the row is expanded', async () => {
        setupMocks();
        const { result } = renderHook(() =>
          useTable({ allRowIds: [1], columns: [], data: [] })
        );

        // Expand the row
        const rendered1 = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('expand'),
          })
        );
        await act(async () => {
          fireEvent.click(rendered1.getByTestId('center'));
        });
        rendered1.unmount();

        // Re-render with updated state — should now show ChevronDown
        const rendered2 = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('expand'),
          })
        );
        expect(rendered2.getByTestId('icon-chevron-down')).toBeInTheDocument();
        expect(
          rendered2.queryByTestId('icon-chevron-right')
        ).not.toBeInTheDocument();
      });

      it('only one row can be expanded at a time (prior expanded row is collapsed)', async () => {
        setupMocks();
        const { result } = renderHook(() =>
          useTable({ allRowIds: [1, 2], columns: [], data: [] })
        );

        // Expand row 1
        const rendered1 = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('expand'),
          })
        );
        await act(async () => {
          fireEvent.click(rendered1.getByTestId('center'));
        });
        expect(result.current.expandedRowIds).toEqual([1]);
        rendered1.unmount();

        // Expand row 2 — row 1 should no longer be expanded
        const rendered2 = render(
          result.current.renderBodyCell({
            row: makeRow(2),
            cell: makeCell('expand'),
          })
        );
        await act(async () => {
          fireEvent.click(rendered2.getByTestId('center'));
        });

        expect(result.current.expandedRowIds).toEqual([2]);
      });

      it('calls onRowExpansionChange with the new expanded ids', async () => {
        setupMocks();
        const onRowExpansionChange = vi.fn();
        const { result } = renderHook(() =>
          useTable({
            allRowIds: [1],
            columns: [],
            data: [],
            onRowExpansionChange,
          })
        );

        const { getByTestId } = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('expand'),
          })
        );

        await act(async () => {
          fireEvent.click(getByTestId('center'));
        });

        expect(onRowExpansionChange).toHaveBeenCalledWith([1]);
      });
    });

    describe('default column', () => {
      it('calls flexRender for an unrecognized column id', () => {
        setupMocks();
        vi.mocked(flexRender).mockReturnValue(
          <span data-testid="flex-rendered" />
        );
        const { result } = renderHook(() =>
          useTable({ allRowIds: [], columns: [], data: [] })
        );

        const cell = makeCell('some-data-column');
        render(
          result.current.renderBodyCell({ row: makeRow(1), cell })
        );

        expect(flexRender).toHaveBeenCalledWith(
          cell.column.columnDef.cell,
          cell.getContext()
        );
      });

      it('renders the output returned by flexRender', () => {
        setupMocks();
        vi.mocked(flexRender).mockReturnValue(
          <span data-testid="flex-rendered" />
        );
        const { result } = renderHook(() =>
          useTable({ allRowIds: [], columns: [], data: [] })
        );

        const { getByTestId } = render(
          result.current.renderBodyCell({
            row: makeRow(1),
            cell: makeCell('data-col'),
          })
        );

        expect(getByTestId('flex-rendered')).toBeInTheDocument();
      });
    });
  });
});
