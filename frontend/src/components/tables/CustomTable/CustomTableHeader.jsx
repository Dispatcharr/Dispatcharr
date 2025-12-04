import { Box, Center, Checkbox, Flex } from '@mantine/core';
import { flexRender } from '@tanstack/react-table';
import { useCallback, useMemo } from 'react';

const CustomTableHeader = ({
  getHeaderGroups,
  allRowIds,
  selectedTableIds,
  headerCellRenderFns,
  onSelectAllChange,
  tableCellProps,
}) => {
  const renderHeaderCell = (header) => {
    if (headerCellRenderFns[header.id]) {
      return headerCellRenderFns[header.id](header);
    }

    switch (header.id) {
      case 'select':
        return (
          <Center style={{ width: '100%' }}>
            <Checkbox
              size="xs"
              checked={
                allRowIds.length == 0
                  ? false
                  : selectedTableIds.length == allRowIds.length
              }
              indeterminate={
                selectedTableIds.length > 0 &&
                selectedTableIds.length !== allRowIds.length
              }
              onChange={onSelectAllChange}
            />
          </Center>
        );

      default:
        return flexRender(header.column.columnDef.header, header.getContext());
    }
  };

  // Get header groups for dependency tracking
  const headerGroups = getHeaderGroups();

  // Calculate minimum width based only on fixed-size columns
  const minTableWidth = useMemo(() => {
    if (!headerGroups || headerGroups.length === 0) return 0;

    const width =
      headerGroups[0]?.headers.reduce((total, header) => {
        // Only count columns with fixed sizes, flexible columns will expand
        const columnSize = header.column.columnDef.size
          ? header.getSize()
          : header.column.columnDef.minSize || 150; // Default min for flexible columns
        return total + columnSize;
      }, 0) || 0;

    return width;
  }, [headerGroups]);

  return (
    <Box
      className="thead"
      style={{
        position: 'sticky',
        top: 0,
        backgroundColor: '#3E3E45',
        zIndex: 10,
      }}
    >
      {getHeaderGroups().map((headerGroup) => (
        <Box
          className="tr"
          key={headerGroup.id}
          style={{
            display: 'flex',
            width: '100%',
            minWidth: '100%', // Force full width
          }}
        >
          {headerGroup.headers.map((header) => {
            return (
              <Box
                className="th"
                key={header.id}
                style={{
                  ...(header.column.columnDef.grow
                    ? {
                        flex: '1 1 0%',
                        minWidth: 0,
                      }
                    : {
                        flex: `0 0 ${header.getSize ? header.getSize() : 150}px`,
                        width: `${header.getSize ? header.getSize() : 150}px`,
                        maxWidth: `${header.getSize ? header.getSize() : 150}px`,
                      }),
                  position: 'relative',
                  // ...(tableCellProps && tableCellProps({ cell: header })),
                }}
              >
                <Flex
                  align="center"
                  style={{
                    ...(header.column.columnDef.style &&
                      header.column.columnDef.style),
                    height: '100%',
                    width: '100%',
                    paddingRight: header.column.getCanResize() ? '8px' : '0px', // Add padding for resize handle
                  }}
                >
                  {renderHeaderCell(header)}
                </Flex>
                {header.column.getCanResize() && (
                  <div
                    onMouseDown={header.getResizeHandler()}
                    onTouchStart={header.getResizeHandler()}
                    className={`resizer ${
                      header.column.getIsResizing() ? 'isResizing' : ''
                    }`}
                    style={{
                      position: 'absolute',
                      right: 0,
                      top: 0,
                      height: '100%',
                      width: '8px', // Make it slightly wider
                      cursor: 'col-resize',
                      userSelect: 'none',
                      touchAction: 'none',
                      backgroundColor: header.column.getIsResizing()
                        ? '#3b82f6'
                        : 'transparent',
                      opacity: header.column.getIsResizing() ? 1 : 0.3, // Make it more visible by default
                      transition: 'opacity 0.2s',
                      zIndex: 1000, // Ensure it's on top
                    }}
                    onMouseEnter={(e) => {
                      e.target.style.opacity = '1';
                      e.target.style.backgroundColor = '#6b7280';
                    }}
                    onMouseLeave={(e) => {
                      if (!header.column.getIsResizing()) {
                        e.target.style.opacity = '0.5';
                        e.target.style.backgroundColor = 'transparent';
                      }
                    }}
                  />
                )}
              </Box>
            );
          })}
        </Box>
      ))}
    </Box>
  );
};

export default CustomTableHeader;
