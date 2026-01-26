import React, {
  useEffect,
  useMemo,
  useState,
  useCallback,
  useRef,
} from 'react';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import useChannelsStore from '../../store/channels';
import { notifications } from '@mantine/notifications';
import API from '../../api';
import ChannelForm from '../forms/Channel';
import ChannelBatchForm from '../forms/ChannelBatch';
import RecordingForm from '../forms/Recording';
import { useDebounce, copyToClipboard } from '../../utils';
import logo from '../../images/logo.png';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';
import {
  Tv2,
  ScreenShare,
  Scroll,
  SquareMinus,
  CirclePlay,
  SquarePen,
  Copy,
  ScanEye,
  EllipsisVertical,
  ArrowUpNarrowWide,
  ArrowUpDown,
  ArrowDownWideNarrow,
  Search,
} from 'lucide-react';
import {
  Box,
  TextInput,
  Popover,
  ActionIcon,
  Button,
  Paper,
  Flex,
  Text,
  Group,
  useMantineTheme,
  Center,
  Switch,
  Menu,
  MultiSelect,
  Pagination,
  NativeSelect,
  UnstyledButton,
  Stack,
  Select,
  NumberInput,
  Tooltip,
  Skeleton,
} from '@mantine/core';
import { getCoreRowModel, flexRender } from '@tanstack/react-table';
import './table.css';
import useChannelsTableStore from '../../store/channelsTable';
import ChannelTableStreams from './ChannelTableStreams';
import LazyLogo from '../LazyLogo';
import useLocalStorage from '../../hooks/useLocalStorage';
import useEPGsStore from '../../store/epgs';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import { CustomTable, useTable } from './CustomTable';
import ChannelsTableOnboarding from './ChannelsTable/ChannelsTableOnboarding';
import ChannelTableHeader from './ChannelsTable/ChannelTableHeader';
import {
  EditableTextCell,
  EditableNumberCell,
  EditableGroupCell,
  EditableEPGCell,
  EditableLogoCell,
} from './ChannelsTable/EditableCell';
import { DraggableRow } from './ChannelsTable/DraggableRow';
import useWarningsStore from '../../store/warnings';
import ConfirmationDialog from '../ConfirmationDialog';
import useAuthStore from '../../store/auth';
import { USER_LEVELS } from '../../constants';

const m3uUrlBase = `${window.location.protocol}//${window.location.host}/output/m3u`;
const epgUrlBase = `${window.location.protocol}//${window.location.host}/output/epg`;
const hdhrUrlBase = `${window.location.protocol}//${window.location.host}/hdhr`;

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
        API.updateProfileChannels(
          selectedTableIds,
          selectedProfileId,
          !isEnabled
        );
      } else {
        API.updateProfileChannel(rowId, selectedProfileId, !isEnabled);
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
            <Menu.Target>
              <ActionIcon variant="transparent" size={iconSize}>
                <EllipsisVertical size="18" />
              </ActionIcon>
            </Menu.Target>

            <Menu.Dropdown>
              <Menu.Item leftSection={<Copy size="14" />}>
                <UnstyledButton
                  size="xs"
                  onClick={() => copyToClipboard(getChannelURL(row.original))}
                >
                  <Text size="xs">Copy URL</Text>
                </UnstyledButton>
              </Menu.Item>
              <Menu.Item
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
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Center>
      </Box>
    );
  }
);

