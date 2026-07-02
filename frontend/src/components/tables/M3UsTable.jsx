import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useCallback,
} from 'react';
import usePlaylistsStore from '../../store/playlists';
import M3UForm from '../forms/M3U';
import ServerGroupsManagerModal from '../ServerGroupsManagerModal';
import { TableHelper } from '../../helpers';
import {
  useMantineTheme,
  Paper,
  Button,
  Flex,
  Text,
  Box,
  ActionIcon,
  Tooltip,
  Switch,
} from '@mantine/core';
import {
  SquareMinus,
  SquarePen,
  RefreshCcw,
  SquarePlus,
} from 'lucide-react';
import useLocalStorage from '../../hooks/useLocalStorage';
import {
  useDateTimeFormat,
  format,
  diff,
  getNow,
} from '../../utils/dateTimeUtils.js';
import ConfirmationDialog from '../../components/ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import { CustomTable, useTable } from './CustomTable';
import {
  deletePlaylist,
  getExpirationInfo,
  getExpirationTooltip,
  getPlaylistAutoCreatedChannelsCount,
  getSortedPlaylists,
  getStatusColor,
  getStatusContent,
  formatStatusText,
  refreshPlaylist,
  updatePlaylist,
} from '../../utils/tables/M3UsTableUtils.js';
import {
  makeHeaderCellRenderer,
  makeSortingChangeHandler,
} from './M3uTableUtils.jsx';

const StatusRow = ({ label, value }) => (
  <Flex justify="space-between" align="center">
    <Text size="xs" fw={500}>{label}{value ? ':' : ''}</Text>
    {value && <Text size="xs">{value}</Text>}
  </Flex>
);

const StatusBox = ({ children }) => (
  <Box>
    <Flex direction="column" gap={2}>{children}</Flex>
  </Box>
);

const RowActions = ({
  tableSize,
  editPlaylist,
  handleDeletePlaylist,
  row,
  handleRefreshPlaylist,
}) => {
  const iconSize =
    tableSize == 'default' ? 'sm' : tableSize == 'compact' ? 'xs' : 'md';

  return (
    <>
      <ActionIcon
        variant="transparent"
        size={iconSize}
        color="yellow.5"
        onClick={() => {
          editPlaylist(row.original);
        }}
      >
        <SquarePen size={tableSize === 'compact' ? 16 : 18} />
      </ActionIcon>
      <ActionIcon
        variant="transparent"
        size={iconSize}
        color="red.9"
        onClick={() => handleDeletePlaylist(row.original.id)}
      >
        <SquareMinus size={tableSize === 'compact' ? 16 : 18} />
      </ActionIcon>
      <ActionIcon
        variant="transparent"
        size={iconSize}
        color="blue.5"
        onClick={() => handleRefreshPlaylist(row.original.id)}
        disabled={!row.original.is_active}
      >
        <RefreshCcw size={tableSize === 'compact' ? 16 : 18} />
      </ActionIcon>
    </>
  );
};


