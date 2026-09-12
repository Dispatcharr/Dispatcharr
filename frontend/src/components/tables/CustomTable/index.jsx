import { Center, Checkbox } from '@mantine/core';
import CustomTable from './CustomTable';
import CustomTableHeader from './CustomTableHeader';
import useTablePreferences from '../../../hooks/useTablePreferences';
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

const useTable = ({
  allRowIds,
  headerCellRenderFns = {},
  bodyCellRenderFns = {},
  expandedRowRenderer = () => <></>,
  onRowSelectionChange = null,
  onRowExpansionChange = null,
  state = {},
  columnSizing,
  setColumnSizing,
  onColumnVisibilityChange,
  pairedColumnSizing,
  tableId,
  onResetColumnSizing,
  fillHeight = false,
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

  const pairedResizeMetricsRef = useRef(null);
  const resizePreviewCleanupRef = useRef(null);

  useEffect(() => {
    pairedResizeMetricsRef.current = null;
  }, [pairedColumnSizing, tableId]);

  const clearPairedResizeMetrics = useCallback(() => {
    pairedResizeMetricsRef.current = null;
  }, []);

  const handlePairedColumnSizingChange = useCallback(
    (updater) => {
      setColumnSizing((previousSizing) => {
        const nextSizing =
          typeof updater === 'function' ? updater(previousSizing) : updater;
        const columnIndex = pairedColumnSizing.findIndex(({ id, size }) => {
          return (nextSizing[id] ?? size) !== (previousSizing[id] ?? size);
        });

        if (
          columnIndex === -1 ||
          columnIndex === pairedColumnSizing.length - 1
        ) {
          return nextSizing;
        }

        const column = pairedColumnSizing[columnIndex];
        const neighbor = pairedColumnSizing[columnIndex + 1];
        const currentSizing = pairedColumnSizing.reduce(
          (sizes, pairedColumn) => {
            sizes[pairedColumn.id] =
              previousSizing[pairedColumn.id] ?? pairedColumn.size;
            return sizes;
          },
          {}
        );
        const totalRatio = Object.values(currentSizing).reduce(
          (total, ratio) => total + ratio,
          0
        );

        // Measure headers once per drag.
        let metrics = pairedResizeMetricsRef.current;
        if (!metrics) {
          const measuredWidths = pairedColumnSizing.map((pairedColumn) => {
            const header =
              typeof document === 'undefined'
                ? null
                : document.querySelector(
                    `[data-table-id="${tableId}"] [data-column-id="${pairedColumn.id}"]`
                  );
            return header?.getBoundingClientRect().width || 0;
          });
          const totalWidth = measuredWidths.reduce(
            (total, width) => total + width,
            0
          );
          metrics = {
            columnId: column.id,
            ratioPerPixel: totalWidth ? totalRatio / totalWidth : 1,
            startColumnSize: currentSizing[column.id],
            startNeighborSize: currentSizing[neighbor.id],
          };
          pairedResizeMetricsRef.current = metrics;
          window.addEventListener('mouseup', clearPairedResizeMetrics, {
            once: true,
          });
          window.addEventListener('touchend', clearPairedResizeMetrics, {
            once: true,
          });
          window.addEventListener('touchcancel', clearPairedResizeMetrics, {
            once: true,
          });
        }

        const { ratioPerPixel, startColumnSize, startNeighborSize } = metrics;
        const requestedSize = nextSizing[column.id] ?? column.size;
        const requestedRatioDelta =
          (requestedSize - startColumnSize) * ratioPerPixel;
        const getMinimum = (pairedColumn) =>
          pairedColumn.minRatio != null
            ? pairedColumn.minRatio * totalRatio
            : pairedColumn.minSize * ratioPerPixel;
        const getMaximum = (pairedColumn) =>
          pairedColumn.maxRatio != null
            ? pairedColumn.maxRatio * totalRatio
            : (pairedColumn.maxSize ?? Infinity) * ratioPerPixel;
        const maxGrowth = Math.min(
          getMaximum(column) - startColumnSize,
          startNeighborSize - getMinimum(neighbor)
        );
        const maxShrink = Math.min(
          startColumnSize - getMinimum(column),
          getMaximum(neighbor) - startNeighborSize
        );
        const delta = Math.max(
          -maxShrink,
          Math.min(requestedRatioDelta, maxGrowth)
        );

        if (delta === 0) {
          return previousSizing;
        }

        return {
          ...currentSizing,
          [column.id]: startColumnSize + delta,
          [neighbor.id]: startNeighborSize - delta,
        };
      });
    },
    [clearPairedResizeMetrics, pairedColumnSizing, setColumnSizing, tableId]
  );

  useEffect(
    () => () => {
      resizePreviewCleanupRef.current?.();
      clearPairedResizeMetrics();
    },
    [clearPairedResizeMetrics]
  );

  const onColumnResizePreview = useCallback((header, event) => {
    clearPairedResizeMetrics();
    resizePreviewCleanupRef.current?.();
    const tableElement =
      event.currentTarget.closest('[data-table-id]') ||
      event.currentTarget.closest('.divTable');
    const bodyElement = tableElement?.querySelector('.tbody');
    if (!tableElement || !bodyElement) return;
    const scrollElement = tableElement;

    const getClientX = (pointerEvent) =>
      pointerEvent.touches?.[0]?.clientX ?? pointerEvent.clientX;
    const clamp = (value, minimum, maximum) =>
      Math.max(minimum, Math.min(value, maximum));
    const startX = getClientX(event);
    const columnId = header.column.id;
    const bodyBounds = scrollElement.getBoundingClientRect();
    const visibleRows = Array.from(
      bodyElement.querySelectorAll('.native-table-row')
    )
      .filter((row) => {
        const bounds = row.getBoundingClientRect();
        return bounds.bottom > bodyBounds.top && bounds.top < bodyBounds.bottom;
      });
    const getPreviewCells = (id) => {
      const headerCell = tableElement.querySelector(
        `.thead [data-column-id="${id}"]`
      );
      return [
        headerCell,
        ...visibleRows.flatMap((row) =>
          Array.from(row.querySelectorAll(`[data-column-id="${id}"]`))
        ),
      ].filter(Boolean);
    };
    const pairedIndex = pairedColumnSizing?.findIndex(({ id }) => id === columnId);
    const pairedColumn =
      pairedIndex >= 0 ? pairedColumnSizing[pairedIndex] : null;
    const pairedNeighbor = pairedColumnSizing?.[pairedIndex + 1];
    let pairedMetrics;
    if (pairedColumn && pairedNeighbor) {
      const pairedSizing = pairedColumnSizing.map(
        (column) => columnSizing[column.id] ?? column.size
      );
      const totalRatio = pairedSizing.reduce((total, size) => total + size, 0);
      const totalWidth = pairedColumnSizing.reduce(
        (total, column) =>
          total +
          (tableElement.querySelector(
            `.thead [data-column-id="${column.id}"]`
          )?.getBoundingClientRect().width || 0),
        0
      );
      const ratioPerPixel = totalWidth ? totalRatio / totalWidth : 1;
      const getMinimum = (column) =>
        column.minRatio != null
          ? column.minRatio * totalRatio
          : column.minSize * ratioPerPixel;
      const getMaximum = (column) =>
        column.maxRatio != null
          ? column.maxRatio * totalRatio
          : (column.maxSize ?? Infinity) * ratioPerPixel;
      const activeRatio = pairedSizing[pairedIndex];
      const neighborRatio = pairedSizing[pairedIndex + 1];

      pairedMetrics = {
        activeRatio,
        neighborRatio,
        ratioPerPixel,
        maxGrowth: Math.min(
          getMaximum(pairedColumn) - activeRatio,
          neighborRatio - getMinimum(pairedNeighbor)
        ),
        maxShrink: Math.min(
          activeRatio - getMinimum(pairedColumn),
          getMaximum(pairedNeighbor) - neighborRatio
        ),
      };
    }

    const pairedCells = pairedMetrics && {
      active: getPreviewCells(pairedColumn.id),
      neighbor: getPreviewCells(pairedNeighbor.id),
    };
    const cells = pairedCells
      ? [...pairedCells.active, ...pairedCells.neighbor]
      : getPreviewCells(columnId);
    const originalStyles = cells.map((cell) => ({
      cell,
      flex: cell.style.flex,
      width: cell.style.width,
      maxWidth: cell.style.maxWidth,
    }));
    const initialScrollTop = scrollElement.scrollTop;
    let pendingX = startX;

    const updatePreview = () => {
      const pixelDelta = pendingX - startX;
      if (pairedMetrics) {
        const delta = clamp(
          pixelDelta * pairedMetrics.ratioPerPixel,
          -pairedMetrics.maxShrink,
          pairedMetrics.maxGrowth
        );
        for (const cell of pairedCells.active) {
          cell.style.flex = `${pairedMetrics.activeRatio + delta} 1 0%`;
        }
        for (const cell of pairedCells.neighbor) {
          cell.style.flex = `${pairedMetrics.neighborRatio - delta} 1 0%`;
        }
        return;
      }

      const size = clamp(
        header.getSize() + pixelDelta,
        header.column.columnDef.minSize ?? 0,
        header.column.columnDef.maxSize ?? Infinity
      );
      for (const cell of cells) {
        if (header.column.columnDef.flexRatio) {
          cell.style.flex = `${size} 1 0%`;
        } else {
          cell.style.flex = `0 0 ${size}px`;
          cell.style.width = `${size}px`;
          cell.style.maxWidth = `${size}px`;
        }
      }
    };
    const onMove = (moveEvent) => {
      moveEvent.preventDefault();
      pendingX = getClientX(moveEvent);
      updatePreview();
    };
    const preventScroll = (scrollEvent) => scrollEvent.preventDefault();
    const restoreScrollPosition = () => {
      scrollElement.scrollTop = initialScrollTop;
    };
    let isActive = true;
    const cleanup = () => {
      if (!isActive) return;
      isActive = false;
      for (const { cell, flex, width, maxWidth } of originalStyles) {
        cell.style.flex = flex;
        cell.style.width = width;
        cell.style.maxWidth = maxWidth;
      }
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('touchmove', onMove);
      window.removeEventListener('wheel', preventScroll);
      window.removeEventListener('blur', cleanup);
      scrollElement.removeEventListener('scroll', restoreScrollPosition);
      window.removeEventListener('mouseup', onEnd);
      window.removeEventListener('touchend', onEnd);
      window.removeEventListener('touchcancel', onEnd);
      resizePreviewCleanupRef.current = null;
    };
    const onEnd = () => cleanup();

    window.addEventListener('mousemove', onMove);
    window.addEventListener('touchmove', onMove, { passive: false });
    window.addEventListener('wheel', preventScroll, { passive: false });
    scrollElement.addEventListener('scroll', restoreScrollPosition);
    window.addEventListener('mouseup', onEnd, { once: true });
    window.addEventListener('touchend', onEnd, { once: true });
    window.addEventListener('touchcancel', onEnd, { once: true });
    window.addEventListener('blur', cleanup, { once: true });
    resizePreviewCleanupRef.current = cleanup;
  }, [clearPairedResizeMetrics, columnSizing, pairedColumnSizing]);

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
    ...(setColumnSizing && {
      onColumnSizingChange: pairedColumnSizing
        ? handlePairedColumnSizingChange
        : setColumnSizing,
    }),
    ...(onColumnVisibilityChange && { onColumnVisibilityChange }),
    getCoreRowModel: options.getCoreRowModel ?? getCoreRowModel(),
    enableColumnResizing: true,
    columnResizeMode: 'onEnd',
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
      tableId,
      onResetColumnSizing,
      fillHeight,
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
      tableId,
      onResetColumnSizing,
      fillHeight,
    ]
  );

  return {
    ...tableInstance,
    headerCellRenderFns,
    bodyCellRenderFns,
    renderBodyCell,
    onColumnResizePreview,
  };
};

export { useTable, CustomTable, CustomTableHeader };
