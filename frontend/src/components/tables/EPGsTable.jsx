import { useEffect, useMemo, useRef, useState } from 'react';
import { MantineReactTable, useMantineReactTable } from 'mantine-react-table';
import API from '../../api';
import useEPGsStore from '../../store/epgs';
import EPGForm from '../forms/EPG';
import { TableHelper } from '../../helpers';
import {
  ActionIcon,
  Text,
  Tooltip,
  Box,
  Paper,
  Button,
  Flex,
  useMantineTheme,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconSquarePlus } from '@tabler/icons-react';
import { RefreshCcw, SquareMinus, SquarePen } from 'lucide-react';

const EPGsTable = () => {
  const [epg, setEPG] = useState(null);
  const [epgModalOpen, setEPGModalOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState([]);

  const { epgs } = useEPGsStore();
  console.log(epgs);

  const theme = useMantineTheme();

  const columns = useMemo(
    //column definitions...
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
      },
      {
        header: 'Source Type',
        accessorKey: 'source_type',
      },
      {
        header: 'URL / API Key',
        accessorKey: 'max_streams',
        enableSorting: false,
      },
    ],
    []
  );

  //optionally access the underlying virtualizer instance
  const rowVirtualizerInstanceRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const editEPG = async (epg = null) => {
    setEPG(epg);
    setEPGModalOpen(true);
  };

  const deleteEPG = async (id) => {
    setIsLoading(true);
    await API.deleteEPG(id);
    setIsLoading(false);
  };

  const refreshEPG = async (id) => {
    await API.refreshEPG(id);
    notifications.show({
      title: 'EPG refresh initiated',
    });
  };

  const closeEPGForm = () => {
    setEPG(null);
    setEPGModalOpen(false);
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
    data: Object.values(epgs),
    enablePagination: false,
    enableRowVirtualization: true,
    enableRowSelection: false,
    renderTopToolbar: false,
    onRowSelectionChange: setRowSelection,
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
          size="sm" // Makes the button smaller
          color="yellow.5" // Red color for delete actions
          onClick={() => editEPG(row.original)}
        >
          <SquarePen size="18" /> {/* Small icon size */}
        </ActionIcon>
        <ActionIcon
          variant="transparent"
          size="sm" // Makes the button smaller
          color="red.9" // Red color for delete actions
          onClick={() => deleteEPG(row.original.id)}
        >
          <SquareMinus size="18" /> {/* Small icon size */}
        </ActionIcon>
        <ActionIcon
          variant="transparent"
          size="sm" // Makes the button smaller
          color="blue.5" // Red color for delete actions
          onClick={() => refreshEPG(row.original.id)}
        >
          <RefreshCcw size="18" /> {/* Small icon size */}
        </ActionIcon>
      </>
    ),
    mantineTableContainerProps: {
      style: {
        height: 'calc(40vh - 0px)',
      },
    },
    displayColumnDefOptions: {
      'mrt-row-actions': {
        size: 10,
      },
    },
  });

  return (
    <Box>
      <Flex
        style={{
          display: 'flex',
          alignItems: 'center',
          paddingBottom: 10,
        }}
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
          EPGs
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
                leftSection={<IconSquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editEPG()}
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
            </Tooltip>
          </Flex>
        </Box>
      </Paper>

      <MantineReactTable table={table} />
      <EPGForm epg={epg} isOpen={epgModalOpen} onClose={closeEPGForm} />
    </Box>
  );
};

export default EPGsTable;
