import React, { useEffect, useState, useCallback } from 'react';
import {
  Stack,
  Group,
  Text,
  Card,
  ActionIcon,
  Menu,
  Loader,
  Center,
  Badge,
} from '@mantine/core';
import {
  MoreVertical,
  Edit,
  Trash,
  RefreshCw,
  Eye,
  GripVertical,
} from 'lucide-react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { usePluginContext } from './PluginRenderer';
import API from '../../api';

/**
 * PluginDragDropList - Renders a drag-and-drop reorderable list from plugin data
 *
 * Features:
 * - Fetches data from plugin data collection
 * - Drag and drop reordering with @dnd-kit
 * - Calls on_reorder action when items are reordered
 * - Item templates with variable substitution
 * - Row actions (edit, delete, custom)
 */
const PluginDragDropList = ({
  id,
  data_source,
  item_template = {},
  empty_message = 'No items',
  on_reorder,
  actions = [],
  order_field = 'order',
}) => {
  const context = usePluginContext();
  const { pluginKey, dataRefreshKey, runAction } = context;

  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  // Configure sensors for drag and drop
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // 8px movement required before drag starts
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Fetch data from collection
  const fetchData = useCallback(async () => {
    if (!data_source) return;

    setLoading(true);
    try {
      const result = await API.getPluginData(pluginKey, data_source);
      // Sort by order field if present
      const sortedResult = (result || []).sort((a, b) => {
        const aOrder = a[order_field] ?? Infinity;
        const bOrder = b[order_field] ?? Infinity;
        return aOrder - bOrder;
      });
      setData(sortedResult);
    } catch (error) {
      console.error('Failed to fetch plugin data:', error);
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [pluginKey, data_source, order_field]);

  // Fetch data on mount and when refresh key changes
  useEffect(() => {
    fetchData();
  }, [fetchData, dataRefreshKey]);

  // Handle drag end
  const handleDragEnd = async (event) => {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      const oldIndex = data.findIndex((item) => item._id === active.id);
      const newIndex = data.findIndex((item) => item._id === over.id);

      if (oldIndex !== -1 && newIndex !== -1) {
        // Update local state immediately for responsiveness
        const newData = arrayMove(data, oldIndex, newIndex);
        setData(newData);

        // Call the reorder action if configured
        if (on_reorder) {
          try {
            // Send the new order to the backend
            const orderData = newData.map((item, index) => ({
              _id: item._id,
              [order_field]: index,
            }));

            await runAction(on_reorder, {
              items: orderData,
              moved_item_id: active.id,
              from_index: oldIndex,
              to_index: newIndex,
            });
          } catch (error) {
            // Revert on error
            console.error('Failed to persist order:', error);
            fetchData();
          }
        }
      }
    }
  };

  // Handle item action
  const handleAction = async (action, item) => {
    if (action.confirm) {
      const message =
        typeof action.confirm === 'object'
          ? action.confirm.message
          : `Are you sure?`;

      if (!window.confirm(message)) {
        return;
      }
    }

    await runAction(action.action, { _id: item._id, ...item });
  };

  // Interpolate template string with item data
  const interpolate = (template, item) => {
    if (!template) return '';
    return template.replace(/\{\{(\w+)\}\}/g, (match, key) => {
      const value = item[key];
      if (value === null || value === undefined) return '';
      return String(value);
    });
  };

  // Get icon for action
  const getActionIcon = (iconName) => {
    switch (iconName?.toLowerCase()) {
      case 'edit':
        return <Edit size={14} />;
      case 'trash':
      case 'delete':
        return <Trash size={14} />;
      case 'refresh':
        return <RefreshCw size={14} />;
      case 'view':
      case 'eye':
        return <Eye size={14} />;
      default:
        return null;
    }
  };

  if (loading) {
    return (
      <Center py="xl">
        <Loader size="md" />
      </Center>
    );
  }

  if (data.length === 0) {
    return (
      <Center py="xl">
        <Text c="dimmed">{empty_message}</Text>
      </Center>
    );
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
      modifiers={[restrictToVerticalAxis]}
    >
      <SortableContext
        items={data.map((item) => item._id)}
        strategy={verticalListSortingStrategy}
      >
        <Stack gap="sm">
          {data.map((item, index) => (
            <SortableItem
              key={item._id}
              item={item}
              index={index}
              itemTemplate={item_template}
              actions={actions}
              interpolate={interpolate}
              handleAction={handleAction}
              getActionIcon={getActionIcon}
            />
          ))}
        </Stack>
      </SortableContext>
    </DndContext>
  );
};

/**
 * SortableItem - A single sortable item in the drag-drop list
 */
const SortableItem = ({
  item,
  index,
  itemTemplate,
  actions,
  interpolate,
  handleAction,
  getActionIcon,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item._id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.8 : 1,
    zIndex: isDragging ? 1000 : 'auto',
  };

  const title = interpolate(itemTemplate.title, item);
  const subtitle = interpolate(itemTemplate.subtitle, item);
  const badge = interpolate(itemTemplate.badge, item);

  return (
    <Card
      ref={setNodeRef}
      style={style}
      padding="sm"
      withBorder
      shadow={isDragging ? 'md' : 'xs'}
    >
      <Group justify="space-between" wrap="nowrap">
        {/* Drag handle */}
        <ActionIcon
          variant="subtle"
          color="gray"
          style={{ cursor: 'grab', touchAction: 'none' }}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={16} />
        </ActionIcon>

        {/* Content */}
        <Group gap="sm" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
          {itemTemplate.icon && <Text c="dimmed">{itemTemplate.icon}</Text>}

          <Stack gap={2} style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Text fw={500} truncate>
                {title || `Item ${index + 1}`}
              </Text>
              {badge && (
                <Badge size="sm" variant="light">
                  {badge}
                </Badge>
              )}
            </Group>
            {subtitle && (
              <Text size="sm" c="dimmed" truncate>
                {subtitle}
              </Text>
            )}
          </Stack>
        </Group>

        {/* Actions menu */}
        {actions.length > 0 && (
          <Menu position="bottom-end" withinPortal>
            <Menu.Target>
              <ActionIcon variant="subtle" color="gray">
                <MoreVertical size={16} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {actions.map((action) => (
                <Menu.Item
                  key={action.id}
                  color={action.color}
                  leftSection={getActionIcon(action.icon)}
                  onClick={() => handleAction(action, item)}
                >
                  {action.label}
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>
        )}
      </Group>
    </Card>
  );
};

export default PluginDragDropList;
