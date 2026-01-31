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
import { usePluginContext } from './PluginRenderer';
import API from '../../api';

/**
 * PluginList - Renders a list of items from plugin data
 *
 * Simpler than table, designed for card-style item display.
 * Supports item templates with variable substitution.
 */
const PluginList = ({
  id,
  data_source,
  item_template = {},
  empty_message = 'No items',
  max_items,
  actions = [],
}) => {
  const context = usePluginContext();
  const { pluginKey, dataRefreshKey, runAction } = context;

  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  // Fetch data from collection
  const fetchData = useCallback(async () => {
    if (!data_source) return;

    setLoading(true);
    try {
      const result = await API.getPluginData(pluginKey, data_source);
      setData(result || []);
    } catch (error) {
      console.error('Failed to fetch plugin data:', error);
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [pluginKey, data_source]);

  // Fetch data on mount and when refresh key changes
  useEffect(() => {
    fetchData();
  }, [fetchData, dataRefreshKey]);

  // Apply max_items limit
  const displayData = max_items ? data.slice(0, max_items) : data;

  // Handle item action
  const handleAction = async (action, item) => {
    if (action.confirm) {
      const message = typeof action.confirm === 'object'
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
    <Stack gap="sm">
      {displayData.map((item, index) => {
        const title = interpolate(item_template.title, item);
        const subtitle = interpolate(item_template.subtitle, item);
        const badge = interpolate(item_template.badge, item);

        return (
          <Card key={item._id || index} padding="sm" withBorder>
            <Group justify="space-between" wrap="nowrap">
              <Group gap="sm" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
                {item_template.icon && (
                  <Text c="dimmed">{item_template.icon}</Text>
                )}

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
      })}

      {max_items && data.length > max_items && (
        <Text size="sm" c="dimmed" ta="center">
          Showing {max_items} of {data.length} items
        </Text>
      )}
    </Stack>
  );
};

export default PluginList;
