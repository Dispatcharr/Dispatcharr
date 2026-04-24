import { Box, Flex } from '@mantine/core';
import React, { useRef } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import useChannelsTableStore from '../../../store/channelsTable';

// Memoized row — only re-renders when this specific row's data, expansion
// state, or drag-drop config actually changes.  Callback functions are read
// from refs so the memoized row always uses the latest version when it *does*
// re-render, without needing them as comparator inputs.
const MemoizedTableRow = React.memo(
  ({
    row,
    index,
    isExpanded,
    isSelected,
    renderBodyCellRef,
    expandedRowRendererRef,
    getRowStyles,
    tableCellProps,
    enableDragDrop,
  }) => {
    const renderBodyCell = renderBodyCellRef.current;
    const customRowStyles = getRowStyles ? getRowStyles(row) : {};
    const customClassName = customRowStyles.className || '';
    delete customRowStyles.className;

    return (
      <DraggableRowWrapper
        row={row}
        key={`row-${row.id}`}
        enableDragDrop={enableDragDrop}
      >
        <Box
          key={`tr-${row.id}`}
          className={`tr ${index % 2 == 0 ? 'tr-even' : 'tr-odd'} ${customClassName}`}
          style={{
            display: 'flex',
            width: '100%',
            minWidth: '100%',
            ...(row.getIsSelected() && {
              backgroundColor: '#163632',
            }),
            ...customRowStyles,
          }}
        >
          {row.getVisibleCells().map((cell) => {
            return (
              <Box
                className="td"
                key={`td-${cell.id}`}
                style={{
                  ...(cell.column.columnDef.grow
                    ? {
                        flex: `${cell.column.columnDef.grow === true ? 1 : cell.column.columnDef.grow} 1 0%`,
                        minWidth: 0,
                        ...(cell.column.columnDef.maxSize && {
                          maxWidth: `${cell.column.columnDef.maxSize}px`,
                        }),
                      }
                    : {
                        flex: `0 0 var(--header-${cell.column.id}-size)`,
                        width: `var(--header-${cell.column.id}-size)`,
                        maxWidth: `var(--header-${cell.column.id}-size)`,
                      }),
                  ...(tableCellProps && tableCellProps({ cell })),
                }}
              >
                <Flex align="center" style={{ height: '100%' }}>
                  {renderBodyCell({ row, cell })}
                </Flex>
              </Box>
            );
          })}
        </Box>
        {isExpanded && expandedRowRendererRef.current({ row })}
      </DraggableRowWrapper>
    );
  },
  (prev, next) => {
    return (
      prev.row.original === next.row.original &&
      prev.index === next.index &&
      prev.isExpanded === next.isExpanded &&
      prev.isSelected === next.isSelected &&
      prev.enableDragDrop === next.enableDragDrop
    );
  }
);

const CustomTableBody = ({
  getRowModel,
  expandedRowIds,
  expandedRowRenderer,
  renderBodyCell,
  getRowStyles,
  tableCellProps,
  enableDragDrop = false,
  selectedTableIdsSet,
}) => {
  // Store callbacks in refs so memoized rows always access the latest versions
  // without the function references themselves triggering re-renders.
  const renderBodyCellRef = useRef(renderBodyCell);
  renderBodyCellRef.current = renderBodyCell;

  const expandedRowRendererRef = useRef(expandedRowRenderer);
  expandedRowRendererRef.current = expandedRowRenderer;

  const rows = getRowModel().rows;

  return (
    <Box className="tbody" style={{ flex: 1 }}>
      {rows.map((row, index) => (
        <MemoizedTableRow
          key={`row-${row.id}`}
          row={row}
          index={index}
          isExpanded={expandedRowIds.includes(row.original.id)}
          isSelected={
            selectedTableIdsSet
              ? selectedTableIdsSet.has(row.original.id)
              : false
          }
          renderBodyCellRef={renderBodyCellRef}
          expandedRowRendererRef={expandedRowRendererRef}
          getRowStyles={getRowStyles}
          tableCellProps={tableCellProps}
          enableDragDrop={enableDragDrop}
        />
      ))}
    </Box>
  );
};

const DraggableRowWrapper = ({
  row,
  children,
  style = {},
  enableDragDrop = false,
}) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const shouldEnableDrag = enableDragDrop && isUnlocked;

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: row.id,
    disabled: !shouldEnableDrag,
  });

  const dragStyle = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    position: 'relative',
    ...style,
  };

  return (
    <Box ref={setNodeRef} style={dragStyle}>
      {shouldEnableDrag && (
        <Box
          {...attributes}
          {...listeners}
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: 24,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: isDragging ? 'grabbing' : 'grab',
            backgroundColor: 'rgba(255, 255, 255, 0.05)',
            borderRight: '1px solid rgba(255, 255, 255, 0.1)',
            borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
            zIndex: 1,
          }}
        >
          <GripVertical size={16} opacity={0.5} />
        </Box>
      )}
      <div style={{ paddingLeft: shouldEnableDrag ? 28 : 0, width: '100%' }}>
        {children}
      </div>
    </Box>
  );
};

export default CustomTableBody;
