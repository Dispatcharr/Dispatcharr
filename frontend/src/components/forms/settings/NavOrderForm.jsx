import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box,
  Button,
  Text,
  Group,
  ActionIcon,
  Stack,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { GripVertical, Eye, EyeOff } from 'lucide-react';
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

const DraggableNavItem = ({ item, isHidden, canHide, onToggleVisibility }) => {
  const { transform, transition, setNodeRef, isDragging, attributes, listeners } = useSortable({
    id: item.id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition: transition,
    opacity: isDragging ? 0.8 : isHidden ? 0.5 : 1,
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
          {IconComponent && <IconComponent size={18} color={isHidden ? '#666' : '#ccc'} />}
          <Text size="sm" c={isHidden ? 'dimmed' : 'gray.3'}>
            {item.label}
          </Text>
        </Group>
        {canHide && (
          <ActionIcon
            variant="transparent"
            size="sm"
            onClick={() => onToggleVisibility(item.id)}
            title={isHidden ? 'Show in navigation' : 'Hide from navigation'}
          >
            {isHidden ? (
              <EyeOff size={16} color="#666" />
            ) : (
              <Eye size={16} color="#888" />
            )}
          </ActionIcon>
        )}
      </Group>
    </Box>
  );
};

const NavOrderForm = ({ active }) => {
  // All store selectors grouped together
  const user = useAuthStore((s) => s.user);
  const getNavOrder = useAuthStore((s) => s.getNavOrder);
  const setNavOrder = useAuthStore((s) => s.setNavOrder);
  const getHiddenNav = useAuthStore((s) => s.getHiddenNav);
  const toggleNavVisibility = useAuthStore((s) => s.toggleNavVisibility);
  const updateUserPreferences = useAuthStore((s) => s.updateUserPreferences);

  const isAdmin = user?.user_level >= USER_LEVELS.ADMIN;
  const defaultOrder = isAdmin ? DEFAULT_ADMIN_ORDER : DEFAULT_USER_ORDER;

  const [items, setItems] = useState([]);
  const [isSaving, setIsSaving] = useState(false);

  // Refs for debouncing
  const saveTimeoutRef = useRef(null);
  const pendingOrderRef = useRef(null);

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

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  // Debounced save function
  const debouncedSave = useCallback(async (newOrder) => {
    // Clear any pending save
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    // Store the pending order
    pendingOrderRef.current = newOrder;

    // Schedule save after 800ms of inactivity
    saveTimeoutRef.current = setTimeout(async () => {
      const orderToSave = pendingOrderRef.current;
      if (!orderToSave) return;

      setIsSaving(true);
      try {
        await setNavOrder(orderToSave);
        notifications.show({
          title: 'Navigation',
          message: 'Order saved successfully',
          color: 'green',
          autoClose: 2000,
        });
      } catch {
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
        pendingOrderRef.current = null;
      }
    }, 800);
  }, [setNavOrder, getNavOrder, isAdmin]);

  const handleDragEnd = ({ active, over }) => {
    if (!over || active.id === over.id) return;

    const oldIndex = items.findIndex((item) => item.id === active.id);
    const newIndex = items.findIndex((item) => item.id === over.id);
    const newItems = arrayMove(items, oldIndex, newIndex);

    // Optimistic update
    setItems(newItems);

    // Debounced save to backend
    const newOrder = newItems.map((item) => item.id);
    debouncedSave(newOrder);
  };

  // Wrapped visibility toggle with error handling
  const handleToggleVisibility = useCallback(async (itemId) => {
    try {
      await toggleNavVisibility(itemId);
      notifications.show({
        title: 'Navigation',
        message: 'Visibility updated',
        color: 'green',
        autoClose: 2000,
      });
    } catch {
      notifications.show({
        title: 'Error',
        message: 'Failed to update visibility',
        color: 'red',
      });
    }
  }, [toggleNavVisibility]);

  const handleReset = async () => {
    // Cancel any pending debounced save
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
      pendingOrderRef.current = null;
    }

    setIsSaving(true);
    try {
      await updateUserPreferences({ navOrder: defaultOrder, hiddenNav: [] });
      const orderedItems = getOrderedNavItems(defaultOrder, isAdmin);
      setItems(orderedItems);
      notifications.show({
        title: 'Navigation',
        message: 'Reset to default order',
        color: 'blue',
        autoClose: 2000,
      });
    } catch {
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

  // Cache hiddenNav before render loop to avoid calling getter N times
  const hiddenNav = getHiddenNav();

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
            <DraggableNavItem
              key={item.id}
              item={item}
              isHidden={hiddenNav.includes(item.id)}
              canHide={item.canHide !== false}
              onToggleVisibility={handleToggleVisibility}
            />
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
