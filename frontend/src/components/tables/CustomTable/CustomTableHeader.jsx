import { Box, Center, Checkbox, Flex } from '@mantine/core';
import { flexRender } from '@tanstack/react-table';
import { RotateCcw } from 'lucide-react';
import { useMemo } from 'react';
import MultiSelectHeaderWrapper from './MultiSelectHeaderWrapper';
import useChannelsTableStore from '../../../store/channelsTable';

const CustomTableHeader = ({
  getHeaderGroups,
  allRowIds,
  selectedTableIds,
  headerCellRenderFns,
  onSelectAllChange,
  tableCellProps,
  headerPinned = true,
  enableDragDrop = false,
  onResetColumnSizing,
}) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const shouldEnableDrag = enableDragDrop && isUnlocked;
  const handleResizeStart = (event, resizeHandler) => {
    event.preventDefault();
    document.body.style.userSelect = 'none';
    document.body.style.webkitUserSelect = 'none';

    const restoreSelection = () => {
      document.body.style.removeProperty('user-select');
      document.body.style.removeProperty('-webkit-user-select');
    };
    window.addEventListener('mouseup', restoreSelection, { once: true });
    window.addEventListener('touchend', restoreSelection, { once: true });
    window.addEventListener('touchcancel', restoreSelection, { once: true });
    resizeHandler(event);
  };
  const renderHeaderCell = (header) => {
    let content;

    if (headerCellRenderFns[header.id]) {
      content = headerCellRenderFns[header.id](header);
    } else {
      switch (header.id) {
        case 'select':
          content = (
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
          break;

        default:
          content = flexRender(
            header.column.columnDef.header,
            header.getContext()
          );
      }
    }

    // Automatically wrap content to enhance MultiSelect components
    return <MultiSelectHeaderWrapper>{content}</MultiSelectHeaderWrapper>;
  };

  // Memoize the style object to ensure it updates when headerPinned changes
  const headerStyle = useMemo(
    () => ({
      position: headerPinned ? 'sticky' : 'relative',
      top: headerPinned ? 0 : 'auto',
      backgroundColor: '#3E3E45',
      zIndex: headerPinned ? 10 : 1,
    }),
    [headerPinned]
  );

  return (
    <Box
      className="thead"
      style={headerStyle}
      data-header-pinned={headerPinned ? 'true' : 'false'}
    >
      {getHeaderGroups().map((headerGroup) => (
        <Box
          className="tr"
          key={headerGroup.id}
          style={{
            display: 'flex',
            width: '100%',
            minWidth: '100%', // Force full width
            paddingLeft: shouldEnableDrag ? 28 : 0,
          }}
        >
          {headerGroup.headers.map((header) => {
            return (
              <Box
                className="th"
                key={header.id}
                data-column-id={header.column.id}
                style={{
                  boxSizing: 'border-box',
                  ...(header.column.columnDef.grow
                    ? {
                        flex: header.column.columnDef.flexRatio
                          ? `var(--header-${header.id}-ratio) 1 0%`
                          : `${header.column.columnDef.grow === true ? 1 : header.column.columnDef.grow} 1 0%`,
                        minWidth: 0,
                        ...(!header.column.columnDef.flexRatio &&
                          header.column.columnDef.maxSize && {
                          maxWidth: `${header.column.columnDef.maxSize}px`,
                          }),
                      }
                    : {
                        flex: `0 0 var(--header-${header.id}-size)`,
                        width: `var(--header-${header.id}-size)`,
                        maxWidth: `var(--header-${header.id}-size)`,
                      }),
                  position: 'relative',
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
                    onMouseDown={(event) =>
                      handleResizeStart(event, header.getResizeHandler())
                    }
                    onTouchStart={(event) =>
                      handleResizeStart(event, header.getResizeHandler())
                    }
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
                      WebkitUserSelect: 'none',
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
      {onResetColumnSizing && (
        <button
          type="button"
          aria-label="Reset Widths and Sorting"
          title="Reset Widths and Sorting"
          onClick={(event) => {
            event.stopPropagation();
            onResetColumnSizing();
          }}
          style={{
            position: 'absolute',
            top: 4,
            right: 4,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 24,
            height: 24,
            padding: 0,
            color: 'rgba(255, 255, 255, 0.45)',
            background: 'transparent',
            border: 0,
            cursor: 'pointer',
            zIndex: 11,
          }}
        >
          <RotateCcw size={14} />
        </button>
      )}
    </Box>
  );
};

export default CustomTableHeader;
