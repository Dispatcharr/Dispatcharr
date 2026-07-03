import React, { useCallback, useEffect, useMemo, useRef, useState, } from 'react';
import { closestCenter, DndContext, PointerSensor, useSensor, useSensors, } from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy, } from '@dnd-kit/sortable';
import useChannelsStore from '../../store/channels';
import ChannelForm from '../forms/Channel';
import ChannelBatchForm from '../forms/ChannelBatch';
import RecordingForm from '../forms/Recording';
import { copyToClipboard, useDebounce } from '../../utils';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';
import {
  ArrowDownWideNarrow,
  ArrowUpDown,
  ArrowUpNarrowWide,
  CirclePlay,
  Copy,
  EllipsisVertical,
  EyeOff,
  Pencil,
  ScanEye,
  ScreenShare,
  Scroll,
  Search,
  SquareMinus,
  SquarePen,
  Tv2,
} from 'lucide-react';
import { listOverriddenFields, requeryChannels, } from '../../utils/forms/ChannelUtils.js';
import { buildLiveStreamUrl } from '../../utils/components/FloatingVideoUtils.js';
import {
  ActionIcon,
  Box,
  Button,
  Center,
  Flex,
  Group,
  Menu,
  MenuDropdown,
  MenuItem,
  MenuTarget,
  MultiSelect,
  NativeSelect,
  NumberInput,
  Pagination,
  Paper,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
  useMantineTheme,
} from '@mantine/core';
import './table.css';
import useChannelsTableStore from '../../store/channelsTable';
import ChannelTableStreams from './ChannelTableStreams';
import CatchupIndicator from '../CatchupIndicator';
import LazyLogo from '../LazyLogo';
import useLocalStorage from '../../hooks/useLocalStorage';
import useEPGsStore from '../../store/epgs';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import { CustomTable, useTable } from './CustomTable';
import ChannelsTableOnboarding from './ChannelsTable/ChannelsTableOnboarding';
import ChannelTableHeader from './ChannelsTable/ChannelTableHeader';
import useOutputProfilesStore from '../../store/outputProfiles';
import {
  EditableEPGCell,
  EditableGroupCell,
  EditableLogoCell,
  EditableNumberCell,
  EditableTextCell,
} from './ChannelsTable/EditableCell';
import useWarningsStore from '../../store/warnings';
import ConfirmationDialog from '../ConfirmationDialog';
import useAuthStore from '../../store/auth';
import { USER_LEVELS } from '../../constants';
import { getShowVideoUrl } from '../../utils/cards/RecordingCardUtils.js';
import {
  buildEPGUrl,
  buildFetchParams,
  buildHDHRUrl,
  buildM3UUrl,
  deleteChannel,
  deleteChannels,
  epgUrlBase,
  getAllChannelIds,
  hdhrUrlBase,
  m3uUrlBase,
  queryChannels,
  reorderChannel,
  updateProfileChannel,
  updateProfileChannels,
} from '../../utils/tables/ChannelsTableUtils.js';

const ChannelEnabledSwitch = React.memo(
  ({ rowId, selectedProfileId, selectedTableIds }) => {
    // Directly extract the channels set once to avoid re-renders on every change.
    const isEnabled = useChannelsStore(
      useCallback(
        (state) =>
          selectedProfileId === '0' ||
          state.profiles[selectedProfileId]?.channels.has(rowId),
        [rowId, selectedProfileId]
      )
    );

    const handleToggle = () => {
      if (selectedTableIds.length > 1) {
        updateProfileChannels(
          selectedTableIds,
          selectedProfileId,
          !isEnabled
        );
      } else {
        updateProfileChannel(rowId, selectedProfileId, !isEnabled);
      }
    };

    return (
      <Center style={{ width: '100%' }}>
        <Switch
          size="xs"
          checked={isEnabled}
          onChange={handleToggle}
          disabled={selectedProfileId === '0'}
        />
      </Center>
    );
  }
);

const ChannelRowActions = React.memo(
  ({
    theme,
    row,
    table,
    editChannel,
    deleteChannel,
    handleWatchStream,
    createRecording,
    getChannelURL,
  }) => {
    // Extract the channel ID once to ensure consistency
    const channelId = row.original.id;
    const channelUuid = row.original.uuid;

    const authUser = useAuthStore((s) => s.user);

    const onEdit = useCallback(() => {
      // Use the ID directly to avoid issues with filtered tables
      console.log(`Editing channel ID: ${channelId}`);
      editChannel(row.original);
    }, [channelId, row.original]);

    const onDelete = useCallback(() => {
      console.log(`Deleting channel ID: ${channelId}`);
      deleteChannel(channelId);
    }, [channelId]);

    const onPreview = useCallback(() => {
      // Use direct channel UUID for preview to avoid issues
      console.log(`Previewing channel UUID: ${channelUuid}`);
      handleWatchStream(row.original);
    }, [channelUuid]);

    const onRecord = useCallback(() => {
      console.log(`Recording channel ID: ${channelId}`);
      createRecording(row.original);
    }, [channelId]);

    const tableSize = table?.tableSize ?? 'default';
    const iconSize =
      tableSize == 'default' ? 'sm' : tableSize == 'compact' ? 'xs' : 'md';

    return (
      <Box style={{ width: '100%', justifyContent: 'left' }}>
        <Center>
          <ActionIcon
            size={iconSize}
            variant="transparent"
            color={theme.tailwind.yellow[3]}
            onClick={onEdit}
            disabled={authUser.user_level != USER_LEVELS.ADMIN}
          >
            <SquarePen size="18" />
          </ActionIcon>

          <ActionIcon
            size={iconSize}
            variant="transparent"
            color={theme.tailwind.red[6]}
            onClick={onDelete}
            disabled={authUser.user_level != USER_LEVELS.ADMIN}
          >
            <SquareMinus size="18" />
          </ActionIcon>

          <ActionIcon
            size={iconSize}
            variant="transparent"
            color={theme.tailwind.green[5]}
            onClick={onPreview}
          >
            <CirclePlay size="18" />
          </ActionIcon>

          <Menu>
            <MenuTarget>
              <ActionIcon variant="transparent" size={iconSize}>
                <EllipsisVertical size="18" />
              </ActionIcon>
            </MenuTarget>

            <MenuDropdown>
              <MenuItem leftSection={<Copy size="14" />}>
                <UnstyledButton
                  size="xs"
                  onClick={() => copyToClipboard(getChannelURL(row.original))}
                >
                  <Text size="xs">Copy URL</Text>
                </UnstyledButton>
              </MenuItem>
              <MenuItem
                onClick={onRecord}
                disabled={authUser.user_level != USER_LEVELS.ADMIN}
                leftSection={
                  <div
                    style={{
                      borderRadius: '50%',
                      width: '10px',
                      height: '10px',
                      display: 'flex',
                      backgroundColor: 'red',
                    }}
                  ></div>
                }
              >
                <Text size="xs">Record</Text>
              </MenuItem>
            </MenuDropdown>
          </Menu>
        </Center>
      </Box>
    );
  },
  // Custom comparator: skip re-render when the channel's data object hasn't
  // changed. row.original is stable when the underlying channel hasn't been
  // updated; it becomes a new reference when the store replaces that channel.
  (prevProps, nextProps) => prevProps.row.original === nextProps.row.original
);

