import { useCallback, useEffect, useMemo, useState } from 'react';
import usePlaylistsStore from '../../store/playlists';
import M3UForm from '../forms/M3U';
import M3USetup from '../forms/M3USetup.jsx';
import ServerGroupsManagerModal from '../ServerGroupsManagerModal';
import {
  Paper,
  Button,
  Flex,
  Text,
  Box,
  ActionIcon,
  Tooltip,
  Switch,
  Menu,
  MenuDivider,
  MenuDropdown,
  MenuItem,
  MenuTarget,
  Badge,
  Group,
  ScrollArea,
  SimpleGrid,
  Stack,
} from '@mantine/core';
import {
  Trash2,
  SquarePen,
  RefreshCw,
  Film,
  RotateCcw,
  SquarePlus,
  Filter,
  Square,
  SquareCheck,
  ArrowRight,
} from 'lucide-react';
import useBrowserStorage from '../../hooks/useBrowserStorage';
import {
  useDateTimeFormat,
  format,
  diff,
  getNow,
} from '../../utils/dateTimeUtils.js';
import ConfirmationDialog from '../../components/ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import {
  deletePlaylist,
  getExpirationInfo,
  getExpirationTooltip,
  getPlaylistAutoCreatedChannelsCount,
  getStatusColor,
  formatStatusText,
  refreshLivePlaylist,
  refreshVODContent,
  updatePlaylist,
} from '../../utils/tables/M3UsTableUtils.js';
import tableClasses from './M3UsTable.module.css';
import { SensitiveValue } from '../SensitiveFields.jsx';
import SourceStatus from '../SourceStatus.jsx';
import { isTrialProfile } from '../../utils/forms/M3uProfilesUtils.js';
import { getM3UStreamLabel } from '../../utils/forms/M3uSetupUtils.js';

const ALL_ACCOUNT_TYPES = ['STD', 'XC'];

const formatRefreshDuration = (seconds) => {
  if (
    seconds == null ||
    !Number.isFinite(Number(seconds)) ||
    Number(seconds) < 0
  )
    return '—';
  const total = Math.max(0, Math.round(Number(seconds)));
  if (total >= 3600)
    return `${Math.floor(total / 3600)}h ${Math.floor((total % 3600) / 60)}m`;
  if (total >= 60) return `${Math.floor(total / 60)}m ${total % 60}s`;
  return `${Math.round(Number(seconds) * 10) / 10}s`;
};

const refreshKinds = (account) => {
  const kinds = [['live', getM3UStreamLabel(account.account_type)]];
  if (
    account.account_type === 'XC' &&
    (account.enable_vod !== false ||
      account.custom_properties?.refresh_timings?.vod_completed_at)
  ) {
    kinds.push(['vod', 'VOD']);
  }
  return kinds;
};

const AccountStatus = ({ account, progress }) => {
  const refreshError =
    account.is_active && progress?.status === 'error' ? progress.error : null;
  const status = refreshError ? 'error' : account.status;
  const autoSync = account.custom_properties?.live_auto_sync_result;
  const warning =
    autoSync?.status === 'error'
      ? `Auto-sync failed: ${autoSync.error || 'Unknown error'}`
      : autoSync?.channels_failed > 0
        ? `Auto-sync: ${autoSync.channels_failed} channel(s) failed`
        : account.last_message?.match(
            /Auto-sync error: .+|Auto-sync: .*\b\d+ failed\./
          )?.[0];
  return (
    <SourceStatus
      label={formatStatusText(status)}
      color={getStatusColor(status)}
      messages={[
        refreshError ||
          (['error', 'pending_setup'].includes(status)
            ? account.last_message
            : null),
        warning,
      ]}
      messageColor={status === 'error' ? 'red' : 'yellow'}
    />
  );
};