const M3UTable = () => {
  const [playlist, setPlaylist] = useState(null);
  const [playlistModalOpen, setPlaylistModalOpen] = useState(false);
  const [playlistCreated, setPlaylistCreated] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [playlistToDelete, setPlaylistToDelete] = useState(null);
  // Auto-created channel preview shown in the delete confirmation so the
  // user sees what cascades along with the account.
  const [autoChannelsInfo, setAutoChannelsInfo] = useState({
    count: 0,
    sample_names: [],
  });
  const [data, setData] = useState([]);
  const [sorting, setSorting] = useState([{ id: 'name', desc: '' }]);
  const [deleting, setDeleting] = useState(false);
  const [serverGroupsManagerOpen, setServerGroupsManagerOpen] = useState(false);

  const playlists = usePlaylistsStore((s) => s.playlists);
  const refreshProgress = usePlaylistsStore((s) => s.refreshProgress);
  const setRefreshProgress = usePlaylistsStore((s) => s.setRefreshProgress);
  const editPlaylistId = usePlaylistsStore((s) => s.editPlaylistId);
  const setEditPlaylistId = usePlaylistsStore((s) => s.setEditPlaylistId);

  // Memoize data to prevent unnecessary re-renders during progress updates
  const processedData = useMemo(() => {
    return playlists
      .filter((playlist) => playlist.locked === false)
      .sort((a, b) => {
        // First sort by active status (active items first)
        if (a.is_active !== b.is_active) {
          return a.is_active ? -1 : 1;
        }
        // Then sort by name (case-insensitive)
        return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
      });
  }, [playlists]);

  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  const theme = useMantineTheme();
  const [tableSize] = useLocalStorage('table-size', 'default');
  const { fullDateFormat, fullDateTimeFormat } = useDateTimeFormat();

  const generateStatusString = (data) => {
    if (data.progress == 100) {
      return 'Idle';
    }

    const content = getStatusContent(data);

    switch (content.type) {
      case 'initializing':
        return (
          <StatusBox><StatusRow label="Initializing refresh..." /></StatusBox>
        );
      case 'downloading':
        return (
          <StatusBox>
            <StatusRow label="Downloading" value={`${content.progress}%`} />
            <StatusRow label="Speed" value={content.speed} />
            <StatusRow label="Time left" value={content.timeRemaining} />
          </StatusBox>
        );
      case 'groups':
        return (
          <StatusBox>
            <StatusRow label="Processing groups" value={`${content.progress}%`} />
            {content.elapsedTime && <StatusRow label="Elapsed" value={content.elapsedTime} />}
            {content.groupsProcessed && <StatusRow label="Groups" value={content.groupsProcessed} />}
          </StatusBox>
        );
      case 'parsing':
        return (
          <StatusBox>
            <StatusRow label="Parsing" value={`${content.progress}%`} />
            {content.elapsedTime && <StatusRow label="Elapsed" value={content.elapsedTime} />}
            {content.timeRemaining && <StatusRow label="Remaining" value={content.timeRemaining} />}
            {content.streamsProcessed && <StatusRow label="Streams" value={content.streamsProcessed} />}
          </StatusBox>
        );
      case 'error':
        return (
          <StatusBox>
            <Text size="xs" fw={500} color="red">Error:</Text>
            <Text size="xs" color="red" style={{ lineHeight: 1.3 }}>
              {content.error || 'Unknown error occurred'}
            </Text>
          </StatusBox>
        );
      default:
        return content.label;
    }
  };

  const editPlaylist = async (playlist = null) => {
    setPlaylist(playlist);
    setPlaylistModalOpen(true);
  };

  const handleRefreshPlaylist = async (id) => {
    // Provide immediate visual feedback before the API call
    setRefreshProgress(id, {
      action: 'initializing',
      progress: 0,
      account: id,
      type: 'm3u_refresh',
    });

    try {
      await refreshPlaylist(id);
      // No need to set again since WebSocket will update us once the task starts
    } catch {
      // If the API call fails, show an error state
      setRefreshProgress(id, {
        action: 'error',
        progress: 0,
        account: id,
        type: 'm3u_refresh',
        error: 'Failed to start refresh task',
        status: 'error',
      });
    }
  };

  const handleDeletePlaylist = async (id) => {
    // Get playlist details for the confirmation dialog
    const playlist = playlists.find((p) => p.id === id);
    setPlaylistToDelete(playlist);
    setDeleteTarget(id);

    // Fetch how many auto-created channels this playlist owns. Populates the
    // confirmation message so the user can decide whether to also delete
    // them. On failure, surface "unknown" so the user is not misled into
    // thinking there are zero auto-created channels.
    let info;
    try {
      const result = await getPlaylistAutoCreatedChannelsCount(id);
      info = result || { count: 0, sample_names: [] };
    } catch {
      info = {
        count: null,
        sample_names: [],
        countUnavailable: true,
      };
    }
    setAutoChannelsInfo(info);

    // Skip the warning when it has been suppressed AND the account has
    // no auto-created channels. When the account did create channels (or
    // the count could not be resolved), the dialog still opens so the
    // user sees and confirms what cascades.
    if (
      isWarningSuppressed('delete-m3u') &&
      info.count === 0 &&
      !info.countUnavailable
    ) {
      return executeDeletePlaylist(id);
    }

    setConfirmDeleteOpen(true);
  };

  const executeDeletePlaylist = async (id) => {
    setIsLoading(true);
    setDeleting(true);
    try {
      await deletePlaylist(id);
    } catch (error) {
      console.error('Error deleting playlist:', error);
    } finally {
      setDeleting(false);
      setIsLoading(false);
      setConfirmDeleteOpen(false);
      setAutoChannelsInfo({ count: 0, sample_names: [] });
    }
  };

  const toggleActive = async (playlist) => {
    try {
      // Send only the is_active field to trigger our special handling
      await updatePlaylist(
        {
          is_active: !playlist.is_active,
        },
        playlist,
        true
      ); // Add a new parameter to indicate this is just a toggle
    } catch (error) {
      console.error('Error toggling active state:', error);
    }
  };

  const columns = useMemo(
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        size: 200,
        sortable: true,
      },
      {
        header: 'Type',
        accessorKey: 'account_type',
        sortable: true,
        size: 100,
        cell: ({ cell }) => {
          const value = cell.getValue();
          return value === 'XC' ? 'XC' : 'M3U';
        },
      },
      {
        header: 'URL / File',
        accessorKey: 'server_url',
        size: 250,
        cell: ({ cell, row }) => {
          const value = cell.getValue() || row.original.file_path || '';
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
        cell: ({ cell }) => {
          const value = cell.getValue();
          if (!value) return null;

          // Match EPG table styling with Text component - always use xs size
          return (
            <Text size="xs" c={getStatusColor(value)}>
              {formatStatusText(value)}
            </Text>
          );
        },
      },
      {
        header: 'Status Message',
        accessorKey: 'last_message',
        grow: true,
        minSize: 250,
        cell: ({ cell, row }) => {
          const value = cell.getValue();
          const data = row.original;

          // Get account id to check for refresh progress
          const accountId = data.id;
          const progressData = refreshProgress[accountId];

          // If we have active progress data for this account, show that instead
          if (progressData && progressData.progress < 100) {
            return (
              <Box
                style={{
                  // Use full height of the cell with proper spacing
                  height: '100%',
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'flex-start',
                  // Add some padding to give content room to breathe
                  padding: '4px 0',
                }}
              >
                {generateStatusString(progressData)}
              </Box>
            );
          }

          // No progress data, display normal status message
          if (!value) return null;

          // Show error message with red styling for errors
          if (data.status === 'error') {
            return (
              <Tooltip label={value} multiline width={300}>
                <Text
                  c="dimmed"
                  size="xs"
                  lineClamp={2}
                  style={{ color: theme.colors.red[6], lineHeight: 1.3 }}
                >
                  {value}
                </Text>
              </Tooltip>
            );
          }

          // Show success message with green styling for success
          if (data.status === 'success') {
            return (
              <Tooltip label={value} multiline width={300}>
                <Text
                  c="dimmed"
                  size="xs"
                  style={{
                    color: theme.colors.green[6],
                    lineHeight: 1.3,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {value}
                </Text>
              </Tooltip>
            );
          }

          // For all other status values, just use dimmed text
          return (
            <Tooltip label={value} multiline width={300}>
              <Text
                c="dimmed"
                size="xs"
                lineClamp={2}
                style={{ lineHeight: 1.1 }}
              >
                {value}
              </Text>
            </Tooltip>
          );
        },
      },
      {
        header: 'Max Streams',
        id: 'max_streams',
        accessorFn: (row) => {
          const activeProfiles = (row.profiles || []).filter(
            (p) => p.is_active
          );
          if (activeProfiles.length === 0) return row.max_streams;
          if (activeProfiles.some((p) => p.max_streams === 0)) return Infinity;
          return activeProfiles.reduce((sum, p) => sum + p.max_streams, 0);
        },
        sortable: true,
        size: 125,
        cell: ({ row }) => {
          const profiles = row.original.profiles || [];
          const activeProfiles = profiles.filter((p) => p.is_active);

          if (activeProfiles.length <= 1) {
            const val = row.original.max_streams;
            return <Text size="xs">{val === 0 ? '∞' : val}</Text>;
          }

          const hasUnlimited = activeProfiles.some((p) => p.max_streams === 0);
          const total = hasUnlimited
            ? null
            : activeProfiles.reduce((sum, p) => sum + p.max_streams, 0);

          const tooltipLines = activeProfiles
            .map(
              (p) =>
                `${p.name}: ${p.max_streams === 0 ? 'Unlimited' : p.max_streams}`
            )
            .join('\n');

          return (
            <Tooltip
              label={tooltipLines}
              multiline
              width={220}
              style={{ whiteSpace: 'pre-line' }}
            >
              <Text
                size="xs"
                style={{
                  cursor: 'default',
                  textDecoration: 'underline dotted',
                }}
              >
                {hasUnlimited ? '∞' : total}
              </Text>
            </Tooltip>
          );
        },
      },
      {
        header: 'Expiration',
        accessorKey: 'earliest_expiration',
        sortable: true,
        size: 110,
        cell: ({ cell, row }) => {
          const data = row.original;

          const earliest = cell.getValue();
          if (!earliest) {
            return null;
          }

          const now = getNow();
          const daysLeft = diff(earliest, now, 'day');
          const { color, label } = getExpirationInfo(daysLeft, earliest, fullDateFormat);

          const allExpirations = data.all_expirations || [];
          const tooltipContent = getExpirationTooltip(allExpirations, fullDateTimeFormat, label);

          return (
            <Tooltip
              label={tooltipContent}
              multiline
              width={300}
              style={{ whiteSpace: 'pre-line' }}
            >
              <Text size="xs" c={color} fw={daysLeft <= 7 ? 600 : 400}>
                {label}
              </Text>
            </Tooltip>
          );
        },
      },
      {
        header: 'Updated',
        accessorKey: 'updated_at',
        size: 175,
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
        cell: ({ cell, row }) => {
          return (
            <Box sx={{ display: 'flex', justifyContent: 'center' }}>
              <Switch
                size="xs"
                checked={cell.getValue()}
                onChange={() => toggleActive(row.original)}
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
    [
      handleRefreshPlaylist,
      editPlaylist,
      handleDeletePlaylist,
      toggleActive,
      fullDateFormat,
      fullDateTimeFormat,
    ]
  );

  //optionally access the underlying virtualizer instance
  const rowVirtualizerInstanceRef = useRef(null);

  const [_isLoading, setIsLoading] = useState(true);

  const closeModal = (newPlaylist = null) => {
    if (newPlaylist) {
      setPlaylistCreated(true);
      setPlaylist(newPlaylist);
    } else {
      setPlaylistModalOpen(false);
      setPlaylist(null);
      setPlaylistCreated(false);
    }
  };

  useEffect(() => {
    //scroll to the top of the table when the sorting changes
    try {
      rowVirtualizerInstanceRef.current?.scrollToIndex?.(0);
    } catch (error) {
      console.error(error);
    }
  }, [sorting]);

  // Listen for edit playlist requests from notifications
  useEffect(() => {
    setData(processedData);

    if (editPlaylistId) {
      const playlistToEdit = playlists.find((p) => p.id === editPlaylistId);
      if (playlistToEdit) {
        editPlaylist(playlistToEdit);
        // Reset the ID after handling
        setEditPlaylistId(null);
      }
    }
  }, [editPlaylistId, processedData, playlists, setEditPlaylistId]);

  const onSortingChange = makeSortingChangeHandler(sorting, setSorting, (col, desc) =>
    setData(getSortedPlaylists(playlists, col, desc))
  );

  const renderHeaderCell = makeHeaderCellRenderer(sorting, onSortingChange);

  const renderBodyCell = useCallback(({ cell, row }) => {
    switch (cell.column.id) {
      case 'actions':
        return (
          <RowActions
            tableSize={tableSize}
            editPlaylist={editPlaylist}
            handleDeletePlaylist={handleDeletePlaylist}
            row={row}
            handleRefreshPlaylist={handleRefreshPlaylist}
          />
        );
    }
  }, []);

  const table = useTable({
    columns,
    // Sort data before passing to table: active first, then by name
    data,
    allRowIds: data.map((playlist) => playlist.id),
    enablePagination: false,
    enableRowVirtualization: true,
    enableRowSelection: false,
    renderTopToolbar: false,
    sorting,
    manualSorting: true,
    rowVirtualizerInstanceRef, //optional
    rowVirtualizerOptions: { overscan: 5 }, //optionally customize the row virtualizer
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    headerCellRenderFns: {
      name: renderHeaderCell,
      account_type: renderHeaderCell,
      server_url: renderHeaderCell,
      max_streams: renderHeaderCell,
      status: renderHeaderCell,
      last_message: renderHeaderCell,
      updated_at: renderHeaderCell,
      earliest_expiration: renderHeaderCell,
      is_active: renderHeaderCell,
      actions: renderHeaderCell,
    },
    mantineTableContainerProps: {
      style: {
        height: 'calc(40vh - 10px)',
        overflowX: 'auto', // Ensure horizontal scrolling works
      },
    },
    mantineTableProps: {
      ...TableHelper.defaultProperties.mantineTableProps,
      className: `table-size-${tableSize}`,
    },
    // Add custom cell styles to match CustomTable's sizing
    tableCellProps: ({ cell }) => {
      return {
        fontSize:
          tableSize === 'compact'
            ? 'var(--mantine-font-size-xs)'
            : 'var(--mantine-font-size-sm)',
        padding: tableSize === 'compact' ? '2px 8px' : '4px 10px',
      };
    },
    // Additional text styling to match ChannelsTable
    tableBodyProps: () => ({
      fontSize:
        tableSize === 'compact'
          ? 'var(--mantine-font-size-xs)'
          : 'var(--mantine-font-size-sm)',
    }),
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
          M3U Accounts
        </Text>
        <Flex gap={6}>
          <Button
            variant="light"
            size="xs"
            onClick={() => setServerGroupsManagerOpen(true)}
            p={5}
          >
            Server Groups
          </Button>
          <Button
            leftSection={<SquarePlus size={14} />}
            variant="light"
            size="xs"
            onClick={() => editPlaylist()}
            p={5}
            color="green"
            style={{
              borderWidth: '1px',
              borderColor: 'green',
              color: 'white',
            }}
          >
            Add M3U
          </Button>
        </Flex>
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

      <M3UForm
        m3uAccount={playlist}
        isOpen={playlistModalOpen}
        onClose={closeModal}
        playlistCreated={playlistCreated}
      />

      <ServerGroupsManagerModal
        isOpen={serverGroupsManagerOpen}
        onClose={() => setServerGroupsManagerOpen(false)}
      />

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => executeDeletePlaylist(deleteTarget)}
        loading={deleting}
        title="Confirm M3U Account Deletion"
        message={
          playlistToDelete ? (
            <div>
              <div style={{ whiteSpace: 'pre-line', marginBottom: 12 }}>
                {`Delete the following M3U account?

Name: ${playlistToDelete.name}
Type: ${playlistToDelete.account_type === 'XC' ? 'Xtream Codes' : 'Standard'}
Server: ${playlistToDelete.server_url || 'Local file'}

Streams owned by this provider will be removed. Manual channels that include those streams will lose them, but the channels and any other streams on them survive.

This action cannot be undone.`}
              </div>
              {autoChannelsInfo.countUnavailable ? (
                <div
                  style={{
                    background: 'rgba(234,179,8,0.08)',
                    border: '1px solid rgba(234,179,8,0.3)',
                    borderRadius: 4,
                    padding: 10,
                    marginTop: 6,
                  }}
                >
                  <Text size="sm" fw={600}>
                    Auto-synced channel count is unavailable; any channels
                    auto-created by this provider will be deleted with the
                    account.
                  </Text>
                </div>
              ) : autoChannelsInfo.count > 0 ? (
                <div
                  style={{
                    background: 'rgba(234,179,8,0.08)',
                    border: '1px solid rgba(234,179,8,0.3)',
                    borderRadius: 4,
                    padding: 10,
                    marginTop: 6,
                  }}
                >
                  <Text size="sm" fw={600}>
                    {`${autoChannelsInfo.count} auto-synced ${autoChannelsInfo.count === 1 ? 'channel' : 'channels'} created by this provider will also be deleted.`}
                  </Text>
                </div>
              ) : null}
            </div>
          ) : (
            'Are you sure you want to delete this M3U account? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey="delete-m3u"
        onSuppressChange={suppressWarning}
        size="lg"
      />
    </Box>
  );
};

export default M3UTable;
