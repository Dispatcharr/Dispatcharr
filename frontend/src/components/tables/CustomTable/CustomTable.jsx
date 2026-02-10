import { Box, Flex } from '@mantine/core';
import CustomTableHeader from './CustomTableHeader';
import { useCallback, useState, useRef, useMemo } from 'react';
import CustomTableBody from './CustomTableBody';

const CustomTable = ({ table }) => {
  const tableSize = table?.tableSize ?? 'default';

  // Get column sizing state for dependency tracking
  const columnSizing = table.getState().columnSizing;

  // Calculate minimum table width reactively based on column sizes
  const minTableWidth = useMemo(() => {
    const headerGroups = table.getHeaderGroups();
    if (!headerGroups || headerGroups.length === 0) return 0;

    const width =
      headerGroups[0]?.headers.reduce((total, header) => {
        return total + header.getSize();
      }, 0) || 0;

    return width;
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
        getExpandedRowHeight={table.getExpandedRowHeight}
        getRowStyles={table.getRowStyles}
        tableBodyProps={table.tableBodyProps}
        tableCellProps={table.tableCellProps}
        enableDragDrop={table.enableDragDrop}
      />
    </Box>
  );
};

export default CustomTable;
