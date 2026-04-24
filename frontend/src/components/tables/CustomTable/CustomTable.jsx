import { Box, Flex } from '@mantine/core';
import CustomTableHeader from './CustomTableHeader';
import { useCallback, useState, useRef, useMemo } from 'react';
import CustomTableBody from './CustomTableBody';

const CustomTable = ({ table }) => {
  const tableSize = table?.tableSize ?? 'default';

  // columnSizing is read here so the memo below re-runs when columns are resized.
  const columnSizing = table.getState().columnSizing;

  // Calculate minimum table width reactively based on column sizes.
  // Grow columns contribute only their minSize (not TanStack's default 150px)
  // so the wrapper doesn't force the table wider than its container.
  const minTableWidth = useMemo(() => {
    void columnSizing; // reactive trigger: recalculate when column sizes change
    const headerGroups = table.getHeaderGroups();
    if (!headerGroups || headerGroups.length === 0) return 0;

    const width =
      headerGroups[0]?.headers.reduce((total, header) => {
        const colDef = header.column.columnDef;
        const size = colDef.grow ? colDef.minSize || 0 : header.getSize();
        return total + size;
      }, 0) || 0;

    return width;
  }, [table, columnSizing]);

  // CSS custom properties for each fixed-width column's current size.
  // These are injected on the table wrapper and cascade to all descendant cells,
  // so body cells (which are memoized and don't re-render on resize) still pick
  // up the new width via CSS cascade without needing a React re-render.
  const columnSizeVars = useMemo(() => {
    void columnSizing;
    return table.getFlatHeaders().reduce((vars, header) => {
      if (!header.column.columnDef.grow) {
        vars[`--header-${header.id}-size`] = `${header.getSize()}px`;
      }
      return vars;
    }, {});
  }, [table, columnSizing]);

  return (
    <Box
      className={`divTable table-striped table-size-${tableSize}`}
      style={{
        width: '100%',
        maxWidth: '100%',
        minWidth: `${minTableWidth}px`,
        display: 'flex',
        flexDirection: 'column',
        ...columnSizeVars,
      }}
    >
      <CustomTableHeader
        filters={table.filters}
        getHeaderGroups={table.getHeaderGroups}
        allRowIds={table.allRowIds}
        headerCellRenderFns={table.headerCellRenderFns}
        onSelectAllChange={
          table.onSelectAllChange ? table.onSelectAllChange : null
        }
        selectedTableIds={table.selectedTableIds}
        tableCellProps={table.tableCellProps}
        headerPinned={table.headerPinned}
        enableDragDrop={table.enableDragDrop}
      />
      <CustomTableBody
        getRowModel={table.getRowModel}
        bodyCellRenderFns={table.bodyCellRenderFns}
        expandedRowIds={table.expandedRowIds}
        expandedRowRenderer={table.expandedRowRenderer}
        renderBodyCell={table.renderBodyCell}
        getRowStyles={table.getRowStyles}
        tableCellProps={table.tableCellProps}
        enableDragDrop={table.enableDragDrop}
        selectedTableIdsSet={table.selectedTableIdsSet}
      />
    </Box>
  );
};

export default CustomTable;
