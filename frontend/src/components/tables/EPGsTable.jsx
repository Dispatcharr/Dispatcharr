import { useCallback, useEffect, useMemo, useState } from 'react';
import useEPGsStore from '../../store/epgs';
import EPGForm from '../forms/EPG';
import DummyEPGForm from '../forms/DummyEPG';
import {
  ActionIcon,
  Badge,
  Group,
  ScrollArea,
  Box,
  Button,
  Flex,
  Menu,
  MenuDivider,
  MenuDropdown,
  MenuItem,
  MenuTarget,
  Paper,
  Progress,
  Stack,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import {
  ChevronDown,
  Filter,
  RefreshCw,
  RotateCcw,
  Square,
  SquareCheck,
  Trash2,
  SquarePen,
  SquarePlus,
} from 'lucide-react';
import { format, useDateTimeFormat } from '../../utils/dateTimeUtils.js';
import useBrowserStorage from '../../hooks/useBrowserStorage';
import ConfirmationDialog from '../../components/ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  deleteEpg,
  formatStatusText,
  getProgressInfo,
  getProgressLabel,
  refreshEpg,
  updateEpg,
} from '../../utils/tables/EPGsTableUtils.js';
import cardClasses from './M3UsTable.module.css';
import { SensitiveValue, ScreenshotText } from '../SensitiveFields.jsx';
import SourceStatus from '../SourceStatus.jsx';

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

const RowActions = ({ row, editEPG, deleteEPG, refreshEPG }) => {
  const epg = row.original;
  return (
    <Paper
      className={cardClasses.controls}
      withBorder
      px={6}
      py={4}
      radius="md"
      role="group"
      aria-label={`Actions for ${epg.name}`}
    >
      <Group gap={4} wrap="nowrap">
        <Tooltip label="Refresh EPG">
          <ActionIcon
            variant="subtle"
            size="md"
            aria-label={`Refresh ${epg.name}`}
            onClick={() => refreshEPG(epg.id)}
            disabled={!epg.is_active || epg.source_type === 'dummy'}
          >
            <RefreshCw size={17} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label="Edit EPG">
          <ActionIcon
            variant="subtle"
            size="md"
            aria-label={`Edit ${epg.name}`}
            color="yellow"
            onClick={() => editEPG(epg)}
          >
            <SquarePen size={17} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label="Delete EPG">
          <ActionIcon
            variant="subtle"
            size="md"
            color="red"
            aria-label={`Delete ${epg.name}`}
            onClick={() => deleteEPG(epg.id)}
          >
            <Trash2 size={17} />
          </ActionIcon>
        </Tooltip>
      </Group>
    </Paper>
  );
};

const EPGStatusCell = ({ epg }) => {
  // Direct Zustand subscription scoped to this source only.
  // This component re-renders whenever its source's progress changes,
  // independent of the parent table's render cycle.
  const progress = useEPGsStore((s) => s.refreshProgress[epg.id]);

  const isDummyEPG = epg.source_type === 'dummy';
  if (isDummyEPG) return null;

  // Show progress bar if an active fetch is in progress
  if (
    progress &&
    progress.status !== 'error' &&
    (progress.progress < 100 ||
      progress.status === 'in_progress' ||
      (progress.action === 'parsing_channels' && epg.status === 'parsing'))
  ) {
    const label = getProgressLabel(progress.action);
    if (!label) return null;

    const additionalInfo = getProgressInfo(progress);

    return (
      <Stack gap={2}>
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
          <Tooltip
            label={<ScreenshotText>{additionalInfo}</ScreenshotText>}
            multiline
            className={cardClasses.detailTooltip}
          >
            <Text size="xs" c="dimmed" truncate>
              <ScreenshotText>{additionalInfo}</ScreenshotText>
            </Text>
          </Tooltip>
        )}
      </Stack>
    );
  }

  return null;
};