const RowActions = ({
  editPlaylist,
  handleDeletePlaylist,
  row,
  handleRefreshPlaylist,
  handleRefreshVOD,
}) => {
  return (
    <Paper
      className={tableClasses.controls}
      withBorder
      px={6}
      py={4}
      radius="md"
      role="group"
      aria-label={`Actions for ${row.original.name}`}
    >
      <Flex gap={4} align="center" wrap="nowrap">
        {row.original.setup_step ? (
          <Button
            size="compact-sm"
            leftSection={<ArrowRight size={16} />}
            aria-label={`Continue setup for ${row.original.name}`}
            onClick={() => editPlaylist(row.original)}
          >
            Continue setup
          </Button>
        ) : (
          <>
            <Tooltip
              label={`Refresh ${getM3UStreamLabel(row.original.account_type)}`}
            >
              <ActionIcon
                aria-label={`Refresh ${getM3UStreamLabel(row.original.account_type)} for ${row.original.name}`}
                variant="subtle"
                size="md"
                color="blue.5"
                onClick={() => handleRefreshPlaylist(row.original.id)}
                disabled={!row.original.is_active}
              >
                <RefreshCw size={17} />
              </ActionIcon>
            </Tooltip>
            {row.original.account_type === 'XC' && (
              <Tooltip label="Refresh VOD">
                <ActionIcon
                  aria-label={`Refresh VOD for ${row.original.name}`}
                  variant="subtle"
                  size="md"
                  color="blue.5"
                  onClick={() => handleRefreshVOD(row.original.id)}
                  disabled={!row.original.is_active || !row.original.enable_vod}
                >
                  <Film size={17} />
                </ActionIcon>
              </Tooltip>
            )}
            <Tooltip label="Edit account">
              <ActionIcon
                aria-label={`Edit ${row.original.name}`}
                variant="subtle"
                size="md"
                color="yellow"
                onClick={() => {
                  editPlaylist(row.original);
                }}
              >
                <SquarePen size={17} />
              </ActionIcon>
            </Tooltip>
          </>
        )}
        <Tooltip label="Delete account">
          <ActionIcon
            aria-label={`Delete ${row.original.name}`}
            variant="subtle"
            size="md"
            color="red"
            onClick={() => handleDeletePlaylist(row.original.id)}
          >
            <Trash2 size={17} />
          </ActionIcon>
        </Tooltip>
      </Flex>
    </Paper>
  );
};

