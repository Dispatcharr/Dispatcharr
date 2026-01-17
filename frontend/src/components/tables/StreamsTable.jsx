import React, {
  useEffect,
  useMemo,
  useCallback,
  useState,
  useRef,
} from 'react';
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
  Filter,
  Square,
  SquareCheck,
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
  Skeleton,
  Modal,
  NumberInput,
  Radio,
  LoadingOverlay,
} from '@mantine/core';
import { useNavigate } from 'react-router-dom';
import useSettingsStore from '../../store/settings';
import useVideoStore from '../../store/useVideoStore';
import useChannelsTableStore from '../../store/channelsTable';
import useWarningsStore from '../../store/warnings';
import { CustomTable, useTable } from './CustomTable';
import useLocalStorage from '../../hooks/useLocalStorage';
import ConfirmationDialog from '../ConfirmationDialog';
import CreateChannelModal from '../modals/CreateChannelModal';
import useStreamsTableStore from '../../store/streamsTable';

const StreamRowActions = ({
  theme,
  row,
  editStream,
  deleteStream,
  handleWatchStream,
  selectedChannelIds,
  createChannelFromStream,
  table,
}) => {
  const tableSize = table?.tableSize ?? 'default';
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

const StreamsTable = ({ onReady }) => {
  const theme = useMantineTheme();
  const hasSignaledReady = useRef(false);
  const hasFetchedOnce = useRef(false);

  /**
   * useState
   */
  const [stream, setStream] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [groupOptions, setGroupOptions] = useState([]);
  const [m3uOptions, setM3uOptions] = useState([]);
  const [initialDataCount, setInitialDataCount] = useState(null);

  const [paginationString, setPaginationString] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  // Channel creation modal state (bulk)
  const [channelNumberingModalOpen, setChannelNumberingModalOpen] =
    useState(false);
  const [numberingMode, setNumberingMode] = useState('provider'); // 'provider', 'auto', or 'custom'
  const [customStartNumber, setCustomStartNumber] = useState(1);
  const [rememberChoice, setRememberChoice] = useState(false);
  const [bulkSelectedProfileIds, setBulkSelectedProfileIds] = useState([]);

  // Channel creation modal state (single)
  const [singleChannelModalOpen, setSingleChannelModalOpen] = useState(false);
  const [singleChannelMode, setSingleChannelMode] = useState('provider'); // 'provider', 'auto', or 'specific'
  const [specificChannelNumber, setSpecificChannelNumber] = useState(1);
  const [rememberSingleChoice, setRememberSingleChoice] = useState(false);
  const [currentStreamForChannel, setCurrentStreamForChannel] = useState(null);
  const [singleSelectedProfileIds, setSingleSelectedProfileIds] = useState([]);

  // Confirmation dialog state
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [streamToDelete, setStreamToDelete] = useState(null);
  const [isBulkDelete, setIsBulkDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // const [allRowsSelected, setAllRowsSelected] = useState(false);

  // Add local storage for page size
  const [storedPageSize, setStoredPageSize] = useLocalStorage(
    'streams-page-size',
    50
  );
  const [filters, setFilters] = useState({
    name: '',
    channel_group: '',
    m3u_account: '',
    unassigned: '',
  });
  const [columnSizing, setColumnSizing] = useLocalStorage(
    'streams-table-column-sizing',
    {}
  );
  const debouncedFilters = useDebounce(filters, 500, () => {
    // Reset to first page whenever filters change to avoid "Invalid page" errors
    setPagination({
      ...pagination,
      pageIndex: 0,
    });
  });

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
  const channelProfiles = useChannelsStore((s) => s.profiles);
  const selectedProfileId = useChannelsStore((s) => s.selectedProfileId);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);

  const data = useStreamsTableStore((s) => s.streams);
  const pageCount = useStreamsTableStore((s) => s.pageCount);
  const totalCount = useStreamsTableStore((s) => s.totalCount);
  const allRowIds = useStreamsTableStore((s) => s.allQueryIds);
  const setAllRowIds = useStreamsTableStore((s) => s.setAllQueryIds);
  const pagination = useStreamsTableStore((s) => s.pagination);
  const setPagination = useStreamsTableStore((s) => s.setPagination);
  const sorting = useStreamsTableStore((s) => s.sorting);
  const setSorting = useStreamsTableStore((s) => s.setSorting);
  const selectedStreamIds = useStreamsTableStore((s) => s.selectedStreamIds);
  const setSelectedStreamIds = useStreamsTableStore(
    (s) => s.setSelectedStreamIds
  );

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
        size: columnSizing.actions || 75,
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
    [channelGroups, playlists, columnSizing]
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
      channel_group: value && value.length > 0 ? value.join(',') : '',
    }));
  };

  const handleM3UChange = (value) => {
    setFilters((prev) => ({
      ...prev,
      m3u_account: value && value.length > 0 ? value.join(',') : '',
    }));
  };

  const toggleUnassignedOnly = () => {
    setFilters((prev) => ({
      ...prev,
      unassigned: prev.unassigned === '1' ? '' : '1',
    }));
  };

  const fetchData = useCallback(
    async ({ showLoader = true } = {}) => {
      if (showLoader) {
        setIsLoading(true);
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
        const [result, ids, filterOptions] = await Promise.all([
          API.queryStreamsTable(params),
          API.getAllStreamIds(params),
          API.getStreamFilterOptions(params),
        ]);

        setAllRowIds(ids);

        // Set filtered options based on current filters
        setGroupOptions(filterOptions.groups);
        setM3uOptions(
          filterOptions.m3u_accounts.map((m3u) => ({
            label: m3u.name,
            value: `${m3u.id}`,
          }))
        );

        if (initialDataCount === null) {
          setInitialDataCount(result.count);
        }

        // Signal that initial data load is complete
        if (!hasSignaledReady.current && onReady) {
          hasSignaledReady.current = true;
          onReady();
        }
      } catch (error) {
        console.error('Error fetching data:', error);
      }

      hasFetchedOnce.current = true;
      if (showLoader) {
        setIsLoading(false);
      }
    },
    [pagination, sorting, debouncedFilters, onReady]
  );

  // Bulk creation: create channels from selected streams asynchronously
  const createChannelsFromStreams = async () => {
    if (selectedStreamIds.length === 0) return;

    // Set default profile selection based on current profile filter
    const defaultProfileIds =
      selectedProfileId === '0' ? ['all'] : [selectedProfileId];
    setBulkSelectedProfileIds(defaultProfileIds);

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

      await executeChannelCreation(
        startingChannelNumberValue,
        defaultProfileIds
      );
    } else {
      // Show the modal to let user choose
      setChannelNumberingModalOpen(true);
    }
  };

  // Separate function to actually execute the channel creation
  const executeChannelCreation = async (
    startingChannelNumberValue,
    profileIds = null
  ) => {
    try {
      // Convert profile selection: 'all' means all profiles (null), 'none' means no profiles ([]), specific IDs otherwise
      let channelProfileIds;
      if (profileIds) {
        if (profileIds.includes('none')) {
          channelProfileIds = [];
        } else if (profileIds.includes('all')) {
          channelProfileIds = null;
        } else {
          channelProfileIds = profileIds
            .filter((id) => id !== 'all' && id !== 'none')
            .map((id) => parseInt(id));
        }
      } else {
        channelProfileIds =
          selectedProfileId !== '0' ? [parseInt(selectedProfileId)] : null;
      }

      // Use the async API for all bulk operations
      const response = await API.createChannelsFromStreamsAsync(
        selectedStreamIds,
        channelProfileIds,
        startingChannelNumberValue
      );

      console.log(
        `Bulk creation task started: ${response.task_id} for ${response.stream_count} streams`
      );

      // Clear selection since the task has started
      setSelectedStreamIds([]);

      // Note: This is a background task, so the update happens on WebSocket completion
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
    await executeChannelCreation(
      startingChannelNumberValue,
      bulkSelectedProfileIds
    );
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
    setDeleting(true);
    setIsLoading(true);
    try {
      await API.deleteStream(id);
      // Clear the selection for the deleted stream
      setSelectedStreamIds([]);
      table.setSelectedTableIds([]);
    } finally {
      setDeleting(false);
      setIsLoading(false);
      setConfirmDeleteOpen(false);
    }
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
    setDeleting(true);
    setIsLoading(true);
    try {
      await API.deleteStreams(selectedStreamIds);
      setSelectedStreamIds([]);
      table.setSelectedTableIds([]);
    } finally {
      setDeleting(false);
      setIsLoading(false);
      setConfirmDeleteOpen(false);
    }
  };

  const closeStreamForm = async () => {
    setStream(null);
    setModalOpen(false);
    setIsLoading(true);
    try {
      await API.requeryStreams();
    } finally {
      setIsLoading(false);
    }
  };

  // Single channel creation functions
  const createChannelFromStream = async (stream) => {
    // Set default profile selection based on current profile filter
    const defaultProfileIds =
      selectedProfileId === '0' ? ['all'] : [selectedProfileId];
    setSingleSelectedProfileIds(defaultProfileIds);

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

      await executeSingleChannelCreation(
        stream,
        channelNumberValue,
        defaultProfileIds
      );
    } else {
      // Show the modal to let user choose
      setCurrentStreamForChannel(stream);
      setSingleChannelModalOpen(true);
    }
  };

  // Separate function to actually execute single channel creation
  const executeSingleChannelCreation = async (
    stream,
    channelNumber = null,
    profileIds = null
  ) => {
    // Convert profile selection: 'all' means all profiles (null), 'none' means no profiles ([]), specific IDs otherwise
    let channelProfileIds;
    if (profileIds) {
      if (profileIds.includes('none')) {
        channelProfileIds = [];
      } else if (profileIds.includes('all')) {
        channelProfileIds = null;
      } else {
        channelProfileIds = profileIds
          .filter((id) => id !== 'all' && id !== 'none')
          .map((id) => parseInt(id));
      }
    } else {
      channelProfileIds =
        selectedProfileId !== '0' ? [parseInt(selectedProfileId)] : null;
    }

    await API.createChannelFromStream({
      name: stream.name,
      channel_number: channelNumber,
      stream_id: stream.id,
      channel_profile_ids: channelProfileIds,
    });
    await API.requeryChannels();
    // const fetchLogos = useChannelsStore.getState().fetchLogos;
    // fetchLogos();
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
      channelNumberValue,
      singleSelectedProfileIds
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

      case 'group': {
        const selectedGroups = filters.channel_group
          ? filters.channel_group.split(',').filter(Boolean)
          : [];
        return (
          <MultiSelect
            placeholder="Group"
            searchable
            size="xs"
            nothingFoundMessage="No options"
            onClick={handleSelectClick}
            onChange={handleGroupChange}
            value={selectedGroups}
            data={groupOptions}
            variant="unstyled"
            className="table-input-header custom-multiselect"
            clearable
            valueComponent={({ value }) => {
              const index = selectedGroups.indexOf(value);
              if (index === 0) {
                return (
                  <Flex gap={4} align="center">
                    <Text
                      size="xs"
                      style={{
                        padding: '2px 6px',
                        backgroundColor: 'var(--mantine-color-dark-4)',
                        borderRadius: '4px',
                      }}
                    >
                      {value}
                    </Text>
                    {selectedGroups.length > 1 && (
                      <Text
                        size="xs"
                        style={{
                          padding: '2px 6px',
                          backgroundColor: 'var(--mantine-color-dark-4)',
                          borderRadius: '4px',
                        }}
                      >
                        +{selectedGroups.length - 1}
                      </Text>
                    )}
                  </Flex>
                );
              }
              return null;
            }}
            style={{ width: '100%' }}
          />
        );
      }

      case 'm3u': {
        const selectedM3Us = filters.m3u_account
          ? filters.m3u_account.split(',').filter(Boolean)
          : [];
        return (
          <Flex align="center" style={{ width: '100%', flex: 1 }}>
            <MultiSelect
              placeholder="M3U"
              searchable
              clearable
              size="xs"
              nothingFoundMessage="No options"
              onClick={handleSelectClick}
              onChange={handleM3UChange}
              value={selectedM3Us}
              data={m3uOptions}
              variant="unstyled"
              className="table-input-header custom-multiselect"
              valueComponent={({ value }) => {
                const index = selectedM3Us.indexOf(value);
                if (index === 0) {
                  const label =
                    m3uOptions.find((opt) => opt.value === value)?.label ||
                    value;
                  return (
                    <Flex gap={4} align="center">
                      <Text
                        size="xs"
                        style={{
                          padding: '2px 6px',
                          backgroundColor: 'var(--mantine-color-dark-4)',
                          borderRadius: '4px',
                        }}
                      >
                        {label}
                      </Text>
                      {selectedM3Us.length > 1 && (
                        <Text
                          size="xs"
                          style={{
                            padding: '2px 6px',
                            backgroundColor: 'var(--mantine-color-dark-4)',
                            borderRadius: '4px',
                          }}
                        >
                          +{selectedM3Us.length - 1}
                        </Text>
                      )}
                    </Flex>
                  );
                }
                return null;
              }}
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
    state: {
      pagination,
      sorting,
    },
    headerCellRenderFns: {
      name: renderHeaderCell,
      group: renderHeaderCell,
      m3u: renderHeaderCell,
    },
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    getRowStyles: (row) => {
      if (row.original.is_stale) {
        return {
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
        };
      }
      return {};
    },
  });

  /**
   * useEffects
   */
  useEffect(() => {
    // Load data independently, don't wait for logos or other data
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (Object.keys(channelGroups).length > 0) {
      return;
    }

    const loadGroups = async () => {
      try {
        await fetchChannelGroups();
      } catch (error) {
        console.error('Error fetching channel groups:', error);
      }
    };

    loadGroups();
  }, [channelGroups, fetchChannelGroups]);

  useEffect(() => {
    const startItem = pagination.pageIndex * pagination.pageSize + 1;
    const endItem = Math.min(
      (pagination.pageIndex + 1) * pagination.pageSize,
      totalCount
    );
    setPaginationString(`${startItem} to ${endItem} of ${totalCount}`);
  }, [pagination.pageIndex, pagination.pageSize, totalCount]);

  // Clear dependent filters if selected values are no longer in filtered options
  useEffect(() => {
    // Clear group filter if the selected groups are no longer available
    if (filters.channel_group) {
      const selectedGroups = filters.channel_group.split(',').filter(Boolean);
      const stillValid = selectedGroups.filter((group) =>
        groupOptions.includes(group)
      );

      if (stillValid.length !== selectedGroups.length) {
        setFilters((prev) => ({
          ...prev,
          channel_group: stillValid.join(','),
        }));
      }
    }

    // Clear M3U filter if the selected M3Us are no longer available
    if (filters.m3u_account) {
      const selectedIds = filters.m3u_account.split(',').filter(Boolean);
      const availableIds = m3uOptions.map((opt) => opt.value);
      const stillValid = selectedIds.filter((id) => availableIds.includes(id));

      if (stillValid.length !== selectedIds.length) {
        setFilters((prev) => ({
          ...prev,
          m3u_account: stillValid.join(','),
        }));
      }
    }
  }, [groupOptions, m3uOptions, filters.channel_group, filters.m3u_account]);

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
            <Menu shadow="md" width={200}>
              <Menu.Target>
                <Button size="xs" variant="default">
                  <Filter size={18} />
                </Button>
              </Menu.Target>

              <Menu.Dropdown>
                <Menu.Item
                  onClick={toggleUnassignedOnly}
                  leftSection={
                    filters.unassigned === '1' ? (
                      <SquareCheck size={18} />
                    ) : (
                      <Square size={18} />
                    )
                  }
                >
                  <Text size="xs">Only Unassociated</Text>
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>

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

      {/* Bulk Channel Creation Modal */}
      <CreateChannelModal
        opened={channelNumberingModalOpen}
        onClose={() => setChannelNumberingModalOpen(false)}
        mode={numberingMode}
        onModeChange={setNumberingMode}
        numberValue={customStartNumber}
        onNumberValueChange={setCustomStartNumber}
        rememberChoice={rememberChoice}
        onRememberChoiceChange={setRememberChoice}
        onConfirm={handleChannelNumberingConfirm}
        isBulk={true}
        streamCount={selectedStreamIds.length}
        selectedProfileIds={bulkSelectedProfileIds}
        onProfileIdsChange={setBulkSelectedProfileIds}
        channelProfiles={channelProfiles ? Object.values(channelProfiles) : []}
      />

      {/* Single Channel Creation Modal */}
      <CreateChannelModal
        opened={singleChannelModalOpen}
        onClose={() => setSingleChannelModalOpen(false)}
        mode={singleChannelMode}
        onModeChange={setSingleChannelMode}
        numberValue={specificChannelNumber}
        onNumberValueChange={setSpecificChannelNumber}
        rememberChoice={rememberSingleChoice}
        onRememberChoiceChange={setRememberSingleChoice}
        onConfirm={handleSingleChannelNumberingConfirm}
        isBulk={false}
        streamName={currentStreamForChannel?.name}
        selectedProfileIds={singleSelectedProfileIds}
        onProfileIdsChange={setSingleSelectedProfileIds}
        channelProfiles={channelProfiles ? Object.values(channelProfiles) : []}
      />

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
        loading={deleting}
        size="md"
      />
    </>
  );
};

export default StreamsTable;
