import { useEffect, useMemo, useRef, useState } from 'react';
import {
  MaterialReactTable,
  useMaterialReactTable,
} from 'material-react-table';
import {
  Box,
  Grid2,
  Stack,
  Typography,
  Tooltip,
  IconButton,
  Button,
  ButtonGroup,
  Snackbar,
  Popover,
  TextField,
} from '@mui/material';
import useChannelsStore from '../../store/channels';
import {
  Delete as DeleteIcon,
  Edit as EditIcon,
  Add as AddIcon,
  SwapVert as SwapVertIcon,
  LiveTv as LiveTvIcon,
  ContentCopy,
  Tv as TvIcon, // <-- ADD THIS IMPORT
} from '@mui/icons-material';
import API from '../../api';
import ChannelForm from '../forms/Channel';
import { TableHelper } from '../../helpers';
import utils from '../../utils';
import logo from '../../images/logo.png';
import useVideoStore from '../../store/useVideoStore';

const ChannelsTable = () => {
  const [channel, setChannel] = useState(null);
  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);

  const [anchorEl, setAnchorEl] = useState(null);
  const [textToCopy, setTextToCopy] = useState('');
  const [snackbarMessage, setSnackbarMessage] = useState('');
  const [snackbarOpen, setSnackbarOpen] = useState(false);

  const { channels, isLoading: channelsLoading } = useChannelsStore();
  const { showVideo } = useVideoStore.getState(); // or useVideoStore()

  // Configure columns
  const columns = useMemo(
    () => [
      {
        header: '#',
        size: 50,
        accessorKey: 'channel_number',
      },
      {
        header: 'Name',
        accessorKey: 'channel_name',
      },
      {
        header: 'Group',
        accessorFn: (row) => row.channel_group?.name || '',
      },
      {
        header: 'Logo',
        accessorKey: 'logo_url',
        size: 55,
        Cell: ({ cell }) => (
          <Grid2
            container
            direction="row"
            sx={{
              justifyContent: 'center',
              alignItems: 'center',
            }}
          >
            <img src={cell.getValue() || logo} width="20" alt="channel logo" />
          </Grid2>
        ),
        meta: {
          filterVariant: null,
        },
      },
    ],
    []
  );

  // Access the row virtualizer instance (optional)
  const rowVirtualizerInstanceRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const closeSnackbar = () => setSnackbarOpen(false);

  const editChannel = async (ch = null) => {
    setChannel(ch);
    setChannelModalOpen(true);
  };

  const deleteChannel = async (id) => {
    await API.deleteChannel(id);
  };

  function handleWatchStream(channelNumber) {
    showVideo(`http://192.168.1.151:5656/output/stream/${channelNumber}/`);
  }

  // (Optional) bulk delete, but your endpoint is @TODO
  const deleteChannels = async () => {
    setIsLoading(true);
    const selected = table
      .getRowModel()
      .rows.filter((row) => row.getIsSelected());
    await utils.Limiter(
      4,
      selected.map((chan) => () => deleteChannel(chan.original.id))
    );
    // If you have a real bulk-delete endpoint, call it here:
    // await API.deleteChannels(selected.map((sel) => sel.id));
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
      const result = await API.assignChannelNumbers(rowOrder);

      // We might get { message: "Channels have been auto-assigned!" }
      setSnackbarMessage(result.message || 'Channels assigned');
      setSnackbarOpen(true);

      // Refresh the channel list
      await useChannelsStore.getState().fetchChannels();
    } catch (err) {
      console.error(err);
      setSnackbarMessage('Failed to assign channels');
      setSnackbarOpen(true);
    }
  };

  // ─────────────────────────────────────────────────────────
  // The new "Match EPG" button logic
  // ─────────────────────────────────────────────────────────
  const matchEpg = async () => {
    try {
      // Hit our new endpoint that triggers the fuzzy matching Celery task
      const resp = await fetch('/api/channels/channels/match-epg/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${await API.getAuthToken()}`,
        },
      });

      if (resp.ok) {
        setSnackbarMessage('EPG matching task started!');
      } else {
        const text = await resp.text();
        setSnackbarMessage(`Failed to start EPG matching: ${text}`);
      }
    } catch (err) {
      setSnackbarMessage(`Error: ${err.message}`);
    }
    setSnackbarOpen(true);
  };

  const closeChannelForm = () => {
    setChannel(null);
    setChannelModalOpen(false);
  };

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

  const closePopover = () => {
    setAnchorEl(null);
    setSnackbarMessage('');
  };
  const openPopover = Boolean(anchorEl);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(textToCopy);
      setSnackbarMessage('Copied!');
    } catch (err) {
      setSnackbarMessage('Failed to copy');
    }
    setSnackbarOpen(true);
  };

  // Example copy URLs
  const copyM3UUrl = (event) => {
    setAnchorEl(event.currentTarget);
    setTextToCopy(
      `${window.location.protocol}//${window.location.host}/output/m3u`
    );
  };
  const copyEPGUrl = (event) => {
    setAnchorEl(event.currentTarget);
    setTextToCopy(
      `${window.location.protocol}//${window.location.host}/output/epg`
    );
  };
  const copyHDHRUrl = (event) => {
    setAnchorEl(event.currentTarget);
    setTextToCopy(
      `${window.location.protocol}//${window.location.host}/output/hdhr`
    );
  };

  // Configure the MaterialReactTable
  const table = useMaterialReactTable({
    ...TableHelper.defaultProperties,
    columns,
    data: channels,
    enablePagination: false,
    enableRowVirtualization: true,
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    state: {
      isLoading: isLoading || channelsLoading,
      sorting,
      rowSelection,
    },
    rowVirtualizerInstanceRef, // optional
    rowVirtualizerOptions: { overscan: 5 },
    initialState: {
      density: 'compact',
    },
    enableRowActions: true,
    renderRowActions: ({ row }) => (
      <Box sx={{ justifyContent: 'right' }}>
        <IconButton
          size="small"
          color="warning"
          onClick={() => {
            editChannel(row.original);
          }}
          sx={{ p: 0 }}
        >
          <EditIcon fontSize="small" />
        </IconButton>
        <IconButton
          size="small"
          color="error"
          onClick={() => deleteChannel(row.original.id)}
          sx={{ p: 0 }}
        >
          <DeleteIcon fontSize="small" />
        </IconButton>
        <IconButton
          size="small"
          color="info"
          onClick={() => handleWatchStream(row.original.channel_number)}
          sx={{ p: 0 }}
        >
          <LiveTvIcon fontSize="small" />
        </IconButton>
      </Box>
    ),
    muiTableContainerProps: {
      sx: {
        height: 'calc(100vh - 75px)',
        overflowY: 'auto',
      },
    },
    muiSearchTextFieldProps: {
      variant: 'standard',
    },
    renderTopToolbarCustomActions: ({ table }) => (
      <Stack direction="row" sx={{ alignItems: 'center' }}>
        <Typography>Channels</Typography>
        <Tooltip title="Add New Channel">
          <IconButton
            size="small"
            color="success"
            variant="contained"
            onClick={() => editChannel()}
          >
            <AddIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Delete Channels">
          <IconButton
            size="small"
            color="error"
            variant="contained"
            onClick={deleteChannels}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Assign Channels">
          <IconButton
            size="small"
            color="warning"
            variant="contained"
            onClick={assignChannels}
          >
            <SwapVertIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        {/* Our brand-new button for EPG matching */}
        <Tooltip title="Auto-match EPG with fuzzy logic">
          <IconButton
            size="small"
            color="success"
            variant="contained"
            onClick={matchEpg}
          >
            <TvIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        <ButtonGroup sx={{ marginLeft: 1 }}>
          <Button variant="contained" size="small" onClick={copyHDHRUrl}>
            HDHR URL
          </Button>
          <Button variant="contained" size="small" onClick={copyM3UUrl}>
            M3U URL
          </Button>
          <Button variant="contained" size="small" onClick={copyEPGUrl}>
            EPG
          </Button>
        </ButtonGroup>
      </Stack>
    ),
  });

  return (
    <Box>
      <MaterialReactTable table={table} />

      {/* Channel Form Modal */}
      <ChannelForm
        channel={channel}
        isOpen={channelModalOpen}
        onClose={closeChannelForm}
      />

      {/* Popover for the "copy" URLs */}
      <Popover
        open={openPopover}
        anchorEl={anchorEl}
        onClose={closePopover}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'left',
        }}
      >
        <div style={{ padding: 16, display: 'flex', alignItems: 'center' }}>
          <TextField
            value={textToCopy}
            variant="standard"
            disabled
            size="small"
            sx={{ marginRight: 1 }}
          />
          <IconButton onClick={handleCopy} color="primary">
            <ContentCopy />
          </IconButton>
        </div>
      </Popover>

      {/* Snackbar for feedback */}
      <Snackbar
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
        open={snackbarOpen}
        autoHideDuration={5000}
        onClose={closeSnackbar}
        message={snackbarMessage}
      />
    </Box>
  );
};

export default ChannelsTable;