const epgMessage = (epg) => {
  if (epg.source_type === 'dummy') return null;
  // Missing configuration is already described below the source name.
  if (
    epg.source_type === 'xmltv' &&
    !epg.url &&
    !epg.file_path &&
    epg.last_message === 'No URL provided and no valid local file exists'
  )
    return null;
  if (epg.status === 'success')
    return epg.last_message || 'EPG data refreshed successfully';
  return ['error', 'idle'].includes(epg.status) ? epg.last_message : null;
};

const ALL_SOURCE_TYPES = ['xmltv', 'schedules_direct', 'dummy'];

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

  const { fullDateTimeFormat } = useDateTimeFormat();
  const [typeFilter, setTypeFilter] = useBrowserStorage(
    'epg-table-type-filter',
    ALL_SOURCE_TYPES,
    { storage: 'session' }
  );
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  const toggleActive = useCallback(async (epg) => {
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
  }, []);

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

          if (sourceType === 'schedules_direct') {
            // Passwords are never displayed; screenshot mode also masks the username.
            const username = row.original.username || '';
            value = username ? `User: ${username}` : '(credentials set)';
          } else {
            value =
              cell.getValue() ||
              row.original.file_path ||
              (sourceType === 'xmltv' ? 'No URL or local file configured' : '');
          }

          return (
            <SensitiveValue
              withTooltip
              sensitive={
                sourceType === 'schedules_direct'
                  ? !!row.original.username
                  : !!row.original.url
              }
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
            return (
              <Text size="xs" c="dimmed">
                Never
              </Text>
            );
          }
          const formatted = format(value, fullDateTimeFormat);
          return (
            <Text size="xs" c="dimmed">
              {formatted}
            </Text>
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
            <Tooltip
              label={
                isDummyEPG
                  ? 'Dummy EPG sources are always enabled'
                  : 'Enable or disable this EPG source'
              }
              withArrow
              events={{ hover: true, focus: true, touch: true }}
            >
              <Paper
                className={cardClasses.controls}
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
                  disabled={isDummyEPG}
                />
              </Paper>
            </Tooltip>
          );
        },
      },
    ],
    [fullDateTimeFormat, toggleActive]
  );

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

  const filteredData = useMemo(
    () => data.filter((e) => typeFilter.includes(e.source_type)),
    [data, typeFilter]
  );

  const isTypeFiltered = typeFilter.length !== ALL_SOURCE_TYPES.length;

  const toggleTypeFilter = (value) => {
    setTypeFilter(
      typeFilter.includes(value)
        ? typeFilter.filter((v) => v !== value)
        : [...typeFilter, value]
    );
  };

  const renderDetail = (epg, id) => {
    const column = columns.find((column) => column.accessorKey === id);
    return column.cell({
      cell: { getValue: () => epg[id] },
      row: { original: epg },
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
          EPG Sources
        </Text>
        <Flex gap={6} align="center">
          <Menu shadow="md" width={200} closeOnItemClick={false}>
            <MenuTarget>
              <Button
                aria-label="Filter EPG types"
                size="xs"
                variant={isTypeFiltered ? 'filled' : 'default'}
                color={isTypeFiltered ? 'blue' : undefined}
              >
                <Filter size={18} />
              </Button>
            </MenuTarget>

            <MenuDropdown>
              <MenuItem
                onClick={() => toggleTypeFilter('xmltv')}
                leftSection={
                  typeFilter.includes('xmltv') ? (
                    <SquareCheck size={18} />
                  ) : (
                    <Square size={18} />
                  )
                }
              >
                <Text size="xs">XMLTV</Text>
              </MenuItem>
              <MenuItem
                onClick={() => toggleTypeFilter('schedules_direct')}
                leftSection={
                  typeFilter.includes('schedules_direct') ? (
                    <SquareCheck size={18} />
                  ) : (
                    <Square size={18} />
                  )
                }
              >
                <Text size="xs">Schedules Direct</Text>
              </MenuItem>
              <MenuItem
                onClick={() => toggleTypeFilter('dummy')}
                leftSection={
                  typeFilter.includes('dummy') ? (
                    <SquareCheck size={18} />
                  ) : (
                    <Square size={18} />
                  )
                }
              >
                <Text size="xs">Dummy</Text>
              </MenuItem>
              <MenuDivider />
              <MenuItem
                onClick={() => setTypeFilter(ALL_SOURCE_TYPES)}
                leftSection={<RotateCcw size={18} />}
                disabled={!isTypeFiltered}
              >
                <Text size="xs">Reset</Text>
              </MenuItem>
            </MenuDropdown>
          </Menu>
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
      </Flex>

      <ScrollArea style={{ flex: 1, minHeight: 0 }} type="auto">
        {filteredData.length === 0 ? (
          <Text size="xl" c="dimmed" ta="center" py="xl">
            {data.length === 0
              ? 'No EPG sources yet.'
              : 'No EPG sources match this filter.'}
          </Text>
        ) : (
          <Stack gap="md">
            {filteredData.map((source) => (
              <Paper
                key={source.id}
                component="article"
                aria-label={`EPG source ${source.name}`}
                className={cardClasses.card}
                withBorder
                p="md"
                radius="md"
                style={
                  source.is_active
                    ? undefined
                    : { opacity: 0.65, filter: 'grayscale(0.75)' }
                }
              >
                <Stack gap="sm">
                  <Group justify="space-between" align="flex-start">
                    <Box style={{ minWidth: 0, flex: '1 1 200px' }}>
                      <Group gap="xs">
                        <Tooltip
                          label={source.name}
                          multiline
                          className={cardClasses.detailTooltip}
                        >
                          <Text
                            fw={700}
                            size="lg"
                            truncate
                            className={cardClasses.name}
                          >
                            {source.name}
                          </Text>
                        </Tooltip>
                        <Badge variant="light">
                          {renderDetail(source, 'source_type')}
                        </Badge>
                        <SourceStatus
                          label={formatStatusText(
                            source.source_type === 'dummy'
                              ? 'idle'
                              : source.status
                          )}
                          color={getStatusColor(
                            source.source_type === 'dummy'
                              ? 'idle'
                              : source.status
                          )}
                          messages={[epgMessage(source)]}
                          messageColor={
                            source.status === 'error' ? 'red' : undefined
                          }
                        />
                      </Group>
                      {renderDetail(source, 'url')}
                    </Box>
                    <Group gap="xs" align="stretch" wrap="nowrap">
                      {renderDetail(source, 'is_active')}
                      <RowActions
                        row={{ original: source }}
                        editEPG={editEPG}
                        deleteEPG={deleteEPG}
                        refreshEPG={handleRefreshEPG}
                      />
                    </Group>
                  </Group>
                  <Group gap="xl" align="flex-start">
                    <Box>
                      <Text size="xs" fw={600} mb={4}>
                        EPG channels
                      </Text>
                      <Text size="xs" c="dimmed">
                        {source.epg_data_count ?? '—'}
                      </Text>
                    </Box>
                    <Box>
                      <Text size="xs" fw={600} mb={4}>
                        Last refresh
                      </Text>
                      <Stack gap={4}>
                        {renderDetail(source, 'updated_at')}
                        <EPGStatusCell epg={source} />
                      </Stack>
                    </Box>
                  </Group>
                </Stack>
              </Paper>
            ))}
          </Stack>
        )}
      </ScrollArea>

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
`}
              {epgToDelete.source_type === 'schedules_direct' ? (
                epgToDelete.username ? (
                  <>
                    Username:{' '}
                    <SensitiveValue component="span" inherit>
                      {epgToDelete.username}
                    </SensitiveValue>
                  </>
                ) : (
                  '(credentials set)'
                )
              ) : epgToDelete.url ? (
                `URL: ${epgToDelete.url}`
              ) : epgToDelete.file_path ? (
                `File Path: ${epgToDelete.file_path}`
              ) : (
                ''
              )}
              {`

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
