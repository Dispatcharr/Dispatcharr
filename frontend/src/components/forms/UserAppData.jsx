import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Eye, SquareMinus } from 'lucide-react';
import API from '../../api';
import ConfirmationDialog from '../ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import { CustomTable, useTable } from '../tables/CustomTable';
import '../tables/table.css';

const CLEAR_APP_DATA_KEY = 'clear-app-data';
const CLEAR_ALL_APP_DATA_KEY = 'clear-all-app-data';

const formatBytes = (bytes) => {
  const value = Number(bytes) || 0;
  if (value < 1024) {
    return `${value} B`;
  }
  return `${(value / 1024).toFixed(1)} KiB`;
};

const UserAppData = ({ userId, username, onClearAllChange }) => {
  const theme = useMantineTheme();
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [summary, setSummary] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [viewing, setViewing] = useState(null);

  const load = useCallback(async () => {
    if (!userId) {
      return;
    }
    setLoading(true);
    setLoadError(false);
    try {
      const data = await API.getUserAppData(userId);
      setSummary(data || { apps: [], total_bytes: 0, limits: null });
    } catch {
      // API shows notifications; do not pretend the user has an empty store.
      setLoadError(true);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  const clearAppData = useCallback(
    async (key) => {
      setClearing(true);
      try {
        await API.clearUserAppData(userId, key || null);
        notifications.show({
          title: 'App data cleared',
          message: key
            ? `Cleared data for ${key}.`
            : 'Cleared all app data for this user.',
          color: 'green',
        });
        setConfirm(null);
        await load();
      } catch {
        // API shows notifications
      } finally {
        setClearing(false);
      }
    },
    [load, userId]
  );

  const requestClear = useCallback(
    (key) => {
      const actionKey = key ? CLEAR_APP_DATA_KEY : CLEAR_ALL_APP_DATA_KEY;
      if (isWarningSuppressed(actionKey)) {
        clearAppData(key);
        return;
      }
      setConfirm({
        key,
        actionKey,
        title: key ? 'Confirm App Data Clear' : 'Confirm Clear All App Data',
        message: key
          ? `Are you sure you want to clear stored data for this app?\n\nUsername: ${username}\nApp key: ${key}\n\nThis action cannot be undone.`
          : `Are you sure you want to clear all app data for the following user?\n\nUsername: ${username}\n\nThis action cannot be undone.`,
      });
    },
    [clearAppData, isWarningSuppressed, username]
  );

  const viewAppData = useCallback(
    async (key) => {
      setViewing({ key, loading: true, text: '' });
      try {
        const value = await API.getUserAppDataValue(userId, key);
        setViewing({
          key,
          loading: false,
          text: JSON.stringify(value, null, 2),
        });
      } catch {
        setViewing(null);
      }
    },
    [userId]
  );

  const apps = useMemo(() => summary?.apps ?? [], [summary]);
  const tableData = useMemo(
    () =>
      apps.map((app) => ({
        id: app.key,
        key: app.key,
        bytes: app.bytes,
      })),
    [apps]
  );

  const columns = useMemo(
    () => [
      {
        id: 'key',
        header: 'App key',
        accessorKey: 'key',
        grow: true,
        minSize: 160,
        cell: ({ getValue }) => (
          <Text size="sm" style={{ wordBreak: 'break-all' }}>
            {getValue()}
          </Text>
        ),
      },
      {
        id: 'bytes',
        header: 'Size',
        accessorKey: 'bytes',
        size: 90,
        minSize: 70,
        cell: ({ getValue }) => (
          <Text size="sm">{formatBytes(getValue())}</Text>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        size: 60,
        minSize: 50,
        style: { justifyContent: 'flex-end' },
      },
    ],
    []
  );

  const renderHeaderCell = (header) => (
    <Text size="sm">{header.column.columnDef.header}</Text>
  );

  const renderBodyCell = ({ row }) => (
    <Group gap={4} justify="flex-end" wrap="nowrap" w="100%">
      <Tooltip label="View" openDelay={500}>
        <ActionIcon
          variant="transparent"
          size="sm"
          color="blue"
          aria-label={`View ${row.original.key}`}
          onClick={() => viewAppData(row.original.key)}
        >
          <Eye size={16} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Clear" openDelay={500}>
        <ActionIcon
          variant="transparent"
          size="sm"
          aria-label={`Clear ${row.original.key}`}
          onClick={() => requestClear(row.original.key)}
        >
          <SquareMinus size={18} color={theme.tailwind.red[6]} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );

  const table = useTable({
    columns,
    data: tableData,
    allRowIds: tableData.map((row) => row.id),
    headerCellRenderFns: {
      key: renderHeaderCell,
      bytes: renderHeaderCell,
      actions: renderHeaderCell,
    },
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
  });

  const canClearAll = !loadError && apps.length > 0;

  useEffect(() => {
    if (!onClearAllChange) {
      return undefined;
    }
    // An object, not a bare function: the parent stores this with setState,
    // which would treat a function as an updater and call it immediately.
    onClearAllChange(canClearAll ? { clear: () => requestClear(null) } : null);
    return () => onClearAllChange(null);
  }, [canClearAll, onClearAllChange, requestClear]);

  if (loading && !summary) {
    return (
      <Group justify="center" py="md">
        <Loader size="sm" />
      </Group>
    );
  }

  if (loadError) {
    return (
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          Could not load app data for this user.
        </Text>
        <Button
          size="xs"
          variant="light"
          onClick={load}
          style={{ alignSelf: 'flex-start' }}
        >
          Retry
        </Button>
      </Stack>
    );
  }

  const totalBytes = summary?.total_bytes || 0;
  const limits = summary?.limits;

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Third-party apps can store a small JSON blob under a unique key for this
        user. Clearing removes what that app saved; it does not revoke API keys.
      </Text>
      {limits && (
        <Text size="xs" c="dimmed">
          Limits: {formatBytes(limits.max_value_bytes)} per app,{' '}
          {formatBytes(limits.max_total_bytes)} total, {limits.max_apps} apps.
          Using {formatBytes(totalBytes)}.
        </Text>
      )}

      {apps.length === 0 ? (
        <Text size="sm" c="dimmed">
          No app data stored for this user.
        </Text>
      ) : (
        <Box
          style={{
            maxHeight: 320,
            overflowY: 'auto',
            overflowX: 'auto',
            border: 'solid 1px rgb(68, 68, 68)',
            borderRadius: 'var(--mantine-radius-default)',
          }}
        >
          <CustomTable table={table} />
        </Box>
      )}

      <Modal
        opened={!!viewing}
        onClose={() => setViewing(null)}
        title={viewing?.key || 'App data'}
        size="lg"
        zIndex={1100}
      >
        {viewing?.loading ? (
          <Group justify="center" py="md">
            <Loader size="sm" />
          </Group>
        ) : (
          <Code
            block
            style={{
              maxHeight: 360,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {viewing?.text}
          </Code>
        )}
      </Modal>

      <ConfirmationDialog
        opened={!!confirm}
        onClose={() => setConfirm(null)}
        onConfirm={() => clearAppData(confirm?.key)}
        loading={clearing}
        title={confirm?.title || 'Confirm'}
        message={
          <div style={{ whiteSpace: 'pre-line' }}>{confirm?.message || ''}</div>
        }
        confirmLabel="Clear"
        cancelLabel="Cancel"
        actionKey={confirm?.actionKey}
        onSuppressChange={suppressWarning}
        size="md"
        zIndex={1100}
      />
    </Stack>
  );
};

export default UserAppData;
