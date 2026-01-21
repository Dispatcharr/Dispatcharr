import { useLocation } from 'react-router-dom';
import React, { useEffect, useMemo, useState } from 'react';
import useLocalStorage from '../../hooks/useLocalStorage.jsx';
import usePlaylistsStore from '../../store/playlists.jsx';
import useSettingsStore from '../../store/settings.jsx';
import {
  ActionIcon,
  Badge,
  Box,
  Card,
  Center,
  Flex,
  Group,
  Progress,
  Select,
  Stack,
  Text,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import {
  ChevronDown,
  ChevronRight,
  CirclePlay,
  Gauge,
  HardDriveDownload,
  HardDriveUpload,
  Radio,
  SquareX,
  Timer,
  Users,
  Video,
} from 'lucide-react';
import {
  toFriendlyDuration,
  useDateTimeFormat,
} from '../../utils/dateTimeUtils.js';
import { CustomTable, useTable } from '../tables/CustomTable/index.jsx';
import { TableHelper } from '../../helpers/index.jsx';
import logo from '../../images/logo.png';
import { formatBytes, formatSpeed } from '../../utils/networkUtils.js';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  connectedAccessor,
  durationAccessor,
  getBufferingSpeedThreshold,
  getChannelStreams,
  getLogoUrl,
  getM3uAccountsMap,
  getMatchingStreamByUrl,
  getSelectedStream,
  getStartDate,
  getStreamOptions,
  getStreamsByIds,
  switchStream,
} from '../../utils/cards/StreamConnectionCardUtils.js';
import useVideoStore from '../../store/useVideoStore';

