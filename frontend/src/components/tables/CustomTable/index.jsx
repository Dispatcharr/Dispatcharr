import { Center, Checkbox } from '@mantine/core';
import CustomTable from './CustomTable';
import CustomTableHeader from './CustomTableHeader';
import useTablePreferences from '../../../hooks/useTablePreferences';
import { flexRender, getCoreRowModel, useReactTable, } from '@tanstack/react-table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  findGrowResizeNeighbor,
  getColumnId,
  GROW_COLUMN_ACCOUNTING_SIZE,
  transferGrowColumnResize,
} from './transferGrowColumnResize';

const useTable = ({
  allRowIds,
  headerCellRenderFns = {},
  bodyCellRenderFns = {},
  expandedRowRenderer = () => <></>,
  onRowSelectionChange = null,
  onRowExpansionChange = null,
  getExpandedRowHeight = null,
  state = {},
  columnSizing,
  setColumnSizing,
  onColumnVisibilityChange,
  ...options
}) => {
  const [selectedTableIds, setSelectedTableIds] = useState([]);
  const selectedTableIdsRef = useRef(selectedTableIds);
  selectedTableIdsRef.current = selectedTableIds;
  const [expandedRowIds, setExpandedRowIds] = useState([]);
  const [lastClickedId, setLastClickedId] = useState(null);
  const lastClickedIdRef = useRef(lastClickedId);
  lastClickedIdRef.current = lastClickedId;
  const allRowIdsRef = useRef(allRowIds);
  allRowIdsRef.current = allRowIds;
  const handleRowClickRef = useRef(null);
  const columns = options.columns ?? [];
  const columnVisibility = state.columnVisibility;

  // Use shared table preferences hook
  const { headerPinned, setHeaderPinned, tableSize, setTableSize } =
    useTablePreferences();

  // Event handlers for shift key detection with improved handling
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Shift') {
      document.body.classList.add('shift-key-active');
      // Set a style attribute directly on body for extra assurance
      document.body.style.userSelect = 'none';
      document.body.style.webkitUserSelect = 'none';
      document.body.style.msUserSelect = 'none';
      document.body.style.cursor = 'default';
    }
  }, []);

  const handleKeyUp = useCallback((e) => {
    if (e.key === 'Shift') {
      document.body.classList.remove('shift-key-active');
      // Reset the style attributes
      document.body.style.removeProperty('user-select');
      document.body.style.removeProperty('-webkit-user-select');
      document.body.style.removeProperty('-ms-user-select');
      document.body.style.removeProperty('cursor');
    }
  }, []);

  // Add global event listeners for shift key detection with improved cleanup
  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    const handleBlur = () => {
      document.body.classList.remove('shift-key-active');
      document.body.style.removeProperty('user-select');
      document.body.style.removeProperty('-webkit-user-select');
      document.body.style.removeProperty('-ms-user-select');
      document.body.style.removeProperty('cursor');
    };
    window.addEventListener('blur', handleBlur);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
    };
  }, [handleKeyDown, handleKeyUp]);

  const resizeDragRef = useRef(null);

  const clearResizeDrag = useCallback(() => {
    const drag = resizeDragRef.current;
    resizeDragRef.current = null;
    if (!drag?.rebaseColumnId || !setColumnSizing) {
      return;
    }
    // Grow column size is only for TanStack delta accounting. Reset it after
    // each drag so the next drag has headroom in both directions without
    // changing the neighbor (layout ignores the grow column's size).
    setColumnSizing((previousSizing) => {
      if (previousSizing[drag.rebaseColumnId] === drag.rebaseSize) {
        return previousSizing;
      }
      return {
        ...previousSizing,
        [drag.rebaseColumnId]: drag.rebaseSize,
      };
    });
  }, [setColumnSizing]);

  const handleColumnSizingChange = useCallback(
    (updater) => {
      if (!setColumnSizing) {
        return;
      }

      setColumnSizing((previousSizing) => {
        const nextSizing =
          typeof updater === 'function' ? updater(previousSizing) : updater;

        const resizingColumn = columns.find((column) => {
          if (!column.transferResizeToNeighbor) {
            return false;
          }
          const id = getColumnId(column);
          if (!id) {
            return false;
          }
          const previousSize = previousSizing[id] ?? column.size ?? 0;
          const nextSize = nextSizing[id] ?? previousSize;
          return nextSize !== previousSize;
        });

        if (!resizingColumn) {
          return nextSizing;
        }

        const resizingColumnId = getColumnId(resizingColumn);
        const neighbor = findGrowResizeNeighbor(
          columns,
          resizingColumnId,
          columnVisibility
        );
        if (!neighbor) {
          return nextSizing;
        }

        const neighborId = getColumnId(neighbor);
        const defaults = {
          [resizingColumnId]: resizingColumn.size ?? 150,
          [neighborId]: neighbor.size ?? 150,
        };

        if (!resizeDragRef.current) {
          resizeDragRef.current = {
            columnId: resizingColumnId,
            sourceSize:
              previousSizing[resizingColumnId] ?? defaults[resizingColumnId],
            neighborSize: previousSizing[neighborId] ?? defaults[neighborId],
            rebaseColumnId: resizingColumn.grow ? resizingColumnId : null,
            rebaseSize: resizingColumn.grow
              ? GROW_COLUMN_ACCOUNTING_SIZE
              : null,
          };
          window.addEventListener('mouseup', clearResizeDrag, { once: true });
          window.addEventListener('touchend', clearResizeDrag, { once: true });
          window.addEventListener('touchcancel', clearResizeDrag, {
            once: true,
          });
        }

        const dragStart =
          resizeDragRef.current.columnId === resizingColumnId
            ? {
                sourceSize: resizeDragRef.current.sourceSize,
                neighborSize: resizeDragRef.current.neighborSize,
              }
            : null;

        return transferGrowColumnResize({
          previousSizing,
          nextSizing,
          growColumnId: resizingColumnId,
          neighborId,
          defaults,
          neighborMin: neighbor.minSize ?? 0,
          neighborMax: neighbor.maxSize ?? Number.POSITIVE_INFINITY,
          dragStart,
        });
      });
    },
    [clearResizeDrag, columnVisibility, columns, setColumnSizing]
  );

  const table = useReactTable({
    defaultColumn: {
      minSize: 0,
      maxSize: Number.MAX_SAFE_INTEGER,
      size: 150,
    },
    ...options,
    state: {
      ...state,
      selectedTableIds,
      ...(columnSizing && { columnSizing }),
    },
    autoResetPageIndex: false,
    autoResetExpanded: false,

    onStateChange: options.onStateChange,
    ...(setColumnSizing && { onColumnSizingChange: handleColumnSizingChange }),
    ...(onColumnVisibilityChange && { onColumnVisibilityChange }),
    getCoreRowModel: options.getCoreRowModel ?? getCoreRowModel(),
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
  });

  const selectedTableIdsSet = useMemo(
    () => new Set(selectedTableIds),
    [selectedTableIds]
  );

  const updateSelectedTableIds = (ids) => {
    setSelectedTableIds(ids);
    if (onRowSelectionChange) {
      onRowSelectionChange(ids);
    }
  };

  const onSelectAllChange = async (e) => {
    const selectAll = e.target.checked;
    if (selectAll) {
      updateSelectedTableIds(allRowIds);
    } else {
      updateSelectedTableIds([]);
    }
  };

  const onRowExpansion = (row) => {
    const rowId = row.original.id;
    let newIds;
    setExpandedRowIds((prev) => {
      newIds = prev.includes(rowId) ? [] : [rowId];
      return newIds;
    });
    if (onRowExpansionChange) {
      onRowExpansionChange(newIds);
    }
  };

  // Handle the shift+click selection
  const handleShiftSelect = (rowId, isShiftKey) => {
    if (!isShiftKey || lastClickedIdRef.current === null) {
      // Normal selection behavior
      setLastClickedId(rowId);
      return false; // Return false to indicate we're not handling it
    }

    // Handle shift-click range selection
    const currentIndex = allRowIdsRef.current.indexOf(rowId);
    const lastIndex = allRowIdsRef.current.indexOf(lastClickedIdRef.current);

    if (currentIndex === -1 || lastIndex === -1) return false;

    // Determine range
    const startIndex = Math.min(currentIndex, lastIndex);
    const endIndex = Math.max(currentIndex, lastIndex);
    const rangeIds = allRowIdsRef.current.slice(startIndex, endIndex + 1);

    // Preserve existing selections outside the range
    const idsOutsideRange = selectedTableIdsRef.current.filter(
      (id) => !rangeIds.includes(id)
    );
    const newSelection = [...new Set([...rangeIds, ...idsOutsideRange])];
    updateSelectedTableIds(newSelection);

    setLastClickedId(rowId);
    return true; // Return true to indicate we've handled it
  };

  handleRowClickRef.current = (rowId, e) => {
    if (
      e.target.closest(
        'button, a, input, select, textarea, [role="menuitem"], [role="option"], [role="button"]'
      )
    ) {
      return;
    }
    if (e.shiftKey) {
      handleShiftSelect(rowId, true);
    } else if (e.ctrlKey || e.metaKey) {
      const newSet = new Set(selectedTableIdsRef.current);
      if (newSet.has(rowId)) {
        newSet.delete(rowId);
      } else {
        newSet.add(rowId);
        setLastClickedId(rowId);
      }
      updateSelectedTableIds([...newSet]);
    }
  };

  const renderBodyCell = ({ row, cell }) => {
    if (bodyCellRenderFns[cell.column.id]) {
      return bodyCellRenderFns[cell.column.id]({ row, cell });
    }

    const isExpanded = expandedRowIds.includes(row.original.id);
    switch (cell.column.id) {
      case 'select':
        return (
          <Center style={{ width: '100%' }}>
            <Checkbox
              size="xs"
              checked={selectedTableIdsSet.has(row.original.id)}
              onChange={(e) => {
                const rowId = row.original.id;

                // Get shift key state from the event
                const isShiftKey = e.nativeEvent.shiftKey;

                // Try to handle with shift-select logic first
                if (!handleShiftSelect(rowId, isShiftKey)) {
                  // If not handled by shift-select, do regular toggle
                  const newSet = new Set(selectedTableIdsRef.current);
                  if (e.target.checked) {
                    newSet.add(rowId);
                  } else {
                    newSet.delete(rowId);
                  }
                  updateSelectedTableIds([...newSet]);
                }
              }}
            />
          </Center>
        );
      case 'expand':
        return (
          <Center
            style={{ width: '100%', cursor: 'pointer' }}
            onClick={(e) => {
              e.stopPropagation();
              onRowExpansion(row);
            }}
          >
            {isExpanded ? (
              <ChevronDown size={16} />
            ) : (
              <ChevronRight size={16} />
            )}
          </Center>
        );

      default:
        return flexRender(cell.column.columnDef.cell, cell.getContext());
    }
  };

  // Return both the table instance and your custom methods
  const tableInstance = useMemo(
    () => ({
      ...table,
      ...options,
      selectedTableIds,
      updateSelectedTableIds,
      allRowIds,
      onSelectAllChange,
      selectedTableIdsSet,
      expandedRowIds,
      expandedRowRenderer,
      setSelectedTableIds,
      handleRowClickRef,
      headerPinned,
      setHeaderPinned,
      tableSize,
      setTableSize,
    }),
    [
      selectedTableIdsSet,
      expandedRowIds,
      allRowIds,
      options,
      headerPinned,
      setHeaderPinned,
      tableSize,
      setTableSize,
    ]
  );

  return {
    ...tableInstance,
    headerCellRenderFns,
    bodyCellRenderFns,
    renderBodyCell,
    getExpandedRowHeight,
  };
};

export { useTable, CustomTable, CustomTableHeader };
