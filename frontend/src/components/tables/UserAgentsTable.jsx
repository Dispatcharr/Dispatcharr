import { useEffect, useMemo, useRef, useState } from 'react';
import { MantineReactTable, useMantineReactTable } from 'mantine-react-table';
import API from '../../api';
import useUserAgentsStore from '../../store/userAgents';
import UserAgentForm from '../forms/UserAgent';
import { TableHelper } from '../../helpers';
import useSettingsStore from '../../store/settings';
import { notifications } from '@mantine/notifications';
import {
  ActionIcon,
  Center,
  Flex,
  Select,
  Tooltip,
  Text,
  Paper,
  Box,
  Button,
} from '@mantine/core';
import { IconSquarePlus } from '@tabler/icons-react';
import { SquareMinus, SquarePen, Check, X } from 'lucide-react';

const UserAgentsTable = () => {
  const [userAgent, setUserAgent] = useState(null);
  const [userAgentModalOpen, setUserAgentModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);
  const [activeFilterValue, setActiveFilterValue] = useState('all');

  const userAgents = useUserAgentsStore((state) => state.userAgents);
  const { settings } = useSettingsStore();

  const columns = useMemo(
    //column definitions...
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
      },
      {
        header: 'User-Agent',
        accessorKey: 'user_agent',
        enableSorting: false,
        Cell: ({ cell }) => (
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
        header: 'Desecription',
        accessorKey: 'description',
        enableSorting: false,
        Cell: ({ cell }) => (
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
        size: 10,
        sortingFn: 'basic',
        enableSorting: false,
        mantineTableHeadCellProps: {
          align: 'right',
        },
        mantineTableBodyCellProps: {
          align: 'right',
        },
        Cell: ({ cell }) => (
          <Center>
            {cell.getValue() ? <Check color="green" /> : <X color="red" />}
          </Center>
        ),
        Filter: ({ column }) => (
          <Select
            size="small"
            value={activeFilterValue}
            onChange={(e) => {
              setActiveFilterValue(e.target.value);
              column.setFilterValue(e.target.value);
            }}
            displayEmpty
            data={[
              {
                value: 'all',
                label: 'All',
              },
              {
                value: 'active',
                label: 'Active',
              },
              {
                value: 'inactive',
                label: 'Inactive',
              },
            ]}
          />
        ),
        filterFn: (row, _columnId, activeFilterValue) => {
          if (activeFilterValue == 'all') return true; // Show all if no filter
          return String(row.getValue('is_active')) === activeFilterValue;
        },
      },
    ],
    []
  );

  //optionally access the underlying virtualizer instance
  const rowVirtualizerInstanceRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const editUserAgent = async (userAgent = null) => {
    setUserAgent(userAgent);
    setUserAgentModalOpen(true);
  };

  const deleteUserAgent = async (ids) => {
    if (Array.isArray(ids)) {
      if (ids.includes(settings['default-user-agent'].value)) {
        notifications.show({
          title: 'Cannot delete default user-agent',
          color: 'red.5',
        });
        return;
      }

      await API.deleteUserAgents(ids);
    } else {
      if (ids == settings['default-user-agent'].value) {
        notifications.show({
          title: 'Cannot delete default user-agent',
          color: 'red.5',
        });
        return;
      }

      await API.deleteUserAgent(ids);
    }
  };

  const closeUserAgentForm = () => {
    setUserAgent(null);
    setUserAgentModalOpen(false);
  };

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    //scroll to the top of the table when the sorting changes
    try {
      rowVirtualizerInstanceRef.current?.scrollToIndex?.(0);
    } catch (error) {
      console.error(error);
    }
  }, [sorting]);

  const table = useMantineReactTable({
    ...TableHelper.defaultProperties,
    columns,
    data: userAgents,
    enablePagination: false,
    enableRowVirtualization: true,
    // enableRowSelection: true,
    renderTopToolbar: false,
    // onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    state: {
      isLoading,
      sorting,
      // rowSelection,
    },
    rowVirtualizerInstanceRef, //optional
    rowVirtualizerOptions: { overscan: 5 }, //optionally customize the row virtualizer
    initialState: {
      density: 'compact',
    },
    enableRowActions: true,
    renderRowActions: ({ row }) => (
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
          onClick={() => deleteUserAgent(row.original.id)}
        >
          <SquareMinus size="18" /> {/* Small icon size */}
        </ActionIcon>
      </>
    ),
    mantineTableContainerProps: {
      style: {
        height: 'calc(43vh - 55px)',
      },
    },
    displayColumnDefOptions: {
      'mrt-row-actions': {
        size: 10,
      },
    },
  });

  return (
    <>
      <Flex
        style={{
          display: 'flex',
          alignItems: 'center',
          paddingTop: 10,
          paddingBottom: 10,
        }}
        gap={15}
      >
        <Text
          h={24}
          style={{
            fontFamily: 'Inter, sans-serif',
            fontWeight: 500,
            fontSize: '20px',
            lineHeight: 1,
            letterSpacing: '-0.3px',
            color: 'gray.6', // Adjust this to match MUI's theme.palette.text.secondary
            marginBottom: 0,
          }}
        >
          User-Agents
        </Text>
      </Flex>

      <Paper
        style={
          {
            // bgcolor: theme.palette.background.paper,
            // borderRadius: 2,
            // overflow: 'hidden',
            // height: 'calc(100vh - 75px)',
            // display: 'flex',
            // flexDirection: 'column',
          }
        }
      >
        {/* Top toolbar with Remove, Assign, Auto-match, and Add buttons */}
        <Box
          style={{
            display: 'flex',
            // alignItems: 'center',
            // backgroundColor: theme.palette.background.paper,
            justifyContent: 'flex-end',
            padding: 10,
            // gap: 1,
          }}
        >
          <Flex gap={6}>
            <Tooltip label="Assign">
              <Button
                leftSection={<IconSquarePlus size={18} />}
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

      <MantineReactTable table={table} />
      <UserAgentForm
        userAgent={userAgent}
        isOpen={userAgentModalOpen}
        onClose={closeUserAgentForm}
      />
    </>
  );
};

export default UserAgentsTable;
