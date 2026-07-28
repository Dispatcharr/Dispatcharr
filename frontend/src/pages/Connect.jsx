import React, { useEffect, useMemo, useState, useCallback } from 'react';
import {
  Box,
  Button,
  Group,
  Stack,
  Switch,
  Card,
  Flex,
  useMantineTheme,
  Text,
  Badge,
  Tooltip,
  Title,
  ActionIcon,
  NativeSelect,
  Pagination,
  Select,
  LoadingOverlay,
} from '@mantine/core';
import API from '../api';
import useConnectStore from '../store/connect';
import {
  SquarePlus,
  Webhook,
  FileCode,
  Logs,
  ChevronDown,
} from 'lucide-react';
import ConnectionForm from '../components/forms/Connection';
import { SUBSCRIPTION_EVENTS } from '../constants';
import { CustomTable, useTable } from '../components/tables/CustomTable';
import { copyToClipboard } from '../utils';

const deleteConnectIntegration = (id) => {
  return API.deleteConnectIntegration(id);
};

const updateConnectIntegration = (id, values) => {
  return API.updateConnectIntegration(id, values);
};

const getConnectLogs = (params) => {
  return API.getConnectLogs(params);
};

export default function ConnectPage() {
  const { integrations, isLoading, fetchIntegrations } = useConnectStore();
  const theme = useMantineTheme();
  const [connection, setConnection] = useState(null);
  const [isConnectionModalOpen, setIsConnectionModalOpen] = useState(false);

  useEffect(() => {
    fetchIntegrations();
  }, [fetchIntegrations]);

  const newConnection = () => {
    setConnection(null);
    setIsConnectionModalOpen(true);
  };

  const editConnection = (connection) => {
    setConnection(connection);
    setIsConnectionModalOpen(true);
  };

  const deleteConnection = async (id) => {
    console.log('Deleting connection', id);
    await deleteConnectIntegration(id);
  };

  return (
    <>
      <Box p="md" pb={120}>
        <Button
          leftSection={<SquarePlus size={18} />}
          variant="light"
          size="sm"
          onClick={() => newConnection()}
          p={10}
          color={theme.tailwind.green[5]}
          style={{
            borderWidth: '1px',
            borderColor: theme.tailwind.green[5],
            color: 'white',
          }}
        >
          New Connection
        </Button>
        {isLoading && <div>Loading...</div>}
        {!isLoading && (
          <Box
            style={{
              gap: '1rem',
              gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))',
              alignContent: 'start',
            }}
            display="grid"
            py={10}
          >
            {integrations.map((i) => (
              <IntegrationRow
                key={i.id}
                integration={i}
                editConnection={editConnection}
                deleteConnection={deleteConnection}
              />
            ))}
          </Box>
        )}

        <ConnectionForm
          connection={connection}
          isOpen={isConnectionModalOpen}
          onClose={() => setIsConnectionModalOpen(false)}
        />
      </Box>

      {/* Logs Section - Fixed at bottom, like SystemEvents on the Stats page */}
      <Box
        style={{
          zIndex: 100,
          pointerEvents: 'none',
        }}
        pos="fixed"
        bottom={0}
        left="var(--app-shell-navbar-width, 0)"
        right={0}
        p={'0 1rem 1rem 1rem'}
      >
        <Box style={{ pointerEvents: 'auto' }}>
          <ConnectLogsSection integrations={integrations} />
        </Box>
      </Box>
    </>
  );
}

