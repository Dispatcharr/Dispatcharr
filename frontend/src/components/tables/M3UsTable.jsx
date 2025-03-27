import { useEffect, useMemo, useRef, useState } from 'react';
import { MantineReactTable, useMantineReactTable } from 'mantine-react-table';
import API from '../../api';
import usePlaylistsStore from '../../store/playlists';
import M3UForm from '../forms/M3U';
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
} from '@mantine/core';
import { SquareMinus, SquarePen, RefreshCcw, Check, X } from 'lucide-react';
import { IconSquarePlus } from '@tabler/icons-react'; // Import custom icons

const M3UTable = () => {
  const [playlist, setPlaylist] = useState(null);
  const [playlistModalOpen, setPlaylistModalOpen] = useState(false);
  const [groupFilterModalOpen, setGroupFilterModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);
  const [activeFilterValue, setActiveFilterValue] = useState('all');
  const [playlistCreated, setPlaylistCreated] = useState(false);

  const { playlists, setRefreshProgress } = usePlaylistsStore();

  const theme = useMantineTheme();

  const columns = useMemo(
    //column definitions...
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
      },
      {
        header: 'URL / File',
        accessorKey: 'server_url',
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
        header: 'Max Streams',
        accessorKey: 'max_streams',
        size: 200,
      },
      {
        header: 'Active',
        accessorKey: 'is_active',
        size: 100,
        sortingFn: 'basic',
        mantineTableBodyCellProps: {
          align: 'left',
        },
        Cell: ({ cell }) => (
          <Box sx={{ display: 'flex', justifyContent: 'center' }}>
            {cell.getValue() ? <Check color="green" /> : <X color="red" />}
          </Box>
        ),
      },
    ],
    []
  );

  //optionally access the underlying virtualizer instance
  const rowVirtualizerInstanceRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const editPlaylist = async (playlist = null) => {
    if (playlist) {
      setPlaylist(playlist);
    }
    setPlaylistModalOpen(true);
  };

  const refreshPlaylist = async (id) => {
    await API.refreshPlaylist(id);
    setRefreshProgress(id, 0);
  };

  const deletePlaylist = async (id) => {
    setIsLoading(true);
    await API.deletePlaylist(id);
    setIsLoading(false);
  };

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

  const deletePlaylists = async (ids) => {
    const selected = table
      .getRowModel()
      .rows.filter((row) => row.getIsSelected());
    // await API.deleteStreams(selected.map(stream => stream.original.id))
  };

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    //scroll to the top of the table when the sorting changes
    try {
      rowVirtualizerInstanceRef.current?.scrollToIndex?.(0);
    } catch (error) {
      console.error(error);
    }
  }, [sorting]);

  const table = useMantineReactTable({
    ...TableHelper.defaultProperties,
    columns,
    data: playlists.filter((playlist) => playlist.locked === false),
    enablePagination: false,
    enableRowVirtualization: true,
    enableRowSelection: false,
    onRowSelectionChange: setRowSelection,
    renderTopToolbar: false,
    onSortingChange: setSorting,
    state: {
      isLoading,
      sorting,
      rowSelection,
    },
    rowVirtualizerInstanceRef, //optional
    rowVirtualizerOptions: { overscan: 5 }, //optionally customize the row virtualizer
    initialState: {
      density: 'compact',
    },
    enableRowActions: true,
    renderRowActions: ({ row }) => (
      <>
        <ActionIcon
          variant="transparent"
          size="sm"
          color="yellow.5"
          onClick={() => {
            editPlaylist(row.original);
          }}
        >
          <SquarePen size="18" />
        </ActionIcon>
        <ActionIcon
          variant="transparent"
          size="sm"
          color="red.9"
          onClick={() => deletePlaylist(row.original.id)}
        >
          <SquareMinus size="18" />
        </ActionIcon>
        <ActionIcon
          variant="transparent"
          size="sm"
          color="blue.5"
          onClick={() => refreshPlaylist(row.original.id)}
        >
          <RefreshCcw size="18" />
        </ActionIcon>
      </>
    ),
    mantineTableContainerProps: {
      style: {
        height: 'calc(40vh - 0px)',
      },
    },
  });

  return (
    <Box>
      <Flex
        style={{ display: 'flex', alignItems: 'center', paddingBottom: 10 }}
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
            // alignItems: 'center',
            // backgroundColor: theme.palette.background.paper,
            justifyContent: 'flex-end',
            padding: 10,
            // gap: 1,
          }}
        >
          <Flex gap={6}>
            <Tooltip label="Assign">
              <Button
                leftSection={<IconSquarePlus size={14} />}
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
                Add
              </Button>
            </Tooltip>
          </Flex>
        </Box>
      </Paper>
      <MantineReactTable table={table} />

      <M3UForm
        playlist={playlist}
        isOpen={playlistModalOpen}
        onClose={closeModal}
        playlistCreated={playlistCreated}
      />
    </Box>
  );
};

export default M3UTable;
