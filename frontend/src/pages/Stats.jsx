import React, { useMemo, useState, useEffect, useCallback } from 'react';
import {
  ActionIcon,
  Box,
  Card,
  Center,
  Flex,
  Grid,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { MantineReactTable, useMantineReactTable } from 'mantine-react-table';
import { TableHelper } from '../helpers';
import API from '../api';
import useChannelsStore from '../store/channels';
import logo from '../images/logo.png';
import {
  Tv2,
  ScreenShare,
  Scroll,
  SquareMinus,
  CirclePlay,
  SquarePen,
  Binary,
  ArrowDown01,
  SquareX,
  Timer,
} from 'lucide-react';
import dayjs from 'dayjs';
import duration from 'dayjs/plugin/duration';
import relativeTime from 'dayjs/plugin/relativeTime';

dayjs.extend(duration);
dayjs.extend(relativeTime);

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
  const { channels, channelsByUUID, stats: channelStats } = useChannelsStore();
  const [activeChannels, setActiveChannels] = useState([]);
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

  const channelsTable = useMantineReactTable({
    ...TableHelper.defaultProperties,
    renderTopToolbar: false,
    columns: channelsColumns,
    data: activeChannels,
    enableRowActions: true,
    mantineTableBodyCellProps: {
      style: {
        padding: 4,
        borderColor: '#444',
        color: '#E0E0E0',
        fontSize: '0.85rem',
      },
    },
    renderRowActions: ({ row }) => (
      <Box sx={{ justifyContent: 'right' }}>
        <Center>
          <ActionIcon
            size="sm"
            variant="transparent"
            color="red.9"
            onClick={() => stopChannel(row.original.uuid)}
          >
            <SquareX size="18" />
          </ActionIcon>
        </Center>
      </Box>
    ),
  });

  const clientsTable = useMantineReactTable({
    ...TableHelper.defaultProperties,
    renderTopToolbar: false,
    data: clients,
    columns: useMemo(
      () => [
        {
          header: 'User-Agent',
          accessorKey: 'user_agent',
          size: 250,
          mantineTableBodyCellProps: {
            style: {
              whiteSpace: 'nowrap',
              maxWidth: 400,
              paddingLeft: 10,
              paddingRight: 10,
            },
          },
        },
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
        color: '#E0E0E0',
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
  });

  useEffect(() => {
    const stats = channelStats.channels.map((ch) => ({
      ...ch,
      ...channels[channelsByUUID[ch.channel_id]],
    }));
    setActiveChannels(stats);

    const clientStats = stats.reduce((acc, ch) => {
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
    <SimpleGrid cols={2} spacing="md" style={{ padding: 10 }}>
      {activeChannels.map((channel) => (
        <Card shadow="sm" padding="lg" radius="md" withBorder>
          <Stack>
            <Flex justify="space-between" align="center">
              <Group>
                <Title order={5}>{channel.name}</Title>
                <img
                  src={channel.logo_url || logo}
                  width="20"
                  alt="channel logo"
                />
              </Group>

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
            </Flex>

            <Box>
              <Flex
                justify="space-between"
                align="center"
                style={{ paddingRight: 10, paddingLeft: 10 }}
              >
                <Text>Clients</Text>
                <Text>{channel.client_count}</Text>
              </Flex>
              <MantineReactTable table={clientsTable} />
            </Box>
          </Stack>
        </Card>
      ))}
    </SimpleGrid>
  );
};

export default ChannelsPage;