const M3UTable = () => {
  const [playlist, setPlaylist] = useState(null);
  const [playlistModalOpen, setPlaylistModalOpen] = useState(false);
  const [playlistCreated, setPlaylistCreated] = useState(false);
  const [setupAccount, setSetupAccount] = useState(null);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [playlistToDelete, setPlaylistToDelete] = useState(null);
  // Auto-created channel preview shown in the delete confirmation so the
  // user sees what cascades along with the account.
  const [autoChannelsInfo, setAutoChannelsInfo] = useState({
    count: 0,
    sample_names: [],
  });
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

  const [typeFilter, setTypeFilter] = useBrowserStorage(
    'm3u-table-type-filter',
    ALL_ACCOUNT_TYPES,
    { storage: 'session' }
  );
  const { fullDateFormat, fullDateTimeFormat } = useDateTimeFormat();

  const editPlaylist = async (playlist = null) => {
    if (playlist?.setup_step) {
      setSetupAccount(playlist);
      return;
    }
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
      await refreshLivePlaylist(id);
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

  const handleRefreshVOD = async (id) => {
    setRefreshProgress(id, {
      action: 'vod_refresh',
      progress: 0,
      account: id,
      type: 'm3u_refresh',
    });

    try {
      await refreshVODContent(id);
    } catch {
      setRefreshProgress(id, {
        action: 'vod_refresh',
        progress: 0,
        account: id,
        type: 'm3u_refresh',
        error: 'Failed to start VOD refresh task',
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
    setDeleting(true);
    try {
      await deletePlaylist(id);
    } catch (error) {
      console.error('Error deleting playlist:', error);
    } finally {
      setDeleting(false);
      setConfirmDeleteOpen(false);
      setAutoChannelsInfo({ count: 0, sample_names: [] });
    }
  };

  const toggleActive = useCallback(async (playlist) => {
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
  }, []);

  const details = useMemo(
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        cell: ({ row }) => {
          const custom = row.original.custom_properties || {};
          const live = custom.live_catalog_counts;
          const vod = custom.vod_catalog_counts || {};
          const summaries =
            row.original.account_type === 'XC'
              ? [
                  ['Live TV', live],
                  ['Movies', vod.movies],
                  ['Series', vod.series],
                ]
              : [[getM3UStreamLabel(row.original.account_type), live]];
          return (
            <Box>
              <Tooltip label="Provider entries / imported entries from the last successful refresh">
                <Box style={{ cursor: 'help' }}>
                  {summaries.map(([label, counts]) => (
                    <Text key={label} size="xs" c="dimmed">
                      {label}:{' '}
                      {counts
                        ? `${counts.provider_total} / ${counts.selected_total}`
                        : '— / —'}
                    </Text>
                  ))}
                </Box>
              </Tooltip>
            </Box>
          );
        },
      },
      {
        header: 'URL / File',
        accessorKey: 'server_url',
        cell: ({ cell, row }) => {
          const value = cell.getValue() || row.original.file_path || '';
          return (
            <SensitiveValue
              withTooltip
              sensitive={!!row.original.server_url}
              size="sm"
              c="dimmed"
              mt={4}
              style={{
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: '100%',
              }}
            >
              {value}
            </SensitiveValue>
          );
        },
      },
      {
        header: 'Last refresh',
        accessorKey: 'last_message',
        cell: ({ row }) => {
          const data = row.original;
          const timings = data.custom_properties?.refresh_timings || {};
          return (
            <Stack gap={4}>
              {refreshKinds(data).map(([kind, label]) => {
                const latest = refreshProgress[data.id];
                const progress =
                  latest &&
                  (latest.action === 'vod_refresh' ? 'vod' : 'live') === kind
                    ? latest
                    : null;
                const running =
                  progress &&
                  !(
                    progress.progress === 100 &&
                    ['parsing', 'processing_groups', 'vod_refresh'].includes(
                      progress.action
                    )
                  ) &&
                  progress.status !== 'error';
                const completedAt =
                  timings[`${kind}_completed_at`] ||
                  (kind === 'live' ? data.updated_at : null);
                return (
                  <Text key={kind} size="xs" c={running ? 'blue' : 'dimmed'}>
                    {running ? (
                      `Refreshing ${label}…`
                    ) : (
                      <>
                        {label}:{' '}
                        {completedAt
                          ? format(completedAt, fullDateTimeFormat)
                          : 'Never'}
                        {timings[`${kind}_seconds`] != null &&
                          ` · ${formatRefreshDuration(timings[`${kind}_seconds`])}`}
                      </>
                    )}
                  </Text>
                );
              })}
            </Stack>
          );
        },
      },
      {
        header: 'Max Streams',
        id: 'max_streams',
        cell: ({ row }) => {
          const profiles = row.original.profiles || [];
          const activeProfiles = profiles.filter((p) => p.is_active);

          if (activeProfiles.length <= 1) {
            const val =
              activeProfiles[0]?.max_streams ?? row.original.max_streams;
            return (
              <Badge variant="light" color="gray" radius="xl">
                {val === 0 ? '∞' : val}
              </Badge>
            );
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
              <Badge variant="light" color="gray" radius="xl">
                {hasUnlimited ? '∞' : total}
              </Badge>
            </Tooltip>
          );
        },
      },
      {
        header: 'Expiration',
        accessorKey: 'earliest_expiration',
        cell: ({ cell, row }) => {
          const data = row.original;

          const earliest = cell.getValue();
          if (!earliest)
            return (
              <Badge variant="light" color="gray" radius="xl">
                —
              </Badge>
            );

          const now = getNow();
          const daysLeft = diff(earliest, now, 'day');
          const { color, label } = getExpirationInfo(
            daysLeft,
            earliest,
            fullDateFormat
          );

          const allExpirations = data.all_expirations || [];
          const tooltipContent = getExpirationTooltip(
            allExpirations,
            fullDateTimeFormat,
            label
          );

          return (
            <Tooltip
              label={tooltipContent}
              multiline
              width={300}
              style={{ whiteSpace: 'pre-line' }}
            >
              <Badge variant="light" color={color || 'gray'} radius="xl">
                {label}
              </Badge>
            </Tooltip>
          );
        },
      },
      {
        header: 'Enabled',
        accessorKey: 'is_active',
        cell: ({ cell, row }) => {
          return (
            <Tooltip
              label="Enable or disable this M3U account"
              withArrow
              events={{ hover: true, focus: true, touch: true }}
            >
              <Paper
                className={tableClasses.controls}
                withBorder
                px={6}
                py={4}
                radius="md"
                role="group"
                aria-label={`Enabled state for ${row.original.name}`}
              >
                <Switch
                  size="sm"
                  aria-label={`Enable ${row.original.name}`}
                  checked={cell.getValue()}
                  onChange={() => toggleActive(row.original)}
                />
              </Paper>
            </Tooltip>
          );
        },
      },
    ],
    [toggleActive, fullDateFormat, fullDateTimeFormat, refreshProgress]
  );

  const closeModal = (newPlaylist = null) => {
    if (newPlaylist) {
      setPlaylistModalOpen(false);
      setPlaylist(null);
      setPlaylistCreated(false);
      setSetupAccount(newPlaylist);
    } else {
      setPlaylistModalOpen(false);
      setPlaylist(null);
      setPlaylistCreated(false);
    }
  };

  // Listen for edit playlist requests from notifications
  useEffect(() => {
    if (editPlaylistId) {
      const playlistToEdit = playlists.find((p) => p.id === editPlaylistId);
      if (playlistToEdit) {
        editPlaylist(playlistToEdit);
        // Reset the ID after handling
        setEditPlaylistId(null);
      }
    }
  }, [editPlaylistId, processedData, playlists, setEditPlaylistId]);

  const filteredData = useMemo(
    () =>
      processedData.filter((account) =>
        typeFilter.includes(account.account_type === 'XC' ? 'XC' : 'STD')
      ),
    [processedData, typeFilter]
  );

  const isTypeFiltered = typeFilter.length !== ALL_ACCOUNT_TYPES.length;

  const toggleTypeFilter = (value) => {
    setTypeFilter(
      typeFilter.includes(value)
        ? typeFilter.filter((v) => v !== value)
        : [...typeFilter, value]
    );
  };

  const renderDetail = (account, id) => {
    const detail = details.find(
      (column) => (column.id || column.accessorKey) === id
    );
    return detail.cell({
      cell: { getValue: () => account[detail.accessorKey] },
      row: { original: account },
    });
  };

  return (
    <Box
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        height: '100%',
      }}
    >
      <Flex
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 10,
          flexShrink: 0,
        }}
        gap={15}
        wrap="wrap"
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
        <Flex gap={6} align="center">
          <Menu shadow="md" width={200} closeOnItemClick={false}>
            <MenuTarget>
              <Button
                aria-label="Filter account types"
                size="xs"
                variant={isTypeFiltered ? 'filled' : 'default'}
                color={isTypeFiltered ? 'blue' : undefined}
              >
                <Filter size={18} />
              </Button>
            </MenuTarget>

            <MenuDropdown>
              <MenuItem
                onClick={() => toggleTypeFilter('STD')}
                leftSection={
                  typeFilter.includes('STD') ? (
                    <SquareCheck size={18} />
                  ) : (
                    <Square size={18} />
                  )
                }
              >
                <Text size="xs">M3U</Text>
              </MenuItem>
              <MenuItem
                onClick={() => toggleTypeFilter('XC')}
                leftSection={
                  typeFilter.includes('XC') ? (
                    <SquareCheck size={18} />
                  ) : (
                    <Square size={18} />
                  )
                }
              >
                <Text size="xs">XC</Text>
              </MenuItem>
              <MenuDivider />
              <MenuItem
                onClick={() => setTypeFilter(ALL_ACCOUNT_TYPES)}
                leftSection={<RotateCcw size={18} />}
                disabled={!isTypeFiltered}
              >
                <Text size="xs">Reset</Text>
              </MenuItem>
            </MenuDropdown>
          </Menu>
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

      <ScrollArea style={{ flex: 1, minHeight: 0 }} type="auto">
        {filteredData.length === 0 ? (
          <Text size="xl" c="dimmed" ta="center" py="xl">
            {processedData.length === 0
              ? 'No M3U accounts yet.'
              : 'No M3U accounts match this filter.'}
          </Text>
        ) : (
          <Stack gap="md">
            {filteredData.map((account) => (
              <Paper
                key={account.id}
                component="article"
                aria-label={`M3U account ${account.name}`}
                className={tableClasses.card}
                withBorder
                p="md"
                radius="md"
                style={
                  account.is_active
                    ? undefined
                    : { opacity: 0.65, filter: 'grayscale(0.75)' }
                }
              >
                <Stack gap="sm">
                  <Group justify="space-between" align="flex-start">
                    <Box style={{ minWidth: 0, flex: '1 1 200px' }}>
                      <Group gap="xs">
                        <Tooltip
                          label={account.name}
                          multiline
                          className={tableClasses.detailTooltip}
                        >
                          <Text
                            fw={700}
                            size="lg"
                            truncate
                            className={tableClasses.name}
                          >
                            {account.name}
                          </Text>
                        </Tooltip>
                        <Badge variant="light">
                          {account.account_type === 'XC' ? 'XC' : 'M3U'}
                        </Badge>
                        {account.account_type === 'XC' &&
                          isTrialProfile(
                            account.profiles?.find(
                              (profile) => profile.is_default
                            )
                          ) && (
                            <Badge variant="light" color="orange">
                              Trial
                            </Badge>
                          )}
                        <AccountStatus
                          account={account}
                          progress={refreshProgress[account.id]}
                        />
                      </Group>
                      {renderDetail(account, 'server_url')}
                    </Box>
                    <Group gap="xs" align="stretch" wrap="nowrap">
                      {renderDetail(account, 'is_active')}
                      <RowActions
                        editPlaylist={editPlaylist}
                        handleDeletePlaylist={handleDeletePlaylist}
                        row={{ original: account }}
                        handleRefreshPlaylist={handleRefreshPlaylist}
                        handleRefreshVOD={handleRefreshVOD}
                      />
                    </Group>
                  </Group>
                  <SimpleGrid cols={{ base: 1, xs: 2, lg: 4 }} spacing="md">
                    <Box>
                      <Text size="xs" fw={600} mb={4}>
                        Provider / imported entries
                      </Text>
                      {renderDetail(account, 'name')}
                    </Box>
                    {['last_message', 'max_streams', 'earliest_expiration'].map(
                      (id) => (
                        <Box
                          key={id}
                          style={{
                            minWidth: 0,
                            textAlign:
                              id === 'last_message' ? undefined : 'center',
                          }}
                        >
                          <Text size="xs" fw={600} mb={4}>
                            {
                              details.find(
                                (column) =>
                                  (column.id || column.accessorKey) === id
                              ).header
                            }
                          </Text>
                          {renderDetail(account, id)}
                        </Box>
                      )
                    )}
                  </SimpleGrid>
                </Stack>
              </Paper>
            ))}
          </Stack>
        )}
      </ScrollArea>

      <M3UForm
        m3uAccount={playlist}
        isOpen={playlistModalOpen}
        onClose={closeModal}
        onSaved={(account) => closeModal(account.setup_step ? account : null)}
        playlistCreated={playlistCreated}
      />
      {setupAccount && (
        <M3USetup
          key={setupAccount.id}
          account={setupAccount}
          onClose={() => setSetupAccount(null)}
        />
      )}

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
                    borderRadius: 'var(--mantine-radius-default)',
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
                    borderRadius: 'var(--mantine-radius-default)',
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
