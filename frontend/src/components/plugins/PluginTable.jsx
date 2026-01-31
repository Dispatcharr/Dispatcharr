import React, { useEffect, useState, useCallback } from 'react';
import {
  Table,
  Stack,
  Text,
  TextInput,
  Group,
  ActionIcon,
  Menu,
  Pagination,
  Loader,
  Center,
  Badge,
} from '@mantine/core';
import {
  Search,
  MoreVertical,
  Edit,
  Trash,
  RefreshCw,
  Eye,
} from 'lucide-react';
import { usePluginContext } from './PluginRenderer';
import API from '../../api';

/**
 * PluginTable - Renders a data table with plugin data
 *
 * Features:
 * - Fetches data from plugin data collection
 * - Search/filter support
 * - Pagination
 * - Row actions (edit, delete, custom)
 * - Column rendering (datetime, badge, etc.)
 */
const PluginTable = ({
  id,
  data_source,
  columns = [],
  row_actions = [],
  empty_message = 'No data',
  searchable = false,
  search_fields = [],
  pagination = true,
  page_size = 10,
}) => {
  const context = usePluginContext();
  const { pluginKey, dataRefreshKey, runAction } = context;

  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [sortField, setSortField] = useState(null);
  const [sortDirection, setSortDirection] = useState('asc');

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

  // Filter data by search query
  const filteredData = React.useMemo(() => {
    if (!searchQuery) return data;

    const query = searchQuery.toLowerCase();
    const fieldsToSearch = search_fields.length > 0
      ? search_fields
      : columns.map((c) => c.id);

    return data.filter((row) =>
      fieldsToSearch.some((field) => {
        const value = row[field];
        if (value === null || value === undefined) return false;
        return String(value).toLowerCase().includes(query);
      })
    );
  }, [data, searchQuery, search_fields, columns]);

  // Sort data
  const sortedData = React.useMemo(() => {
    if (!sortField) return filteredData;

    return [...filteredData].sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];

      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      let comparison = 0;
      if (typeof aVal === 'string') {
        comparison = aVal.localeCompare(bVal);
      } else {
        comparison = aVal - bVal;
      }

      return sortDirection === 'asc' ? comparison : -comparison;
    });
  }, [filteredData, sortField, sortDirection]);

  // Paginate data
  const paginatedData = React.useMemo(() => {
    if (!pagination) return sortedData;

    const start = (currentPage - 1) * page_size;
    return sortedData.slice(start, start + page_size);
  }, [sortedData, pagination, currentPage, page_size]);

  const totalPages = Math.ceil(sortedData.length / page_size);

  // Handle column header click for sorting
  const handleSort = (columnId, sortable) => {
    if (!sortable) return;

    if (sortField === columnId) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(columnId);
      setSortDirection('asc');
    }
  };

  // Handle row action click
  const handleRowAction = async (action, row) => {
    if (action.confirm) {
      const message = typeof action.confirm === 'object'
        ? action.confirm.message
        : `Are you sure you want to ${action.label.toLowerCase()}?`;

      if (!window.confirm(message)) {
        return;
      }
    }

    await runAction(action.action, { _id: row._id, ...row });
  };

  // Render cell value based on column render type
  const renderCell = (column, row) => {
    const value = row[column.id];

    if (value === null || value === undefined) {
      return <Text c="dimmed">—</Text>;
    }

    switch (column.render) {
      case 'datetime':
        try {
          const date = new Date(value);
          return date.toLocaleString();
        } catch {
          return value;
        }

      case 'date':
        try {
          const date = new Date(value);
          return date.toLocaleDateString();
        } catch {
          return value;
        }

      case 'time':
        try {
          const date = new Date(value);
          return date.toLocaleTimeString();
        } catch {
          return value;
        }

      case 'badge':
        return (
          <Badge color={column.badge_color || 'blue'} variant="light">
            {value}
          </Badge>
        );

      case 'boolean':
        return value ? 'Yes' : 'No';

      case 'link':
        return (
          <a href={value} target="_blank" rel="noopener noreferrer">
            {value}
          </a>
        );

      case 'truncate':
        const maxLen = column.max_length || 50;
        if (String(value).length > maxLen) {
          return (
            <Text title={value}>
              {String(value).substring(0, maxLen)}...
            </Text>
          );
        }
        return value;

      default:
        return String(value);
    }
  };

  // Get icon for row action
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
        <Stack align="center" gap="sm">
          <Text c="dimmed">{empty_message}</Text>
        </Stack>
      </Center>
    );
  }

  return (
    <Stack gap="md">
      {/* Search bar */}
      {searchable && (
        <TextInput
          placeholder="Search..."
          leftSection={<Search size={16} />}
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            setCurrentPage(1);
          }}
        />
      )}

      {/* Table */}
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            {columns.map((column) => (
              <Table.Th
                key={column.id}
                style={{
                  width: column.width,
                  textAlign: column.align || 'left',
                  cursor: column.sortable ? 'pointer' : 'default',
                }}
                onClick={() => handleSort(column.id, column.sortable)}
              >
                <Group gap="xs">
                  {column.label}
                  {column.sortable && sortField === column.id && (
                    <Text size="xs" c="dimmed">
                      {sortDirection === 'asc' ? '▲' : '▼'}
                    </Text>
                  )}
                </Group>
              </Table.Th>
            ))}
            {row_actions.length > 0 && (
              <Table.Th style={{ width: 50 }}>Actions</Table.Th>
            )}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {paginatedData.map((row, rowIndex) => (
            <Table.Tr key={row._id || rowIndex}>
              {columns.map((column) => (
                <Table.Td
                  key={column.id}
                  style={{ textAlign: column.align || 'left' }}
                >
                  {renderCell(column, row)}
                </Table.Td>
              ))}
              {row_actions.length > 0 && (
                <Table.Td>
                  <Menu position="bottom-end" withinPortal>
                    <Menu.Target>
                      <ActionIcon variant="subtle" color="gray">
                        <MoreVertical size={16} />
                      </ActionIcon>
                    </Menu.Target>
                    <Menu.Dropdown>
                      {row_actions.map((action) => (
                        <Menu.Item
                          key={action.id}
                          color={action.color}
                          leftSection={getActionIcon(action.icon)}
                          onClick={() => handleRowAction(action, row)}
                        >
                          {action.label}
                        </Menu.Item>
                      ))}
                    </Menu.Dropdown>
                  </Menu>
                </Table.Td>
              )}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      {/* Pagination */}
      {pagination && totalPages > 1 && (
        <Group justify="center">
          <Pagination
            value={currentPage}
            onChange={setCurrentPage}
            total={totalPages}
          />
        </Group>
      )}

      {/* Results count */}
      <Text size="sm" c="dimmed" ta="center">
        Showing {paginatedData.length} of {sortedData.length} items
        {searchQuery && ` (filtered from ${data.length})`}
      </Text>
    </Stack>
  );
};

export default PluginTable;
