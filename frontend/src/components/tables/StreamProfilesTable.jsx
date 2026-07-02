import { useEffect, useMemo, useState } from 'react';
import API from '../../api';
import StreamProfileForm from '../forms/StreamProfile';
import useStreamProfilesStore from '../../store/streamProfiles';
import useSettingsStore from '../../store/settings';
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
import {
  SquareMinus,
  SquarePen,
  Eye,
  EyeOff,
  SquarePlus,
} from 'lucide-react';
import { CustomTable, useTable } from './CustomTable';
import useLocalStorage from '../../hooks/useLocalStorage';
import { showNotification } from '../../utils/notificationUtils.js';
import { updateStreamProfile } from '../../utils/forms/StreamProfileUtils.js';

const RowActions = ({ row, editStreamProfile, handleDeleteStreamProfile }) => {
  return (
    <>
      <ActionIcon
        variant="transparent"
        color="yellow.5"
        size="sm"
        disabled={row.original.locked}
        onClick={() => editStreamProfile(row.original)}
      >
        <SquarePen size="18" /> {/* Small icon size */}
      </ActionIcon>
      <ActionIcon
        variant="transparent"
        size="sm"
        color="red.9"
        disabled={row.original.locked}
        onClick={() => handleDeleteStreamProfile(row.original.id)}
      >
        <SquareMinus fontSize="small" /> {/* Small icon size */}
      </ActionIcon>
    </>
  );
};

const deleteStreamProfile = (id) => {
  return API.deleteStreamProfile(id);
}

const StreamProfiles = () => {
  const [profile, setProfile] = useState(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [hideInactive, setHideInactive] = useState(false);
  const [data, setData] = useState([]);

  const streamProfiles = useStreamProfilesStore((state) => state.profiles);
  const settings = useSettingsStore((s) => s.settings);
  const [tableSize] = useLocalStorage('table-size', 'default');

  const theme = useMantineTheme();

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
        size: tableSize == 'compact' ? 50 : 75,
      },
    ],
    []
  );

  const editStreamProfile = async (profile = null) => {
    setProfile(profile);
    setProfileModalOpen(true);
  };

  const handleDeleteStreamProfile = async (id) => {
    if (id == settings.default_stream_profile) {
      showNotification({
        title: 'Cannot delete default stream-profile',
        color: 'red.5',
      });
      return;
    }

    await deleteStreamProfile(id);
  };

  const closeStreamProfileForm = () => {
    setProfile(null);
    setProfileModalOpen(false);
  };

  const toggleHideInactive = () => {
    setHideInactive(!hideInactive);
  };

  const toggleProfileIsActive = async (profile) => {
    await updateStreamProfile(
      profile.id,
      {
      ...profile,
      is_active: !profile.is_active,
    });
  };

  useEffect(() => {
    setData(
      streamProfiles.filter((profile) => !(hideInactive && !profile.is_active))
    );
  }, [streamProfiles, hideInactive]);

  const renderHeaderCell = (header) => {
    return (
      <Text size="sm" name={header.id}>
        {header.column.columnDef.header}
      </Text>
    );
  };

  const renderBodyCell = ({ cell, row }) => {
    switch (cell.column.id) {
      case 'actions':
        return (
          <RowActions
            row={row}
            editStreamProfile={editStreamProfile}
            handleDeleteStreamProfile={handleDeleteStreamProfile}
          />
        );
    }
  };

  const table = useTable({
    columns,
    data,
    allRowIds: data.map((d) => d.id),
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
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
        style={{
          bgcolor: theme.palette.background.paper,
          borderRadius: 2,
        }}
      >
        {/* Top toolbar with Remove, Assign, Auto-match, and Add buttons */}
        <Box
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            padding: 10,
          }}
        >
          <Flex gap={6}>
            <Tooltip label={hideInactive ? 'Show All' : 'Hide Inactive'}>
              <Center>
                <ActionIcon
                  onClick={toggleHideInactive}
                  variant="filled"
                  color="gray"
                  style={{
                    borderWidth: '1px',
                    borderColor: 'white',
                  }}
                >
                  {hideInactive ? <EyeOff size={18} /> : <Eye size={18} />}
                </ActionIcon>
              </Center>
            </Tooltip>
            <Tooltip label="Assign">
              <Button
                leftSection={<SquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editStreamProfile()}
                p={5}
                color="green"
                style={{
                  borderWidth: '1px',
                  borderColor: 'green',
                  color: 'white',
                }}
              >
                Add Stream Profile
              </Button>
            </Tooltip>
          </Flex>
        </Box>
      </Paper>

      <Box
        style={{
          display: 'flex',
          flexDirection: 'column',
          maxHeight: 300,
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
          <div style={{ minWidth: 600 }}>
            <CustomTable table={table} />
          </div>
        </Box>
      </Box>

      <StreamProfileForm
        profile={profile}
        isOpen={profileModalOpen}
        onClose={closeStreamProfileForm}
      />
    </Stack>
  );
};

export default StreamProfiles;
