import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert,
  Anchor,
  Box,
  Button,
  Group,
  Loader,
  Text,
  Title,
} from '@mantine/core';
import API from '../api';
import DownloadLogButton from '../components/DownloadLogButton';
import { CustomTable, useTable } from '../components/tables/CustomTable';
import { useDateTimeFormat, format } from '../utils/dateTimeUtils.js';
import { formatBytes } from '../utils/networkUtils.js';

const LogFilesPage = () => {
  const [files, setFiles] = useState([]);
  const [collectorRunning, setCollectorRunning] = useState(true);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const { fullDateTimeFormat } = useDateTimeFormat();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await API.getLogFiles();
      if (response) {
        setFiles(response.files || []);
        // A missing flag counts as running.
        setCollectorRunning(response.collector_running !== false);
        setLoadError(false);
      }
    } catch {
      // errorNotification already surfaced the failure
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const columns = useMemo(
    () => [
      {
        header: 'Filename',
        accessorKey: 'name',
        grow: true,
        minSize: 200,
        cell: ({ cell }) => (
          <Anchor
            component={Link}
            to={`/logs/${encodeURIComponent(cell.getValue())}`}
            size="sm"
          >
            {cell.getValue()}
          </Anchor>
        ),
      },
      {
        header: 'Last Write Time',
        accessorKey: 'modified',
        minSize: 190,
        cell: ({ cell }) => (
          <Text size="sm" style={{ whiteSpace: 'nowrap' }}>
            {format(cell.getValue(), fullDateTimeFormat)}
          </Text>
        ),
      },
      {
        header: 'Size',
        accessorKey: 'size',
        size: 110,
        cell: ({ cell }) => (
          <Text size="sm" title={`${cell.getValue().toLocaleString()} bytes`}>
            {formatBytes(cell.getValue())}
          </Text>
        ),
      },
      {
        id: 'actions',
        header: '',
        size: 120,
      },
    ],
    [fullDateTimeFormat]
  );

  const allRowIds = useMemo(() => files.map((file) => file.name), [files]);

  const renderHeaderCell = (header) => (
    <Text size="sm" name={header.id}>
      {header.column.columnDef.header}
    </Text>
  );

  const renderBodyCell = ({ cell, row }) => {
    switch (cell.column.id) {
      case 'actions':
        return <DownloadLogButton name={row.original.name} />;
    }
  };

  const table = useTable({
    columns,
    data: files,
    allRowIds,
    bodyCellRenderFns: { actions: renderBodyCell },
    headerCellRenderFns: {
      name: renderHeaderCell,
      modified: renderHeaderCell,
      size: renderHeaderCell,
      actions: renderHeaderCell,
    },
  });

  return (
    <Box p="md" maw={1100} mx="auto">
      <Group justify="space-between" mb="md">
        <Title order={3}>Logs</Title>
        <Button size="xs" variant="subtle" onClick={load} loading={loading}>
          Refresh
        </Button>
      </Group>

      {!collectorRunning && (
        <Alert
          variant="light"
          color="yellow"
          mb="md"
          title="Log collector not running"
        >
          These files are not being written to, and log settings will not take
          effect until a collector is running. Process output is unaffected.
        </Alert>
      )}

      <Box
        style={{
          overflowX: 'auto',
          overflowY: 'auto',
          border: 'solid 1px rgb(68,68,68)',
          borderRadius: 'var(--mantine-radius-default)',
        }}
      >
        {loading && files.length === 0 ? (
          <Box p="xl" style={{ display: 'flex', justifyContent: 'center' }}>
            <Loader />
          </Box>
        ) : files.length === 0 ? (
          <Text size="sm" c={loadError ? 'red' : 'dimmed'} p="md" ta="center">
            {loadError ? 'Failed to load log files' : 'No log files yet'}
          </Text>
        ) : (
          <CustomTable table={table} />
        )}
      </Box>
    </Box>
  );
};

export default LogFilesPage;