function IntegrationRow({ integration, editConnection, deleteConnection }) {
  const type = integration.type || 'webhook';
  const [enabled, setEnabled] = useState(!!integration.enabled);
  const webhookUrl = integration?.config?.url || '';
  const scriptPath = integration?.config?.path || '';

  const toggleIntegration = async () => {
    try {
      await updateConnectIntegration(integration.id, {
        ...integration,
        enabled: !enabled,
      });
      setEnabled(!enabled);
    } catch (error) {
      console.error('Failed to update integration', error);
    }
  };

  return (
    <Card
      key={integration.id}
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{
        backgroundColor: '#27272A',
      }}
      color="#fff"
      w={'100%'}
    >
      <Stack gap="xs">
        <Group justify="space-between">
          <Group align="flex-start">
            {integration.type == 'webhook' ? <Webhook /> : <FileCode />}
            <Text fw={800}>{integration.name}</Text>
          </Group>
          <Switch
            label="Enabled"
            checked={enabled}
            onChange={toggleIntegration}
          />
        </Group>

        {type === 'webhook' ? (
          <Group gap={5} align="center">
            <Text fw={500}>Target:</Text>
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Tooltip label={webhookUrl} withArrow multiline>
                <Text
                  style={{
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {webhookUrl}
                </Text>
              </Tooltip>
            </Box>
          </Group>
        ) : (
          <Group gap={5} align="center">
            <Text fw={500}>Target:</Text>
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Tooltip label={scriptPath} withArrow multiline>
                <Text
                  style={{
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {scriptPath}
                </Text>
              </Tooltip>
            </Box>
          </Group>
        )}

        <Text>Triggers</Text>
        <Group>
          {integration.subscriptions.map(
            (sub) =>
              sub.enabled && (
                <Badge size="sm" variant="light" color="green">
                  {SUBSCRIPTION_EVENTS[sub.event] || sub.event}
                </Badge>
              )
          )}
        </Group>
      </Stack>

      <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
        <Button size="xs" onClick={() => editConnection(integration)}>
          Edit
        </Button>
        <Button
          variant="outline"
          size="xs"
          color="red"
          onClick={() => deleteConnection(integration.id)}
        >
          Delete
        </Button>
      </Flex>
    </Card>
  );
}

function ConnectLogsSection({ integrations }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const [logs, setLogs] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [count, setCount] = useState(0);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 50 });
  const [filters, setFilters] = useState({ type: '', integration: '' });

  const pageCount = useMemo(
    () => Math.max(1, Math.ceil(count / Math.max(1, pagination.pageSize))),
    [count, pagination.pageSize]
  );

  const onPageSizeChange = useCallback((e) => {
    const value = parseInt(e.target.value, 10);
    setPagination((prev) => ({ ...prev, pageSize: value, pageIndex: 0 }));
  }, []);

  const onPageIndexChange = useCallback((page) => {
    setPagination((prev) => ({ ...prev, pageIndex: page - 1 }));
  }, []);

  const fetchLogs = useCallback(async () => {
    setIsLoading(true);
    try {
      const params = {
        page: pagination.pageIndex + 1,
        page_size: pagination.pageSize,
      };
      if (filters.type) params.type = filters.type;
      if (filters.integration) params.integration = filters.integration;

      const data = await getConnectLogs(params);
      const results = Array.isArray(data) ? data : data?.results || [];
      setLogs(results);
      setCount(data?.count || results.length || 0);
    } finally {
      setIsLoading(false);
    }
  }, [pagination.pageIndex, pagination.pageSize, filters]);

  useEffect(() => {
    if (isExpanded) {
      fetchLogs();
    }
  }, [isExpanded, fetchLogs]);

  const columns = useMemo(
    () => [
      {
        header: 'Time',
        accessorKey: 'created_at',
        size: 180,
        cell: ({ getValue }) => (
          <Text size="sm">{new Date(getValue()).toLocaleString()}</Text>
        ),
      },
      {
        header: 'Integration',
        accessorKey: 'subscription',
        size: 200,
        cell: ({ getValue }) => {
          const subscription = getValue();
          const integration = integrations.find(
            (i) => i.id === subscription?.integration
          );
          const isWebhook = integration?.type === 'webhook';
          return (
            <Group gap={6}>
              {isWebhook ? <Webhook size={16} /> : <FileCode size={16} />}
              <Text size="sm">{integration?.name || '-'}</Text>
            </Group>
          );
        },
      },
      {
        header: 'Event',
        accessorKey: 'subscription',
        size: 160,
        cell: ({ getValue }) => (
          <Text size="sm">{SUBSCRIPTION_EVENTS[getValue()?.event] || '—'}</Text>
        ),
      },
      {
        header: 'Response',
        accessorKey: 'response_payload',
        grow: true,
        cell: ({ getValue }) => (
          <Text
            size="sm"
            truncate
            style={{ cursor: 'pointer' }}
            onClick={() =>
              copyToClipboard(getValue() ? JSON.stringify(getValue()) : '')
            }
          >
            {getValue() ? JSON.stringify(getValue()) : '—'}
          </Text>
        ),
      },
      {
        header: 'Error',
        accessorKey: 'error_message',
        size: 150,
        cell: ({ getValue }) => (
          <Text
            size="sm"
            truncate
            onClick={() => copyToClipboard(getValue() || '')}
            style={{ cursor: 'pointer' }}
          >
            {getValue() || '—'}
          </Text>
        ),
      },
      {
        header: 'Status',
        accessorKey: 'status',
        size: 100,
        cell: ({ getValue }) => (
          <Badge
            color={getValue() === 'success' ? 'green' : 'red'}
            variant="light"
          >
            {getValue()}
          </Badge>
        ),
      },
    ],
    [integrations]
  );

  const data = useMemo(() => logs, [logs]);
  const allRowIds = useMemo(() => logs.map((l) => l.id), [logs]);

  const renderHeaderCell = (header) => (
    <Text size="sm" name={header.id}>
      {header.column.columnDef.header}
    </Text>
  );

  const table = useTable({
    columns,
    data,
    allRowIds,
    enablePagination: false,
    enableRowSelection: false,
    enableRowVirtualization: false,
    renderTopToolbar: false,
    manualSorting: false,
    manualFiltering: false,
    manualPagination: true,
    headerCellRenderFns: {
      created_at: renderHeaderCell,
      subscription: renderHeaderCell,
      response_payload: renderHeaderCell,
      error_message: renderHeaderCell,
      status: renderHeaderCell,
    },
  });

  const startIdx = pagination.pageIndex * pagination.pageSize + 1;
  const endIdx = Math.min(
    (pagination.pageIndex + 1) * pagination.pageSize,
    count
  );
  const paginationString = `Showing ${startIdx}-${endIdx} of ${count}`;

  const integrationOptions = useMemo(
    () => integrations.map((i) => ({ value: String(i.id), label: i.name })),
    [integrations]
  );

  return (
    <Card
      shadow="sm"
      padding="sm"
      radius="md"
      withBorder
      style={{
        color: '#fff',
        backgroundColor: '#27272A',
        width: '100%',
        maxWidth: isExpanded ? '100%' : '800px',
        marginLeft: 'auto',
        marginRight: 'auto',
        transition: 'max-width 0.3s ease',
      }}
    >
      <Group justify="space-between" mb={isExpanded ? 'sm' : 0}>
        <Group gap="xs">
          <Logs size={20} />
          <Title order={4}>Logs</Title>
        </Group>
        <ActionIcon
          variant="subtle"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <ChevronDown
            size={18}
            style={{
              transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s',
            }}
          />
        </ActionIcon>
      </Group>

      {isExpanded && (
        <Stack gap={0}>
          <Group gap={12} p={12} style={{ borderBottom: '1px solid #3f3f46' }}>
            <Text size="sm">Type</Text>
            <Select
              size="xs"
              data={[
                { value: '', label: 'All' },
                { value: 'webhook', label: 'Webhooks' },
                { value: 'script', label: 'Scripts' },
              ]}
              value={filters.type}
              onChange={(value) =>
                setFilters((prev) => ({ ...prev, type: value }))
              }
              style={{ width: 150 }}
            />
            <Text size="sm">Integration</Text>
            <Select
              size="xs"
              searchable
              data={[{ value: '', label: 'All' }, ...integrationOptions]}
              value={filters.integration}
              onChange={(value) =>
                setFilters((prev) => ({ ...prev, integration: value }))
              }
              style={{ width: 250 }}
            />
          </Group>
          <Box
            style={{
              overflowY: 'auto',
              overflowX: 'auto',
              border: 'solid 1px rgb(68,68,68)',
              borderRadius: 'var(--mantine-radius-default)',
              maxHeight: '50vh',
            }}
          >
            <div style={{ minWidth: '900px', position: 'relative' }}>
              <LoadingOverlay visible={isLoading} />
              <CustomTable table={table} />
            </div>
          </Box>
          <Group gap={5} justify="center" p={8}>
            <Text size="xs">Page Size</Text>
            <NativeSelect
              size="xxs"
              value={pagination.pageSize}
              data={['25', '50', '100', '250']}
              onChange={onPageSizeChange}
              style={{ paddingRight: 20 }}
            />
            <Pagination
              total={pageCount}
              value={pagination.pageIndex + 1}
              onChange={onPageIndexChange}
              size="xs"
              withEdges
              style={{ paddingRight: 20 }}
            />
            <Text size="xs">{paginationString}</Text>
          </Group>
        </Stack>
      )}
    </Card>
  );
}
