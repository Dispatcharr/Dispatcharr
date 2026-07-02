import { useEffect, useMemo, useState } from 'react';
import useEPGsStore from '../../store/epgs';
import EPGForm from '../forms/EPG';
import DummyEPGForm from '../forms/DummyEPG';
import {
  ActionIcon,
  Box,
  Button,
  Flex,
  Menu,
  MenuDropdown,
  MenuItem,
  MenuTarget,
  Paper,
  Progress,
  Stack,
  Switch,
  Text,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import {
  ChevronDown,
  RefreshCcw,
  SquareMinus,
  SquarePen,
  SquarePlus,
} from 'lucide-react';
import { format, useDateTimeFormat } from '../../utils/dateTimeUtils.js';
import useLocalStorage from '../../hooks/useLocalStorage';
import ConfirmationDialog from '../../components/ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import { CustomTable, useTable } from './CustomTable';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  deleteEpg,
  formatStatusText,
  getProgressInfo,
  getProgressLabel,
  getSortedEpgs,
  refreshEpg,
  updateEpg,
} from '../../utils/tables/EPGsTableUtils.js';
import {
  makeHeaderCellRenderer,
  makeSortingChangeHandler,
} from './M3uTableUtils.jsx';

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

const EPGStatusCell = ({ epg }) => {
  // Direct Zustand subscription scoped to this source only.
  // This component re-renders whenever its source's progress changes,
  // independent of the parent table's render cycle.
  const progress = useEPGsStore((s) => s.refreshProgress[epg.id]);
  const theme = useMantineTheme();

  const isDummyEPG = epg.source_type === 'dummy';
  if (isDummyEPG) return null;

  // Show progress bar if an active fetch is in progress
  if (
    progress &&
    (progress.progress < 100 ||
      progress.status === 'in_progress' ||
      (progress.action === 'parsing_channels' && epg.status === 'parsing'))
  ) {
    const label = getProgressLabel(progress.action);
    if (!label) return null;

    const additionalInfo = getProgressInfo(progress);

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
          <Text size="xs" c="dimmed">
            Speed: {parseInt(progress.speed)} KB/s
          </Text>
        )}
        {additionalInfo && (
          <Text size="xs" c="dimmed" lineClamp={1}>
            {additionalInfo}
          </Text>
        )}
      </Stack>
    );
  }

  // Show error message
  if (epg.status === 'error' && epg.last_message) {
    return (
      <Tooltip label={epg.last_message} multiline width={300}>
        <Text
          c="dimmed"
          size="xs"
          lineClamp={2}
          style={{ color: theme.colors.red[6], lineHeight: 1.3 }}
        >
          {epg.last_message}
        </Text>
      </Tooltip>
    );
  }

  // Show success message
  if (epg.status === 'success') {
    const successMessage =
      epg.last_message || 'EPG data refreshed successfully';
    return (
      <Tooltip label={successMessage} multiline width={300}>
        <Text
          c="dimmed"
          size="xs"
          lineClamp={2}
          style={{ color: theme.colors.green[6], lineHeight: 1.3 }}
        >
          {successMessage}
        </Text>
      </Tooltip>
    );
  }

  // Show idle message
  if (epg.status === 'idle' && epg.last_message) {
    return (
      <Tooltip label={epg.last_message} multiline width={300}>
        <Text c="dimmed" size="xs" lineClamp={2} style={{ lineHeight: 1.3 }}>
          {epg.last_message}
        </Text>
      </Tooltip>
    );
  }

  return null;
};

