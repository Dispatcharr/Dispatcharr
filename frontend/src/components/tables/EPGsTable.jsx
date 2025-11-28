import React, { useEffect, useMemo, useRef, useState } from 'react';
import API from '../../api';
import useEPGsStore from '../../store/epgs';
import EPGForm from '../forms/EPG';
import DummyEPGForm from '../forms/DummyEPG';
import { TableHelper } from '../../helpers';
import {
  ActionIcon,
  Text,
  Tooltip,
  Box,
  Paper,
  Button,
  Flex,
  useMantineTheme,
  Switch,
  Badge,
  Progress,
  Stack,
  Group,
  Menu,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  ArrowDownWideNarrow,
  ArrowUpDown,
  ArrowUpNarrowWide,
  RefreshCcw,
  SquareMinus,
  SquarePen,
  SquarePlus,
  ChevronDown,
} from 'lucide-react';
import dayjs from 'dayjs';
import useSettingsStore from '../../store/settings';
import useLocalStorage from '../../hooks/useLocalStorage';
import ConfirmationDialog from '../../components/ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import { CustomTable, useTable } from './CustomTable';

// Helper function to format status text
const formatStatusText = (status) => {
  if (!status) return 'Unknown';
  return status.charAt(0).toUpperCase() + status.slice(1).toLowerCase();
};

// Helper function to get status text color
const getStatusColor = (status) => {
  switch (status) {
    case 'idle':
      return 'gray.5';
    case 'fetching':
      return 'blue.5';
    case 'parsing':
      return 'indigo.5';
    case 'error':
      return 'red.5';
    case 'success':
      return 'green.5';
    default:
      return 'gray.5';
  }
};

const RowActions = ({ tableSize, row, editEPG, deleteEPG, refreshEPG }) => {
  const iconSize =
    tableSize == 'default' ? 'sm' : tableSize == 'compact' ? 'xs' : 'md';
  const isDummyEPG = row.original.source_type === 'dummy';

  return (
    <>
      <ActionIcon
        variant="transparent"
        size={iconSize} // Use standardized icon size
        color="yellow.5" // Red color for delete actions
        onClick={() => editEPG(row.original)}
      >
        <SquarePen size={tableSize === 'compact' ? 16 : 18} />{' '}
        {/* Small icon size */}
      </ActionIcon>
      <ActionIcon
        variant="transparent"
        size={iconSize} // Use standardized icon size
        color="red.9" // Red color for delete actions
        onClick={() => deleteEPG(row.original.id)}
      >
        <SquareMinus size={tableSize === 'compact' ? 16 : 18} />{' '}
        {/* Small icon size */}
      </ActionIcon>
      <ActionIcon
        variant="transparent"
        size={iconSize} // Use standardized icon size
        color="blue.5" // Red color for delete actions
        onClick={() => refreshEPG(row.original.id)}
        disabled={!row.original.is_active || isDummyEPG}
      >
        <RefreshCcw size={tableSize === 'compact' ? 16 : 18} />{' '}
        {/* Small icon size */}
      </ActionIcon>
    </>
  );
};

