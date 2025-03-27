import React, { useMemo, useState, useEffect } from 'react';
import {
  ActionIcon,
  Box,
  Card,
  Center,
  Container,
  Flex,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import { MantineReactTable, useMantineReactTable } from 'mantine-react-table';
import { TableHelper } from '../helpers';
import API from '../api';
import useChannelsStore from '../store/channels';
import logo from '../images/logo.png';
import {
  Gauge,
  HardDriveDownload,
  HardDriveUpload,
  SquareX,
  Timer,
  Users,
  Video,
} from 'lucide-react';
import dayjs from 'dayjs';
import duration from 'dayjs/plugin/duration';
import relativeTime from 'dayjs/plugin/relativeTime';
import { Sparkline } from '@mantine/charts';
import useStreamProfilesStore from '../store/streamProfiles';

dayjs.extend(duration);
dayjs.extend(relativeTime);

function formatBytes(bytes) {
  if (bytes === 0) return '0 Bytes';

  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));

  return (bytes / Math.pow(1024, i)).toFixed(2) + ' ' + sizes[i];
}

function formatSpeed(bytes) {
  if (bytes === 0) return '0 Bytes';

  const sizes = ['bps', 'Kbps', 'Mbps', 'Gbps'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));

  return (bytes / Math.pow(1024, i)).toFixed(2) + ' ' + sizes[i];
}

const getStartDate = (uptime) => {
  // Get the current date and time
  const currentDate = new Date();
  // Calculate the start date by subtracting uptime (in milliseconds)
  const startDate = new Date(currentDate.getTime() - uptime * 1000);
  // Format the date as a string (you can adjust the format as needed)
  return startDate.toLocaleString({
    weekday: 'short', // optional, adds day of the week
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true, // 12-hour format with AM/PM
  });
};

