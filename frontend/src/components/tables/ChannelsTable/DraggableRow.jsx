import React from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import { Box } from '@mantine/core';
import useChannelsTableStore from '../../../store/channelsTable';

export const DraggableRow = ({ row, children }) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: row.id,
    disabled: !isUnlocked,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    position: 'relative',
  };

  return (
    <div ref={setNodeRef} style={style} className="tr">
      {isUnlocked && (
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
            zIndex: 1,
          }}
        >
          <GripVertical size={16} opacity={0.5} />
        </Box>
      )}
      <div style={{ paddingLeft: isUnlocked ? 28 : 0, width: '100%' }}>
        {children}
      </div>
    </div>
  );
};
