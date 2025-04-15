import React, {
  useEffect,
  useMemo,
  useRef,
  useState,
  useCallback,
} from 'react';
import { MantineReactTable, useMantineReactTable } from 'mantine-react-table';
import useChannelsStore from '../../store/channels';
import { notifications } from '@mantine/notifications';
import API from '../../api';
import ChannelForm from '../forms/Channel';
import RecordingForm from '../forms/Recording';
import { TableHelper } from '../../helpers';
import { getDescendantProp, useDebounce } from '../../utils';
import logo from '../../images/logo.png';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';
import usePlaylistsStore from '../../store/playlists';
import {
  Tv2,
  ScreenShare,
  Scroll,
  SquareMinus,
  CirclePlay,
  SquarePen,
  Binary,
  ArrowDown01,
  SquarePlus,
  Copy,
  CircleCheck,
  ScanEye,
  EllipsisVertical,
  CircleEllipsis,
  CopyMinus,
} from 'lucide-react';
import ghostImage from '../../images/ghost.svg';
import {
  Box,
  TextInput,
  Popover,
  ActionIcon,
  Select,
  Button,
  Paper,
  Flex,
  Text,
  Tooltip,
  Grid,
  Group,
  useMantineTheme,
  Center,
  Switch,
  Menu,
  MultiSelect,
  Pagination,
  NativeSelect,
} from '@mantine/core';