const ChannelsPage = () => {
  const theme = useMantineTheme();

  const { channels, channelsByUUID, stats: channelStats } = useChannelsStore();
  const { profiles: streamProfiles } = useStreamProfilesStore();

  const [activeChannels, setActiveChannels] = useState({});
  const [clients, setClients] = useState([]);

  const channelsColumns = useMemo(
    () => [
      {
        id: 'logo',
        header: 'Logo',
        accessorKey: 'logo_url',
        size: 50,
        Cell: ({ cell }) => (
          <Center>
            <img src={cell.getValue() || logo} width="20" alt="channel logo" />
          </Center>
        ),
      },
      {
        id: 'name',
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
        id: 'started',
        header: 'Started',
        accessorFn: (row) => {
          // Get the current date and time
          const currentDate = new Date();
          // Calculate the start date by subtracting uptime (in milliseconds)
          const startDate = new Date(currentDate.getTime() - row.uptime * 1000);
          // Format the date as a string (you can adjust the format as needed)
          return startDate.toLocaleString({
            weekday: 'short', // optional, adds day of the week
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true, // 12-hour format with AM/PM
          }); // This will give you a string like: "2025-03-14T14:00:00.000Z"
        },
      },
      {
        id: 'uptime',
        header: 'Uptime',
        size: 50,
        accessorFn: (row) => {
          const days = Math.floor(row.uptime / (3600 * 24)); // Calculate the number of days
          const hours = Math.floor((row.uptime % (3600 * 24)) / 3600); // Calculate remaining hours
          const minutes = Math.floor((row.uptime % 3600) / 60); // Calculate remaining minutes
          const seconds = parseInt(row.uptime % 60); // Remaining seconds

          // Format uptime as "d hh:mm:ss"
          return `${days ? days : ''} ${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
        },
        mantineTableBodyCellProps: {
          align: 'right',
        },
      },
      {
        id: 'num_clients',
        header: 'Clients',
        accessorKey: 'client_count',
        size: 50,
        mantineTableBodyCellProps: {
          align: 'center',
        },
      },
    ],
    []
  );

  const stopChannel = async (id) => {
    await API.stopChannel(id);
  };

  const stopClient = async (channelId, clientId) => {
    await API.stopClient(channelId, clientId);
  };

  // const channelsTable = useMantineReactTable({
  //   ...TableHelper.defaultProperties,
  //   renderTopToolbar: false,
  //   columns: channelsColumns,
  //   data: activeChannels,
  //   enableRowActions: true,
  //   mantineTableBodyCellProps: {
  //     style: {
  //       padding: 4,
  //       borderColor: '#444',
  //       color: '#E0E0E0',
  //       fontSize: '0.85rem',
  //     },
  //   },
  //   renderRowActions: ({ row }) => (
  //     <Box sx={{ justifyContent: 'right' }}>
  //       <Center>
  //         <ActionIcon
  //           size="sm"
  //           variant="transparent"
  //           color="red.9"
  //           onClick={() => stopChannel(row.original.uuid)}
  //         >
  //           <SquareX size="18" />
  //         </ActionIcon>
  //       </Center>
  //     </Box>
  //   ),
  // });

  const clientsTable = useMantineReactTable({
    ...TableHelper.defaultProperties,
    renderTopToolbar: false,
    data: clients,
    columns: useMemo(
      () => [
        // {
        //   header: 'User-Agent',
        //   accessorKey: 'user_agent',
        //   size: 250,
        //   mantineTableBodyCellProps: {
        //     style: {
        //       whiteSpace: 'nowrap',
        //       maxWidth: 400,
        //       paddingLeft: 10,
        //       paddingRight: 10,
        //     },
        //   },
        // },
        {
          header: 'IP Address',
          accessorKey: 'ip_address',
          size: 50,
        },
      ],
      []
    ),
    mantineTableBodyCellProps: {
      style: {
        padding: 4,
        borderColor: '#444',
        // color: '#E0E0E0',
        fontSize: '0.85rem',
      },
    },
    enableRowActions: true,
    renderRowActions: ({ row }) => (
      <Box sx={{ justifyContent: 'right' }}>
        <Center>
          <ActionIcon
            size="sm"
            variant="transparent"
            color="red.9"
            onClick={() =>
              stopClient(row.original.channel.uuid, row.original.client_id)
            }
          >
            <SquareX size="18" />
          </ActionIcon>
        </Center>
      </Box>
    ),
    mantineTableContainerProps: {
      style: {
        height: '100%',
        overflowY: 'auto',
      },
    },
    renderDetailPanel: ({ row }) => <Box>{row.original.user_agent}</Box>,
    mantineExpandButtonProps: ({ row, table }) => ({
      size: 'xs',
      style: {
        transform: row.getIsExpanded() ? 'rotate(180deg)' : 'rotate(-90deg)',
        transition: 'transform 0.2s',
      },
    }),
    enableExpandAll: false,
    displayColumnDefOptions: {
      'mrt-row-expand': {
        size: 15,
        header: '',
        // mantineTableHeadCellProps: {
        //   style: {
        //     padding: 0,
        //     minWidth: '20px !important',
        //   },
        // },
        // mantineTableBodyCellProps: {
        //   style: {
        //     padding: 0,
        //     minWidth: '20px !important',
        //   },
        // },
      },
      'mrt-row-actions': {
        size: 74,
      },
    },
  });

  useEffect(() => {
    if (!channelStats.channels) {
      return;
    }

    const stats = channelStats.channels.reduce((acc, ch) => {
      let bitrates = [];
      if (activeChannels[ch.channel_id]) {
        bitrates = activeChannels[ch.channel_id].bitrates;
        const bitrate =
          ch.total_bytes - activeChannels[ch.channel_id].total_bytes;
        if (bitrate > 0) {
          bitrates.push(bitrate);
        }

        if (bitrates.length > 15) {
          bitrates = bitrates.slice(1);
        }
      }

      acc[ch.channel_id] = {
        ...ch,
        ...channels[channelsByUUID[ch.channel_id]],
        bitrates,
        stream_profile: streamProfiles.find(
          (profile) => profile.id == parseInt(ch.profile)
        ),
      };

      return acc;
    }, {});

    setActiveChannels(stats);

    const clientStats = Object.values(stats).reduce((acc, ch) => {
      return acc.concat(
        ch.clients.map((client) => ({
          ...client,
          channel: ch,
        }))
      );
    }, []);
    setClients(clientStats);
  }, [channelStats]);

  return (
    <SimpleGrid cols={3} spacing="md" style={{ padding: 10 }}>
      {Object.values(activeChannels).map((channel) => (
        <Card
          shadow="sm"
          padding="md"
          radius="md"
          withBorder
          style={{
            color: '#fff',
            backgroundColor: '#27272A',
          }}
        >
          <Stack style={{ position: 'relative' }}>
            <Group justify="space-between">
              <img
                src={channel.logo_url || logo}
                width="30"
                alt="channel logo"
              />

              <Group>
                <Box>
                  <Tooltip label={getStartDate(channel.uptime)}>
                    <Center>
                      <Timer style={{ paddingRight: 5 }} />
                      {dayjs.duration(channel.uptime, 'seconds').humanize()}
                    </Center>
                  </Tooltip>
                </Box>
                <Center>
                  <Tooltip label="Stop Channel">
                    <ActionIcon variant="transparent" color="red.9">
                      <SquareX size="24" />
                    </ActionIcon>
                  </Tooltip>
                </Center>
              </Group>
            </Group>

            <Flex justify="space-between" align="center">
              <Group>
                <Text fw={500}>{channel.name}</Text>
              </Group>

              <Group gap={5}>
                <Video size="18" />
                {channel.stream_profile.name}
              </Group>
            </Flex>

            <Group justify="space-between">
              <Group gap={4}>
                <Gauge style={{ paddingRight: 5 }} size="22" />
                <Text size="sm">{formatSpeed(channel.bitrates.at(-1))}</Text>
              </Group>

              <Text size="sm">Avg: {channel.avg_bitrate}</Text>

              <Group gap={4}>
                <HardDriveDownload size="18" />
                <Text size="sm">{formatBytes(channel.total_bytes)}</Text>
              </Group>

              <Group gap={5}>
                <Users size="18" />
                <Text size="sm">{channel.client_count}</Text>
              </Group>
            </Group>

            <MantineReactTable table={clientsTable} />
          </Stack>
        </Card>
      ))}
    </SimpleGrid>
  );
};

export default ChannelsPage;
