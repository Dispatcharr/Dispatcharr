import { useEffect, useMemo, useCallback, useState, useRef } from 'react';
import { MantineReactTable, useMantineReactTable } from 'mantine-react-table';
import API from '../../api';
import {
  Delete as DeleteIcon,
  Edit as EditIcon,
  Add as AddIcon,
  MoreVert as MoreVertIcon,
  PlaylistAdd as PlaylistAddIcon,
} from '@mui/icons-material';
import { TableHelper } from '../../helpers';
import StreamForm from '../forms/Stream';
import usePlaylistsStore from '../../store/playlists';
import useChannelsStore from '../../store/channels';
import { useDebounce } from '../../utils';
import { SquarePlus, ListPlus } from 'lucide-react';
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
} from '@mantine/core';
import {
  IconArrowDown,
  IconArrowUp,
  IconDeviceDesktopSearch,
  IconSelector,
  IconSortAscendingNumbers,
  IconSquareMinus,
  IconSquarePlus,
} from '@tabler/icons-react';

const StreamsTable = ({}) => {
  /**
   * useState
   */
  const [rowSelection, setRowSelection] = useState([]);
  const [stream, setStream] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [moreActionsAnchorEl, setMoreActionsAnchorEl] = useState(null);
  const [groupOptions, setGroupOptions] = useState([]);
  const [m3uOptions, setM3uOptions] = useState([]);
  const [actionsOpenRow, setActionsOpenRow] = useState(null);

  const [data, setData] = useState([]); // Holds fetched data
  const [rowCount, setRowCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);
  const [selectedStreamIds, setSelectedStreamIds] = useState([]);
  const [unselectedStreamIds, setUnselectedStreamIds] = useState([]);
  // const [allRowsSelected, setAllRowsSelected] = useState(false);
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: 25,
  });
  const [filters, setFilters] = useState({
    name: '',
    group_name: '',
    m3u_account: '',
  });
  const debouncedFilters = useDebounce(filters, 500);

  /**
   * Stores
   */
  const { playlists } = usePlaylistsStore();
  const { channelsPageSelection } = useChannelsStore();
  const channelSelectionStreams = useChannelsStore(
    (state) => state.channels[state.channelsPageSelection[0]?.id]?.streams
  );

  const isMoreActionsOpen = Boolean(moreActionsAnchorEl);

  // Access the row virtualizer instance (optional)
  const rowVirtualizerInstanceRef = useRef(null);

  /**
   * useMemo
   */
  const columns = useMemo(
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        mantineTableHeadCellProps: {
          style: { textAlign: 'center' }, // Center-align the header
        },
        Header: ({ column }) => (
          <TextInput
            name="name"
            placeholder="Name"
            value={filters.name || ''}
            onClick={(e) => e.stopPropagation()}
            onChange={handleFilterChange}
            size="xs"
            margin="none"
          />
        ),
        Cell: ({ cell }) => (
          <div
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {cell.getValue()}
          </div>
        ),
      },
      {
        header: 'Group',
        accessorKey: 'group_name',
        size: 100,
        Header: ({ column }) => (
          <Select
            placeholder="Group"
            searchable
            size="xs"
            nothingFound="No options"
            onClick={(e) => e.stopPropagation()}
            onChange={handleGroupChange}
            data={groupOptions}
          />
        ),
        Cell: ({ cell }) => (
          <div
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {cell.getValue()}
          </div>
        ),
      },
      {
        header: 'M3U',
        size: 75,
        accessorFn: (row) =>
          playlists.find((playlist) => playlist.id === row.m3u_account)?.name,
        Header: ({ column }) => (
          <Select
            placeholder="M3U"
            searchable
            size="xs"
            nothingFound="No options"
            onClick={(e) => e.stopPropagation()}
            onChange={handleM3UChange}
            data={playlists.map((playlist) => ({
              label: playlist.name,
              value: `${playlist.id}`,
            }))}
          />
        ),
      },
    ],
    [playlists, groupOptions, filters]
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
      group_name: value ? value.value : '',
    }));
  };

  const handleM3UChange = (value) => {
    setFilters((prev) => ({
      ...prev,
      m3u_account: value ? value.value : '',
    }));
  };

  const fetchData = useCallback(async () => {
    setIsLoading(true);

    const params = new URLSearchParams();
    params.append('page', pagination.pageIndex + 1);
    params.append('page_size', pagination.pageSize);

    // Apply sorting
    if (sorting.length > 0) {
      const sortField = sorting[0].id;
      const sortDirection = sorting[0].desc ? '-' : '';
      params.append('ordering', `${sortDirection}${sortField}`);
    }

    // Apply debounced filters
    Object.entries(debouncedFilters).forEach(([key, value]) => {
      if (value) params.append(key, value);
    });

    try {
      const result = await API.queryStreams(params);
      setData(result.results);
      setRowCount(result.count);

      const newSelection = {};
      result.results.forEach((item, index) => {
        if (selectedStreamIds.includes(item.id)) {
          newSelection[index] = true;
        }
      });

      // ✅ Only update rowSelection if it's different
      if (JSON.stringify(newSelection) !== JSON.stringify(rowSelection)) {
        setRowSelection(newSelection);
      }
    } catch (error) {
      console.error('Error fetching data:', error);
    }

    const groups = await API.getStreamGroups();
    setGroupOptions(groups);

    setIsLoading(false);
  }, [pagination, sorting, debouncedFilters]);

  // Fallback: Individual creation (optional)
  const createChannelFromStream = async (stream) => {
    await API.createChannelFromStream({
      channel_name: stream.name,
      channel_number: null,
      stream_id: stream.id,
    });
  };

  // Bulk creation: create channels from selected streams in one API call
  const createChannelsFromStreams = async () => {
    setIsLoading(true);
    await API.createChannelsFromStreams(
      selectedStreamIds.map((stream_id) => ({
        stream_id,
      }))
    );
    setIsLoading(false);
  };

  const editStream = async (stream = null) => {
    setStream(stream);
    setModalOpen(true);
  };

  const deleteStream = async (id) => {
    await API.deleteStream(id);
  };

  const deleteStreams = async () => {
    setIsLoading(true);
    await API.deleteStreams(selectedStreamIds);
    setIsLoading(false);
  };

  const closeStreamForm = () => {
    setStream(null);
    setModalOpen(false);
  };

  const addStreamsToChannel = async () => {
    const { streams, ...channel } = { ...channelsPageSelection[0] };
    await API.updateChannel({
      ...channel,
      stream_ids: [
        ...new Set(
          channelSelectionStreams
            .map((stream) => stream.id)
            .concat(selectedStreamIds)
        ),
      ],
    });
  };

  const addStreamToChannel = async (streamId) => {
    const { streams, ...channel } = { ...channelsPageSelection[0] };
    await API.updateChannel({
      ...channel,
      stream_ids: [
        ...new Set(
          channelSelectionStreams.map((stream) => stream.id).concat([streamId])
        ),
      ],
    });
  };

  const handleMoreActionsClick = (event, rowId) => {
    setMoreActionsAnchorEl(event.currentTarget);
    setActionsOpenRow(rowId);
  };

  const handleMoreActionsClose = () => {
    setMoreActionsAnchorEl(null);
    setActionsOpenRow(null);
  };

  const onRowSelectionChange = (updater) => {
    setRowSelection((prevRowSelection) => {
      const newRowSelection =
        typeof updater === 'function' ? updater(prevRowSelection) : updater;

      const updatedSelected = new Set([...selectedStreamIds]);
      table.getRowModel().rows.map((row) => {
        if (newRowSelection[row.id] === undefined || !newRowSelection[row.id]) {
          updatedSelected.delete(row.original.id);
        } else {
          updatedSelected.add(row.original.id);
        }
      });
      setSelectedStreamIds([...updatedSelected]);

      return newRowSelection;
    });
  };

  const onSelectAllChange = async (e) => {
    const selectAll = e.target.checked;
    if (selectAll) {
      // Get all stream IDs for current view
      const params = new URLSearchParams();

      // Apply debounced filters
      Object.entries(debouncedFilters).forEach(([key, value]) => {
        if (value) params.append(key, value);
      });

      const ids = await API.getAllStreamIds(params);
      setSelectedStreamIds(ids);
    } else {
      setSelectedStreamIds([]);
    }

    const newSelection = {};
    table.getRowModel().rows.forEach((item, index) => {
      newSelection[index] = selectAll;
    });
    setRowSelection(newSelection);
  };

  const onPageSizeChange = (pageSize) => {
    setPagination({
      ...pagination,
      pageSize,
    });
  };

  const onPageIndexChange = (pageIndex) => {
    setPagination({
      ...pagination,
      pageIndex,
    });
  };

  const onPaginationChange = (updater) => {
    const newPagination = updater(pagination);
    if (JSON.stringify(newPagination) === JSON.stringify(pagination)) {
      // Prevent infinite re-render when there are no results
      return;
    }

    setPagination(updater);
  };

  const table = useMantineReactTable({
    ...TableHelper.defaultProperties,
    columns,
    data,
    enablePagination: true,
    manualPagination: true,
    enableTopToolbar: false,
    enableRowVirtualization: true,
    rowVirtualizerInstanceRef,
    rowVirtualizerOptions: { overscan: 5 }, //optionally customize the row virtualizer
    enableBottomToolbar: true,
    enableStickyHeader: true,
    onPaginationChange: onPaginationChange,
    rowCount: rowCount,
    enableRowSelection: true,
    muiPaginationProps: {
      size: 'small',
      rowsPerPageOptions: [25, 50, 100, 250, 500, 1000, 10000],
      labelRowsPerPage: 'Rows per page',
    },
    onSortingChange: setSorting,
    onRowSelectionChange: onRowSelectionChange,
    initialState: {
      density: 'compact',
    },
    state: {
      isLoading: isLoading,
      sorting,
      pagination,
      rowSelection,
    },
    enableRowActions: true,
    positionActionsColumn: 'first',
    renderRowActions: ({ row }) => (
      <>
        <Tooltip label="Add to Channel">
          <ActionIcon
            size="sm"
            color="blue.5"
            variant="transparent"
            onClick={() => addStreamToChannel(row.original.id)}
            disabled={
              channelsPageSelection.length != 1 ||
              (channelSelectionStreams &&
                channelSelectionStreams
                  .map((stream) => stream.id)
                  .includes(row.original.id))
            }
          >
            <ListPlus size="18" fontSize="small" />
          </ActionIcon>
        </Tooltip>

        <Tooltip label="Create New Channel">
          <ActionIcon
            size="sm"
            color="green.5"
            variant="transparent"
            onClick={() => createChannelFromStream(row.original)}
          >
            <SquarePlus size="18" fontSize="small" />
          </ActionIcon>
        </Tooltip>

        <Menu>
          <Menu.Target>
            <ActionIcon
              onClick={(event) =>
                handleMoreActionsClick(event, row.original.id)
              }
              variant="transparent"
              size="sm"
            >
              <MoreVertIcon />
            </ActionIcon>
          </Menu.Target>

          <Menu.Dropdown>
            <Menu.Item
              onClick={() => editStream(row.original.id)}
              disabled={row.original.m3u_account ? true : false}
            >
              Edit
            </Menu.Item>
            <Menu.Item onClick={() => deleteStream(row.original.id)}>
              Delete Stream
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </>
    ),
    mantineTableContainerProps: {
      style: {
        height: 'calc(100vh - 165px)',
        overflowY: 'auto',
      },
    },
    displayColumnDefOptions: {
      'mrt-row-actions': {
        size: 68,
      },
      'mrt-row-select': {
        size: 50,
      },
    },
  });

  /**
   * useEffects
   */
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    // Scroll to the top of the table when sorting changes
    try {
      rowVirtualizerInstanceRef.current?.scrollToIndex?.(0);
    } catch (error) {
      console.error(error);
    }
  }, [sorting]);

  return (
    <>
      <Flex style={{ display: 'flex', alignItems: 'center', pb: 1 }} gap={15}>
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
          Streams
        </Text>
      </Flex>

      <Paper
        style={
          {
            // bgcolor: theme.palette.background.paper,
            // borderRadius: 2,
            // overflow: 'hidden',
            // height: 'calc(100vh - 75px)',
            // display: 'flex',
            // flexDirection: 'column',
          }
        }
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
            <Tooltip label="Remove Channels">
              <Button
                leftSection={<IconSquareMinus size={14} />}
                variant="default"
                size="xs"
                onClick={deleteStreams}
              >
                Remove
              </Button>
            </Tooltip>

            <Tooltip label="Auto-Match EPG">
              <Button
                leftSection={<IconDeviceDesktopSearch size={14} />}
                variant="default"
                size="xs"
                onClick={createChannelsFromStreams}
                p={5}
              >
                Create Channels
              </Button>
            </Tooltip>

            <Tooltip label="Assign">
              <Button
                leftSection={<IconSquarePlus size={14} />}
                variant="light"
                size="xs"
                onClick={editStream}
                p={5}
                color="green"
                style={{
                  borderWidth: '1px',
                  borderColor: 'green',
                  color: 'white',
                }}
              >
                Add Stream
              </Button>
            </Tooltip>
          </Flex>
        </Box>
      </Paper>

      <MantineReactTable table={table} />
      <StreamForm
        stream={stream}
        isOpen={modalOpen}
        onClose={closeStreamForm}
      />
    </>
  );
};

export default StreamsTable;