const ChannelsTable = ({ onReady }) => {
  // EPG data lookup
  const tvgsById = useEPGsStore((s) => s.tvgsById);
  const epgs = useEPGsStore((s) => s.epgs);
  const tvgsLoaded = useEPGsStore((s) => s.tvgsLoaded);

  // Get channel logos for logo selection
  const { ensureLogosLoaded } = useChannelLogoSelection();

  const theme = useMantineTheme();
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const canEditChannelGroup = useChannelsStore((s) => s.canEditChannelGroup);
  const canDeleteChannelGroup = useChannelsStore(
    (s) => s.canDeleteChannelGroup
  );
  const hasSignaledReady = useRef(false);

  /**
   * STORES
   */

  // store/channelsTable
  const data = useChannelsTableStore((s) => s.channels);
  const pageCount = useChannelsTableStore((s) => s.pageCount);
  const setSelectedChannelIds = useChannelsTableStore(
    (s) => s.setSelectedChannelIds
  );
  const selectedChannelIds = useChannelsTableStore((s) => s.selectedChannelIds);
  const pagination = useChannelsTableStore((s) => s.pagination);
  const setPagination = useChannelsTableStore((s) => s.setPagination);
  const sorting = useChannelsTableStore((s) => s.sorting);
  const setSorting = useChannelsTableStore((s) => s.setSorting);
  const totalCount = useChannelsTableStore((s) => s.totalCount);
  const setChannelStreams = useChannelsTableStore((s) => s.setChannelStreams);
  const allRowIds = useChannelsTableStore((s) => s.allQueryIds);
  const setAllRowIds = useChannelsTableStore((s) => s.setAllQueryIds);
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);

  // store/channels
  const channels = useChannelsStore((s) => s.channels);
  const profiles = useChannelsStore((s) => s.profiles);
  const selectedProfileId = useChannelsStore((s) => s.selectedProfileId);
  const [tablePrefs, setTablePrefs] = useLocalStorage('channel-table-prefs', {
    pageSize: 50,
  });
  const selectedProfileChannels = useChannelsStore(
    (s) => s.profiles[selectedProfileId]?.channels
  );

  // store/settings
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);

  // store/warnings
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  /**
   * useMemo
   */
  const selectedProfileChannelIds = useMemo(
    () => new Set(selectedProfileChannels),
    [selectedProfileChannels]
  );

  /**
   * useState
   */
  const [channel, setChannel] = useState(null);
  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [channelBatchModalOpen, setChannelBatchModalOpen] = useState(false);
  const [recordingModalOpen, setRecordingModalOpen] = useState(false);
  const [selectedProfile, setSelectedProfile] = useState(
    profiles[selectedProfileId]
  );
  const [showDisabled, setShowDisabled] = useState(true);
  const [showOnlyStreamlessChannels, setShowOnlyStreamlessChannels] =
    useState(false);

  const [paginationString, setPaginationString] = useState('');
  const [filters, setFilters] = useState({
    name: '',
    channel_group: '',
    epg: '',
  });
  const [isLoading, setIsLoading] = useState(true);

  const [hdhrUrl, setHDHRUrl] = useState(hdhrUrlBase);
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
  });
  const [epgParams, setEpgParams] = useState({
    cachedlogos: true,
    tvg_id_source: 'channel_number',
    days: 0,
  });

  /**
   * Derived variables
   */
  const activeGroupIds = new Set(
    Object.values(channels).map((channel) => channel.channel_group_id)
  );
  const groupOptions = Object.values(channelGroups)
    .filter((group) => activeGroupIds.has(group.id))
    .map((group) => group.name);

  // Get unique EPG sources from active channels
  const activeEPGSources = new Set();
  let hasUnlinkedChannels = false;
  Object.values(channels).forEach((channel) => {
    if (channel.epg_data_id) {
      const epgObj = tvgsById[channel.epg_data_id];
      if (epgObj && epgObj.epg_source) {
        const epgName = epgs[epgObj.epg_source]?.name || epgObj.epg_source;
        activeEPGSources.add(epgName);
      }
    } else {
      hasUnlinkedChannels = true;
    }
  });
  const epgOptions = Array.from(activeEPGSources).sort();
  if (hasUnlinkedChannels) {
    epgOptions.unshift('No EPG');
  }
  // Map for MultiSelect: value 'null' for 'No EPG', label for display
  const epgSelectOptions = epgOptions.map((opt) =>
    opt === 'No EPG'
      ? { value: 'null', label: 'No EPG' }
      : { value: opt, label: opt }
  );
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
  const fetchData = useCallback(async () => {
    // Build params first to check for duplicates
    const params = new URLSearchParams();
    params.append('page', pagination.pageIndex + 1);
    params.append('page_size', pagination.pageSize);
    params.append('include_streams', 'true');
    if (selectedProfileId !== '0') {
      params.append('channel_profile_id', selectedProfileId);
    }
    if (showDisabled === true) {
      params.append('show_disabled', true);
    }
    if (showOnlyStreamlessChannels === true) {
      params.append('only_streamless', true);
    }

    // Apply sorting
    if (sorting.length > 0) {
      const sortField = sorting[0].id;
      const sortDirection = sorting[0].desc ? '-' : '';
      params.append('ordering', `${sortDirection}${sortField}`);
    }

    // Apply debounced filters
    Object.entries(debouncedFilters).forEach(([key, value]) => {
      if (value) {
        if (Array.isArray(value)) {
          // Convert null values to "null" string for URL parameter
          const processedValue = value
            .map((v) => (v === null ? 'null' : v))
            .join(',');
          params.append(key, processedValue);
        } else {
          params.append(key, value);
        }
      }
    });

    const paramsString = params.toString();

    // Skip if same fetch is already in progress (prevents StrictMode double-fetch)
    if (
      fetchInProgressRef.current &&
      lastFetchParamsRef.current === paramsString
    ) {
      return;
    }

    // Increment fetch version to track this specific fetch request
    const currentFetchVersion = ++fetchVersionRef.current;
    lastFetchParamsRef.current = paramsString;
    fetchInProgressRef.current = true;

    setIsLoading(true);

    try {
      const [results, ids] = await Promise.all([
        API.queryChannels(params),
        API.getAllChannelIds(params),
      ]);

      fetchInProgressRef.current = false;

      // Skip state updates if a newer fetch has been initiated
      if (currentFetchVersion !== fetchVersionRef.current) {
        return;
      }

      setIsLoading(false);
      hasFetchedData.current = true;

      setTablePrefs((prev) => ({
        ...prev,
        pageSize: pagination.pageSize,
      }));
      setAllRowIds(ids);

      // Signal ready after first successful data fetch AND EPG data is loaded
      // This prevents the EPG column from showing "Not Assigned" while EPG data is still loading
      if (!hasSignaledReady.current && onReady && tvgsLoaded) {
        hasSignaledReady.current = true;
        onReady();
      }
    } catch (error) {
      fetchInProgressRef.current = false;

      // Skip state updates if a newer fetch has been initiated
      if (currentFetchVersion !== fetchVersionRef.current) {
        return;
      }
      setIsLoading(false);
      // API layer handles "Invalid page" errors by resetting and retrying
      // Just re-throw to show notification for actual errors
      throw error;
    }
  }, [
    pagination,
    sorting,
    debouncedFilters,
    showDisabled,
    selectedProfileId,
    showOnlyStreamlessChannels,
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

  const editChannel = async (ch = null, opts = {}) => {
    // If forceAdd is set, always open a blank form
    if (opts.forceAdd) {
      setChannel(null);
      setChannelModalOpen(true);
      return;
    }
    // Use table's selected state instead of store state to avoid stale selections
    const currentSelection = table ? table.selectedTableIds : [];
    console.log('editChannel called with:', {
      ch,
      currentSelection,
      tableExists: !!table,
    });

    if (currentSelection.length > 1) {
      setChannelBatchModalOpen(true);
    } else {
      // If no channel object is passed but we have a selection, get the selected channel
      let channelToEdit = ch;
      if (!channelToEdit && currentSelection.length === 1) {
        const selectedId = currentSelection[0];

        // Use table data since that's what's currently displayed
        channelToEdit = data.find((d) => d.id === selectedId);
      }
      setChannel(channelToEdit);
      setChannelModalOpen(true);
    }
  };

  const deleteChannel = async (id) => {
    console.log(`Deleting channel with ID: ${id}`);
    table.setSelectedTableIds([]);

    if (selectedChannelIds.length > 0) {
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
    setChannelToDelete(channels[id]); // Store the channel object for displaying details

    if (isWarningSuppressed('delete-channel')) {
      // Skip warning if suppressed
      return executeDeleteChannel(id);
    }

    setConfirmDeleteOpen(true);
  };

  const executeDeleteChannel = async (id) => {
    setDeleting(true);
    try {
      await API.deleteChannel(id);
      API.requeryChannels();
    } finally {
      setDeleting(false);
      setConfirmDeleteOpen(false);
    }
  };

  const deleteChannels = async () => {
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
      await API.deleteChannels(table.selectedTableIds);
      await API.requeryChannels();
      setSelectedChannelIds([]);
      table.setSelectedTableIds([]);
    } finally {
      setDeleting(false);
      setIsLoading(false);
      setConfirmDeleteOpen(false);
    }
  };

  const createRecording = (channel) => {
    console.log(`Recording channel ID: ${channel.id}`);
    setChannel(channel);
    setRecordingModalOpen(true);
  };

  const getChannelURL = (channel) => {
    // Make sure we're using the channel UUID consistently
    if (!channel || !channel.uuid) {
      console.error('Invalid channel object or missing UUID:', channel);
      return '';
    }

    const uri = `/proxy/ts/stream/${channel.uuid}`;
    let channelUrl = `${window.location.protocol}//${window.location.host}${uri}`;
    if (env_mode == 'dev') {
      channelUrl = `${window.location.protocol}//${window.location.hostname}:5656${uri}`;
    }

    return channelUrl;
  };

  const handleWatchStream = (channel) => {
    // Add additional logging to help debug issues
    console.log(
      `Watching stream for channel: ${channel.name} (${channel.id}), UUID: ${channel.uuid}`
    );
    const url = getChannelURL(channel);
    console.log(`Stream URL: ${url}`);
    showVideo(url);
  };

  const onRowSelectionChange = (newSelection) => {
    setSelectedChannelIds(newSelection);
  };

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

  const handleCopy = async (textToCopy, ref) => {
    const success = await copyToClipboard(textToCopy);
    notifications.show({
      title: success ? 'Copied!' : 'Copy Failed',
      message: success ? undefined : 'Failed to copy to clipboard',
      color: success ? 'green' : 'red',
    });
  };
  // Build URLs with parameters
  const buildM3UUrl = () => {
    const params = new URLSearchParams();
    if (!m3uParams.cachedlogos) params.append('cachedlogos', 'false');
    if (m3uParams.direct) params.append('direct', 'true');
    if (m3uParams.tvg_id_source !== 'channel_number')
      params.append('tvg_id_source', m3uParams.tvg_id_source);

    const baseUrl = m3uUrl;
    return params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
  };

  const buildEPGUrl = () => {
    const params = new URLSearchParams();
    if (!epgParams.cachedlogos) params.append('cachedlogos', 'false');
    if (epgParams.tvg_id_source !== 'channel_number')
      params.append('tvg_id_source', epgParams.tvg_id_source);
    if (epgParams.days > 0) params.append('days', epgParams.days.toString());

    const baseUrl = epgUrl;
    return params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
  };
  // Example copy URLs
  const copyM3UUrl = async () => {
    const success = await copyToClipboard(buildM3UUrl());
    notifications.show({
      title: success ? 'M3U URL Copied!' : 'Copy Failed',
      message: success
        ? 'The M3U URL has been copied to your clipboard.'
        : 'Failed to copy M3U URL to clipboard',
      color: success ? 'green' : 'red',
    });
  };

  const copyEPGUrl = async () => {
    const success = await copyToClipboard(buildEPGUrl());
    notifications.show({
      title: success ? 'EPG URL Copied!' : 'Copy Failed',
      message: success
        ? 'The EPG URL has been copied to your clipboard.'
        : 'Failed to copy EPG URL to clipboard',
      color: success ? 'green' : 'red',
    });
  };

  const copyHDHRUrl = async () => {
    const success = await copyToClipboard(hdhrUrl);
    notifications.show({
      title: success ? 'HDHR URL Copied!' : 'Copy Failed',
      message: success
        ? 'The HDHR URL has been copied to your clipboard.'
        : 'Failed to copy HDHR URL to clipboard',
      color: success ? 'green' : 'red',
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
      await API.reorderChannel(
        activeChannel.id,
        overIndex > activeIndex
          ? overChannel.id
          : rows[overIndex - 1]?.original.id || null
      );

      // Refetch to get updated channel numbers
      await API.requeryChannels();
    } catch (error) {
      // Revert on error
      console.error('Failed to reorder channel:', error);
      await API.requeryChannels();
    }
  };

  /**
   * useEffect
   */
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    setSelectedProfile(profiles[selectedProfileId]);

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
        accessorKey: 'channel_number',
        size: columnSizing.channel_number || 40,
        minSize: 30,
        maxSize: 100,
        cell: (props) => <EditableNumberCell {...props} />,
      },
      {
        id: 'name',
        accessorKey: 'name',
        size: columnSizing.name || 200,
        minSize: 100,
        grow: true,
        cell: (props) => <EditableTextCell {...props} />,
      },
      {
        id: 'epg',
        header: 'EPG',
        accessorKey: 'epg_data_id',
        cell: (props) => (
          <EditableEPGCell
            {...props}
            tvgsById={tvgsById}
            epgs={epgs}
            tvgsLoaded={tvgsLoaded}
          />
        ),
        size: columnSizing.epg || 200,
        minSize: 80,
      },
      {
        id: 'channel_group',
        accessorFn: (row) =>
          channelGroups[row.channel_group_id]
            ? channelGroups[row.channel_group_id].name
            : '',
        cell: (props) => (
          <EditableGroupCell {...props} channelGroups={channelGroups} />
        ),
        size: columnSizing.channel_group || 175,
        minSize: 100,
      },
      {
        id: 'logo',
        accessorFn: (row) => {
          // Just pass the logo_id directly, not the full logo object
          return row.logo_id;
        },
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
            deleteChannel={deleteChannel}
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
    [selectedProfileId, channelGroups, theme, tvgsById, epgs]
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
          <Flex gap={2}>
            #
            <Center>
              {React.createElement(sortingIcon, {
                onClick: () => onSortingChange('channel_number'),
                size: 14,
              })}
            </Center>
          </Flex>
        );

      case 'name':
        return (
          <Flex gap="sm">
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
            />
            <Center>
              {React.createElement(sortingIcon, {
                onClick: () => onSortingChange('name'),
                size: 14,
              })}
            </Center>
          </Flex>
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
          <ChannelTableStreams channel={row.original} isExpanded={true} />
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
      const hasStreams =
        row.original.streams && row.original.streams.length > 0;
      return hasStreams
        ? {} // Default style for channels with streams
        : {
            className: 'no-streams-row', // Add a class instead of background color
          };
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
                <Popover.Target>
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
                </Popover.Target>
                <Popover.Dropdown>
                  <Group
                    gap="sm"
                    style={{
                      minWidth: 250,
                      maxWidth: 'min(400px, 80vw)',
                      width: 'max-content',
                    }}
                  >
                    <TextInput value={hdhrUrl} size="small" readOnly />
                    <ActionIcon
                      onClick={copyHDHRUrl}
                      size="sm"
                      variant="transparent"
                      color="gray.5"
                    >
                      <Copy size="18" fontSize="small" />
                    </ActionIcon>
                  </Group>
                </Popover.Dropdown>
              </Popover>
              <Popover
                withArrow
                shadow="md"
                zIndex={1000}
                position="bottom-start"
                withinPortal
              >
                <Popover.Target>
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
                </Popover.Target>
                <Popover.Dropdown>
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
                    <TextInput
                      value={buildM3UUrl()}
                      size="xs"
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
                    <Group justify="space-between">
                      <Text size="sm">Use cached logos</Text>
                      <Switch
                        size="sm"
                        checked={m3uParams.cachedlogos}
                        onChange={(event) =>
                          setM3uParams((prev) => ({
                            ...prev,
                            cachedlogos: event.target.checked,
                          }))
                        }
                      />
                    </Group>
                    <Group justify="space-between">
                      <Text size="sm">Direct stream URLs</Text>
                      <Switch
                        size="sm"
                        checked={m3uParams.direct}
                        onChange={(event) =>
                          setM3uParams((prev) => ({
                            ...prev,
                            direct: event.target.checked,
                          }))
                        }
                      />
                    </Group>{' '}
                    <Select
                      label="TVG-ID Source"
                      size="xs"
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
                  </Stack>
                </Popover.Dropdown>
              </Popover>
              <Popover
                withArrow
                shadow="md"
                zIndex={1000}
                position="bottom-start"
                withinPortal
              >
                <Popover.Target>
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
                </Popover.Target>
                <Popover.Dropdown>
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
                    <TextInput
                      value={buildEPGUrl()}
                      size="xs"
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
                    <Group justify="space-between">
                      <Text size="sm">Use cached logos</Text>
                      <Switch
                        size="sm"
                        checked={epgParams.cachedlogos}
                        onChange={(event) =>
                          setEpgParams((prev) => ({
                            ...prev,
                            cachedlogos: event.target.checked,
                          }))
                        }
                      />
                    </Group>
                    <Select
                      label="TVG-ID Source"
                      size="xs"
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
                      label="Days (0 = all data)"
                      size="xs"
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
                  </Stack>
                </Popover.Dropdown>
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
            deleteChannels={deleteChannels}
            selectedTableIds={table.selectedTableIds}
            table={table}
            showDisabled={showDisabled}
            setShowDisabled={setShowDisabled}
            showOnlyStreamlessChannels={showOnlyStreamlessChannels}
            setShowOnlyStreamlessChannels={setShowOnlyStreamlessChannels}
          />

          {/* Table or ghost empty state inside Paper */}
          <Box>
            {channelsTableLength === 0 &&
              Object.keys(channels).length === 0 && (
                <ChannelsTableOnboarding editChannel={editChannel} />
              )}
          </Box>

          {(channelsTableLength > 0 || Object.keys(channels).length > 0) && (
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
          channelIds={selectedChannelIds}
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
