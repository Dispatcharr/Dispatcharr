import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Text,
  Group,
  ActionIcon,
  Stack,
  useMantineTheme,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { GripVertical } from 'lucide-react';
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import useAuthStore from '../../../store/auth';
import {
  NAV_ITEMS,
  DEFAULT_ADMIN_ORDER,
  DEFAULT_USER_ORDER,
  getOrderedNavItems,
} from '../../../config/navigation';
import { USER_LEVELS } from '../../../constants';

const DraggableNavItem = ({ item }) => {
  const theme = useMantineTheme();
  const { transform, transition, setNodeRef, isDragging, attributes, listeners } = useSortable({
    id: item.id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition: transition,
    opacity: isDragging ? 0.8 : 1,
    zIndex: isDragging ? 1 : 0,
    position: 'relative',
  };

  const IconComponent = item.icon;

  return (
    <Box
      ref={setNodeRef}
      style={{
        ...style,
        padding: '10px 12px',
        border: '1px solid #444',
        borderRadius: '6px',
        backgroundColor: isDragging ? '#3A3A3E' : '#2A2A2E',
        marginBottom: 6,
      }}
    >
      <Group justify="space-between">
        <Group gap="sm">
          <ActionIcon
            {...attributes}
            {...listeners}
            variant="transparent"
            size="sm"
            style={{ cursor: 'grab' }}
          >
            <GripVertical size={16} color="#888" />
          </ActionIcon>
          {IconComponent && <IconComponent size={18} color="#ccc" />}
          <Text size="sm" c="gray.3">
            {item.label}
          </Text>
        </Group>
      </Group>
    </Box>
  );
};

const NavOrderForm = ({ active }) => {
  const theme = useMantineTheme();
  const user = useAuthStore((s) => s.user);
  const getNavOrder = useAuthStore((s) => s.getNavOrder);
  const setNavOrder = useAuthStore((s) => s.setNavOrder);

  const isAdmin = user?.user_level >= USER_LEVELS.ADMIN;
  const defaultOrder = isAdmin ? DEFAULT_ADMIN_ORDER : DEFAULT_USER_ORDER;

  const [items, setItems] = useState([]);
  const [isSaving, setIsSaving] = useState(false);

  const sensors = useSensors(
    useSensor(MouseSensor, {}),
    useSensor(TouchSensor, {}),
    useSensor(KeyboardSensor, {})
  );

  useEffect(() => {
    if (active) {
      const savedOrder = getNavOrder();
      const orderedItems = getOrderedNavItems(savedOrder, isAdmin);
      setItems(orderedItems);
    }
  }, [active, isAdmin, getNavOrder]);

  const handleDragEnd = async ({ active, over }) => {
    if (!over || active.id === over.id) return;

    const oldIndex = items.findIndex((item) => item.id === active.id);
    const newIndex = items.findIndex((item) => item.id === over.id);
    const newItems = arrayMove(items, oldIndex, newIndex);

    // Optimistic update
    setItems(newItems);

    // Save to backend
    setIsSaving(true);
    try {
      const newOrder = newItems.map((item) => item.id);
      await setNavOrder(newOrder);
      notifications.show({
        title: 'Navigation',
        message: 'Order saved successfully',
        color: 'green',
        autoClose: 2000,
      });
    } catch (error) {
      // Revert on failure
      const savedOrder = getNavOrder();
      const orderedItems = getOrderedNavItems(savedOrder, isAdmin);
      setItems(orderedItems);
      notifications.show({
        title: 'Error',
        message: 'Failed to save navigation order',
        color: 'red',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async () => {
    setIsSaving(true);
    try {
      await setNavOrder(defaultOrder);
      const orderedItems = getOrderedNavItems(defaultOrder, isAdmin);
      setItems(orderedItems);
      notifications.show({
        title: 'Navigation',
        message: 'Reset to default order',
        color: 'blue',
        autoClose: 2000,
      });
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: 'Failed to reset navigation order',
        color: 'red',
      });
    } finally {
      setIsSaving(false);
    }
  };

  if (!active) {
    return null;
  }

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Drag and drop to reorder the sidebar navigation items.
      </Text>

      <DndContext
        collisionDetection={closestCenter}
        modifiers={[restrictToVerticalAxis]}
        onDragEnd={handleDragEnd}
        sensors={sensors}
      >
        <SortableContext
          items={items.map((item) => item.id)}
          strategy={verticalListSortingStrategy}
        >
          {items.map((item) => (
            <DraggableNavItem key={item.id} item={item} />
          ))}
        </SortableContext>
      </DndContext>

      <Group justify="flex-end">
        <Button
          variant="subtle"
          color="gray"
          onClick={handleReset}
          disabled={isSaving}
        >
          Reset to Default
        </Button>
      </Group>
    </Stack>
  );
};

export default NavOrderForm;
