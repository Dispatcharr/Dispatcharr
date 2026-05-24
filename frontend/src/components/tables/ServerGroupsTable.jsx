import { useEffect, useMemo, useState } from 'react';
import API from '../../api';
import useServerGroupsStore from '../../store/serverGroups';
import ServerGroupForm from '../forms/ServerGroup';
import {
  ActionIcon,
  Box,
  Button,
  Center,
  Flex,
  Paper,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { SquareMinus, SquarePen, SquarePlus } from 'lucide-react';
import { CustomTable, useTable } from './CustomTable';
import useLocalStorage from '../../hooks/useLocalStorage';

const RowActions = ({ row, editServerGroup, deleteServerGroup }) => {
  return (
    <>
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
    </>
  );
};

const ServerGroupsTable = () => {
  const [serverGroup, setServerGroup] = useState(null);
  const [serverGroupModalOpen, setServerGroupModalOpen] = useState(false);

  const serverGroups = useServerGroupsStore((state) => state.serverGroups);
  const fetchServerGroups = useServerGroupsStore(
    (state) => state.fetchServerGroups
  );
  const [tableSize] = useLocalStorage('table-size', 'default');

  const columns = useMemo(
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        size: 175,
      },
      {
        header: 'Max Streams',
        accessorKey: 'max_streams',
        size: 100,
        cell: ({ cell }) => {
          const value = cell.getValue();
          return value === 0 ? 'Unlimited' : value;
        },
      },
      {
        id: 'actions',
        header: 'Actions',
        size: tableSize == 'compact' ? 50 : 75,
      },
    ],
    [tableSize]
  );

  const [isLoading, setIsLoading] = useState(true);

  const editServerGroup = (group = null) => {
    setServerGroup(group);
    setServerGroupModalOpen(true);
  };

  const deleteServerGroup = async (id) => {
    await API.deleteServerGroup(id);
  };

  const closeServerGroupForm = () => {
    setServerGroup(null);
    setServerGroupModalOpen(false);
  };

  useEffect(() => {
    fetchServerGroups().finally(() => setIsLoading(false));
  }, [fetchServerGroups]);

  const renderHeaderCell = (header) => {
    return (
      <Text size="sm" name={header.id}>
        {header.column.columnDef.header}
      </Text>
    );
  };

  const renderBodyCell = ({ row }) => {
    return (
      <RowActions
        row={row}
        editServerGroup={editServerGroup}
        deleteServerGroup={deleteServerGroup}
      />
    );
  };

  const table = useTable({
    columns,
    data: serverGroups,
    allRowIds: serverGroups.map((group) => group.id),
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    headerCellRenderFns: {
      name: renderHeaderCell,
      max_streams: renderHeaderCell,
      actions: renderHeaderCell,
    },
  });

  if (isLoading) {
    return (
      <Center>
        <Text size="sm">Loading server groups...</Text>
      </Center>
    );
  }

  return (
    <Stack gap={0} style={{ padding: 0 }}>
      <Paper>
        <Box
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            padding: 10,
          }}
        >
          <Flex gap={6}>
            <Tooltip label="Create a shared connection pool for multiple accounts">
              <Button
                leftSection={<SquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editServerGroup()}
                p={5}
                color="green"
                style={{
                  borderWidth: '1px',
                  borderColor: 'green',
                  color: 'white',
                }}
              >
                Add Server Group
              </Button>
            </Tooltip>
          </Flex>
        </Box>
      </Paper>

      <Box
        style={{
          display: 'flex',
          flexDirection: 'column',
          maxHeight: 300,
          width: '100%',
          overflow: 'hidden',
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
          <div style={{ minWidth: 400 }}>
            <CustomTable table={table} />
          </div>
        </Box>
      </Box>

      <ServerGroupForm
        serverGroup={serverGroup}
        isOpen={serverGroupModalOpen}
        onClose={closeServerGroupForm}
      />
    </Stack>
  );
};

export default ServerGroupsTable;
