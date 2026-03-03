import React, { useEffect, useMemo, useState, useCallback } from 'react';
import {
  Box,
  Title,
  Badge,
  Group,
  Text,
  Paper,
  NativeSelect,
  Pagination,
  Select,
  LoadingOverlay,
} from '@mantine/core';
import API from '../api';
import useConnectStore from '../store/connect';
import { FileCode, Webhook } from 'lucide-react';
import { SUBSCRIPTION_EVENTS } from '../constants';
import { CustomTable, useTable } from '../components/tables/CustomTable';
import { copyToClipboard } from '../utils';

export default function ConnectLogsPage() {
  const { integrations, fetchIntegrations } = useConnectStore();

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

      const data = await API.getConnectLogs(params);
      const results = Array.isArray(data) ? data : data?.results || [];
      setLogs(results);
      setCount(data?.count || results.length || 0);
    } finally {
      setIsLoading(false);
    }
  }, [pagination.pageIndex, pagination.pageSize, filters]);

  useEffect(() => {
    // Load integrations for filter options if not already available
    if (!integrations || integrations.length === 0) {
      fetchIntegrations?.();
    }
  }, []);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

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
    <Box p="md">
      <Title order={3} fw={'bold'}>
        Connect Logs
      </Title>
      <Paper
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: 'calc(100vh - 65px)',
          backgroundColor: '#27272A',
          border: '1px solid #3f3f46',
          borderRadius: 'var(--mantine-radius-md)',
        }}
      >
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
            display: 'flex',
            flexDirection: 'column',
            height: 'calc(100vh - 100px)',
          }}
        >
          <Box
            style={{
              flex: 1,
              overflowY: 'auto',
              overflowX: 'auto',
              border: 'solid 1px rgb(68,68,68)',
              borderRadius: 'var(--mantine-radius-default)',
            }}
          >
            <div style={{ minWidth: '900px', position: 'relative' }}>
              <LoadingOverlay visible={isLoading} />
              <CustomTable table={table} />
            </div>
          </Box>
          <Box
            style={{
              position: 'sticky',
              bottom: 0,
              zIndex: 3,
              backgroundColor: '#27272A',
            }}
          >
            <Group
              gap={5}
              justify="center"
              style={{ padding: 8, borderTop: '1px solid #666' }}
            >
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
          </Box>
        </Box>
      </Paper>
    </Box>
  );
}
