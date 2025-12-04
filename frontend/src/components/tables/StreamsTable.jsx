import React, { useEffect, useMemo, useCallback, useState } from 'react';
import API from '../../api';
import StreamForm from '../forms/Stream';
import usePlaylistsStore from '../../store/playlists';
import useChannelsStore from '../../store/channels';
import { copyToClipboard, useDebounce } from '../../utils';
import {
  SquarePlus,
  ListPlus,
  SquareMinus,
  EllipsisVertical,
  Copy,
  ArrowUpDown,
  ArrowUpNarrowWide,
  ArrowDownWideNarrow,
  Search,
} from 'lucide-react';
import {
  TextInput,
  ActionIcon,
  Select,
  Tooltip,
  Menu,
  Flex,
  Box,
  Text,
  Paper,
  Button,
  Card,
  Stack,
  Title,
  Divider,
  Center,
  Pagination,
  Group,
  NativeSelect,
  MultiSelect,
  useMantineTheme,
  UnstyledButton,
  LoadingOverlay,
  Skeleton,
  Modal,
  NumberInput,
  Radio,
  Checkbox,
} from '@mantine/core';
import { useNavigate } from 'react-router-dom';
import useSettingsStore from '../../store/settings';
import useVideoStore from '../../store/useVideoStore';
import useChannelsTableStore from '../../store/channelsTable';
import useWarningsStore from '../../store/warnings';
import { CustomTable, useTable } from './CustomTable';
import useLocalStorage from '../../hooks/useLocalStorage';
import ConfirmationDialog from '../ConfirmationDialog';

const StreamRowActions = ({
  theme,
  row,
  editStream,
  deleteStream,
  handleWatchStream,
  selectedChannelIds,
  createChannelFromStream,
}) => {
  const [tableSize, _] = useLocalStorage('table-size', 'default');
  const channelSelectionStreams = useChannelsTableStore(
    (state) =>
      state.channels.find((chan) => chan.id === selectedChannelIds[0])?.streams
  );

  const addStreamToChannel = async () => {
    await API.updateChannel({
      id: selectedChannelIds[0],
      streams: [
        ...new Set(
          channelSelectionStreams.map((s) => s.id).concat([row.original.id])
        ),
      ],
    });
    await API.requeryChannels();
  };

  const onEdit = useCallback(() => {
    editStream(row.original);
  }, [row.original, editStream]);

  const onDelete = useCallback(() => {
    deleteStream(row.original.id);
  }, [row.original.id, deleteStream]);

  const onPreview = useCallback(() => {
    console.log(
      'Previewing stream:',
      row.original.name,
      'ID:',
      row.original.id,
      'Hash:',
      row.original.stream_hash
    );
    handleWatchStream(row.original.stream_hash);
  }, [row.original, handleWatchStream]); // Add proper dependencies to ensure correct stream

  const iconSize =
    tableSize == 'default' ? 'sm' : tableSize == 'compact' ? 'xs' : 'md';

  return (
    <>
      <Tooltip label="Add to Channel">
        <ActionIcon
          size={iconSize}
          color={theme.tailwind.blue[6]}
          variant="transparent"
          onClick={addStreamToChannel}
          style={{ background: 'none' }}
          disabled={
            selectedChannelIds.length !== 1 ||
            (channelSelectionStreams &&
              channelSelectionStreams
                .map((s) => s.id)
                .includes(row.original.id))
          }
        >
          <ListPlus size="18" fontSize="small" />
        </ActionIcon>
      </Tooltip>

      <Tooltip label="Create New Channel">
        <ActionIcon
          size={iconSize}
          color={theme.tailwind.green[5]}
          variant="transparent"
          onClick={() => createChannelFromStream(row.original)}
        >
          <SquarePlus size="18" fontSize="small" />
        </ActionIcon>
      </Tooltip>

      <Menu>
        <Menu.Target>
          <ActionIcon variant="transparent" size={iconSize}>
            <EllipsisVertical size="18" />
          </ActionIcon>
        </Menu.Target>

        <Menu.Dropdown>
          <Menu.Item leftSection={<Copy size="14" />}>
            <UnstyledButton
              variant="unstyled"
              size="xs"
              onClick={() => copyToClipboard(row.original.url)}
            >
              <Text size="xs">Copy URL</Text>
            </UnstyledButton>
          </Menu.Item>
          <Menu.Item onClick={onEdit} disabled={!row.original.is_custom}>
            <Text size="xs">Edit</Text>
          </Menu.Item>
          <Menu.Item onClick={onDelete} disabled={!row.original.is_custom}>
            <Text size="xs">Delete Stream</Text>
          </Menu.Item>
          <Menu.Item onClick={onPreview}>
            <Text size="xs">Preview Stream</Text>
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </>
  );
};

