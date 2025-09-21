import { Center, Checkbox } from '@mantine/core';
import CustomTable from './CustomTable';
import CustomTableHeader from './CustomTableHeader';

import {
  useReactTable,
  getCoreRowModel,
  flexRender,
} from '@tanstack/react-table';
import { useCallback, useMemo, useState, useEffect } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

const useTable = ({
  allRowIds,
  headerCellRenderFns = {},
  bodyCellRenderFns = {},
  expandedRowRenderer = () => <></>,
  onRowSelectionChange = null,
  getExpandedRowHeight = null,
  state = [],
  columnSizing,
  setColumnSizing,
  ...options
}) => {
  const [selectedTableIds, setSelectedTableIds] = useState([]);
  const [expandedRowIds, setExpandedRowIds] = useState([]);
  const [lastClickedId, setLastClickedId] = useState(null);
  const [isShiftKeyDown, setIsShiftKeyDown] = useState(false);

  // Event handlers for shift key detection with improved handling
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Shift') {
      setIsShiftKeyDown(true);
      // Apply the class to disable text selection immediately
      document.body.classList.add('shift-key-active');
      // Set a style attribute directly on body for extra assurance
      document.body.style.userSelect = 'none';
      document.body.style.webkitUserSelect = 'none';
      document.body.style.msUserSelect = 'none';
      document.body.style.cursor = 'pointer';
    }
  }, []);

  const handleKeyUp = useCallback((e) => {
    if (e.key === 'Shift') {
      setIsShiftKeyDown(false);
      // Remove the class when shift is released
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

    // Also detect blur/focus events to handle cases where shift is held and window loses focus
    window.addEventListener('blur', () => {
      setIsShiftKeyDown(false);
      document.body.classList.remove('shift-key-active');
      document.body.style.removeProperty('user-select');
      document.body.style.removeProperty('-webkit-user-select');
      document.body.style.removeProperty('-ms-user-select');
      document.body.style.removeProperty('cursor');
    });

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', () => {
        setIsShiftKeyDown(false);
        document.body.classList.remove('shift-key-active');
        document.body.style.removeProperty('user-select');
        document.body.style.removeProperty('-webkit-user-select');
        document.body.style.removeProperty('-ms-user-select');
        document.body.style.removeProperty('cursor');
      });
    };
  }, [handleKeyDown, handleKeyUp]);

  const rowCount = allRowIds.length;

  const table = useReactTable({
    defaultColumn: {
      minSize: 0,
      maxSize: Number.MAX_SAFE_INTEGER,
      size: 150,
    },
    ...options,
    state: {
      ...options.state,
      selectedTableIds,
      ...(columnSizing && { columnSizing }),
    },
    onStateChange: options.onStateChange,
    ...(setColumnSizing && { onColumnSizingChange: setColumnSizing }),
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

  const rowSelection = useMemo(() => {
    const selection = {};
    table.getRowModel().rows.forEach((row) => {
      if (selectedTableIdsSet.has(row.original.id)) {
        selection[row.id] = true;
      }
    });
    return selection;
  }, [selectedTableIdsSet, table.getRowModel().rows]);

  const onSelectAllChange = async (e) => {
    const selectAll = e.target.checked;
    if (selectAll) {
      updateSelectedTableIds(allRowIds);
    } else {
      updateSelectedTableIds([]);
    }
  };

  const onRowExpansion = (row) => {
    let isExpanded = false;
    setExpandedRowIds((prev) => {
      isExpanded = prev.includes(row.original.id) ? [] : [row.original.id];
      return isExpanded;
    });
    updateSelectedTableIds([row.original.id]);
  };

  // Handle the shift+click selection
  const handleShiftSelect = (rowId, isShiftKey) => {
    if (!isShiftKey || lastClickedId === null) {
      // Normal selection behavior
      setLastClickedId(rowId);
      return false; // Return false to indicate we're not handling it
    }

    // Handle shift-click range selection
    const currentIndex = allRowIds.indexOf(rowId);
    const lastIndex = allRowIds.indexOf(lastClickedId);

    if (currentIndex === -1 || lastIndex === -1) return false;

    // Determine range
    const startIndex = Math.min(currentIndex, lastIndex);
    const endIndex = Math.max(currentIndex, lastIndex);
    const rangeIds = allRowIds.slice(startIndex, endIndex + 1);

    // Preserve existing selections outside the range
    const idsOutsideRange = selectedTableIds.filter(
      (id) => !rangeIds.includes(id)
    );
    const newSelection = [...new Set([...rangeIds, ...idsOutsideRange])];
    updateSelectedTableIds(newSelection);

    setLastClickedId(rowId);
    return true; // Return true to indicate we've handled it
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
                  const newSet = new Set(selectedTableIds);
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
            onClick={() => {
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
      rowSelection,
      allRowIds,
      onSelectAllChange,
      selectedTableIdsSet,
      expandedRowIds,
      expandedRowRenderer,
      setSelectedTableIds,
      isShiftKeyDown, // Include shift key state in the table instance
    }),
    [selectedTableIdsSet, expandedRowIds, allRowIds, isShiftKeyDown]
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
