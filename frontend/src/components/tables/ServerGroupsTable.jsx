import { useEffect, useMemo, useRef, useState } from 'react';
import API from '../../api';
import useServerGroupsStore from '../../store/serverGroups';
import usePlaylistsStore from '../../store/playlists';
import useWarningsStore from '../../store/warnings';
import ServerGroupForm from '../forms/ServerGroup';
import ConfirmationDialog from '../ConfirmationDialog';
import {
  ActionIcon,
  Box,
  Button,
  Center,
  Flex,
  Stack,
  Text,
} from '@mantine/core';
import { SquareMinus, SquarePen, SquarePlus } from 'lucide-react';
import { CustomTable, useTable } from './CustomTable';
import './table.css';

const TABLE_WIDTH = 360;
const ACTIONS_COLUMN_SIZE = 76;
const ACCOUNTS_COLUMN_SIZE = 72;

const RowActions = ({ row, editServerGroup, deleteServerGroup }) => (
  <Flex gap={4} justify="center" w="100%">
    <ActionIcon
      variant="transparent"
      size="sm"
      color="yellow.5"
      onClick={() => editServerGroup(row.original)}
    >
      <SquarePen size="18" />
    </ActionIcon>
    <ActionIcon
      variant="transparent"
      size="sm"
      color="red.9"
      onClick={() => deleteServerGroup(row.original.id)}
    >
      <SquareMinus size="18" />
    </ActionIcon>
  </Flex>
);

const ServerGroupsTable = ({ onGroupCreated, openCreateOnMount = false }) => {
  const [serverGroup, setServerGroup] = useState(null);
  const [serverGroupModalOpen, setServerGroupModalOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [groupToDelete, setGroupToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const openedCreateOnMount = useRef(false);

  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  const serverGroups = useServerGroupsStore((state) => state.serverGroups);
  const fetchServerGroups = useServerGroupsStore(
    (state) => state.fetchServerGroups
  );
  const playlists = usePlaylistsStore((state) => state.playlists);

  const tableData = useMemo(
    () =>
      serverGroups.map((group) => ({
        ...group,
        accountCount: playlists.filter(
          (playlist) => playlist.server_group === group.id
        ).length,
      })),
    [serverGroups, playlists]
  );

  const columns = useMemo(
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        grow: true,
        minSize: 100,
        cell: ({ cell }) => (
          <Text size="sm" truncate>
            {cell.getValue()}
          </Text>
        ),
      },
      {
        header: 'Accounts',
        accessorKey: 'accountCount',
        size: ACCOUNTS_COLUMN_SIZE,
        minSize: 65,
        cell: ({ cell }) => (
          <Center w="100%">
            <Text size="sm">{cell.getValue() ?? 0}</Text>
          </Center>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        size: ACTIONS_COLUMN_SIZE,
        minSize: 65,
      },
    ],
    []
  );

  const [isLoading, setIsLoading] = useState(true);

  const editServerGroup = (group = null) => {
    setServerGroup(group);
    setServerGroupModalOpen(true);
  };

  const executeDeleteServerGroup = async (id) => {
    setDeleting(true);
    try {
      await API.deleteServerGroup(id);
    } finally {
      setDeleting(false);
      setConfirmDeleteOpen(false);
    }
  };

  const deleteServerGroup = (id) => {
    const group = tableData.find((item) => item.id === id);
    setGroupToDelete(group);
    setDeleteTarget(id);

    if (isWarningSuppressed('delete-server-group')) {
      return executeDeleteServerGroup(id);
    }

    setConfirmDeleteOpen(true);
  };

  const closeServerGroupForm = () => {
    setServerGroup(null);
    setServerGroupModalOpen(false);
  };

  const handleServerGroupSaved = (savedGroup) => {
    if (!serverGroup?.id) {
      onGroupCreated?.(savedGroup);
    }
  };

  useEffect(() => {
    fetchServerGroups().finally(() => setIsLoading(false));
  }, [fetchServerGroups]);

  useEffect(() => {
    if (!openCreateOnMount) {
      openedCreateOnMount.current = false;
      return;
    }
    if (!isLoading && !openedCreateOnMount.current) {
      openedCreateOnMount.current = true;
      editServerGroup();
    }
  }, [openCreateOnMount, isLoading]);

  const renderHeaderCell = (header) => (
    <Text size="sm" name={header.id}>
      {header.column.columnDef.header}
    </Text>
  );

  const renderBodyCell = ({ row }) => (
    <RowActions
      row={row}
      editServerGroup={editServerGroup}
      deleteServerGroup={deleteServerGroup}
    />
  );

  const table = useTable({
    columns,
    data: tableData,
    allRowIds: tableData.map((group) => group.id),
    enableColumnResizing: false,
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    headerCellRenderFns: {
      name: renderHeaderCell,
      accountCount: renderHeaderCell,
      actions: renderHeaderCell,
    },
  });

  if (isLoading) {
    return (
      <Center py="md">
        <Text size="sm">Loading server groups...</Text>
      </Center>
    );
  }

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Group accounts that share the same provider login so their connection
        limits are enforced together. Assign a group when editing an M3U
        account.
      </Text>

      <Flex justify="center">
        <Stack gap="xs" w={TABLE_WIDTH} maw="100%">
          <Flex justify="flex-end">
            <Button
              leftSection={<SquarePlus size={18} />}
              variant="light"
              size="xs"
              onClick={() => editServerGroup()}
              p={5}
              color="green"
              title="Create a shared connection pool for multiple accounts"
              style={{
                borderWidth: '1px',
                borderColor: 'green',
                color: 'white',
              }}
            >
              Add Server Group
            </Button>
          </Flex>

          <Box
            style={{
              maxHeight: 280,
              overflowY: 'auto',
              overflowX: 'auto',
              border: 'solid 1px rgb(68,68,68)',
              borderRadius: 'var(--mantine-radius-default)',
            }}
          >
            {tableData.length === 0 ? (
              <Center py="lg" px="xl">
                <Text size="sm" c="dimmed">
                  No server groups yet.
                </Text>
              </Center>
            ) : (
              <CustomTable table={table} />
            )}
          </Box>
        </Stack>
      </Flex>

      <ServerGroupForm
        serverGroup={serverGroup}
        isOpen={serverGroupModalOpen}
        onClose={closeServerGroupForm}
        onSaved={handleServerGroupSaved}
      />

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => executeDeleteServerGroup(deleteTarget)}
        loading={deleting}
        title="Confirm Server Group Deletion"
        message={
          groupToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following server group?

Name: ${groupToDelete.name}
Accounts: ${groupToDelete.accountCount ?? 0}

Accounts in this group will no longer share connection limits. This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this server group? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey="delete-server-group"
        onSuppressChange={suppressWarning}
        zIndex={401}
      />
    </Stack>
  );
};

export default ServerGroupsTable;
