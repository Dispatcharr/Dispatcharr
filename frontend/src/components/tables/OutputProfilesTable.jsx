import { useEffect, useMemo, useRef, useState } from 'react';
import API from '../../api';
import OutputProfileForm from '../forms/OutputProfile';
import useOutputProfilesStore from '../../store/outputProfiles';
import {
  Box,
  ActionIcon,
  Tooltip,
  Text,
  Paper,
  Flex,
  Button,
  useMantineTheme,
  Center,
  Switch,
  Stack,
} from '@mantine/core';
import { SquareMinus, SquarePen, Eye, EyeOff, SquarePlus } from 'lucide-react';
import { CustomTable, useTable } from './CustomTable';
import useLocalStorage from '../../hooks/useLocalStorage';

const RowActions = ({ row, editOutputProfile, deleteOutputProfile }) => {
  return (
    <>
      <ActionIcon
        variant="transparent"
        color="yellow.5"
        size="sm"
        disabled={row.original.locked}
        onClick={() => editOutputProfile(row.original)}
      >
        <SquarePen size="18" />
      </ActionIcon>
      <ActionIcon
        variant="transparent"
        size="sm"
        color="red.9"
        disabled={row.original.locked}
        onClick={() => deleteOutputProfile(row.original.id)}
      >
        <SquareMinus size="18" />
      </ActionIcon>
    </>
  );
};

const OutputProfiles = () => {
  const [profile, setProfile] = useState(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [hideInactive, setHideInactive] = useState(false);
  const [data, setData] = useState([]);

  const outputProfiles = useOutputProfilesStore((state) => state.profiles);
  const [tableSize] = useLocalStorage('table-size', 'default');
  const theme = useMantineTheme();

  const rowVirtualizerInstanceRef = useRef(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([]);

  const columns = useMemo(
    () => [
      {
        header: 'Name',
        accessorKey: 'name',
        size: 175,
        cell: ({ cell }) => (
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
        header: 'Command',
        accessorKey: 'command',
        size: 100,
        cell: ({ cell }) => (
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
        header: 'Parameters',
        accessorKey: 'parameters',
        grow: true,
        cell: ({ cell }) => (
          <Tooltip label={cell.getValue()}>
            <div
              style={{
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {cell.getValue()}
            </div>
          </Tooltip>
        ),
      },
      {
        header: 'Active',
        accessorKey: 'is_active',
        size: 60,
        cell: ({ row, cell }) => (
          <Center>
            <Switch
              size="xs"
              checked={cell.getValue()}
              onChange={() => toggleProfileIsActive(row.original)}
              disabled={row.original.locked}
            />
          </Center>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        size: tableSize === 'compact' ? 50 : 75,
      },
    ],
    []
  );

  const editOutputProfile = async (profile = null) => {
    setProfile(profile);
    setProfileModalOpen(true);
  };

  const deleteOutputProfile = async (id) => {
    await API.deleteOutputProfile(id);
  };

  const closeOutputProfileForm = () => {
    setProfile(null);
    setProfileModalOpen(false);
  };

  const toggleHideInactive = () => setHideInactive((v) => !v);

  const toggleProfileIsActive = async (profile) => {
    await API.updateOutputProfile({
      id: profile.id,
      ...profile,
      is_active: !profile.is_active,
    });
  };

  useEffect(() => {
    if (typeof window !== 'undefined') setIsLoading(false);
  }, []);

  useEffect(() => {
    try {
      rowVirtualizerInstanceRef.current?.scrollToIndex?.(0);
    } catch (error) {
      console.error(error);
    }
  }, [sorting]);

  useEffect(() => {
    setData(
      outputProfiles.filter((p) =>
        hideInactive && !p.is_active ? false : true
      )
    );
  }, [outputProfiles, hideInactive]);

  const renderHeaderCell = (header) => (
    <Text size="sm" name={header.id}>
      {header.column.columnDef.header}
    </Text>
  );

  const renderBodyCell = ({ cell, row }) => {
    if (cell.column.id === 'actions') {
      return (
        <RowActions
          row={row}
          editOutputProfile={editOutputProfile}
          deleteOutputProfile={deleteOutputProfile}
        />
      );
    }
  };

  const table = useTable({
    columns,
    data,
    allRowIds: data.map((d) => d.id),
    bodyCellRenderFns: { actions: renderBodyCell },
    headerCellRenderFns: {
      name: renderHeaderCell,
      command: renderHeaderCell,
      parameters: renderHeaderCell,
      is_active: renderHeaderCell,
      actions: renderHeaderCell,
    },
  });

  return (
    <Stack gap={0} style={{ padding: 0 }}>
      <Paper
        style={{ bgcolor: theme.palette?.background?.paper, borderRadius: 2 }}
      >
        <Box
          style={{ display: 'flex', justifyContent: 'flex-end', padding: 10 }}
        >
          <Flex gap={6}>
            <Tooltip label={hideInactive ? 'Show All' : 'Hide Inactive'}>
              <Center>
                <ActionIcon
                  onClick={toggleHideInactive}
                  variant="filled"
                  color="gray"
                  style={{ borderWidth: '1px', borderColor: 'white' }}
                >
                  {hideInactive ? <EyeOff size={18} /> : <Eye size={18} />}
                </ActionIcon>
              </Center>
            </Tooltip>
            <Tooltip label="Add Output Profile">
              <Button
                leftSection={<SquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editOutputProfile()}
                p={5}
                color="green"
                style={{
                  borderWidth: '1px',
                  borderColor: 'green',
                  color: 'white',
                }}
              >
                Add Output Profile
              </Button>
            </Tooltip>
          </Flex>
        </Box>
      </Paper>

      <Box style={{ display: 'flex', flexDirection: 'column', maxHeight: 300 }}>
        <Box
          style={{
            flex: 1,
            overflowY: 'auto',
            overflowX: 'auto',
            border: 'solid 1px rgb(68,68,68)',
            borderRadius: 'var(--mantine-radius-default)',
          }}
        >
          <div style={{ minWidth: 600 }}>
            <CustomTable table={table} />
          </div>
        </Box>
      </Box>

      <OutputProfileForm
        profile={profile}
        isOpen={profileModalOpen}
        onClose={closeOutputProfileForm}
      />
    </Stack>
  );
};

export default OutputProfiles;