const ChannelsTable = ({ onReady }) => {
  // EPG data lookup
  const tvgsById = useEPGsStore((s) => s.tvgsById);
  const epgs = useEPGsStore((s) => s.epgs);
  const tvgsLoaded = useEPGsStore((s) => s.tvgsLoaded);
  const hasUnassignedEPGChannels = useChannelsTableStore(
    (s) => s.hasUnassignedEPGChannels
  );

  // Get channel logos for logo selection
  const { ensureLogosLoaded } = useChannelLogoSelection();

  const theme = useMantineTheme();
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const hasSignaledReady = useRef(false);

  /**
   * STORES
   */

  // store/channelsTable
  const data = useChannelsTableStore((s) => s.channels);
  const pageCount = useChannelsTableStore((s) => s.pageCount);

  const rowClassMap = useMemo(() => {
    const map = {};
    for (const channel of data) {
      const hasStreams = channel.streams?.length > 0;
      if (!hasStreams) {
        map[channel.id] = 'no-streams-row';
      } else if (channel.streams.some((s) => s.is_stale)) {
        map[channel.id] = 'has-stale-streams-row';
      }
    }
    return map;
  }, [data]);
  const setSelectedChannelIds = useChannelsTableStore(
    (s) => s.setSelectedChannelIds
  );
  const setExpandedChannelId = useChannelsTableStore(
    (s) => s.setExpandedChannelId
  );
  const pagination = useChannelsTableStore((s) => s.pagination);
  const setPagination = useChannelsTableStore((s) => s.setPagination);
  const sorting = useChannelsTableStore((s) => s.sorting);
  const setSorting = useChannelsTableStore((s) => s.setSorting);
  const totalCount = useChannelsTableStore((s) => s.totalCount);
  const allRowIds = useChannelsTableStore((s) => s.allQueryIds);
  const setAllRowIds = useChannelsTableStore((s) => s.setAllQueryIds);

  // store/channels
  const hasChannels = useChannelsStore((s) => s.channelIds.length > 0);
  const profiles = useChannelsStore((s) => s.profiles);
  const selectedProfileId = useChannelsStore((s) => s.selectedProfileId);
  const [, setTablePrefs] = useLocalStorage('channel-table-prefs', {
    pageSize: 50,
  });

  // store/settings
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const outputProfiles = useOutputProfilesStore((s) => s.profiles);
  const showVideo = useVideoStore((s) => s.showVideo);

  // store/warnings
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  /**
   * useState
   */
  const [channel, setChannel] = useState(null);
  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [channelBatchModalOpen, setChannelBatchModalOpen] = useState(false);
  const [recordingModalOpen, setRecordingModalOpen] = useState(false);
  const [showDisabled, setShowDisabled] = useState(true);
  const [showOnlyStreamlessChannels, setShowOnlyStreamlessChannels] =
    useState(false);
  const [showOnlyStaleChannels, setShowOnlyStaleChannels] = useState(false);
  const [showOnlyOverriddenChannels, setShowOnlyOverriddenChannels] =
    useState(false);
  const [showOnlyCatchupChannels, setShowOnlyCatchupChannels] =
    useState(false);
  const [visibilityFilter, setVisibilityFilter] = useState('active');

  const [paginationString, setPaginationString] = useState('');
  const [filters, setFilters] = useState({
    name: '',
    channel_group: '',
    epg: '',
  });
  const [, setIsLoading] = useState(true);

  const [hdhrUrl, setHDHRUrl] = useState(hdhrUrlBase);
  const [hdhrOutputProfileId, setHdhrOutputProfileId] = useState('');
  const [epgUrl, setEPGUrl] = useState(epgUrlBase);
  const [m3uUrl, setM3UUrl] = useState(m3uUrlBase);

  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [isBulkDelete, setIsBulkDelete] = useState(false);
  const [channelToDelete, setChannelToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const hasFetchedData = useRef(false);
  const fetchVersionRef = useRef(0); // Track fetch version to prevent stale updates
  const lastFetchParamsRef = useRef(null); // Track last fetch params to prevent duplicate requests
  const fetchInProgressRef = useRef(false); // Track if a fetch is currently in progress

  // Drag-and-drop sensors
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // Require 8px movement before dragging starts
      },
    })
  );

  // Column sizing state for resizable columns
  // Store in localStorage but with empty object as default
  const [columnSizing, setColumnSizing] = useLocalStorage(
    'channels-table-column-sizing',
    {}
  );

  // M3U and EPG URL configuration state
  const [m3uParams, setM3uParams] = useState({
    cachedlogos: true,
    direct: false,
    tvg_id_source: 'channel_number',
    output_format: '',
    output_profile: '',
  });
  const [epgParams, setEpgParams] = useState({
    cachedlogos: true,
    tvg_id_source: 'channel_number',
    days: 0,
    prev_days: 0,
  });

  /**
   * Derived variables
   */
  const groupOptions = Object.values(channelGroups)
    .filter((group) => group.hasChannels)
    .map((group) => group.name)
    .sort((a, b) => a.localeCompare(b));

  const epgOptions = Object.values(epgs)
    .filter((epg) => epg.is_active && epg.has_channels)
    .map((epg) => epg.name)
    .sort((a, b) => a.localeCompare(b));
  // Only show 'No EPG' if there are channels without an EPG assigned
  const epgSelectOptions = [
    ...(hasUnassignedEPGChannels ? [{ value: 'null', label: 'No EPG' }] : []),
    ...epgOptions.map((opt) => ({ value: opt, label: opt })),
  ];
  const debouncedFilters = useDebounce(filters, 500, () => {
    setPagination({
      ...pagination,
      pageIndex: 0,
    });
  });

  const channelsTableLength =
    Object.keys(data).length > 0 || hasFetchedData.current
      ? Object.keys(data).length
      : undefined;

  /**
   * Functions
   */
  const handleFetchSuccess = useCallback((ids) => {
    setTablePrefs((prev) => ({ ...prev, pageSize: pagination.pageSize }));
    setAllRowIds(ids);
    hasFetchedData.current = true;
    if (!hasSignaledReady.current && onReady && tvgsLoaded) {
      hasSignaledReady.current = true;
      onReady();
    }
  }, [pagination.pageSize, setTablePrefs, setAllRowIds, onReady, tvgsLoaded]);

  const fetchData = useCallback(async () => {
    const params = buildFetchParams({
      pagination, sorting, debouncedFilters, selectedProfileId,
      showDisabled, showOnlyStreamlessChannels, showOnlyStaleChannels,
      showOnlyOverriddenChannels, visibilityFilter, showOnlyCatchupChannels,
    });
    const paramsString = params.toString();

    if (fetchInProgressRef.current && lastFetchParamsRef.current === paramsString) return;

    const currentFetchVersion = ++fetchVersionRef.current;
    lastFetchParamsRef.current = paramsString;
    fetchInProgressRef.current = true;
    setIsLoading(true);

    try {
      const [, ids] = await Promise.all([queryChannels(params), getAllChannelIds(params)]);
      fetchInProgressRef.current = false;
      if (currentFetchVersion !== fetchVersionRef.current) return;
      setIsLoading(false);
      handleFetchSuccess(ids);
    } catch (error) {
      fetchInProgressRef.current = false;
      if (currentFetchVersion !== fetchVersionRef.current) return;
      setIsLoading(false);
      throw error;
    }
  }, [
    pagination, sorting, debouncedFilters, selectedProfileId,
    showDisabled, showOnlyStreamlessChannels, showOnlyStaleChannels,
    showOnlyOverriddenChannels, visibilityFilter, showOnlyCatchupChannels,
    handleFetchSuccess,
  ]);

  const stopPropagation = useCallback((e) => {
    e.stopPropagation();
  }, []);

  const handleFilterChange = (e) => {
    const { name, value } = e.target;
    // Then update filters
    setFilters((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleGroupChange = (value) => {
    // Then update filters
    setFilters((prev) => ({
      ...prev,
      channel_group: value ? value : '',
    }));
  };

  const handleEPGChange = (value) => {
    // Map 'null' (string) back to 'null' for backend, but keep UI label correct
    const processedValue = value
      ? value.map((v) => (v === 'null' ? 'null' : v))
      : '';
    setFilters((prev) => ({
      ...prev,
      epg: processedValue,
    }));
  };

  const editChannel = useCallback(async (ch = null, opts = {}) => {
    if (opts.forceAdd) {
      setChannel(null);
      setChannelModalOpen(true);
      return;
    }
    const currentSelection =
      useChannelsTableStore.getState().selectedChannelIds;
    console.log('editChannel called with:', { ch, currentSelection });

    if (currentSelection.length > 1) {
      setChannelBatchModalOpen(true);
    } else {
      let channelToEdit = ch;
      if (!channelToEdit && currentSelection.length === 1) {
        const selectedId = currentSelection[0];
        channelToEdit = useChannelsTableStore
          .getState()
          .channels.find((d) => d.id === selectedId);
      }
      setChannel(channelToEdit);
      setChannelModalOpen(true);
    }
  }, []);

  const handleDeleteChannel = async (id) => {
    console.log(`Deleting channel with ID: ${id}`);

    const rows = table.getRowModel().rows;
    const knownChannel = rows.find((row) => row.original.id === id)?.original;

    table.setSelectedTableIds([]);

    if (table.selectedTableIds.length > 0) {
      // Use bulk delete for multiple selections
      setIsBulkDelete(true);
      setChannelToDelete(null);

      if (isWarningSuppressed('delete-channels')) {
        // Skip warning if suppressed
        return executeDeleteChannels();
      }

      setConfirmDeleteOpen(true);
      return;
    }

    // Single channel delete
    setIsBulkDelete(false);
    setDeleteTarget(id);
    setChannelToDelete(knownChannel); // Store the channel object for displaying details

    if (isWarningSuppressed('delete-channel')) {
      // Skip warning if suppressed
      return executeDeleteChannel(id);
    }

    setConfirmDeleteOpen(true);
  };

  const executeDeleteChannel = async (id) => {
    setDeleting(true);
    try {
      await deleteChannel(id);
      requeryChannels();
    } finally {
      setDeleting(false);
      setConfirmDeleteOpen(false);
    }
  };

  const handleDeleteChannels = async () => {
    if (isWarningSuppressed('delete-channels')) {
      // Skip warning if suppressed
      return executeDeleteChannels();
    }

    setIsBulkDelete(true);
    setConfirmDeleteOpen(true);
  };

  const executeDeleteChannels = async () => {
    setIsLoading(true);
    setDeleting(true);
    try {
      await deleteChannels(table.selectedTableIds);
      await requeryChannels();
      setSelectedChannelIds([]);
      table.setSelectedTableIds([]);
    } finally {
      setDeleting(false);
      setIsLoading(false);
      setConfirmDeleteOpen(false);
    }
  };

  const createRecording = useCallback((channel) => {
    console.log(`Recording channel ID: ${channel.id}`);
    setChannel(channel);
    setRecordingModalOpen(true);
  }, []);

  const getChannelURL = useCallback(
    (channel) => {
      if (!channel || !channel.uuid) {
        console.error('Invalid channel object or missing UUID:', channel);
        return '';
      }

      const path = getShowVideoUrl(channel, env_mode);
      if (env_mode == 'dev') {
        return path;
      }
      return `${window.location.protocol}//${window.location.host}${path}`;
    },
    [env_mode]
  );

  const handleWatchStream = useCallback(
    (channel) => {
      if (!channel || !channel.uuid) return;
      const path = `/proxy/ts/stream/${channel.uuid}`;
      const uri = buildLiveStreamUrl(path);
      let url = `${window.location.protocol}//${window.location.host}${uri}`;
      if (env_mode == 'dev') {
        url = `${window.location.protocol}//${window.location.hostname}:5656${uri}`;
      }
      showVideo(url, 'live', { name: channel.name, channelId: channel.id });
    },
    [env_mode, showVideo]
  );

  const onRowSelectionChange = (newSelection) => {
    setSelectedChannelIds(newSelection);
  };

  const onRowExpansionChange = useCallback(
    (expandedIds) => {
      setExpandedChannelId(expandedIds.length > 0 ? expandedIds[0] : null);
    },
    [setExpandedChannelId]
  );

  const onPageSizeChange = (e) => {
    setPagination({
      ...pagination,
      pageSize: e.target.value,
    });
  };

  const onPageIndexChange = (pageIndex) => {
    if (!pageIndex || pageIndex > pageCount) {
      return;
    }

    setPagination({
      ...pagination,
      pageIndex: pageIndex - 1,
    });
  };

  const closeChannelBatchForm = () => {
    setChannelBatchModalOpen(false);
  };

  const closeChannelForm = () => {
    setChannel(null);
    setChannelModalOpen(false);
  };

  const closeRecordingForm = () => {
    // setChannel(null);
    setRecordingModalOpen(false);
  };

  // Example copy URLs
  const copyM3UUrl = async () => {
    await copyToClipboard(buildM3UUrl(m3uParams, m3uUrl), {
      successTitle: 'M3U URL Copied!',
      successMessage: 'The M3U URL has been copied to your clipboard.',
    });
  };

  const copyEPGUrl = async () => {
    await copyToClipboard(buildEPGUrl(epgParams, epgUrl), {
      successTitle: 'EPG URL Copied!',
      successMessage: 'The EPG URL has been copied to your clipboard.',
    });
  };

  const copyHDHRUrl = async () => {
    await copyToClipboard(buildHDHRUrl(hdhrOutputProfileId, hdhrUrl), {
      successTitle: 'HDHR URL Copied!',
      successMessage: 'The HDHR URL has been copied to your clipboard.',
    });
  };

  const onSortingChange = (column) => {
    const sortField = sorting[0]?.id;
    const sortDirection = sorting[0]?.desc;

    if (sortField == column) {
      if (sortDirection == false) {
        setSorting([
          {
            id: column,
            desc: true,
          },
        ]);
      } else {
        setSorting([]);
      }
    } else {
      setSorting([
        {
          id: column,
          desc: false,
        },
      ]);
    }
  };

  const handleDragEnd = async (event) => {
    const { active, over } = event;

    if (!over || active.id === over.id) {
      return;
    }

    const activeIndex = rows.findIndex((row) => row.id === active.id);
    const overIndex = rows.findIndex((row) => row.id === over.id);

    if (activeIndex === -1 || overIndex === -1) {
      return;
    }

    const activeChannel = rows[activeIndex].original;
    const overChannel = rows[overIndex].original;

    try {
      // Optimistically update the local state
      const reorderedData = [...data];
      const [movedItem] = reorderedData.splice(activeIndex, 1);
      reorderedData.splice(overIndex, 0, movedItem);
      useChannelsTableStore.setState({ channels: reorderedData });

      // Call backend to reorder
      await reorderChannel(
        activeChannel.id,
        overIndex > activeIndex
          ? overChannel.id
          : rows[overIndex - 1]?.original.id || null
      );

      // Refetch to get updated channel numbers
      await requeryChannels();
    } catch (error) {
      // Revert on error
      console.error('Failed to reorder channel:', error);
      await requeryChannels();
    }
  };

  /**
   * useEffect
   */
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    const profileString =
      selectedProfileId != '0' ? `/${profiles[selectedProfileId].name}` : '';
    setHDHRUrl(`${hdhrUrlBase}${profileString}`);
    setEPGUrl(`${epgUrlBase}${profileString}`);
    setM3UUrl(`${m3uUrlBase}${profileString}`);
  }, [selectedProfileId, profiles]);

  useEffect(() => {
    const startItem = pagination.pageIndex * pagination.pageSize + 1; // +1 to start from 1, not 0
    const endItem = Math.min(
      (pagination.pageIndex + 1) * pagination.pageSize,
      totalCount
    );
    setPaginationString(`${startItem} to ${endItem} of ${totalCount}`);
  }, [pagination.pageIndex, pagination.pageSize, totalCount]);

  // Signal ready when EPG data finishes loading (if channels were already fetched)
  useEffect(() => {
    if (
      hasFetchedData.current &&
      !hasSignaledReady.current &&
      onReady &&
      tvgsLoaded
    ) {
      hasSignaledReady.current = true;
      onReady();
    }
  }, [tvgsLoaded, onReady]);

  const columns = useMemo(
    () => [
      {
        id: 'expand',
        size: 20,
        enableResizing: false,
      },
      {
        id: 'select',
        size: 30,
        enableResizing: false,
      },
      {
        id: 'enabled',
        size: 45,
        enableResizing: false,
        cell: ({ row, table }) => {
          return (
            <ChannelEnabledSwitch
              rowId={row.original.id}
              selectedProfileId={selectedProfileId}
              selectedTableIds={table.getState().selectedTableIds}
            />
          );
        },
      },
      {
        id: 'channel_number',
        // Prefer the backend-resolved effective_channel_number so overrides
        // show through to the table. Inline save still writes to the
        // override row via buildInlinePatch in EditableCell.
        accessorFn: (row) => row.effective_channel_number ?? row.channel_number,
        size: columnSizing.channel_number || 40,
        minSize: 30,
        maxSize: 100,
        cell: (props) => <EditableNumberCell {...props} />,
      },
      {
        id: 'name',
        accessorFn: (row) => row.effective_name ?? row.name,
        size: columnSizing.name || 200,
        minSize: 100,
        grow: true,
        cell: (props) => {
          const row = props.row?.original || {};
          const overriddenLabels = listOverriddenFields(row);
          return (
            <Flex align="center" gap={6} style={{ minWidth: 0 }}>
              <Box style={{ minWidth: 0, flex: 1 }}>
                <EditableTextCell {...props} />
              </Box>
              {overriddenLabels.length > 0 && (
                <Tooltip
                  label={`Overrides active: ${overriddenLabels.join(', ')}`}
                >
                  <Box
                    component="span"
                    role="img"
                    aria-label={`Overrides active: ${overriddenLabels.join(', ')}`}
                    style={{ display: 'inline-flex' }}
                  >
                    <Pencil size={14} color="#eab308" aria-hidden="true" />
                  </Box>
                </Tooltip>
              )}
              {row.hidden_from_output && (
                <Tooltip label="Hidden from HDHR, M3U, EPG, and XC output.">
                  <Box
                    component="span"
                    role="img"
                    aria-label="Hidden from HDHR, M3U, EPG, and XC output"
                    style={{ display: 'inline-flex' }}
                  >
                    <EyeOff size={14} color="#9ca3af" aria-hidden="true" />
                  </Box>
                </Tooltip>
              )}
              <CatchupIndicator
                isCatchup={row.is_catchup}
                catchupDays={row.catchup_days}
              />
            </Flex>
          );
        },
      },
      {
        id: 'epg',
        header: 'EPG',
        // Effective EPG id so overridden EPG assignments show in the table.
        accessorFn: (row) => row.effective_epg_data_id ?? row.epg_data_id,
        cell: (props) => (
          <EditableEPGCell
            {...props}
            tvgsById={tvgsById}
            epgs={epgs}
            tvgsLoaded={tvgsLoaded}
          />
        ),
        size: columnSizing.epg || 200,
        minSize: 120,
      },
      {
        id: 'channel_group',
        accessorFn: (row) => {
          const effectiveGroupId =
            row.effective_channel_group_id ?? row.channel_group_id;
          return channelGroups[effectiveGroupId]
            ? channelGroups[effectiveGroupId].name
            : '';
        },
        cell: (props) => (
          <EditableGroupCell {...props} channelGroups={channelGroups} />
        ),
        size: columnSizing.channel_group || 200,
        minSize: 120,
      },
      {
        id: 'logo',
        accessorFn: (row) => row.effective_logo_id ?? row.logo_id,
        size: 75,
        minSize: 50,
        maxSize: 120,
        enableResizing: false,
        header: '',
        cell: (props) => (
          <EditableLogoCell
            {...props}
            LazyLogo={LazyLogo}
            ensureLogosLoaded={ensureLogosLoaded}
          />
        ),
      },
      {
        id: 'actions',
        size: 100,
        enableResizing: false,
        header: '',
        cell: ({ row, table }) => (
          <ChannelRowActions
            theme={theme}
            row={row}
            table={table}
            editChannel={editChannel}
            deleteChannel={handleDeleteChannel}
            handleWatchStream={handleWatchStream}
            createRecording={createRecording}
            getChannelURL={getChannelURL}
          />
        ),
      },
    ],
    // Note: columnSizing is intentionally excluded from dependencies to prevent
    // columns from being recreated during drag operations (which causes infinite loops).
    // The column.size values are only used for INITIAL sizing - TanStack Table manages
    // the actual sizes through its own state after initialization.
    // Note: logos is intentionally excluded - LazyLogo components handle their own logo data
    // from the store, so we don't need to recreate columns when logos load.
    // Note: tvgsLoaded is intentionally excluded - EditableEPGCell handles loading state internally
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedProfileId, channelGroups, theme, tvgsById, epgs, editChannel]
  );

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
      case 'epg':
        return (
          <MultiSelect
            placeholder="EPG"
            variant="unstyled"
            data={epgSelectOptions}
            className="table-input-header"
            size="xs"
            searchable
            clearable
            onClick={stopPropagation}
            onChange={handleEPGChange}
            value={
              Array.isArray(filters.epg)
                ? filters.epg
                : filters.epg
                  ? filters.epg.split(',').filter(Boolean)
                  : []
            }
            style={{ width: '100%' }}
            rightSectionPointerEvents="auto"
            rightSection={React.createElement(sortingIcon, {
              onClick: (e) => {
                e.stopPropagation();
                onSortingChange('epg');
              },
              size: 14,
              style: { cursor: 'pointer' },
            })}
          />
        );
      case 'enabled':
        return (
          <Center style={{ width: '100%' }}>
            <ScanEye size="16" />
          </Center>
        );

      case 'channel_number':
        return (
          <Flex gap={2} align="center">
            #
            <Center
              onClick={(e) => {
                e.stopPropagation();
                onSortingChange('channel_number');
              }}
              style={{ cursor: 'pointer' }}
            >
              {React.createElement(sortingIcon, {
                size: 14,
              })}
            </Center>
          </Flex>
        );

      case 'name':
        return (
          <TextInput
            name="name"
            placeholder="Name"
            value={filters.name || ''}
            onClick={(e) => e.stopPropagation()}
            onChange={handleFilterChange}
            size="xs"
            variant="unstyled"
            className="table-input-header"
            leftSection={<Search size={14} opacity={0.5} />}
            style={{ width: '100%' }}
            rightSectionPointerEvents="auto"
            rightSection={React.createElement(sortingIcon, {
              onClick: (e) => {
                e.stopPropagation();
                onSortingChange('name');
              },
              size: 14,
              style: { cursor: 'pointer' },
            })}
          />
        );

      case 'channel_group':
        return (
          <MultiSelect
            placeholder="Group"
            className="table-input-header"
            variant="unstyled"
            data={groupOptions}
            size="xs"
            searchable
            clearable
            onClick={stopPropagation}
            onChange={handleGroupChange}
            value={
              Array.isArray(filters.channel_group)
                ? filters.channel_group
                : filters.channel_group
                  ? filters.channel_group.split(',').filter(Boolean)
                  : []
            }
            style={{ width: '100%' }}
            rightSectionPointerEvents="auto"
            rightSection={React.createElement(sortingIcon, {
              onClick: (e) => {
                e.stopPropagation();
                onSortingChange('channel_group');
              },
              size: 14,
              style: { cursor: 'pointer' },
            })}
          />
        );
    }
  };

  const table = useTable({
    data,
    columns,
    allRowIds,
    pageCount,
    filters,
    pagination,
    sorting,
    columnSizing,
    setColumnSizing,
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    enableRowSelection: true,
    enableDragDrop: true,
    onRowSelectionChange: onRowSelectionChange,
    onRowExpansionChange: onRowExpansionChange,
    state: {
      pagination,
      sorting,
    },
    columnResizeMode: 'onChange',
    getExpandedRowHeight: (row) => {
      return 20 + 28 * row.original.streams.length;
    },
    expandedRowRenderer: ({ row }) => {
      return (
        <Box
          key={row.id}
          className="tr"
          style={{ display: 'flex', width: '100%' }}
        >
          <ChannelTableStreams channel={row.original} />
        </Box>
      );
    },
    headerCellRenderFns: {
      name: renderHeaderCell,
      channel_number: renderHeaderCell,
      channel_group: renderHeaderCell,
      enabled: renderHeaderCell,
      epg: renderHeaderCell,
    },
    getRowStyles: (row) => {
      const cls = rowClassMap[row.original.id];
      return cls ? { className: cls } : {};
    },
  });

  const rows = table.getRowModel().rows;

  return (
    <>
      <Box>
        {/* Header Row: outside the Paper */}
        <Flex style={{ alignItems: 'center', paddingBottom: 10 }} gap={15}>
          <Text
            w={88}
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
            Channels
          </Text>
          <Flex
            style={{
              display: 'flex',
              alignItems: 'center',
              marginLeft: 10,
            }}
          >
            <Text
              w={37}
              h={17}
              style={{
                fontFamily: 'Inter, sans-serif',
                fontWeight: 400,
                fontSize: '14px',
                lineHeight: 1,
                letterSpacing: '-0.3px',
                color: 'gray.6', // Adjust this to match MUI's theme.palette.text.secondary
              }}
            >
              Links:
            </Text>
            <Group gap={5} style={{ paddingLeft: 10 }}>
              <Popover
                withArrow
                shadow="md"
                zIndex={1000}
                position="bottom-start"
                withinPortal
              >
                <PopoverTarget>
                  <Button
                    leftSection={<Tv2 size={18} />}
                    size="compact-sm"
                    p={5}
                    color="green"
                    variant="subtle"
                    style={{
                      borderColor: theme.palette.custom.greenMain,
                      color: theme.palette.custom.greenMain,
                    }}
                  >
                    HDHR
                  </Button>
                </PopoverTarget>
                <PopoverDropdown>
                  <Stack
                    gap="sm"
                    style={{
                      minWidth: 300,
                      maxWidth: 'min(500px, 90vw)',
                      width: 'max-content',
                    }}
                    onClick={stopPropagation}
                    onMouseDown={stopPropagation}
                  >
                    <Text size="sm" c="dimmed">
                      Use this URL in HDHomeRun-compatible apps and IPTV
                      clients.
                    </Text>
                    <TextInput
                      value={buildHDHRUrl(hdhrOutputProfileId, hdhrUrl)}
                      size="sm"
                      readOnly
                      label="Generated URL"
                      style={{ width: '100%' }}
                      rightSection={
                        <ActionIcon
                          onClick={copyHDHRUrl}
                          size="sm"
                          variant="transparent"
                          color="gray.5"
                        >
                          <Copy size="16" />
                        </ActionIcon>
                      }
                    />
                    <Select
                      label="Output Profile"
                      description="Pre-delivery transcode profile. Overrides the system-wide HDHR default."
                      clearable
                      searchable
                      placeholder="System default"
                      value={hdhrOutputProfileId || null}
                      onChange={(value) => setHdhrOutputProfileId(value || '')}
                      comboboxProps={{ withinPortal: false }}
                      data={outputProfiles
                        .filter((p) => p.is_active)
                        .map((p) => ({ value: `${p.id}`, label: p.name }))}
                    />
                  </Stack>
                </PopoverDropdown>
              </Popover>
              <Popover
                withArrow
                shadow="md"
                zIndex={1000}
                position="bottom-start"
                withinPortal
              >
                <PopoverTarget>
                  <Button
                    leftSection={<ScreenShare size={18} />}
                    size="compact-sm"
                    p={5}
                    variant="subtle"
                    style={{
                      borderColor: theme.palette.custom.indigoMain,
                      color: theme.palette.custom.indigoMain,
                    }}
                  >
                    M3U
                  </Button>
                </PopoverTarget>
                <PopoverDropdown>
                  <Stack
                    gap="sm"
                    style={{
                      minWidth: 300,
                      maxWidth: 'min(500px, 90vw)',
                      width: 'max-content',
                    }}
                    onClick={stopPropagation}
                    onMouseDown={stopPropagation}
                  >
                    <Text size="sm" c="dimmed">
                      Use this URL in your media player or IPTV app to load your
                      channel list.
                    </Text>
                    <TextInput
                      value={buildM3UUrl(m3uParams, m3uUrl)}
                      size="sm"
                      readOnly
                      label="Generated URL"
                      rightSection={
                        <ActionIcon
                          onClick={copyM3UUrl}
                          size="sm"
                          variant="transparent"
                          color="gray.5"
                        >
                          <Copy size="16" />
                        </ActionIcon>
                      }
                    />
                    <Switch
                      label="Use cached logos"
                      description="Proxy channel logos through Dispatcharr"
                      size="sm"
                      checked={m3uParams.cachedlogos}
                      onChange={(event) =>
                        setM3uParams((prev) => ({
                          ...prev,
                          cachedlogos: event.target.checked,
                        }))
                      }
                    />
                    <Switch
                      label="Direct stream URLs"
                      description="Bypass the Dispatcharr proxy; client connects directly to the source"
                      size="sm"
                      checked={m3uParams.direct}
                      onChange={(event) =>
                        setM3uParams((prev) => ({
                          ...prev,
                          direct: event.target.checked,
                        }))
                      }
                    />
                    <Select
                      label="TVG-ID Source"
                      description="Value used as the tvg-id attribute in the M3U"
                      size="sm"
                      value={m3uParams.tvg_id_source}
                      onChange={(value) =>
                        setM3uParams((prev) => ({
                          ...prev,
                          tvg_id_source: value,
                        }))
                      }
                      comboboxProps={{ withinPortal: false }}
                      data={[
                        { value: 'channel_number', label: 'Channel Number' },
                        { value: 'tvg_id', label: 'TVG-ID' },
                        { value: 'gracenote', label: 'Gracenote Station ID' },
                      ]}
                    />
                    <Select
                      label="Output Format"
                      description="Container format for streams embedded in this M3U"
                      clearable
                      placeholder="Server default"
                      value={m3uParams.output_format || null}
                      onChange={(value) =>
                        setM3uParams((prev) => ({
                          ...prev,
                          output_format: value || '',
                        }))
                      }
                      comboboxProps={{ withinPortal: false }}
                      data={[
                        { value: 'mpegts', label: 'MPEG-TS' },
                        { value: 'fmp4', label: 'fMP4 (fragmented MP4)' },
                      ]}
                    />
                    <Select
                      label="Output Profile"
                      description="Pre-delivery transcode profile applied to all streams in this M3U"
                      clearable
                      searchable
                      placeholder="No transcoding"
                      value={m3uParams.output_profile || null}
                      onChange={(value) =>
                        setM3uParams((prev) => ({
                          ...prev,
                          output_profile: value || '',
                        }))
                      }
                      comboboxProps={{ withinPortal: false }}
                      data={outputProfiles
                        .filter((p) => p.is_active)
                        .map((p) => ({ value: `${p.id}`, label: p.name }))}
                    />
                  </Stack>
                </PopoverDropdown>
              </Popover>
              <Popover
                withArrow
                shadow="md"
                zIndex={1000}
                position="bottom-start"
                withinPortal
              >
                <PopoverTarget>
                  <Button
                    leftSection={<Scroll size={18} />}
                    size="compact-sm"
                    p={5}
                    variant="subtle"
                    color="gray.5"
                    style={{
                      borderColor: theme.palette.custom.greyBorder,
                      color: theme.palette.custom.greyBorder,
                    }}
                  >
                    EPG
                  </Button>
                </PopoverTarget>
                <PopoverDropdown>
                  <Stack
                    gap="sm"
                    style={{
                      minWidth: 300,
                      maxWidth: 'min(450px, 85vw)',
                      width: 'max-content',
                    }}
                    onClick={stopPropagation}
                    onMouseDown={stopPropagation}
                  >
                    <Text size="sm" c="dimmed">
                      Use this URL in your IPTV app for program guide data.
                      Per-user defaults for days forward/back can be set in
                      account settings, which apply automatically for XC
                      clients.
                    </Text>
                    <TextInput
                      value={buildEPGUrl(epgParams, epgUrl)}
                      size="sm"
                      readOnly
                      label="Generated URL"
                      rightSection={
                        <ActionIcon
                          onClick={copyEPGUrl}
                          size="sm"
                          variant="transparent"
                          color="gray.5"
                        >
                          <Copy size="16" />
                        </ActionIcon>
                      }
                    />
                    <Switch
                      label="Use cached logos"
                      description="Proxy channel logos through Dispatcharr"
                      size="sm"
                      checked={epgParams.cachedlogos}
                      onChange={(event) =>
                        setEpgParams((prev) => ({
                          ...prev,
                          cachedlogos: event.target.checked,
                        }))
                      }
                    />
                    <Select
                      label="TVG-ID Source"
                      description="Value used to match EPG channels to M3U streams"
                      size="sm"
                      value={epgParams.tvg_id_source}
                      onChange={(value) =>
                        setEpgParams((prev) => ({
                          ...prev,
                          tvg_id_source: value,
                        }))
                      }
                      comboboxProps={{ withinPortal: false }}
                      data={[
                        { value: 'channel_number', label: 'Channel Number' },
                        { value: 'tvg_id', label: 'TVG-ID' },
                        { value: 'gracenote', label: 'Gracenote Station ID' },
                      ]}
                    />
                    <NumberInput
                      label="Days forward (0 = all)"
                      description="Limit EPG to this many future days; 0 returns all available data"
                      size="sm"
                      min={0}
                      max={365}
                      value={epgParams.days}
                      onChange={(value) =>
                        setEpgParams((prev) => ({
                          ...prev,
                          days: value || 0,
                        }))
                      }
                    />
                    <NumberInput
                      label="Days back (0 = none)"
                      description="Include this many past days of EPG data (max 30)"
                      size="sm"
                      min={0}
                      max={30}
                      value={epgParams.prev_days}
                      onChange={(value) =>
                        setEpgParams((prev) => ({
                          ...prev,
                          prev_days: value || 0,
                        }))
                      }
                    />
                  </Stack>
                </PopoverDropdown>
              </Popover>
            </Group>
          </Flex>
        </Flex>

        {/* Paper container: contains top toolbar and table (or ghost state) */}
        <Paper
          style={{
            display: 'flex',
            flexDirection: 'column',
            height: 'calc(100vh - 60px)',
            backgroundColor: '#27272A',
          }}
        >
          <ChannelTableHeader
            rows={rows}
            editChannel={editChannel}
            deleteChannels={handleDeleteChannels}
            selectedTableIds={table.selectedTableIds}
            table={table}
            showDisabled={showDisabled}
            setShowDisabled={setShowDisabled}
            showOnlyStreamlessChannels={showOnlyStreamlessChannels}
            setShowOnlyStreamlessChannels={setShowOnlyStreamlessChannels}
            showOnlyStaleChannels={showOnlyStaleChannels}
            setShowOnlyStaleChannels={setShowOnlyStaleChannels}
            showOnlyOverriddenChannels={showOnlyOverriddenChannels}
            setShowOnlyOverriddenChannels={setShowOnlyOverriddenChannels}
            showOnlyCatchupChannels={showOnlyCatchupChannels}
            setShowOnlyCatchupChannels={setShowOnlyCatchupChannels}
            visibilityFilter={visibilityFilter}
            setVisibilityFilter={setVisibilityFilter}
          />

          {/* Table or ghost empty state inside Paper */}
          <Box>
            {channelsTableLength === 0 && !hasChannels && (
              <ChannelsTableOnboarding editChannel={editChannel} />
            )}
          </Box>

          {(channelsTableLength > 0 || hasChannels) && (
            <Box
              style={{
                display: 'flex',
                flexDirection: 'column',
                height: 'calc(100vh - 100px)',
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
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleDragEnd}
                >
                  <SortableContext
                    items={rows.map((row) => row.id)}
                    strategy={verticalListSortingStrategy}
                  >
                    <CustomTable table={table} />
                  </SortableContext>
                </DndContext>
              </Box>

              <Box
                style={{
                  position: 'sticky',
                  bottom: 0,
                  zIndex: 3,
                  backgroundColor: '#27272A',
                }}
              >
                <Group
                  gap={5}
                  justify="center"
                  style={{
                    padding: 8,
                    borderTop: '1px solid #666',
                  }}
                >
                  <Text size="xs">Page Size</Text>
                  <NativeSelect
                    size="xxs"
                    value={pagination.pageSize}
                    data={['25', '50', '100', '250']}
                    onChange={onPageSizeChange}
                    style={{ paddingRight: 20 }}
                  />
                  <Pagination
                    total={pageCount}
                    value={pagination.pageIndex + 1}
                    onChange={onPageIndexChange}
                    size="xs"
                    withEdges
                    style={{ paddingRight: 20 }}
                  />
                  <Text size="xs">{paginationString}</Text>
                </Group>
              </Box>
            </Box>
          )}
        </Paper>

        <ChannelForm
          channel={channel}
          isOpen={channelModalOpen}
          onClose={closeChannelForm}
        />

        <ChannelBatchForm
          channelIds={table.selectedTableIds}
          isOpen={channelBatchModalOpen}
          onClose={closeChannelBatchForm}
        />

        <RecordingForm
          channel={channel}
          isOpen={recordingModalOpen}
          onClose={closeRecordingForm}
        />
      </Box>

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() =>
          isBulkDelete
            ? executeDeleteChannels()
            : executeDeleteChannel(deleteTarget)
        }
        loading={deleting}
        title={`Confirm ${isBulkDelete ? 'Bulk ' : ''}Channel Deletion`}
        message={
          isBulkDelete ? (
            `Are you sure you want to delete ${table.selectedTableIds.length} channels? This action cannot be undone.`
          ) : channelToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following channel?

Name: ${channelToDelete.name}
Channel Number: ${channelToDelete.channel_number}

This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this channel? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey={isBulkDelete ? 'delete-channels' : 'delete-channel'}
        onSuppressChange={suppressWarning}
        size="md"
      />
    </>
  );
};

export default ChannelsTable;