const StreamsTable = () => {
  const theme = useMantineTheme();

  /**
   * useState
   */
  const [allRowIds, setAllRowIds] = useState([]);
  const [stream, setStream] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [groupOptions, setGroupOptions] = useState([]);
  const [initialDataCount, setInitialDataCount] = useState(null);

  const [data, setData] = useState([]); // Holds fetched data
  const [pageCount, setPageCount] = useState(0);
  const [paginationString, setPaginationString] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([{ id: 'name', desc: false }]);
  const [selectedStreamIds, setSelectedStreamIds] = useState([]);

  // Channel numbering modal state
  const [channelNumberingModalOpen, setChannelNumberingModalOpen] =
    useState(false);
  const [numberingMode, setNumberingMode] = useState('provider'); // 'provider', 'auto', or 'custom'
  const [customStartNumber, setCustomStartNumber] = useState(1);
  const [rememberChoice, setRememberChoice] = useState(false);

  // Single channel numbering modal state
  const [singleChannelModalOpen, setSingleChannelModalOpen] = useState(false);
  const [singleChannelMode, setSingleChannelMode] = useState('provider'); // 'provider', 'auto', or 'specific'
  const [specificChannelNumber, setSpecificChannelNumber] = useState(1);
  const [rememberSingleChoice, setRememberSingleChoice] = useState(false);
  const [currentStreamForChannel, setCurrentStreamForChannel] = useState(null);

  // Confirmation dialog state
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [streamToDelete, setStreamToDelete] = useState(null);
  const [isBulkDelete, setIsBulkDelete] = useState(false);

  // const [allRowsSelected, setAllRowsSelected] = useState(false);

  // Add local storage for page size
  const [storedPageSize, setStoredPageSize] = useLocalStorage(
    'streams-page-size',
    50
  );
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: storedPageSize,
  });
  const [filters, setFilters] = useState({
    name: '',
    channel_group: '',
    m3u_account: '',
  });
  const [columnSizing, setColumnSizing] = useLocalStorage(
    'streams-table-column-sizing',
    {}
  );
  const debouncedFilters = useDebounce(filters, 500, () => {
    // Reset to first page whenever filters change to avoid "Invalid page" errors
    setPagination((prev) => ({
      ...prev,
      pageIndex: 0,
    }));
  });

  // Add state to track if stream groups are loaded
  const [groupsLoaded, setGroupsLoaded] = useState(false);

  const navigate = useNavigate();

  /**
   * Stores
   */
  const playlists = usePlaylistsStore((s) => s.playlists);

  // Get direct access to channel groups without depending on other data
  const fetchChannelGroups = useChannelsStore((s) => s.fetchChannelGroups);
  const channelGroups = useChannelsStore((s) => s.channelGroups);

  const selectedChannelIds = useChannelsTableStore((s) => s.selectedChannelIds);
  const channelSelectionStreams = useChannelsTableStore(
    (state) =>
      state.channels.find((chan) => chan.id === selectedChannelIds[0])?.streams
  );
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);
  const [tableSize, _] = useLocalStorage('table-size', 'default');

  // Warnings store for "remember choice" functionality
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);

  const handleSelectClick = (e) => {
    e.stopPropagation();
    e.preventDefault();
  };

  /**
   * useMemo
   */
  const columns = useMemo(
    () => [
      {
        id: 'actions',
        size: columnSizing.actions || (tableSize == 'compact' ? 60 : 80),
      },
      {
        id: 'select',
        size: columnSizing.select || 30,
      },
      {
        header: 'Name',
        accessorKey: 'name',
        grow: true,
        size: columnSizing.name || 200,
        cell: ({ getValue }) => (
          <Tooltip label={getValue()} openDelay={500}>
            <Box
              style={{
                whiteSpace: 'pre',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {getValue()}
            </Box>
          </Tooltip>
        ),
      },
      {
        header: 'Group',
        id: 'group',
        accessorFn: (row) =>
          channelGroups[row.channel_group]
            ? channelGroups[row.channel_group].name
            : '',
        size: columnSizing.group || 150,
        cell: ({ getValue }) => (
          <Tooltip label={getValue()} openDelay={500}>
            <Box
              style={{
                whiteSpace: 'pre',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {getValue()}
            </Box>
          </Tooltip>
        ),
      },
      {
        header: 'M3U',
        id: 'm3u',
        size: columnSizing.m3u || 150,
        accessorFn: (row) =>
          playlists.find((playlist) => playlist.id === row.m3u_account)?.name,
        cell: ({ getValue }) => (
          <Tooltip label={getValue()} openDelay={500}>
            <Box
              style={{
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {getValue()}
            </Box>
          </Tooltip>
        ),
      },
    ],
    [channelGroups, playlists, columnSizing, tableSize]
  );

  /**
   * Functions
   */
  const handleFilterChange = (e) => {
    const { name, value } = e.target;
    setFilters((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleGroupChange = (value) => {
    setFilters((prev) => ({
      ...prev,
      channel_group: value ? value : '',
    }));
  };

  const handleM3UChange = (value) => {
    setFilters((prev) => ({
      ...prev,
      m3u_account: value ? value : '',
    }));
  };

  const fetchData = useCallback(async () => {
    setIsLoading(true);

    // Ensure we have channel groups first (if not already loaded)
    if (!groupsLoaded && Object.keys(channelGroups).length === 0) {
      try {
        await fetchChannelGroups();
        setGroupsLoaded(true);
      } catch (error) {
        console.error('Error fetching channel groups:', error);
      }
    }

    const params = new URLSearchParams();
    params.append('page', pagination.pageIndex + 1);
    params.append('page_size', pagination.pageSize);

    // Apply sorting
    if (sorting.length > 0) {
      const columnId = sorting[0].id;
      // Map frontend column IDs to backend field names
      const fieldMapping = {
        name: 'name',
        group: 'channel_group__name',
        m3u: 'm3u_account__name',
      };
      const sortField = fieldMapping[columnId] || columnId;
      const sortDirection = sorting[0].desc ? '-' : '';
      params.append('ordering', `${sortDirection}${sortField}`);
    }

    // Apply debounced filters
    Object.entries(debouncedFilters).forEach(([key, value]) => {
      if (value) params.append(key, value);
    });

    try {
      const [result, ids, groups] = await Promise.all([
        API.queryStreams(params),
        API.getAllStreamIds(params),
        API.getStreamGroups(),
      ]);

      setAllRowIds(ids);
      setData(result.results);
      setPageCount(Math.ceil(result.count / pagination.pageSize));
      setGroupOptions(groups);

      // Calculate the starting and ending item indexes
      const startItem = pagination.pageIndex * pagination.pageSize + 1; // +1 to start from 1, not 0
      const endItem = Math.min(
        (pagination.pageIndex + 1) * pagination.pageSize,
        result.count
      );

      if (initialDataCount === null) {
        setInitialDataCount(result.count);
      }

      // Generate the string
      setPaginationString(`${startItem} to ${endItem} of ${result.count}`);
    } catch (error) {
      console.error('Error fetching data:', error);
    }

    setIsLoading(false);
  }, [
    pagination,
    sorting,
    debouncedFilters,
    groupsLoaded,
    channelGroups,
    fetchChannelGroups,
  ]);

  // Bulk creation: create channels from selected streams asynchronously
  const createChannelsFromStreams = async () => {
    if (selectedStreamIds.length === 0) return;

    // Check if user has suppressed the channel numbering dialog
    const actionKey = 'channel-numbering-choice';
    if (isWarningSuppressed(actionKey)) {
      // Use the remembered settings or default to 'provider' mode
      const savedMode =
        localStorage.getItem('channel-numbering-mode') || 'provider';
      const savedStartNumber =
        localStorage.getItem('channel-numbering-start') || '1';

      const startingChannelNumberValue =
        savedMode === 'provider'
          ? null
          : savedMode === 'auto'
            ? 0
            : Number(savedStartNumber);

      await executeChannelCreation(startingChannelNumberValue);
    } else {
      // Show the modal to let user choose
      setChannelNumberingModalOpen(true);
    }
  };

  // Separate function to actually execute the channel creation
  const executeChannelCreation = async (startingChannelNumberValue) => {
    try {
      const selectedChannelProfileId =
        useChannelsStore.getState().selectedProfileId;

      // Use the async API for all bulk operations
      const response = await API.createChannelsFromStreamsAsync(
        selectedStreamIds,
        selectedChannelProfileId !== '0' ? [selectedChannelProfileId] : null,
        startingChannelNumberValue
      );

      console.log(
        `Bulk creation task started: ${response.task_id} for ${response.stream_count} streams`
      );

      // Clear selection since the task has started
      setSelectedStreamIds([]);
    } catch (error) {
      console.error('Error starting bulk channel creation:', error);
      // Error notifications will be handled by WebSocket
    }
  };

  // Handle confirming the channel numbering modal
  const handleChannelNumberingConfirm = async () => {
    // Save the choice if user wants to remember it
    if (rememberChoice) {
      suppressWarning('channel-numbering-choice');
      localStorage.setItem('channel-numbering-mode', numberingMode);
      if (numberingMode === 'custom') {
        localStorage.setItem(
          'channel-numbering-start',
          customStartNumber.toString()
        );
      }
    }

    // Convert mode to API value
    const startingChannelNumberValue =
      numberingMode === 'provider'
        ? null
        : numberingMode === 'auto'
          ? 0
          : Number(customStartNumber);

    setChannelNumberingModalOpen(false);
    await executeChannelCreation(startingChannelNumberValue);
  };

  const editStream = async (stream = null) => {
    setStream(stream);
    setModalOpen(true);
  };

  const deleteStream = async (id) => {
    // Get stream details for the confirmation dialog
    const streamObj = data.find((s) => s.id === id);
    setStreamToDelete(streamObj);
    setDeleteTarget(id);
    setIsBulkDelete(false);

    // Skip warning if it's been suppressed
    if (isWarningSuppressed('delete-stream')) {
      return executeDeleteStream(id);
    }

    setConfirmDeleteOpen(true);
  };

  const executeDeleteStream = async (id) => {
    await API.deleteStream(id);
    fetchData();
    // Clear the selection for the deleted stream
    setSelectedStreamIds([]);
    table.setSelectedTableIds([]);
    setConfirmDeleteOpen(false);
  };

  const deleteStreams = async () => {
    setIsBulkDelete(true);
    setStreamToDelete(null);

    // Skip warning if it's been suppressed
    if (isWarningSuppressed('delete-streams')) {
      return executeDeleteStreams();
    }

    setConfirmDeleteOpen(true);
  };

  const executeDeleteStreams = async () => {
    setIsLoading(true);
    await API.deleteStreams(selectedStreamIds);
    setIsLoading(false);
    fetchData();
    setSelectedStreamIds([]);
    table.setSelectedTableIds([]);
    setConfirmDeleteOpen(false);
  };

  const closeStreamForm = () => {
    setStream(null);
    setModalOpen(false);
    fetchData();
  };

  // Single channel creation functions
  const createChannelFromStream = async (stream) => {
    // Check if user has suppressed the single channel numbering dialog
    const actionKey = 'single-channel-numbering-choice';
    if (isWarningSuppressed(actionKey)) {
      // Use the remembered settings or default to 'provider' mode
      const savedMode =
        localStorage.getItem('single-channel-numbering-mode') || 'provider';
      const savedChannelNumber =
        localStorage.getItem('single-channel-numbering-specific') || '1';

      const channelNumberValue =
        savedMode === 'provider'
          ? null
          : savedMode === 'auto'
            ? 0
            : Number(savedChannelNumber);

      await executeSingleChannelCreation(stream, channelNumberValue);
    } else {
      // Show the modal to let user choose
      setCurrentStreamForChannel(stream);
      setSingleChannelModalOpen(true);
    }
  };

  // Separate function to actually execute single channel creation
  const executeSingleChannelCreation = async (stream, channelNumber = null) => {
    const selectedChannelProfileId =
      useChannelsStore.getState().selectedProfileId;

    await API.createChannelFromStream({
      name: stream.name,
      channel_number: channelNumber,
      stream_id: stream.id,
      // Only pass channel_profile_ids if a specific profile is selected (not "All")
      ...(selectedChannelProfileId !== '0' && {
        channel_profile_ids: selectedChannelProfileId,
      }),
    });
    await API.requeryChannels();
    const fetchLogos = useChannelsStore.getState().fetchLogos;
    fetchLogos();
  };

  // Handle confirming the single channel numbering modal
  const handleSingleChannelNumberingConfirm = async () => {
    // Save the choice if user wants to remember it
    if (rememberSingleChoice) {
      suppressWarning('single-channel-numbering-choice');
      localStorage.setItem('single-channel-numbering-mode', singleChannelMode);
      if (singleChannelMode === 'specific') {
        localStorage.setItem(
          'single-channel-numbering-specific',
          specificChannelNumber.toString()
        );
      }
    }

    // Convert mode to API value
    const channelNumberValue =
      singleChannelMode === 'provider'
        ? null
        : singleChannelMode === 'auto'
          ? 0
          : Number(specificChannelNumber);

    setSingleChannelModalOpen(false);
    await executeSingleChannelCreation(
      currentStreamForChannel,
      channelNumberValue
    );
  };

  const addStreamsToChannel = async () => {
    await API.updateChannel({
      id: selectedChannelIds[0],
      streams: [
        ...new Set(
          channelSelectionStreams.map((s) => s.id).concat(selectedStreamIds)
        ),
      ],
    });
    await API.requeryChannels();
  };

  const onRowSelectionChange = (updatedIds) => {
    setSelectedStreamIds(updatedIds);
  };

  const onPageSizeChange = (e) => {
    const newPageSize = parseInt(e.target.value);
    setStoredPageSize(newPageSize);
    setPagination({
      ...pagination,
      pageSize: newPageSize,
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

  function handleWatchStream(streamHash) {
    let vidUrl = `/proxy/ts/stream/${streamHash}`;
    if (env_mode == 'dev') {
      vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
    }
    showVideo(vidUrl);
  }

  const onSortingChange = (column) => {
    const sortField = sorting[0]?.id;
    const sortDirection = sorting[0]?.desc;

    if (sortField === column) {
      if (sortDirection === false) {
        setSorting([
          {
            id: column,
            desc: true,
          },
        ]);
      } else {
        // Reset to default sort (name ascending) instead of clearing
        setSorting([{ id: 'name', desc: false }]);
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
      case 'name':
        return (
          <Flex align="center" style={{ width: '100%', flex: 1 }}>
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
              style={{ flex: 1, minWidth: 0 }}
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
          </Flex>
        );

      case 'group':
        return (
          <Flex align="center" style={{ width: '100%', flex: 1 }}>
            <MultiSelect
              placeholder="Group"
              searchable
              size="xs"
              nothingFoundMessage="No options"
              onClick={handleSelectClick}
              onChange={handleGroupChange}
              data={groupOptions}
              variant="unstyled"
              className="table-input-header custom-multiselect"
              clearable
              style={{ flex: 1, minWidth: 0 }}
              rightSectionPointerEvents="auto"
              rightSection={React.createElement(sortingIcon, {
                onClick: (e) => {
                  e.stopPropagation();
                  onSortingChange('group');
                },
                size: 14,
                style: { cursor: 'pointer' },
              })}
            />
          </Flex>
        );

      case 'm3u':
        return (
          <Flex align="center" style={{ width: '100%', flex: 1 }}>
            <Select
              placeholder="M3U"
              searchable
              clearable
              size="xs"
              nothingFoundMessage="No options"
              onClick={handleSelectClick}
              onChange={handleM3UChange}
              data={playlists.map((playlist) => ({
                label: playlist.name,
                value: `${playlist.id}`,
              }))}
              variant="unstyled"
              className="table-input-header"
              style={{ flex: 1, minWidth: 0 }}
              rightSectionPointerEvents="auto"
              rightSection={React.createElement(sortingIcon, {
                onClick: (e) => {
                  e.stopPropagation();
                  onSortingChange('m3u');
                },
                size: 14,
                style: { cursor: 'pointer' },
              })}
            />
          </Flex>
        );
    }
  };

  const renderBodyCell = useCallback(
    ({ cell, row }) => {
      switch (cell.column.id) {
        case 'actions':
          return (
            <StreamRowActions
              theme={theme}
              row={row}
              editStream={editStream}
              deleteStream={deleteStream}
              handleWatchStream={handleWatchStream}
              selectedChannelIds={selectedChannelIds}
              createChannelFromStream={createChannelFromStream}
            />
          );
      }
    },
    [
      selectedChannelIds,
      channelSelectionStreams,
      theme,
      editStream,
      deleteStream,
      handleWatchStream,
    ]
  );

  const table = useTable({
    columns,
    data,
    allRowIds,
    filters,
    pagination,
    sorting,
    columnSizing,
    setColumnSizing,
    onRowSelectionChange: onRowSelectionChange,
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    enableRowSelection: true,
    headerCellRenderFns: {
      name: renderHeaderCell,
      group: renderHeaderCell,
      m3u: renderHeaderCell,
    },
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
  });

  /**
   * useEffects
   */
  useEffect(() => {
    // Load data independently, don't wait for logos or other data
    fetchData();
  }, [fetchData]);

  return (
    <>
      <Flex
        style={{ display: 'flex', alignItems: 'center', paddingBottom: 12 }}
        gap={15}
      >
        <Text
          w={88}
          h={24}
          style={{
            fontFamily: 'Inter, sans-serif',
            fontWeight: 500,
            fontSize: '20px',
            lineHeight: 1,
            letterSpacing: '-0.3px',
            // color: 'gray.6', // Adjust this to match MUI's theme.palette.text.secondary
            marginBottom: 0,
          }}
        >
          Streams
        </Text>
      </Flex>

      <Paper
        style={{
          height: 'calc(100vh - 60px)',
          backgroundColor: '#27272A',
        }}
      >
        {/* Top toolbar with Remove, Assign, Auto-match, and Add buttons */}
        <Flex
          justify="space-between"
          align="center"
          wrap="nowrap"
          style={{ padding: 10 }}
          gap={6}
        >
          <Flex gap={6} wrap="nowrap" style={{ flexShrink: 0 }}>
            <Button
              leftSection={<SquarePlus size={18} />}
              variant={
                selectedStreamIds.length > 0 && selectedChannelIds.length === 1
                  ? 'light'
                  : 'default'
              }
              size="xs"
              onClick={addStreamsToChannel}
              p={5}
              color={
                selectedStreamIds.length > 0 && selectedChannelIds.length === 1
                  ? theme.tailwind.green[5]
                  : undefined
              }
              style={
                selectedStreamIds.length > 0 && selectedChannelIds.length === 1
                  ? {
                      borderWidth: '1px',
                      borderColor: theme.tailwind.green[5],
                      color: 'white',
                    }
                  : undefined
              }
              disabled={
                !(
                  selectedStreamIds.length > 0 &&
                  selectedChannelIds.length === 1
                )
              }
            >
              Add Streams to Channel
            </Button>

            <Button
              leftSection={<SquarePlus size={18} />}
              variant="default"
              size="xs"
              onClick={createChannelsFromStreams}
              p={5}
              disabled={selectedStreamIds.length == 0}
            >
              {`Create Channels (${selectedStreamIds.length})`}
            </Button>
          </Flex>

          <Flex gap={6} wrap="nowrap" style={{ flexShrink: 0 }}>
            <Button
              leftSection={<SquarePlus size={18} />}
              variant="light"
              size="xs"
              onClick={() => editStream()}
              p={5}
              color={theme.tailwind.green[5]}
              style={{
                borderWidth: '1px',
                borderColor: theme.tailwind.green[5],
                color: 'white',
              }}
            >
              Create Stream
            </Button>

            <Button
              leftSection={<SquareMinus size={18} />}
              variant="default"
              size="xs"
              onClick={deleteStreams}
              disabled={selectedStreamIds.length == 0}
            >
              Remove
            </Button>
          </Flex>
        </Flex>

        {initialDataCount === 0 && (
          <Center style={{ paddingTop: 20 }}>
            <Card
              shadow="sm"
              padding="lg"
              radius="md"
              withBorder
              style={{
                backgroundColor: '#222',
                borderColor: '#444',
                textAlign: 'center',
                width: '400px',
              }}
            >
              <Stack align="center">
                <Title order={3} style={{ color: '#d4d4d8' }}>
                  Getting started
                </Title>
                <Text size="sm" color="dimmed">
                  In order to get started, add your M3U or start <br />
                  adding custom streams.
                </Text>
                <Button
                  variant="default"
                  radius="md"
                  size="md"
                  onClick={() => navigate('/sources')}
                  style={{
                    backgroundColor: '#444',
                    color: '#d4d4d8',
                    border: '1px solid #666',
                  }}
                >
                  Add M3U
                </Button>
                <Divider label="or" labelPosition="center" color="gray" />
                <Button
                  variant="default"
                  radius="md"
                  size="md"
                  onClick={() => editStream()}
                  style={{
                    backgroundColor: '#333',
                    color: '#d4d4d8',
                    border: '1px solid #666',
                  }}
                >
                  Add Individual Stream
                </Button>
              </Stack>
            </Card>
          </Center>
        )}
        {initialDataCount > 0 && (
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
              <LoadingOverlay visible={isLoading} />
              <CustomTable table={table} />
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
      <StreamForm
        stream={stream}
        isOpen={modalOpen}
        onClose={closeStreamForm}
      />

      {/* Channel Numbering Modal */}
      <Modal
        opened={channelNumberingModalOpen}
        onClose={() => setChannelNumberingModalOpen(false)}
        title="Channel Numbering Options"
        size="md"
        centered
      >
        <Stack spacing="md">
          <Text size="sm" c="dimmed">
            Choose how to assign channel numbers to the{' '}
            {selectedStreamIds.length} selected streams:
          </Text>

          <Radio.Group
            value={numberingMode}
            onChange={setNumberingMode}
            label="Numbering Mode"
          >
            <Stack mt="xs" spacing="xs">
              <Radio
                value="provider"
                label="Use Provider Numbers"
                description="Use tvg-chno or channel-number from stream metadata, auto-assign for conflicts"
              />
              <Radio
                value="auto"
                label="Auto-Assign Sequential"
                description="Start from the lowest available channel number and increment by 1"
              />
              <Radio
                value="custom"
                label="Start from Custom Number"
                description="Start sequential numbering from a specific channel number"
              />
            </Stack>
          </Radio.Group>

          {numberingMode === 'custom' && (
            <NumberInput
              label="Starting Channel Number"
              description="Channel numbers will be assigned starting from this number"
              value={customStartNumber}
              onChange={setCustomStartNumber}
              min={1}
              max={9999}
              placeholder="Enter starting number..."
            />
          )}

          <Checkbox
            checked={rememberChoice}
            onChange={(event) => setRememberChoice(event.currentTarget.checked)}
            label="Remember this choice and don't ask again"
          />

          <Group justify="flex-end" mt="md">
            <Button
              variant="default"
              onClick={() => setChannelNumberingModalOpen(false)}
            >
              Cancel
            </Button>
            <Button onClick={handleChannelNumberingConfirm}>
              Create Channels
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Single Channel Numbering Modal */}
      <Modal
        opened={singleChannelModalOpen}
        onClose={() => setSingleChannelModalOpen(false)}
        title="Channel Number Assignment"
        size="md"
        centered
      >
        <Stack spacing="md">
          <Text size="sm" c="dimmed">
            Choose how to assign the channel number for "
            {currentStreamForChannel?.name}":
          </Text>

          <Radio.Group
            value={singleChannelMode}
            onChange={setSingleChannelMode}
            label="Number Assignment"
          >
            <Stack mt="xs" spacing="xs">
              <Radio
                value="provider"
                label="Use Provider Number"
                description="Use tvg-chno or channel-number from stream metadata, auto-assign if not available"
              />
              <Radio
                value="auto"
                label="Auto-Assign Next Available"
                description="Automatically assign the next available channel number"
              />
              <Radio
                value="specific"
                label="Use Specific Number"
                description="Use a specific channel number"
              />
            </Stack>
          </Radio.Group>

          {singleChannelMode === 'specific' && (
            <NumberInput
              label="Channel Number"
              description="The specific channel number to assign"
              value={specificChannelNumber}
              onChange={setSpecificChannelNumber}
              min={1}
              max={9999}
              placeholder="Enter channel number..."
            />
          )}

          <Checkbox
            checked={rememberSingleChoice}
            onChange={(event) =>
              setRememberSingleChoice(event.currentTarget.checked)
            }
            label="Remember this choice and don't ask again"
          />

          <Group justify="flex-end" mt="md">
            <Button
              variant="default"
              onClick={() => setSingleChannelModalOpen(false)}
            >
              Cancel
            </Button>
            <Button onClick={handleSingleChannelNumberingConfirm}>
              Create Channel
            </Button>
          </Group>
        </Stack>
      </Modal>

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() =>
          isBulkDelete
            ? executeDeleteStreams()
            : executeDeleteStream(deleteTarget)
        }
        title={`Confirm ${isBulkDelete ? 'Bulk ' : ''}Stream Deletion`}
        message={
          isBulkDelete ? (
            `Are you sure you want to delete ${selectedStreamIds.length} stream${selectedStreamIds.length !== 1 ? 's' : ''}? This action cannot be undone.`
          ) : streamToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following stream?

Name: ${streamToDelete.name}
${streamToDelete.channel_group ? `Group: ${channelGroups[streamToDelete.channel_group]?.name || 'Unknown'}` : ''}
${streamToDelete.m3u_account ? `M3U Account: ${playlists.find((p) => p.id === streamToDelete.m3u_account)?.name || 'Unknown'}` : ''}

This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this stream? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey={isBulkDelete ? 'delete-streams' : 'delete-stream'}
        onSuppressChange={suppressWarning}
        size="md"
      />
    </>
  );
};

export default StreamsTable;