const EPGsTable = () => {
  const [epg, setEPG] = useState(null);
  const [epgModalOpen, setEPGModalOpen] = useState(false);
  const [dummyEpgModalOpen, setDummyEpgModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [epgToDelete, setEpgToDelete] = useState(null);
  const [data, setData] = useState([]);

  const epgs = useEPGsStore((s) => s.epgs);
  const refreshProgress = useEPGsStore((s) => s.refreshProgress);

  const theme = useMantineTheme();
  // Get tableSize directly from localStorage instead of the store
  const [tableSize] = useLocalStorage('table-size', 'default');

  // Get proper size for action icons to match ChannelsTable
  const iconSize =
    tableSize === 'compact' ? 'xs' : tableSize === 'large' ? 'md' : 'sm';

  // Calculate density for Mantine Table
  const tableDensity =
    tableSize === 'compact' ? 'xs' : tableSize === 'large' ? 'xl' : 'md';

  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  const toggleActive = async (epg) => {
    try {
      // Validate that epg is a valid object with an id
      if (!epg || typeof epg !== 'object' || !epg.id) {
        console.error('toggleActive called with invalid epg:', epg);
        return;
      }

      // Send only the is_active field to trigger our special handling
      await API.updateEPG(
        {
          id: epg.id,
          is_active: !epg.is_active,
        },
        true
      ); // Add a new parameter to indicate this is just a toggle
    } catch (error) {
      console.error('Error toggling active state:', error);
    }
  };

  const buildProgressDisplay = (data) => {
    const progress = refreshProgress[data.id] || null;

    if (!progress) return null;

    let label = '';
    switch (progress.action) {
      case 'downloading':
        label = 'Downloading';
        break;
      case 'parsing_channels':
        label = 'Parsing Channels';
        break;
      case 'parsing_programs':
        label = 'Parsing Programs';
        break;
      default:
        return null;
    }

    return (
      <Stack spacing={2}>
        <Text size="xs">
          {label}: {parseInt(progress.progress)}%
        </Text>
        <Progress
          value={parseInt(progress.progress)}
          size="xs"
          style={{ margin: '2px 0' }}
        />
        {progress.speed && (
          <Text size="xs">Speed: {parseInt(progress.speed)} KB/s</Text>
        )}
      </Stack>
    );
  };

  const columns = useMemo(
    //column definitions...
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        size: 200,
      },
      {
        header: 'Type',
        accessorKey: 'source_type',
        size: 100,
      },
      {
        header: 'URL / API Key / File Path',
        accessorKey: 'url',
        enableSorting: false,
        minSize: 250,
        cell: ({ cell, row }) => {
          const value =
            cell.getValue() ||
            row.original.api_key ||
            row.original.file_path ||
            '';
          return (
            <Tooltip label={value} disabled={!value}>
              <div
                style={{
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  maxWidth: '100%',
                }}
              >
                {value}
              </div>
            </Tooltip>
          );
        },
      },
      {
        header: 'Status',
        accessorKey: 'status',
        size: 100,
        cell: ({ row }) => {
          const data = row.original;
          const isDummyEPG = data.source_type === 'dummy';

          // Dummy EPGs always show idle status
          const displayStatus = isDummyEPG ? 'idle' : data.status;

          return (
            <Text size="sm" fw={500} c={getStatusColor(displayStatus)}>
              {formatStatusText(displayStatus)}
            </Text>
          );
        },
      },
      {
        header: 'Status Message',
        accessorKey: 'last_message',
        enableSorting: false,
        minSize: 250,
        grow: true,
        cell: ({ row }) => {
          const data = row.original;
          const isDummyEPG = data.source_type === 'dummy';

          // Dummy EPGs don't have status messages
          if (isDummyEPG) {
            return null;
          }

          // Check if there's an active progress for this EPG - show progress first if active
          if (
            refreshProgress[data.id] &&
            refreshProgress[data.id].progress < 100
          ) {
            return buildProgressDisplay(data);
          }

          // Show error message when status is error
          if (data.status === 'error' && data.last_message) {
            return (
              <Tooltip label={data.last_message} multiline width={300}>
                <Text
                  c="dimmed"
                  size="xs"
                  lineClamp={2}
                  style={{ color: theme.colors.red[6], lineHeight: 1.3 }}
                >
                  {data.last_message}
                </Text>
              </Tooltip>
            );
          }

          // Show success message for successful sources
          if (data.status === 'success') {
            return (
              <Text
                c="dimmed"
                size="xs"
                style={{ color: theme.colors.green[6], lineHeight: 1.3 }}
              >
                EPG data refreshed successfully
              </Text>
            );
          }

          // Otherwise return empty cell
          return null;
        },
      },
      {
        header: 'Updated',
        accessorKey: 'updated_at',
        size: 175,
        enableSorting: false,
        cell: ({ cell }) => {
          const value = cell.getValue();
          return value ? (
            <Text size="xs">{new Date(value).toLocaleString()}</Text>
          ) : (
            <Text size="xs">Never</Text>
          );
        },
      },
      {
        header: 'Active',
        accessorKey: 'is_active',
        size: 50,
        sortingFn: 'basic',
        mantineTableBodyCellProps: {
          align: 'left',
        },
        cell: ({ row, cell }) => {
          const isDummyEPG = row.original.source_type === 'dummy';
          return (
            <Box sx={{ display: 'flex', justifyContent: 'center' }}>
              <Switch
                size="xs"
                checked={cell.getValue()}
                onChange={() => toggleActive(row.original)}
                disabled={isDummyEPG}
              />
            </Box>
          );
        },
      },
      {
        id: 'actions',
        header: 'Actions',
        size: tableSize == 'compact' ? 75 : 100,
      },
    ],
    [refreshProgress]
  );

  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const editEPG = async (epg = null) => {
    setEPG(epg);
    // Open the appropriate modal based on source type
    if (epg?.source_type === 'dummy') {
      setDummyEpgModalOpen(true);
    } else {
      setEPGModalOpen(true);
    }
  };

  const createStandardEPG = () => {
    setEPG(null);
    setEPGModalOpen(true);
  };

  const createDummyEPG = () => {
    setEPG(null);
    setDummyEpgModalOpen(true);
  };

  const deleteEPG = async (id) => {
    // Get EPG details for the confirmation dialog
    const epgObj = epgs[id];
    setEpgToDelete(epgObj);
    setDeleteTarget(id);

    // Skip warning if it's been suppressed
    if (isWarningSuppressed('delete-epg')) {
      return executeDeleteEPG(id);
    }

    setConfirmDeleteOpen(true);
  };

  const executeDeleteEPG = async (id) => {
    setIsLoading(true);
    await API.deleteEPG(id);
    setIsLoading(false);
    setConfirmDeleteOpen(false);
  };

  const refreshEPG = async (id) => {
    await API.refreshEPG(id);
    notifications.show({
      title: 'EPG refresh initiated',
    });
  };

  const closeEPGForm = () => {
    setEPG(null);
    setEPGModalOpen(false);
  };

  const closeDummyEPGForm = () => {
    setEPG(null);
    setDummyEpgModalOpen(false);
  };

  useEffect(() => {
    setData(
      Object.values(epgs).sort((a, b) => {
        // First sort by active status (active items first)
        if (a.is_active !== b.is_active) {
          return a.is_active ? -1 : 1;
        }
        // Then sort by name (case-insensitive)
        return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
      })
    );
  }, [epgs]);

  const renderBodyCell = ({ cell, row }) => {
    switch (cell.column.id) {
      case 'actions':
        return (
          <RowActions
            tableSize={tableSize}
            row={row}
            editEPG={editEPG}
            deleteEPG={deleteEPG}
            refreshEPG={refreshEPG}
          />
        );
    }
  };

  const renderHeaderCell = (header) => {
    let sortingIcon = ArrowUpDown;
    if (sorting[0]?.id == header.id) {
      if (sorting[0].desc === false) {
        sortingIcon = ArrowUpNarrowWide;
      } else {
        sortingIcon = ArrowDownWideNarrow;
      }
    }

    switch (header.id) {
      default:
        return (
          <Group>
            <Text size="sm" name={header.id}>
              {header.column.columnDef.header}
            </Text>
            {header.column.columnDef.sortable && (
              <Center>
                {React.createElement(sortingIcon, {
                  onClick: () => onSortingChange(header.id),
                  size: 14,
                })}
              </Center>
            )}
          </Group>
        );
    }
  };

  const onSortingChange = (column) => {
    console.log(column);
    const sortField = sorting[0]?.id;
    const sortDirection = sorting[0]?.desc;

    const newSorting = [];
    if (sortField == column) {
      if (sortDirection == false) {
        newSorting[0] = {
          id: column,
          desc: true,
        };
      }
    } else {
      newSorting[0] = {
        id: column,
        desc: false,
      };
    }

    setSorting(newSorting);
    if (newSorting.length > 0) {
      const compareColumn = newSorting[0].id;
      const compareDesc = newSorting[0].desc;

      setData(
        epgs.sort((a, b) => {
          console.log(a);
          console.log(newSorting[0].id);
          if (a[compareColumn] !== b[compareColumn]) {
            return compareDesc ? 1 : -1;
          }

          return 0;
        })
      );
    }
  };

  const table = useTable({
    columns,
    data,
    allRowIds: data.map((epg) => epg.id),
    enablePagination: false,
    enableRowSelection: false,
    renderTopToolbar: false,
    onRowSelectionChange: setRowSelection,
    manualSorting: true,
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    headerCellRenderFns: {
      name: renderHeaderCell,
      source_type: renderHeaderCell,
      url: renderHeaderCell,
      status: renderHeaderCell,
      last_message: renderHeaderCell,
      updated_at: renderHeaderCell,
      is_active: renderHeaderCell,
      actions: renderHeaderCell,
    },
    // Add custom cell styles to match CustomTable's sizing
    tableCellProps: ({ cell }) => {
      return {
        // Apply taller height for progress cells (except initializing), otherwise use standard height
        fontSize:
          tableSize === 'compact'
            ? 'var(--mantine-font-size-xs)'
            : 'var(--mantine-font-size-sm)',
        padding: tableSize === 'compact' ? '2px 8px' : '4px 10px',
      };
    },
  });

  return (
    <Box>
      <Flex
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
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
          EPGs
        </Text>
        <Menu shadow="md" width={200}>
          <Menu.Target>
            <Button
              leftSection={<SquarePlus size={18} />}
              rightSection={<ChevronDown size={16} />}
              variant="light"
              size="xs"
              p={5}
              color="green"
              style={{
                borderWidth: '1px',
                borderColor: 'green',
                color: 'white',
              }}
            >
              Add EPG
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={createStandardEPG}>
              Standard EPG Source
            </Menu.Item>
            <Menu.Item onClick={createDummyEPG}>Dummy EPG Source</Menu.Item>
          </Menu.Dropdown>
        </Menu>
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
            padding: 0,
            // gap: 1,
          }}
        ></Box>
      </Paper>

      <Box
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: 'calc(40vh - 15px)',
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
          <CustomTable table={table} />
        </Box>
      </Box>

      <EPGForm epg={epg} isOpen={epgModalOpen} onClose={closeEPGForm} />
      <DummyEPGForm
        epg={epg}
        isOpen={dummyEpgModalOpen}
        onClose={closeDummyEPGForm}
      />

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => executeDeleteEPG(deleteTarget)}
        title="Confirm EPG Source Deletion"
        message={
          epgToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following EPG source?

Name: ${epgToDelete.name}
Source Type: ${epgToDelete.source_type}
${
  epgToDelete.url
    ? `URL: ${epgToDelete.url}`
    : epgToDelete.api_key
      ? `API Key: ${epgToDelete.api_key}`
      : epgToDelete.file_path
        ? `File Path: ${epgToDelete.file_path}`
        : ''
}

This will remove all related program information and channel associations.
This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this EPG source? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey="delete-epg"
        onSuppressChange={suppressWarning}
        size="lg"
      />
    </Box>
  );
};

export default EPGsTable;
