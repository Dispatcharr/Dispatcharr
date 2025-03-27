import { useEffect, useMemo, useRef, useState } from 'react';
import { MantineReactTable, useMantineReactTable } from 'mantine-react-table';
import API from '../../api';
import StreamProfileForm from '../forms/StreamProfile';
import useStreamProfilesStore from '../../store/streamProfiles';
import { TableHelper } from '../../helpers';
import useSettingsStore from '../../store/settings';
import { notifications } from '@mantine/notifications';
import {
  Box,
  ActionIcon,
  Tooltip,
  Text,
  Paper,
  Flex,
  Button,
  useMantineTheme,
  Center,
  Switch,
} from '@mantine/core';
import { IconSquarePlus } from '@tabler/icons-react';
import { SquareMinus, SquarePen, Check, X, Eye, EyeOff } from 'lucide-react';

const StreamProfiles = () => {
  const [profile, setProfile] = useState(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);
  const [activeFilterValue, setActiveFilterValue] = useState('all');
  const [hideInactive, setHideInactive] = useState(false);

  const streamProfiles = useStreamProfilesStore((state) => state.profiles);
  const { settings } = useSettingsStore();

  const theme = useMantineTheme();

  const columns = useMemo(
    //column definitions...
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        size: 50,
      },
      {
        header: 'Command',
        accessorKey: 'command',
        size: 100,
      },
      {
        header: 'Parameters',
        accessorKey: 'parameters',
        enableSorting: false,
        mantineTableBodyCellProps: {
          style: {
            whiteSpace: 'nowrap',
            // maxWidth: 400,
            paddingLeft: 10,
            paddingRight: 10,
          },
        },
      },
      {
        header: 'Active',
        accessorKey: 'is_active',
        size: 10,
        enableSorting: false,
        mantineTableHeadCellProps: {
          align: 'right',
        },
        mantineTableBodyCellProps: {
          align: 'right',
        },
        Cell: ({ row, cell }) => (
          <Center>
            <Switch
              size="xs"
              checked={cell.getValue()}
              onChange={() => toggleProfileIsActive(row.original)}
              disabled={row.original.locked}
            />
          </Center>
        ),
        Filter: ({ column }) => (
          <Box>
            <Select
              size="small"
              value={activeFilterValue}
              onChange={(e) => {
                setActiveFilterValue(e.target.value);
                column.setFilterValue(e.target.value);
              }}
              displayEmpty
              data={['All', 'Active', 'Inactive']}
            />
          </Box>
        ),
        filterFn: (row, _columnId, filterValue) => {
          if (filterValue == 'all') return true;
          return String(row.getValue('is_active')) === filterValue;
        },
      },
    ],
    []
  );

  //optionally access the underlying virtualizer instance
  const rowVirtualizerInstanceRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const editStreamProfile = async (profile = null) => {
    setProfile(profile);
    setProfileModalOpen(true);
  };

  const deleteStreamProfile = async (id) => {
    if (id == settings['default-stream-profile'].value) {
      notifications.show({
        title: 'Cannot delete default stream-profile',
        color: 'red.5',
      });
      return;
    }

    await API.deleteStreamProfile(id);
  };

  const closeStreamProfileForm = () => {
    setProfile(null);
    setProfileModalOpen(false);
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

  const toggleHideInactive = () => {
    setHideInactive(!hideInactive);
  };

  const toggleProfileIsActive = async (profile) => {
    await API.updateStreamProfile({
      id: profile.id,
      ...profile,
      is_active: !profile.is_active,
    });
  };

  const filteredData = streamProfiles.filter((profile) =>
    hideInactive && !profile.is_active ? false : true
  );

  const table = useMantineReactTable({
    ...TableHelper.defaultProperties,
    columns,
    data: filteredData,
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
    displayColumnDefOptions: {
      'mrt-row-actions': {
        size: 10,
      },
    },
    enableRowActions: true,
    renderRowActions: ({ row }) => (
      <>
        <ActionIcon
          variant="transparent"
          color="yellow.5"
          size="sm"
          disabled={row.original.locked}
          onClick={() => editStreamProfile(row.original)}
        >
          <SquarePen size="18" /> {/* Small icon size */}
        </ActionIcon>
        <ActionIcon
          variant="transparent"
          size="sm"
          color="red.9"
          disabled={row.original.locked}
          onClick={() => deleteStreamProfile(row.original.id)}
        >
          <SquareMinus fontSize="small" /> {/* Small icon size */}
        </ActionIcon>
      </>
    ),
    mantineTableContainerProps: {
      style: {
        height: 'calc(100vh - 120px)',
        overflowY: 'auto',
      },
    },
  });

  return (
    <Box>
      <Flex
        style={{
          display: 'flex',
          alignItems: 'center',
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
          Stream Profiles
        </Text>
      </Flex>

      <Paper
        style={{
          bgcolor: theme.palette.background.paper,
          borderRadius: 2,
        }}
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
            <Tooltip label={hideInactive ? 'Show All' : 'Hide Inactive'}>
              <Center>
                <ActionIcon
                  onClick={toggleHideInactive}
                  variant="filled"
                  color="gray"
                  style={{
                    borderWidth: '1px',
                    borderColor: 'white',
                  }}
                >
                  {hideInactive ? <EyeOff size={18} /> : <Eye size={18} />}
                </ActionIcon>
              </Center>
            </Tooltip>
            <Tooltip label="Assign">
              <Button
                leftSection={<IconSquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editStreamProfile()}
                p={5}
                color="green"
                style={{
                  borderWidth: '1px',
                  borderColor: 'green',
                  color: 'white',
                }}
              >
                Add Stream Profile
              </Button>
            </Tooltip>
          </Flex>
        </Box>
      </Paper>

      <MantineReactTable table={table} />

      <StreamProfileForm
        profile={profile}
        isOpen={profileModalOpen}
        onClose={closeStreamProfileForm}
      />
    </Box>
  );
};

export default StreamProfiles;
