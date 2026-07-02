import { useMemo, useState } from 'react';
import API from '../../api';
import useUserAgentsStore from '../../store/userAgents';
import UserAgentForm from '../forms/UserAgent';
import useSettingsStore from '../../store/settings';
import {
  ActionIcon,
  Center,
  Flex,
  Tooltip,
  Text,
  Paper,
  Box,
  Button,
  Stack,
} from '@mantine/core';
import { SquareMinus, SquarePen, Check, X, SquarePlus } from 'lucide-react';
import { CustomTable, useTable } from './CustomTable';
import useLocalStorage from '../../hooks/useLocalStorage';
import { showNotification } from '../../utils/notificationUtils.js';

const deleteUserAgents = async (ids) => {
  for (const id of ids) {
    try {
      await API.deleteUserAgent(id);
    } catch {
      /* empty */
    }
  }
};
const deleteUserAgent = (id) => API.deleteUserAgent(id);

const RowActions = ({ row, editUserAgent, handleDeleteUserAgent }) => {
  return (
    <>
      <ActionIcon
        variant="transparent"
        size="sm" // Makes the button smaller
        color="yellow.5" // Red color for delete actions
        onClick={() => {
          editUserAgent(row.original);
        }}
      >
        <SquarePen size="18" /> {/* Small icon size */}
      </ActionIcon>
      <ActionIcon
        variant="transparent"
        size="sm"
        color="red.9" // Red color for delete actions
        onClick={() => handleDeleteUserAgent(row.original.id)}
      >
        <SquareMinus size="18" /> {/* Small icon size */}
      </ActionIcon>
    </>
  );
};

const UserAgentsTable = () => {
  const [userAgent, setUserAgent] = useState(null);
  const [userAgentModalOpen, setUserAgentModalOpen] = useState(false);

  const userAgents = useUserAgentsStore((state) => state.userAgents);
  const settings = useSettingsStore((s) => s.settings);
  const [tableSize] = useLocalStorage('table-size', 'default');

  const columns = useMemo(
    //column definitions...
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        size: 125,
      },
      {
        header: 'User-Agent',
        accessorKey: 'user_agent',
        enableSorting: false,
        grow: true,
        cell: ({ cell }) => (
          <div
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {cell.getValue()}
          </div>
        ),
      },
      {
        header: 'Description',
        accessorKey: 'description',
        enableSorting: false,
        cell: ({ cell }) => (
          <div
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {cell.getValue()}
          </div>
        ),
      },
      {
        header: 'Active',
        accessorKey: 'is_active',
        sortingFn: 'basic',
        enableSorting: false,
        size: 60,
        cell: ({ cell }) => (
          <Center>
            {cell.getValue() ? <Check color="green" /> : <X color="red" />}
          </Center>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        size: tableSize == 'compact' ? 50 : 75,
      },
    ],
    []
  );

  const editUserAgent = async (userAgent = null) => {
    setUserAgent(userAgent);
    setUserAgentModalOpen(true);
  };

  const handleDeleteUserAgent = async (ids) => {
    if (Array.isArray(ids)) {
      if (ids.includes(settings.default_user_agent)) {
        showNotification({
          title: 'Cannot delete default user-agent',
          color: 'red.5',
        });
        return;
      }
      await deleteUserAgents(ids);
    } else {
      if (ids == settings.default_user_agent) {
        showNotification({
          title: 'Cannot delete default user-agent',
          color: 'red.5',
        });
        return;
      }
      await deleteUserAgent(ids);
    }
  };

  const closeUserAgentForm = () => {
    setUserAgent(null);
    setUserAgentModalOpen(false);
  };

  const renderHeaderCell = (header) => {
    switch (header.id) {
      default:
        return (
          <Text size="sm" name={header.id}>
            {header.column.columnDef.header}
          </Text>
        );
    }
  };

  const renderBodyCell = ({ cell, row }) => {
    switch (cell.column.id) {
      case 'actions':
        return (
          <RowActions
            row={row}
            editUserAgent={editUserAgent}
            handleDeleteUserAgent={handleDeleteUserAgent}
          />
        );
    }
  };

  const table = useTable({
    columns,
    data: userAgents,
    allRowIds: userAgents.map((ua) => ua.id),
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    headerCellRenderFns: {
      name: renderHeaderCell,
      user_agent: renderHeaderCell,
      description: renderHeaderCell,
      is_active: renderHeaderCell,
      actions: renderHeaderCell,
    },
  });

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
            <Tooltip label="Assign">
              <Button
                leftSection={<SquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editUserAgent()}
                p={5}
                color="green"
                style={{
                  borderWidth: '1px',
                  borderColor: 'green',
                  color: 'white',
                }}
              >
                Add User-Agent
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
          <div style={{ minWidth: 500 }}>
            <CustomTable table={table} />
          </div>
        </Box>
      </Box>

      <UserAgentForm
        userAgent={userAgent}
        isOpen={userAgentModalOpen}
        onClose={closeUserAgentForm}
      />
    </Stack>
  );
};

export default UserAgentsTable;