const EPGsTable = () => {
  const [epg, setEPG] = useState(null);
  const [epgModalOpen, setEPGModalOpen] = useState(false);
  const [dummyEpgModalOpen, setDummyEpgModalOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [epgToDelete, setEpgToDelete] = useState(null);
  const [data, setData] = useState([]);
  const [deleting, setDeleting] = useState(false);
  const [confirmSDRefreshOpen, setConfirmSDRefreshOpen] = useState(false);
  const [sdRefreshTarget, setSDRefreshTarget] = useState(null);

  const epgs = useEPGsStore((s) => s.epgs);

  const theme = useMantineTheme();
  const { fullDateTimeFormat } = useDateTimeFormat();
  const [tableSize] = useLocalStorage('table-size', 'default');
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
      await updateEpg(
        {
          is_active: !epg.is_active,
        },
        epg,
        true
      ); // Add a new parameter to indicate this is just a toggle
    } catch (error) {
      console.error('Error toggling active state:', error);
    }
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
        size: 130,
        cell: ({ cell }) => {
          const typeMap = {
            xmltv: 'XMLTV',
            schedules_direct: 'Schedules Direct',
            dummy: 'Custom Dummy',
          };
          return typeMap[cell.getValue()] || cell.getValue();
        },
      },
      {
        header: 'Source / Credentials / File Path',
        accessorKey: 'url',
        enableSorting: false,
        minSize: 250,
        cell: ({ cell, row }) => {
          const sourceType = row.original.source_type;
          let value = '';
          let tooltip = '';

          if (sourceType === 'schedules_direct') {
            // Never expose credentials — show username only
            const username = row.original.username || '';
            value = username ? `User: ${username}` : '(credentials set)';
            tooltip = value;
          } else {
            value =
              cell.getValue() ||
              row.original.password ||
              row.original.file_path ||
              '';
            tooltip = value;
          }

          return (
            <Tooltip label={tooltip} disabled={!tooltip}>
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
        cell: ({ row }) => <EPGStatusCell epg={row.original} />,
      },
      {
        header: 'Updated',
        accessorKey: 'updated_at',
        size: 175,
        enableSorting: false,
        cell: ({ cell }) => {
          const value = cell.getValue();
          if (!value) {
            return <Text size="xs">Never</Text>;
          }
          const formatted = format(value, fullDateTimeFormat);
          return <Text size="xs">{formatted}</Text>;
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
    [fullDateTimeFormat]
  );

  const [sorting, setSorting] = useState([]);

  const editEPG = async (epg = null) => {
    const freshEpg = epg?.id ? epgs[epg.id] || epg : epg;
    setEPG(freshEpg);
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
    setDeleting(true);
    try {
      await deleteEpg(id);
    } finally {
      setDeleting(false);
      setConfirmDeleteOpen(false);
    }
  };

  const refreshEPG = async (id, force = false) => {
    await refreshEpg(id, force);
    showNotification({
      title: 'EPG refresh initiated',
    });
  };

  const handleRefreshEPG = (id) => {
    const epgObj = epgs[id];
    if (
      epgObj?.source_type === 'schedules_direct' &&
      epgObj?.updated_at &&
      Date.now() - new Date(epgObj.updated_at).getTime() < 2 * 60 * 60 * 1000
    ) {
      setSDRefreshTarget(id);
      setConfirmSDRefreshOpen(true);
      return;
    }
    refreshEPG(id);
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
            refreshEPG={handleRefreshEPG}
          />
        );
    }
  };

  const onSortingChange = makeSortingChangeHandler(sorting, setSorting, (col, desc) =>
    setData(getSortedEpgs(epgs, col, desc))
  );

  const renderHeaderCell = makeHeaderCellRenderer(sorting, onSortingChange);

  const table = useTable({
    columns,
    data,
    allRowIds: data.map((epg) => epg.id),
    enablePagination: false,
    enableRowSelection: false,
    renderTopToolbar: false,
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
          <MenuTarget>
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
          </MenuTarget>
          <MenuDropdown>
            <MenuItem onClick={createStandardEPG}>Standard EPG Source</MenuItem>
            <MenuItem onClick={createDummyEPG}>Dummy EPG Source</MenuItem>
          </MenuDropdown>
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
            justifyContent: 'flex-end',
            padding: 0,
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
        opened={confirmSDRefreshOpen}
        onClose={() => setConfirmSDRefreshOpen(false)}
        onConfirm={() => {
          setConfirmSDRefreshOpen(false);
          refreshEPG(sdRefreshTarget, true);
        }}
        title="Refresh Schedules Direct Early?"
        message={
          <div>
            <p>This source was refreshed less than 2 hours ago.</p>
            <p>
              Schedules Direct rate-limits requests per account. Refreshing too
              frequently may cause your account to be temporarily blocked.
            </p>
            <p>Are you sure you want to force a refresh now?</p>
          </div>
        }
        confirmLabel="Refresh Anyway"
        cancelLabel="Cancel"
      />

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => executeDeleteEPG(deleteTarget)}
        loading={deleting}
        title="Confirm EPG Source Deletion"
        message={
          epgToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following EPG source?

Name: ${epgToDelete.name}
Source Type: ${epgToDelete.source_type}
${
  epgToDelete.source_type === 'schedules_direct'
    ? epgToDelete.username
      ? `Username: ${epgToDelete.username}`
      : '(credentials set)'
    : epgToDelete.url
      ? `URL: ${epgToDelete.url}`
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