// Create a separate component for each channel card to properly handle the hook
const StreamConnectionCard = ({
  channel,
  clients,
  stopClient,
  stopChannel,
  logos,
  channelsByUUID,
  channels,
  currentProgram,
}) => {
  const location = useLocation();
  const [availableStreams, setAvailableStreams] = useState([]);
  const [isLoadingStreams, setIsLoadingStreams] = useState(false);
  const [activeStreamId, setActiveStreamId] = useState(null);
  const [currentM3UProfile, setCurrentM3UProfile] = useState(null); // Add state for current M3U profile
  const [data, setData] = useState([]);
  const [previewedStream, setPreviewedStream] = useState(null);
  const [isProgramDescExpanded, setIsProgramDescExpanded] = useState(false);

  const theme = useMantineTheme();

  // Get M3U account data from the playlists store
  const m3uAccounts = usePlaylistsStore((s) => s.playlists);
  // Get settings for speed threshold and environment mode
  const settings = useSettingsStore((s) => s.settings);
  const env_mode =
    useSettingsStore((s) => s.environment?.env_mode) || 'production';
  // Get video preview function
  const showVideo = useVideoStore((s) => s.showVideo);

  // Get user's date/time format preferences
  const { fullDateTimeFormat } = useDateTimeFormat();

  // Create a map of M3U account IDs to names for quick lookup
  const m3uAccountsMap = useMemo(() => {
    return getM3uAccountsMap(m3uAccounts);
  }, [m3uAccounts]);

  // Update M3U profile information when channel data changes
  useEffect(() => {
    // If the channel data includes M3U profile information, update our state
    if (channel.m3u_profile || channel.m3u_profile_name) {
      setCurrentM3UProfile({
        name:
          channel.m3u_profile?.name ||
          channel.m3u_profile_name ||
          'Default M3U',
      });
    }
  }, [channel.m3u_profile, channel.m3u_profile_name, channel.stream_id]);

  // Fetch available streams for this channel
  useEffect(() => {
    const fetchStreams = async () => {
      setIsLoadingStreams(true);
      try {
        // Get channel ID from UUID
        const channelId = channelsByUUID[channel.channel_id];
        if (channelId) {
          const streamData = await getChannelStreams(channelId);

          // Use streams in the order returned by the API without sorting
          setAvailableStreams(streamData);

          // If we have a channel URL, try to find the matching stream
          if (channel.url && streamData.length > 0) {
            // Try to find matching stream based on URL
            const matchingStream = getMatchingStreamByUrl(
              streamData,
              channel.url
            );

            if (matchingStream) {
              setActiveStreamId(matchingStream.id.toString());

              // If the stream has M3U profile info, save it
              if (matchingStream.m3u_profile) {
                setCurrentM3UProfile(matchingStream.m3u_profile);
              }
            }
          }
        }
      } catch (error) {
        console.error('Error fetching streams:', error);
      } finally {
        setIsLoadingStreams(false);
      }
    };

    fetchStreams();
  }, [channel.channel_id, channel.url, channelsByUUID]);

  useEffect(() => {
    setData(
      clients
        .filter((client) => client.channel.channel_id === channel.channel_id)
        .map((client) => ({
          id: client.client_id,
          ...client,
        }))
    );
  }, [clients, channel.channel_id]);

  const renderHeaderCell = (header) => {
    switch (header.id) {
      default:
        return (
          <Group>
            <Text size="sm" name={header.id}>
              {header.column.columnDef.header}
            </Text>
          </Group>
        );
    }
  };

  const renderBodyCell = ({ cell, row }) => {
    switch (cell.column.id) {
      case 'actions':
        return (
          <Box sx={{ justifyContent: 'right' }}>
            <Center>
              <Tooltip label="Disconnect client">
                <ActionIcon
                  size="sm"
                  variant="transparent"
                  color="red.9"
                  onClick={() =>
                    stopClient(
                      row.original.channel.uuid,
                      row.original.client_id
                    )
                  }
                >
                  <SquareX size="18" />
                </ActionIcon>
              </Tooltip>
            </Center>
          </Box>
        );
    }
  };

  const checkStreamsAfterChange = (streamId) => {
    return async () => {
      try {
        const channelId = channelsByUUID[channel.channel_id];
        if (channelId) {
          const updatedStreamData = await getChannelStreams(channelId);
          console.log('Channel streams after switch:', updatedStreamData);

          // Update current stream information with fresh data
          const updatedStream = getSelectedStream(updatedStreamData, streamId);
          if (updatedStream?.m3u_profile) {
            setCurrentM3UProfile(updatedStream.m3u_profile);
          }
        }
      } catch (error) {
        console.error('Error checking streams after switch:', error);
      }
    };
  };

  // Handle stream switching
  const handleStreamChange = async (streamId) => {
    try {
      console.log('Switching to stream ID:', streamId);
      // Find the selected stream in availableStreams for debugging
      const selectedStream = getSelectedStream(availableStreams, streamId);
      console.log('Selected stream details:', selectedStream);

      // Make sure we're passing the correct ID to the API
      const response = await switchStream(channel, streamId);
      console.log('Stream switch API response:', response);

      // Update the local active stream ID immediately
      setActiveStreamId(streamId);

      // Update M3U profile information if available in the response
      if (response?.m3u_profile) {
        setCurrentM3UProfile(response.m3u_profile);
      } else if (selectedStream && selectedStream.m3u_profile) {
        // Fallback to the profile from the selected stream
        setCurrentM3UProfile(selectedStream.m3u_profile);
      }

      // Show detailed notification with stream name
      showNotification({
        title: 'Stream switching',
        message: `Switching to "${selectedStream?.name}" for ${channel.name}`,
        color: 'blue.5',
      });

      // After a short delay, fetch streams again to confirm the switch
      setTimeout(checkStreamsAfterChange(streamId), 2000);
    } catch (error) {
      console.error('Stream switch error:', error);
      showNotification({
        title: 'Error switching stream',
        message: error.toString(),
        color: 'red.5',
      });
    }
  };

  const clientsColumns = useMemo(
    () => [
      {
        id: 'expand',
        size: 20,
      },
      {
        header: 'IP Address',
        accessorKey: 'ip_address',
      },
      // Updated Connected column with tooltip
      {
        id: 'connected',
        header: 'Connected',
        accessorFn: connectedAccessor(fullDateTimeFormat),
        cell: ({ cell }) => (
          <Tooltip
            label={
              cell.getValue() !== 'Unknown'
                ? `Connected at ${cell.getValue()}`
                : 'Unknown connection time'
            }
          >
            <Text size="xs">{cell.getValue()}</Text>
          </Tooltip>
        ),
      },
      // Update Duration column with tooltip showing exact seconds
      {
        id: 'duration',
        header: 'Duration',
        accessorFn: durationAccessor(),
        cell: ({ cell, row }) => {
          const exactDuration =
            row.original.connected_since || row.original.connection_duration;
          return (
            <Tooltip
              label={
                exactDuration
                  ? `${exactDuration.toFixed(1)} seconds`
                  : 'Unknown duration'
              }
            >
              <Text size="xs">{cell.getValue()}</Text>
            </Tooltip>
          );
        },
      },
      {
        id: 'actions',
        header: 'Actions',
        size: 100,
      },
    ],
    [fullDateTimeFormat]
  );

  const channelClientsTable = useTable({
    ...TableHelper.defaultProperties,
    columns: clientsColumns,
    data,
    allRowIds: data.map((client) => client.id),
    tableCellProps: () => ({
      padding: 4,
      borderColor: '#444',
      color: '#E0E0E0',
      fontSize: '0.85rem',
    }),
    headerCellRenderFns: {
      ip_address: renderHeaderCell,
      connected: renderHeaderCell,
      duration: renderHeaderCell,
      actions: renderHeaderCell,
    },
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    getExpandedRowHeight: (row) => {
      return 20 + 28 * row.original.streams.length;
    },
    expandedRowRenderer: ({ row }) => {
      return (
        <Box p="xs">
          <Group spacing="xs" align="flex-start">
            <Text size="xs" fw={500} color="dimmed">
              User Agent:
            </Text>
            <Text size="xs">{row.original.user_agent || 'Unknown'}</Text>
          </Group>
        </Box>
      );
    },
    mantineExpandButtonProps: ({ row, table }) => ({
      size: 'xs',
      style: {
        transform: row.getIsExpanded() ? 'rotate(180deg)' : 'rotate(-90deg)',
        transition: 'transform 0.2s',
      },
    }),
    displayColumnDefOptions: {
      'mrt-row-expand': {
        size: 15,
        header: '',
      },
      'mrt-row-actions': {
        size: 74,
      },
    },
  });

  // Get logo URL from the logos object if available
  const logoUrl = getLogoUrl(channel.logo_id, logos, previewedStream);

  useEffect(() => {
    let isMounted = true;
    // Only fetch if we have a stream_id and NO channel.name
    if (!channel.name && channel.stream_id) {
      getStreamsByIds(channel.stream_id).then((streams) => {
        if (isMounted && streams && streams.length > 0) {
          setPreviewedStream(streams[0]);
        }
      });
    }
    return () => {
      isMounted = false;
    };
  }, [channel.name, channel.stream_id]);

  const channelName =
    channel.name || previewedStream?.name || 'Unnamed Channel';
  const uptime = channel.uptime || 0;
  const bitrates = channel.bitrates || [];
  const totalBytes = channel.total_bytes || 0;
  const clientCount = channel.client_count || 0;
  const avgBitrate = channel.avg_bitrate || '0 Kbps';
  const streamProfileName = channel.stream_profile?.name || 'Unknown Profile';

  // Use currentM3UProfile if available, otherwise fall back to channel data
  const m3uProfileName =
    currentM3UProfile?.name ||
    channel.m3u_profile?.name ||
    channel.m3u_profile_name ||
    'Unknown M3U Profile';

  // Create select options for available streams
  const streamOptions = getStreamOptions(availableStreams, m3uAccountsMap);

  // Handle preview channel button click
  const handlePreviewChannel = () => {
    const channelDbId = channelsByUUID[channel.channel_id];
    if (!channelDbId) return;

    const actualChannel = channels[channelDbId];
    if (!actualChannel?.uuid) return;

    const uri = `/proxy/ts/stream/${actualChannel.uuid}`;
    let url = `${window.location.protocol}//${window.location.host}${uri}`;
    if (env_mode === 'dev') {
      url = `${window.location.protocol}//${window.location.hostname}:5656${uri}`;
    }

    showVideo(url);
  };

  if (location.pathname !== '/stats') {
    return <></>;
  }

  // Safety check - if channel doesn't have required data, don't render
  if (!channel || !channel.channel_id) {
    return null;
  }

  return (
    <Card
      key={channel.channel_id}
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{
        backgroundColor: '#27272A',
      }}
      color="#fff"
      maw={700}
      w={'100%'}
    >
      <Stack pos="relative">
        <Group justify="space-between" align="flex-start">
          <Box
            style={{
              alignItems: 'center',
              justifyContent: 'center',
            }}
            w={140}
            h={70}
            display="flex"
          >
            <img
              src={logoUrl || logo}
              style={{
                maxWidth: '100%',
                maxHeight: '100%',
                objectFit: 'contain',
              }}
              alt="channel logo"
            />
          </Box>

          <Group mt={10}>
            <Box>
              <Tooltip label={getStartDate(uptime)}>
                <Center>
                  <Timer pr={5} />
                  {toFriendlyDuration(uptime, 'seconds')}
                </Center>
              </Tooltip>
            </Box>
            <Center>
              <Tooltip label="Stop Channel">
                <ActionIcon
                  variant="transparent"
                  color="red.9"
                  onClick={() => stopChannel(channel.channel_id)}
                >
                  <SquareX size="24" />
                </ActionIcon>
              </Tooltip>
            </Center>
          </Group>
        </Group>

        {/* Stream Profile on right - absolutely positioned */}
        <Box pos="absolute" top={65} right={16} style={{ zIndex: 1 }}>
          <Tooltip label="Active Stream Profile">
            <Group gap={5}>
              <Video size="18" />
              {streamProfileName}
            </Group>
          </Tooltip>
        </Box>

        {/* M3U Profile on right - absolutely positioned */}
        <Box pos="absolute" top={95} right={16} style={{ zIndex: 1 }}>
          <Group gap={5}>
            <HardDriveUpload size="18" />
            <Tooltip label="Current M3U Profile">
              <Text size="xs">{m3uProfileName}</Text>
            </Tooltip>
          </Group>
        </Box>

        {/* Channel Name on left */}
        <Box mt={4}>
          <Text fw={500}>{channelName}</Text>
        </Box>

        {/* Display current program on its own line */}
        {currentProgram && (
          <Group gap={5} mt={-9} wrap="nowrap">
            <Radio size="14" style={{ color: '#22c55e', flexShrink: 0 }} />
            <Text size="xs" fw={500} c="green.5" style={{ flexShrink: 0 }}>
              Now Playing:
            </Text>
            <Text size="xs" c="dimmed" truncate>
              {currentProgram.title}
            </Text>
            <ActionIcon
              size="xs"
              variant="subtle"
              onClick={() => setIsProgramDescExpanded(!isProgramDescExpanded)}
              style={{ flexShrink: 0 }}
            >
              {isProgramDescExpanded ? (
                <ChevronDown size="14" />
              ) : (
                <ChevronRight size="14" />
              )}
            </ActionIcon>
          </Group>
        )}

        {/* Expandable program description */}
        {currentProgram &&
          isProgramDescExpanded &&
          currentProgram.description && (
            <Box mt={4} ml={24}>
              <Text size="xs" c="dimmed" style={{ fontStyle: 'italic' }}>
                {currentProgram.description}
              </Text>
            </Box>
          )}

        {/* Program progress bar */}
        {currentProgram &&
          isProgramDescExpanded &&
          currentProgram.start_time &&
          currentProgram.end_time &&
          (() => {
            const now = new Date();
            const startTime = new Date(currentProgram.start_time);
            const endTime = new Date(currentProgram.end_time);
            const totalDuration = (endTime - startTime) / 1000; // in seconds
            const elapsed = (now - startTime) / 1000; // in seconds
            const remaining = (endTime - now) / 1000; // in seconds
            const percentage = Math.min(
              100,
              Math.max(0, (elapsed / totalDuration) * 100)
            );

            const formatProgramTime = (seconds) => {
              const absSeconds = Math.abs(seconds);
              const hours = Math.floor(absSeconds / 3600);
              const minutes = Math.floor((absSeconds % 3600) / 60);
              const secs = Math.floor(absSeconds % 60);
              if (hours > 0) {
                return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
              }
              return `${minutes}:${secs.toString().padStart(2, '0')}`;
            };

            return (
              <Stack gap="xs" mt={4}>
                <Group justify="space-between" align="center">
                  <Text size="xs" c="dimmed">
                    {formatProgramTime(elapsed)} elapsed
                  </Text>
                  <Text size="xs" c="dimmed">
                    {formatProgramTime(remaining)} remaining
                  </Text>
                </Group>
                <Progress
                  value={percentage}
                  size="sm"
                  color="#3BA882"
                  style={{
                    backgroundColor: 'rgba(255, 255, 255, 0.1)',
                  }}
                />
              </Stack>
            );
          })()}

        {/* Add stream selection dropdown and preview button */}
        {availableStreams.length > 0 && (
          <Box mt={-10}>
            <Group align="flex-end" gap="xs">
              <Box style={{ flex: 1 }}>
                <Tooltip label="Switch to another stream source">
                  <Select
                    size="xs"
                    label="Active Stream"
                    placeholder={
                      isLoadingStreams ? 'Loading streams...' : 'Select stream'
                    }
                    data={streamOptions}
                    value={
                      activeStreamId || channel.stream_id?.toString() || null
                    }
                    onChange={handleStreamChange}
                    disabled={isLoadingStreams}
                  />
                </Tooltip>
              </Box>
              {channel.name && (
                <Tooltip label="Preview Channel">
                  <ActionIcon
                    size="md"
                    variant="transparent"
                    color={theme.tailwind.green[5]}
                    onClick={handlePreviewChannel}
                    style={{ marginBottom: 1 }}
                  >
                    <CirclePlay size="20" />
                  </ActionIcon>
                </Tooltip>
              )}
            </Group>
          </Box>
        )}

        {/* Add stream information badges */}
        <Group gap="xs" mt="5">
          {channel.resolution && (
            <Tooltip label="Video resolution">
              <Badge size="sm" variant="light" color="red">
                {channel.resolution}
              </Badge>
            </Tooltip>
          )}
          {channel.source_fps && (
            <Tooltip label="Source frames per second">
              <Badge size="sm" variant="light" color="orange">
                {channel.source_fps} FPS
              </Badge>
            </Tooltip>
          )}
          {channel.video_codec && (
            <Tooltip label="Video codec">
              <Badge size="sm" variant="light" color="blue">
                {channel.video_codec.toUpperCase()}
              </Badge>
            </Tooltip>
          )}
          {channel.audio_codec && (
            <Tooltip label="Audio codec">
              <Badge size="sm" variant="light" color="pink">
                {channel.audio_codec.toUpperCase()}
              </Badge>
            </Tooltip>
          )}
          {channel.audio_channels && (
            <Tooltip label="Audio channel configuration">
              <Badge size="sm" variant="light" color="pink">
                {channel.audio_channels}
              </Badge>
            </Tooltip>
          )}
          {channel.stream_type && (
            <Tooltip label="Stream type">
              <Badge size="sm" variant="light" color="cyan">
                {channel.stream_type.toUpperCase()}
              </Badge>
            </Tooltip>
          )}
          {channel.ffmpeg_speed && (
            <Tooltip
              label={`Current Speed: ${parseFloat(channel.ffmpeg_speed).toFixed(2)}x`}
            >
              <Badge
                size="sm"
                variant="light"
                color={
                  parseFloat(channel.ffmpeg_speed) >=
                  getBufferingSpeedThreshold(settings['proxy_settings'])
                    ? 'green'
                    : 'red'
                }
              >
                {parseFloat(channel.ffmpeg_speed).toFixed(2)}x
              </Badge>
            </Tooltip>
          )}
        </Group>

        <Group justify="space-between">
          <Group gap={4}>
            <Tooltip
              label={`Current bitrate: ${formatSpeed(bitrates.at(-1) || 0)}`}
            >
              <Group gap={4} style={{ cursor: 'help' }}>
                <Gauge pr={5} size="22" />
                <Text size="sm">{formatSpeed(bitrates.at(-1) || 0)}</Text>
              </Group>
            </Tooltip>
          </Group>

          <Tooltip label={`Average bitrate: ${avgBitrate}`}>
            <Text size="sm" style={{ cursor: 'help' }}>
              Avg: {avgBitrate}
            </Text>
          </Tooltip>

          <Group gap={4}>
            <Tooltip label={`Total transferred: ${formatBytes(totalBytes)}`}>
              <Group gap={4} style={{ cursor: 'help' }}>
                <HardDriveDownload size="18" />
                <Text size="sm">{formatBytes(totalBytes)}</Text>
              </Group>
            </Tooltip>
          </Group>

          <Group gap={5}>
            <Tooltip
              label={`${clientCount} active client${clientCount !== 1 ? 's' : ''}`}
            >
              <Group gap={4} style={{ cursor: 'help' }}>
                <Users size="18" />
                <Text size="sm">{clientCount}</Text>
              </Group>
            </Tooltip>
          </Group>
        </Group>

        <CustomTable table={channelClientsTable} />
      </Stack>
    </Card>
  );
};

export default StreamConnectionCard;
