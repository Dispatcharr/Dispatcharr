import { Box, Flex } from '@mantine/core';
import React, { useRef } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import useChannelsTableStore from '../../../store/channelsTable';

const intrinsicRowHeights = {
  compact: '28px',
  default: '40px',
  large: '48px',
};

const MemoizedTableRow = React.memo(
  ({
    row,
    index,
    isExpanded,
    isSelected,
    renderBodyCellRef,
    expandedRowRendererRef,
    handleRowClickRef,
    getRowStylesRef,
    tableCellPropsRef,
    enableDragDrop,
  }) => {
    const renderBodyCell = renderBodyCellRef.current;
    const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
    const shouldEnableDrag = enableDragDrop && isUnlocked;
    const getRowStyles = getRowStylesRef.current;
    const tableCellProps = tableCellPropsRef.current;
    const customRowStyles = getRowStyles ? getRowStyles(row) : {};
    const customClassName = customRowStyles.className || '';
    delete customRowStyles.className;

    const content = (
      <>
        <Box
          key={`tr-${row.id}`}
          className={`tr ${index % 2 == 0 ? 'tr-even' : 'tr-odd'} ${customClassName}`}
          onMouseDown={(e) => {
            if (e.shiftKey) e.preventDefault();
          }}
          onClick={(e) => handleRowClickRef?.current?.(row.original.id, e)}
          style={{
            display: 'flex',
            width: '100%',
            minWidth: '100%',
            ...(isSelected && {
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
                data-column-id={cell.column.id}
                style={{
                  boxSizing: 'border-box',
                  ...(cell.column.columnDef.grow
                    ? {
                        flex: cell.column.columnDef.flexRatio
                          ? `var(--header-${cell.column.id}-ratio) 1 0%`
                          : `${cell.column.columnDef.grow === true ? 1 : cell.column.columnDef.grow} 1 0%`,
                        minWidth: 0,
                        ...(!cell.column.columnDef.flexRatio &&
                          cell.column.columnDef.maxSize && {
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
      </>
    );

    if (!shouldEnableDrag) {
      return <Box>{content}</Box>;
    }

    return (
      <DraggableRowWrapper row={row} key={`row-${row.id}`}>
        {content}
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
  handleRowClickRef,
  tableSize = 'default',
}) => {
  const renderBodyCellRef = useRef(renderBodyCell);
  renderBodyCellRef.current = renderBodyCell;

  const expandedRowRendererRef = useRef(expandedRowRenderer);
  expandedRowRendererRef.current = expandedRowRenderer;

  const getRowStylesRef = useRef(getRowStyles);
  getRowStylesRef.current = getRowStyles;
  const tableCellPropsRef = useRef(tableCellProps);
  tableCellPropsRef.current = tableCellProps;

  const rows = getRowModel().rows;
  const intrinsicRowHeight = intrinsicRowHeights[tableSize] ?? intrinsicRowHeights.default;

  return (
    <Box className="tbody" style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
      {rows.map((row, index) => (
        <Box
          key={`row-${row.id}`}
          className="native-table-row"
          style={{
            contentVisibility: 'auto',
            containIntrinsicSize: `auto ${intrinsicRowHeight}`,
          }}
        >
          <MemoizedTableRow
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
            handleRowClickRef={handleRowClickRef}
            getRowStylesRef={getRowStylesRef}
            tableCellPropsRef={tableCellPropsRef}
            enableDragDrop={enableDragDrop}
          />
        </Box>
      ))}
    </Box>
  );
};

const DraggableRowWrapper = ({
  row,
  children,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: row.id,
  });

  const dragStyle = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    position: 'relative',
  };

  return (
    <Box ref={setNodeRef} style={dragStyle}>
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
      <div style={{ paddingLeft: 28, width: '100%' }}>
        {children}
      </div>
    </Box>
  );
};

export default CustomTableBody;