const ChannelStreams = React.memo(({ channel, isExpanded }) => {
  const channelStreams = useChannelsStore(
    (state) => state.channels[channel.id]?.streams
  );
  const { playlists } = usePlaylistsStore();

  const removeStream = async (stream) => {
    const newStreamList = channelStreams.filter((s) => s.id !== stream.id);
    await API.updateChannel({
      ...channel,
      stream_ids: newStreamList.map((s) => s.id),
    });
  };

  const channelStreamsTable = useMantineReactTable({
    ...TableHelper.defaultProperties,
    data: channelStreams,
    columns: useMemo(
      () => [
        {
          size: 400,
          header: 'Name',
          accessorKey: 'name',
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
          size: 100,
          header: 'M3U',
          accessorFn: (row) =>
            playlists.find((playlist) => playlist.id === row.m3u_account)?.name,
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
      ],
      [playlists]
    ),
    displayColumnDefOptions: {
      'mrt-row-actions': {
        size: 10,
      },
    },
    enableKeyboardShortcuts: false,
    enableColumnFilters: false,
    enableBottomToolbar: false,
    enableTopToolbar: false,
    enableTableHead: false,
    columnFilterDisplayMode: 'popover',
    enablePagination: false,
    enableRowVirtualization: true,
    enableColumnHeaders: false,
    rowVirtualizerOptions: { overscan: 5 }, //optionally customize the row virtualizer
    initialState: {
      density: 'compact',
    },
    enableRowActions: true,
    enableRowOrdering: true,
    mantineTableHeadRowProps: {
      style: { display: 'none' },
    },
    mantineTableBodyCellProps: {
      style: {
        // py: 0,
        padding: 4,
        borderColor: '#444',
        color: '#E0E0E0',
        fontSize: '0.85rem',
      },
    },
    mantineRowDragHandleProps: ({ table }) => ({
      onDragEnd: async () => {
        const { draggingRow, hoveredRow } = table.getState();

        if (hoveredRow && draggingRow) {
          channelStreams.splice(
            hoveredRow.index,
            0,
            channelStreams.splice(draggingRow.index, 1)[0]
          );

          const { streams: _, ...channelUpdate } = channel;

          API.updateChannel({
            ...channelUpdate,
            stream_ids: channelStreams.map((stream) => stream.id),
          });
        }
      },
    }),
    renderRowActions: ({ row }) => (
      <Tooltip label="Remove stream">
        <ActionIcon
          size="sm"
          color="red.9"
          variant="transparent"
          onClick={() => removeStream(row.original)}
        >
          <SquareMinus size="18" fontSize="small" />
        </ActionIcon>
      </Tooltip>
    ),
  });

  if (!isExpanded) {
    return <></>;
  }

  return (
    <Box style={{ width: '100%' }}>
      <MantineReactTable table={channelStreamsTable} />
    </Box>
  );
});

const m3uUrlBase = `${window.location.protocol}//${window.location.host}/output/m3u`;
const epgUrlBase = `${window.location.protocol}//${window.location.host}/output/epg`;
const hdhrUrlBase = `${window.location.protocol}//${window.location.host}/hdhr`;

const CreateProfilePopover = React.memo(({ }) => {
  const [opened, setOpened] = useState(false);
  const [name, setName] = useState('');
  const theme = useMantineTheme();

  const setOpen = () => {
    setName('');
    setOpened(!opened);
  };

  const submit = async () => {
    await API.addChannelProfile({ name });
    setName('');
    setOpened(false);
  };

  return (
    <Popover
      opened={opened}
      onChange={setOpen}
      position="bottom"
      withArrow
      shadow="md"
    >
      <Popover.Target>
        <ActionIcon
          variant="transparent"
          color={theme.tailwind.green[5]}
          onClick={setOpen}
        >
          <SquarePlus />
        </ActionIcon>
      </Popover.Target>

      <Popover.Dropdown>
        <Group>
          <TextInput
            placeholder="Profile Name"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            size="xs"
          />

          <ActionIcon
            variant="transparent"
            color={theme.tailwind.green[5]}
            size="sm"
            onClick={submit}
          >
            <CircleCheck />
          </ActionIcon>
        </Group>
      </Popover.Dropdown>
    </Popover>
  );
});

const ChannelsTable = React.memo(({ }) => {
  const {
    channels,
    isLoading: channelsLoading,
    fetchChannels,
    setChannelsPageSelection,
    profiles,
    selectedProfileId,
    setSelectedProfileId,
    selectedProfileChannels,
    channelsPageSelection,
  } = useChannelsStore();

  const {
    environment: { env_mode },
  } = useSettingsStore();

  const [channel, setChannel] = useState(null);
  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [recordingModalOpen, setRecordingModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);
  const [channelGroupOptions, setChannelGroupOptions] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState(
    profiles[selectedProfileId]
  );
  const [channelsEnabledHeaderSwitch, setChannelsEnabledHeaderSwitch] =
    useState(false);
  const [initialDataCount, setInitialDataCount] = useState(null);
  const [data, setData] = useState([]);
  const [rowCount, setRowCount] = useState(0);
  const [pageCount, setPageCount] = useState(0);
  const [paginationString, setPaginationString] = useState('');
  const [selectedStreamIds, setSelectedStreamIds] = useState([]);
  // const [allRowsSelected, setAllRowsSelected] = useState(false);
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: 250,
  });
  const [filters, setFilters] = useState({
    name: '',
    channel_group: '',
    m3u_account: '',
  });
  const debouncedFilters = useDebounce(filters, 500);
  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([
    { id: 'channel_number', desc: false },
    { id: 'name', desc: false },
  ]);

  const [hdhrUrl, setHDHRUrl] = useState(hdhrUrlBase);
  const [epgUrl, setEPGUrl] = useState(epgUrlBase);
  const [m3uUrl, setM3UUrl] = useState(m3uUrlBase);

  const [textToCopy, setTextToCopy] = useState('');

  const [filterValues, setFilterValues] = useState({});

  // const theme = useTheme();
  const theme = useMantineTheme();

  const { showVideo } = useVideoStore();

  useEffect(() => {
    setSelectedProfile(profiles[selectedProfileId]);

    const profileString =
      selectedProfileId != '0' ? `/${profiles[selectedProfileId].name}` : '';
    setHDHRUrl(`${hdhrUrlBase}${profileString}`);
    setEPGUrl(`${epgUrlBase}${profileString}`);
    setM3UUrl(`${m3uUrlBase}${profileString}`);
  }, [selectedProfileId]);

  useEffect(() => {
    setChannelGroupOptions([
      ...new Set(
        Object.values(channels).map((channel) => channel.channel_group?.name)
      ),
    ]);
  }, [channels]);

  const handleFilterChange = (columnId, value) => {
    setFilterValues((prev) => ({
      ...prev,
      [columnId]: Array.isArray(value)
        ? value
        : value
          ? value.toLowerCase()
          : '',
    }));
  };

  const hdhrUrlRef = useRef(null);
  const m3uUrlRef = useRef(null);
  const epgUrlRef = useRef(null);

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
      const result = await API.queryChannels(params);
      setData(result.results);
      setRowCount(result.count);
      setPageCount(Math.ceil(result.count / pagination.pageSize));

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

    setIsLoading(false);
  }, [pagination, sorting, debouncedFilters]);

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const onRowSelectionChange = (updater) => {
    setRowSelection((prevRowSelection) => {
      const newRowSelection =
        typeof updater === 'function' ? updater(prevRowSelection) : updater;

      const updatedSelected = new Set([...selectedStreamIds]);
      table.getRowModel().rows.forEach((row) => {
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

  const toggleChannelEnabled = async (channelIds, enabled) => {
    if (channelIds.length == 1) {
      await API.updateProfileChannel(channelIds[0], selectedProfileId, enabled);
    } else {
      await API.updateProfileChannels(channelIds, selectedProfileId, enabled);
      setChannelsEnabledHeaderSwitch(enabled);
    }
  };

  const enabledChannelSet = useMemo(() => {
    return new Set(
      selectedProfileChannels.filter((c) => c.enabled).map((c) => c.id)
    );
  }, [selectedProfileChannels]);

  const EnabledHeaderSwitch = React.memo(({ isActive, toggle, disabled }) => (
    <Switch
      size="xs"
      checked={disabled || isActive}
      onChange={toggle}
      disabled={disabled}
    />
  ));

  const renderEnabledHeader = useCallback(() => {
    if (Object.values(rowSelection).length === 0) {
      return <ScanEye size="16" style={{ marginRight: 8 }} />;
    }

    const handleToggle = () => {
      toggleChannelEnabled(
        channelsPageSelection.map((row) => row.id),
        !channelsEnabledHeaderSwitch
      );
    };

    return (
      <EnabledHeaderSwitch
        isActive={channelsEnabledHeaderSwitch}
        toggle={handleToggle}
        disabled={selectedProfileId === '0'}
      />
    );
  }, [
    rowSelection,
    channelsPageSelection,
    channelsEnabledHeaderSwitch,
    selectedProfileId,
  ]);

  // Configure columns
  const columns = useMemo(
    () => [
      {
        id: 'enabled',
        Header: renderEnabledHeader,
        enableSorting: false,
        accessorFn: (row) => {
          return selectedProfileId == '0'
            ? true
            : enabledChannelSet.has(row.id);
        },
        mantineTableHeadCellProps: {
          align: 'right',
          style: {
            backgroundColor: '#3F3F46',
            width: '40px',
            minWidth: '40px',
            maxWidth: '40px',
            //   // minWidth: '20px',
            //   // width: '50px !important',
            //   // justifyContent: 'center',
            padding: 0,
            //   // paddingLeft: 8,
            //   // paddingRight: 0,
          },
        },
        mantineTableBodyCellProps: {
          align: 'right',
          style: {
            width: '40px',
            minWidth: '40px',
            maxWidth: '40px',
            //   // minWidth: '20px',
            //   // justifyContent: 'center',
            //   // paddingLeft: 0,
            //   // paddingRight: 0,
            padding: 0,
          },
        },
        Cell: ({ row, cell }) => {
          const memoizedCellValue = useMemo(() => cell.getValue(), [cell]);
          const handleSwitchChange = useCallback(() => {
            toggleChannelEnabled([row.original.id], !memoizedCellValue);
          }, [memoizedCellValue, row.original.id, toggleChannelEnabled]);

          return (
            <Switch
              size="xs"
              checked={cell.getValue()}
              onChange={handleSwitchChange}
              disabled={selectedProfileId == '0'}
            />
          );
        },
      },
      {
        header: '#',
        size: 50,
        maxSize: 50,
        accessorKey: 'channel_number',
        sortingFn: (a, b, columnId) => {
          return (
            parseInt(a.original.channel_number) -
            parseInt(b.original.channel_number)
          );
        },
        mantineTableHeadCellProps: {
          align: 'right',
          //   //   style: {
          //   //     backgroundColor: '#3F3F46',
          //   //     // minWidth: '20px',
          //   //     // justifyContent: 'center',
          //   //     // paddingLeft: 15,
          //   //     paddingRight: 0,
          //   //   },
        },
        mantineTableBodyCellProps: {
          align: 'right',
          //   //   style: {
          //   //     minWidth: '20px',
          //   //     // justifyContent: 'center',
          //   //     paddingLeft: 0,
          //   //     paddingRight: 0,
          //   //   },
        },
      },
      {
        header: 'Name',
        accessorKey: 'name',
        Header: ({ column }) => (
          <TextInput
            name="name"
            placeholder="Name"
            value={filterValues[column.id]}
            onChange={(e) => {
              e.stopPropagation();
              handleFilterChange(column.id, e.target.value);
            }}
            size="xs"
            variant="unstyled"
            className="table-input-header"
            onClick={(e) => e.stopPropagation()}
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
        accessorKey: 'channel_group.name',
        accessorFn: (row) => row.channel_group?.name || '',
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
        Header: ({ column }) => (
          <Box onClick={(e) => e.stopPropagation()}>
            <MultiSelect
              placeholder="Group"
              searchable
              size="xs"
              nothingFoundMessage="No options"
              onChange={(value) => {
                handleFilterChange(column.id, value);
              }}
              data={channelGroupOptions}
              variant="unstyled"
              className="table-input-header custom-multiselect"
            />
          </Box>
        ),
      },
      {
        header: '',
        accessorKey: 'logo',
        enableSorting: false,
        size: 75,
        mantineTableBodyCellProps: {
          align: 'center',
          style: {
            maxWidth: '75px',
          },
        },
        Cell: ({ cell }) => (
          <Grid
            direction="row"
            sx={{
              justifyContent: 'center',
              alignItems: 'center',
            }}
          >
            <img
              src={cell.getValue() ? cell.getValue().cache_url : logo}
              alt="channel logo"
              style={{
                width: 'auto',
                height: 'auto',
                maxWidth: '55px',
                maxHeight: '18px',
              }}
            />
          </Grid>
        ),
      },
    ],
    [
      channelGroupOptions,
      filterValues,
      selectedProfile,
      selectedProfileChannels,
      rowSelection,
      channelsPageSelection,
      channelsEnabledHeaderSwitch,
    ]
  );

  // (Optional) bulk delete, but your endpoint is @TODO
  const deleteChannels = async () => {
    setIsLoading(true);
    const selected = table
      .getRowModel()
      .rows.filter((row) => row.getIsSelected());

    await API.deleteChannels(selected.map((row) => row.original.id));
    setIsLoading(false);
  };

  // ─────────────────────────────────────────────────────────
  // The "Assign Channels" button logic
  // ─────────────────────────────────────────────────────────
  const assignChannels = async () => {
    try {
      // Get row order from the table
      const rowOrder = table.getRowModel().rows.map((row) => row.original.id);

      // Call our custom API endpoint
      setIsLoading(true);
      const result = await API.assignChannelNumbers(rowOrder);
      setIsLoading(false);

      // We might get { message: "Channels have been auto-assigned!" }
      notifications.show({
        title: result.message || 'Channels assigned',
        color: 'green.5',
      });

      // Refresh the channel list
      await fetchChannels();
    } catch (err) {
      console.error(err);
      notifications.show({
        title: 'Failed to assign channels',
        color: 'red.5',
      });
    }
  };

  const matchEpg = async () => {
    try {
      // Hit our new endpoint that triggers the fuzzy matching Celery task
      await API.matchEpg();

      notifications.show({
        title: 'EPG matching task started!',
        // style: { width: '200px', left: '200px' },
      });
    } catch (err) {
      notifications.show(`Error: ${err.message}`);
    }
  };

  const closeChannelForm = () => {
    setChannel(null);
    setChannelModalOpen(false);
  };

  const closeRecordingForm = () => {
    // setChannel(null);
    setRecordingModalOpen(false);
  };

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setIsLoading(false);
    }
  }, []);

  const handleCopy = async (textToCopy, ref) => {
    try {
      await navigator.clipboard.writeText(textToCopy);
      notifications.show({
        title: 'Copied!',
        // style: { width: '200px', left: '200px' },
      });
    } catch (err) {
      const inputElement = ref.current; // Get the actual input

      if (inputElement) {
        inputElement.focus();
        inputElement.select();

        // For older browsers
        document.execCommand('copy');
        notifications.show({ title: 'Copied!' });
      }
    }
  };

  // Example copy URLs
  const copyM3UUrl = () => {
    handleCopy(m3uUrl, m3uUrlRef);
  };
  const copyEPGUrl = () => {
    handleCopy(epgUrl, epgUrlRef);
  };
  const copyHDHRUrl = () => {
    handleCopy(hdhrUrl, hdhrUrlRef);
  };

  useEffect(() => {
    const selectedRows = table
      .getSelectedRowModel()
      .rows.map((row) => row.original);
    setChannelsPageSelection(selectedRows);

    if (selectedProfileId != '0') {
      setChannelsEnabledHeaderSwitch(
        selectedRows.filter(
          (row) =>
            selectedProfileChannels.find((channel) => row.id == channel.id)
              .enabled
        ).length == selectedRows.length
      );
    }
  }, [rowSelection]);

  const filteredData = Object.values(channels).filter((row) =>
    columns.every(({ accessorKey }) => {
      if (!accessorKey) {
        return true;
      }

      const filterValue = filterValues[accessorKey];
      const rowValue = getDescendantProp(row, accessorKey);

      if (Array.isArray(filterValue) && filterValue.length != 0) {
        return filterValue.includes(rowValue);
      } else if (filterValue) {
        return rowValue?.toLowerCase().includes(filterValues[accessorKey]);
      }

      return true;
    })
  );

  const deleteProfile = async (id) => {
    await API.deleteChannelProfile(id);
  };

  const renderProfileOption = ({ option, checked }) => {
    return (
      <Group justify="space-between" style={{ width: '100%' }}>
        <Box>{option.label}</Box>
        {option.value != '0' && (
          <ActionIcon
            size="xs"
            variant="transparent"
            color={theme.tailwind.red[6]}
            onClick={(e) => {
              e.stopPropagation();
              deleteProfile(option.value);
            }}
          >
            <SquareMinus />
          </ActionIcon>
        )}
      </Group>
    );
  };

  const RowActions = React.memo(({ row }) => {
    const editChannel = useCallback(() => {
      setChannel(row.original);
      setChannelModalOpen(true);
    }, []);

    const deleteChannel = useCallback(async () => {
      setRowSelection([]);
      // if (channelsPageSelection.length > 0) {
      //   return deleteChannels();
      // }
      await API.deleteChannel(row.id);
    }, []);

    const createRecording = useCallback(() => {
      setChannel(row);
      setRecordingModalOpen(true);
    }, []);

    const handleWatchStream = useCallback(() => {
      let vidUrl = `/proxy/ts/stream/${row.uuid}`;
      if (env_mode == 'dev') {
        vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
      }
      showVideo(vidUrl);
    }, []);

    return (
      <Box style={{ width: '100%', justifyContent: 'left' }}>
        <Center>
          <ActionIcon
            size="xs"
            variant="transparent"
            color={theme.tailwind.yellow[3]}
            onClick={editChannel}
          >
            <SquarePen size="18" />
          </ActionIcon>

          <ActionIcon
            size="xs"
            variant="transparent"
            color={theme.tailwind.red[6]}
            onClick={deleteChannel}
            disabled={
              channelsPageSelection.length > 0 &&
              !channelsPageSelection.map((row) => row.id).includes(row.id)
            }
          >
            {channelsPageSelection.length === 0 ? (
              <SquareMinus size="18" />
            ) : (
              <CopyMinus size="18" />
            )}
          </ActionIcon>

          <ActionIcon
            size="xs"
            variant="transparent"
            color={theme.tailwind.green[5]}
            onClick={handleWatchStream}
          >
            <CirclePlay size="18" />
          </ActionIcon>

          {env_mode == 'dev' && (
            <Menu>
              <Menu.Target>
                <ActionIcon variant="transparent" size="sm">
                  <EllipsisVertical size="18" />
                </ActionIcon>
              </Menu.Target>

              <Menu.Dropdown>
                <Menu.Item
                  onClick={createRecording}
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
                  Record
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          )}
        </Center>
      </Box>
    );
  });

  const table = useMantineReactTable({
    ...TableHelper.defaultProperties,
    columns,
    data,
    enablePagination: true,
    manualPagination: true,
    enableColumnActions: false,
    enableRowSelection: true,
    renderTopToolbar: false,
    onRowSelectionChange: onRowSelectionChange,
    onSortingChange: setSorting,
    state: {
      isLoading: isLoading || channelsLoading,
      sorting,
      rowSelection,
    },
    enableBottomToolbar: true,
    renderBottomToolbar: ({ table }) => (
      <Group
        gap={5}
        justify="center"
        style={{ padding: 8, borderTop: '1px solid #666' }}
      >
        <Text size="xs">Page Size</Text>
        <NativeSelect
          size="xxs"
          value={pagination.pageSize}
          data={['25', '50', '100', '250', '500', '1000']}
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
    ),
    initialState: {
      density: 'compact',
      sorting: [
        {
          id: 'channel_number',
          desc: false,
        },
      ],
    },
    enableRowActions: true,
    enableExpandAll: false,
    displayColumnDefOptions: {
      'mrt-row-select': {
        size: 10,
        maxSize: 10,
        mantineTableHeadCellProps: {
          align: 'right',
          style: {
            paddding: 0,
            // paddingLeft: 7,
            width: '20px',
            minWidth: '20px',
            backgroundColor: '#3F3F46',
          },
        },
        mantineTableBodyCellProps: {
          align: 'right',
          style: {
            paddingLeft: 0,
            width: '20px',
            minWidth: '20px',
          },
        },
      },
      'mrt-row-expand': {
        size: 20,
        maxSize: 20,
        header: '',
        mantineTableHeadCellProps: {
          style: {
            padding: 0,
            paddingLeft: 2,
            width: '20px',
            minWidth: '20px',
            maxWidth: '20px',
            backgroundColor: '#3F3F46',
          },
        },
        mantineTableBodyCellProps: {
          style: {
            padding: 0,
            paddingLeft: 2,
            width: '20px',
            minWidth: '20px',
            maxWidth: '20px',
          },
        },
      },
      'mrt-row-actions': {
        size: 85,
        maxWidth: 85,
        mantineTableHeadCellProps: {
          align: 'center',
          style: {
            minWidth: '85px',
            maxWidth: '85px',
            // paddingRight: 40,
            fontWeight: 'normal',
            color: 'rgb(207,207,207)',
            backgroundColor: '#3F3F46',
          },
        },
        mantineTableBodyCellProps: {
          style: {
            minWidth: '85px',
            maxWidth: '85px',
            paddingLeft: 0,
            // paddingRight: 10,
          },
        },
      },
    },
    mantineExpandButtonProps: ({ row, table }) => ({
      onClick: () => {
        setRowSelection({ [row.index]: true });
        table.setExpanded({ [row.id]: !row.getIsExpanded() });
      },
      size: 'xs',
      style: {
        transform: row.getIsExpanded() ? 'rotate(180deg)' : 'rotate(-90deg)',
        transition: 'transform 0.2s',
      },
    }),
    renderDetailPanel: ({ row }) => (
      <ChannelStreams channel={row.original} isExpanded={row.getIsExpanded()} />
    ),
    renderRowActions: ({ row }) => <RowActions row={row.original} />,
    mantineTableContainerProps: {
      style: {
        height: 'calc(100vh - 150px)',
        overflowY: 'auto',
        // margin: 5,
      },
    },
  });

  return (
    <Box>
      {/* Header Row: outside the Paper */}
      <Flex
        style={{ display: 'flex', alignItems: 'center', paddingBottom: 10 }}
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
            <Popover withArrow shadow="md">
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
                <Group>
                  <TextInput ref={hdhrUrlRef} value={hdhrUrl} size="small" />
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

            <Popover withArrow shadow="md">
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
                <Group>
                  <TextInput ref={m3uUrlRef} value={m3uUrl} size="small" />
                  <ActionIcon
                    onClick={copyM3UUrl}
                    size="sm"
                    variant="transparent"
                    color="gray.5"
                  >
                    <Copy size="18" fontSize="small" />
                  </ActionIcon>
                </Group>
              </Popover.Dropdown>
            </Popover>

            <Popover withArrow shadow="md">
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
                <Group>
                  <TextInput ref={epgUrlRef} value={epgUrl} size="small" />
                  <ActionIcon
                    onClick={copyEPGUrl}
                    size="sm"
                    variant="transparent"
                    color="gray.5"
                  >
                    <Copy size="18" fontSize="small" />
                  </ActionIcon>
                </Group>
              </Popover.Dropdown>
            </Popover>
          </Group>
        </Flex>
      </Flex>

      {/* Paper container: contains top toolbar and table (or ghost state) */}
      <Paper
        style={{
          height: 'calc(100vh - 60px)',
          backgroundColor: '#27272A',
        }}
      >
        {/* Top toolbar with Remove, Assign, Auto-match, and Add buttons */}
        <Group justify="space-between">
          <Group gap={5} style={{ paddingLeft: 10 }}>
            <Select
              size="xs"
              value={selectedProfileId}
              onChange={setSelectedProfileId}
              data={Object.values(profiles).map((profile) => ({
                label: profile.name,
                value: `${profile.id}`,
              }))}
              renderOption={renderProfileOption}
            />

            <Tooltip label="Create Profile">
              <CreateProfilePopover />
            </Tooltip>
          </Group>

          <Box
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              padding: 10,
            }}
          >
            <Flex gap={6}>
              <Button
                leftSection={<SquareMinus size={18} />}
                variant="default"
                size="xs"
                onClick={deleteChannels}
                disabled={Object.values(rowSelection).length == 0}
              >
                Remove
              </Button>

              <Tooltip label="Assign Channel #s">
                <Button
                  leftSection={<ArrowDown01 size={18} />}
                  variant="default"
                  size="xs"
                  onClick={assignChannels}
                  p={5}
                >
                  Assign
                </Button>
              </Tooltip>

              <Tooltip label="Auto-Match EPG">
                <Button
                  leftSection={<Binary size={18} />}
                  variant="default"
                  size="xs"
                  onClick={matchEpg}
                  p={5}
                >
                  Auto-Match
                </Button>
              </Tooltip>

              <Button
                leftSection={<SquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editChannel()}
                p={5}
                color={theme.tailwind.green[5]}
                style={{
                  borderWidth: '1px',
                  borderColor: theme.tailwind.green[5],
                  color: 'white',
                }}
              >
                Add
              </Button>
            </Flex>
          </Box>
        </Group>

        {/* Table or ghost empty state inside Paper */}
        <Box>
          {Object.keys(channels).length === 0 && (
            <Box
              style={{
                paddingTop: 20,
                bgcolor: theme.palette.background.paper,
              }}
            >
              <Center>
                <Box
                  style={{
                    textAlign: 'center',
                    width: '55%',
                  }}
                >
                  <Text
                    style={{
                      fontFamily: 'Inter, sans-serif',
                      fontWeight: 400,
                      fontSize: '20px',
                      lineHeight: '28px',
                      letterSpacing: '-0.3px',
                      color: theme.palette.text.secondary,
                      mb: 1,
                    }}
                  >
                    It’s recommended to create channels after adding your M3U or
                    streams.
                  </Text>
                  <Text
                    style={{
                      fontFamily: 'Inter, sans-serif',
                      fontWeight: 400,
                      fontSize: '16px',
                      lineHeight: '24px',
                      letterSpacing: '-0.2px',
                      color: theme.palette.text.secondary,
                      mb: 2,
                    }}
                  >
                    You can still create channels without streams if you’d like,
                    and map them later.
                  </Text>
                  <Button
                    leftSection={<SquarePlus size={18} />}
                    variant="light"
                    size="xs"
                    onClick={() => editChannel()}
                    color="gray"
                    style={{
                      marginTop: 20,
                      borderWidth: '1px',
                      borderColor: 'gray',
                      color: 'white',
                    }}
                  >
                    Create Channel
                  </Button>
                </Box>
              </Center>

              <Center>
                <Box
                  component="img"
                  src={ghostImage}
                  alt="Ghost"
                  style={{
                    paddingTop: 30,
                    width: '120px',
                    height: 'auto',
                    opacity: 0.2,
                    pointerEvents: 'none',
                  }}
                />
              </Center>
            </Box>
          )}
        </Box>
        {Object.keys(channels).length > 0 && (
          <MantineReactTable table={table} />
        )}
      </Paper>

      <ChannelForm
        channel={channel}
        isOpen={channelModalOpen}
        onClose={closeChannelForm}
      />

      <RecordingForm
        channel={channel}
        isOpen={recordingModalOpen}
        onClose={closeRecordingForm}
      />
    </Box>
  );
});

export default ChannelsTable;
