import React, { useMemo, useState, useEffect, useCallback } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Card,
  Center,
  Container,
  Flex,
  Group,
  Progress,
  SimpleGrid,
  Stack,
  Text,
  Title,
  Tooltip,
  Select,
  Badge,
  NumberInput,
} from '@mantine/core';
import { TableHelper } from '../helpers';
import API from '../api';
import useChannelsStore from '../store/channels';
import useLogosStore from '../store/logos';
import logo from '../images/logo.png';
import {
  ChevronDown,
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
import usePlaylistsStore from '../store/playlists'; // Add this import
import useSettingsStore from '../store/settings';
import { useLocation } from 'react-router-dom';
import { notifications } from '@mantine/notifications';
import { CustomTable, useTable } from '../components/tables/CustomTable';
import useLocalStorage from '../hooks/useLocalStorage';

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

// Create a VOD Card component similar to ChannelCard
const VODCard = ({ vodContent }) => {
  const [dateFormatSetting] = useLocalStorage('date-format', 'mdy');
  const dateFormat = dateFormatSetting === 'mdy' ? 'MM/DD' : 'DD/MM';
  const [isClientExpanded, setIsClientExpanded] = useState(false);
  const [, setUpdateTrigger] = useState(0); // Force re-renders for progress updates

  // Get metadata from the VOD content
  const metadata = vodContent.content_metadata || {};
  const contentType = vodContent.content_type;
  const isMovie = contentType === 'movie';
  const isEpisode = contentType === 'episode';

  // Set up timer to update progress every second
  useEffect(() => {
    const interval = setInterval(() => {
      setUpdateTrigger((prev) => prev + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  // Get the individual connection (since we now separate cards per connection)
  const connection =
    vodContent.individual_connection ||
    (vodContent.connections && vodContent.connections[0]);

  // Get poster/logo URL
  const posterUrl = metadata.logo_url || logo;

  // Format duration for content length
  const formatDuration = (seconds) => {
    if (!seconds) return 'Unknown';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
  };

  // Get display title
  const getDisplayTitle = () => {
    if (isMovie) {
      return vodContent.content_name;
    } else if (isEpisode) {
      const season = metadata.season_number
        ? `S${metadata.season_number.toString().padStart(2, '0')}`
        : 'S??';
      const episode = metadata.episode_number
        ? `E${metadata.episode_number.toString().padStart(2, '0')}`
        : 'E??';
      return `${metadata.series_name} - ${season}${episode}`;
    }
    return vodContent.content_name;
  };

  // Get subtitle info
  const getSubtitle = () => {
    if (isMovie) {
      const parts = [];
      if (metadata.genre) parts.push(metadata.genre);
      // We'll handle rating separately as a badge now
      return parts;
    } else if (isEpisode) {
      return [metadata.episode_name || 'Episode'];
    }
    return [];
  };

  // Render subtitle
  const renderSubtitle = () => {
    const subtitleParts = getSubtitle();
    if (subtitleParts.length === 0) return null;

    return (
      <Text size="sm" c="dimmed">
        {subtitleParts.join(' • ')}
      </Text>
    );
  };

  // Calculate progress percentage and time
  const calculateProgress = useCallback(() => {
    if (!connection || !metadata.duration_secs) {
      return {
        percentage: 0,
        currentTime: 0,
        totalTime: metadata.duration_secs || 0,
      };
    }

    const totalSeconds = metadata.duration_secs;
    let percentage = 0;
    let currentTime = 0;
    const now = Date.now() / 1000; // Current time in seconds

    // Priority 1: Use last_seek_percentage if available (most accurate from range requests)
    if (
      connection.last_seek_percentage &&
      connection.last_seek_percentage > 0 &&
      connection.last_seek_timestamp
    ) {
      // Calculate the position at the time of seek
      const seekPosition = Math.round(
        (connection.last_seek_percentage / 100) * totalSeconds
      );

      // Add elapsed time since the seek
      const elapsedSinceSeek = now - connection.last_seek_timestamp;
      currentTime = seekPosition + Math.floor(elapsedSinceSeek);

      // Don't exceed the total duration
      currentTime = Math.min(currentTime, totalSeconds);

      percentage = (currentTime / totalSeconds) * 100;
    }
    // Priority 2: Use position_seconds if available
    else if (connection.position_seconds && connection.position_seconds > 0) {
      currentTime = connection.position_seconds;
      percentage = (currentTime / totalSeconds) * 100;
    }

    return {
      percentage: Math.min(percentage, 100), // Cap at 100%
      currentTime: Math.max(0, currentTime), // Don't go negative
      totalTime: totalSeconds,
    };
  }, [connection, metadata.duration_secs]);

  // Format time for display (e.g., "1:23:45" or "23:45")
  const formatTime = (seconds) => {
    if (!seconds || seconds === 0) return '0:00';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    } else {
      return `${minutes}:${secs.toString().padStart(2, '0')}`;
    }
  };

  // Calculate duration for connection
  const calculateConnectionDuration = useCallback((connection) => {
    // If duration is provided by API, use it
    if (connection.duration && connection.duration > 0) {
      return dayjs.duration(connection.duration, 'seconds').humanize();
    }

    // Fallback: try to extract from client_id timestamp
    if (connection.client_id && connection.client_id.startsWith('vod_')) {
      try {
        const parts = connection.client_id.split('_');
        if (parts.length >= 2) {
          const clientStartTime = parseInt(parts[1]) / 1000; // Convert ms to seconds
          const currentTime = Date.now() / 1000;
          const duration = currentTime - clientStartTime;
          return dayjs.duration(duration, 'seconds').humanize();
        }
      } catch {
        // Ignore parsing errors
      }
    }

    return 'Unknown duration';
  }, []);

  // Get connection start time for tooltip
  const getConnectionStartTime = useCallback(
    (connection) => {
      if (connection.connected_at) {
        return dayjs(connection.connected_at * 1000).format(
          `${dateFormat} HH:mm:ss`
        );
      }

      // Fallback: calculate from client_id timestamp
      if (connection.client_id && connection.client_id.startsWith('vod_')) {
        try {
          const parts = connection.client_id.split('_');
          if (parts.length >= 2) {
            const clientStartTime = parseInt(parts[1]);
            return dayjs(clientStartTime).format(`${dateFormat} HH:mm:ss`);
          }
        } catch {
          // Ignore parsing errors
        }
      }

      return 'Unknown';
    },
    [dateFormat]
  );

  return (
    <Card
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{
        color: '#fff',
        backgroundColor: '#27272A',
        maxWidth: '700px',
        width: '100%',
      }}
    >
      <Stack style={{ position: 'relative' }}>
        {/* Header with poster and basic info */}
        <Group justify="space-between">
          <Box
            style={{
              //width: '150px',
              height: '100px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <img
              src={posterUrl}
              style={{
                maxWidth: '100%',
                maxHeight: '100%',
                objectFit: 'contain',
              }}
              alt="content poster"
            />
          </Box>

          <Group>
            {connection && (
              <Tooltip
                label={`Connected at ${getConnectionStartTime(connection)}`}
              >
                <Center>
                  <Timer style={{ paddingRight: 5 }} />
                  {calculateConnectionDuration(connection)}
                </Center>
              </Tooltip>
            )}
          </Group>
        </Group>

        {/* Title and type */}
        <Flex justify="space-between" align="center">
          <Group>
            <Text fw={500}>{getDisplayTitle()}</Text>
          </Group>

          <Tooltip label="Content Type">
            <Group gap={5}>
              <Video size="18" />
              {isMovie ? 'Movie' : 'TV Episode'}
            </Group>
          </Tooltip>
        </Flex>

        {/* Display M3U profile information - matching channel card style */}
        {connection &&
          connection.m3u_profile &&
          (connection.m3u_profile.profile_name ||
            connection.m3u_profile.account_name) && (
            <Flex justify="flex-end" align="flex-start" mt={-8}>
              <Group gap={5} align="flex-start">
                <HardDriveUpload size="18" style={{ marginTop: '2px' }} />
                <Stack gap={0}>
                  <Tooltip label="M3U Account">
                    <Text size="xs" fw={500}>
                      {connection.m3u_profile.account_name || 'Unknown Account'}
                    </Text>
                  </Tooltip>
                  <Tooltip label="M3U Profile">
                    <Text size="xs" c="dimmed">
                      {connection.m3u_profile.profile_name || 'Default Profile'}
                    </Text>
                  </Tooltip>
                </Stack>
              </Group>
            </Flex>
          )}

        {/* Subtitle/episode info */}
        {getSubtitle().length > 0 && (
          <Flex justify="flex-start" align="center" mt={-12}>
            {renderSubtitle()}
          </Flex>
        )}

        {/* Content information badges - streamlined to avoid duplication */}
        <Group gap="xs" mt={-4}>
          {metadata.year && (
            <Tooltip label="Release Year">
              <Badge size="sm" variant="light" color="orange">
                {metadata.year}
              </Badge>
            </Tooltip>
          )}

          {metadata.duration_secs && (
            <Tooltip label="Content Duration">
              <Badge size="sm" variant="light" color="blue">
                {formatDuration(metadata.duration_secs)}
              </Badge>
            </Tooltip>
          )}

          {metadata.rating && (
            <Tooltip label="Critic Rating (out of 10)">
              <Badge size="sm" variant="light" color="yellow">
                {parseFloat(metadata.rating).toFixed(1)}/10
              </Badge>
            </Tooltip>
          )}
        </Group>

        {/* Progress bar - show current position in content */}
        {connection &&
          metadata.duration_secs &&
          (() => {
            const progress = calculateProgress();
            return progress.totalTime > 0 ? (
              <Stack gap="xs" mt="sm">
                <Group justify="space-between" align="center">
                  <Text size="xs" fw={500} color="dimmed">
                    Progress
                  </Text>
                  <Text size="xs" color="dimmed">
                    {formatTime(progress.currentTime)} /{' '}
                    {formatTime(progress.totalTime)}
                  </Text>
                </Group>
                <Progress
                  value={progress.percentage}
                  size="sm"
                  color="blue"
                  style={{
                    backgroundColor: 'rgba(255, 255, 255, 0.1)',
                  }}
                />
                <Text size="xs" color="dimmed" ta="center">
                  {progress.percentage.toFixed(1)}% watched
                </Text>
              </Stack>
            ) : null;
          })()}

        {/* Client information section - collapsible like channel cards */}
        {connection && (
          <Stack gap="xs" mt="xs">
            {/* Client summary header - always visible */}
            <Group
              justify="space-between"
              align="center"
              style={{
                cursor: 'pointer',
                padding: '8px 12px',
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
                borderRadius: '6px',
                border: '1px solid rgba(255, 255, 255, 0.1)',
              }}
              onClick={() => setIsClientExpanded(!isClientExpanded)}
            >
              <Group gap={8}>
                <Text size="sm" fw={500} color="dimmed">
                  Client:
                </Text>
                <Text size="sm" style={{ fontFamily: 'monospace' }}>
                  {connection.client_ip || 'Unknown IP'}
                </Text>
              </Group>

              <Group gap={8}>
                <Text size="xs" color="dimmed">
                  {isClientExpanded ? 'Hide Details' : 'Show Details'}
                </Text>
                <ChevronDown
                  size={16}
                  style={{
                    transform: isClientExpanded
                      ? 'rotate(180deg)'
                      : 'rotate(0deg)',
                    transition: 'transform 0.2s',
                  }}
                />
              </Group>
            </Group>

            {/* Expanded client details */}
            {isClientExpanded && (
              <Stack
                gap="xs"
                style={{
                  padding: '12px',
                  backgroundColor: 'rgba(255, 255, 255, 0.02)',
                  borderRadius: '6px',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                }}
              >
                {connection.user_agent &&
                  connection.user_agent !== 'Unknown' && (
                    <Group gap={8} align="flex-start">
                      <Text
                        size="xs"
                        fw={500}
                        color="dimmed"
                        style={{ minWidth: '80px' }}
                      >
                        User Agent:
                      </Text>
                      <Text
                        size="xs"
                        style={{ fontFamily: 'monospace', flex: 1 }}
                      >
                        {connection.user_agent.length > 100
                          ? `${connection.user_agent.substring(0, 100)}...`
                          : connection.user_agent}
                      </Text>
                    </Group>
                  )}

                <Group gap={8}>
                  <Text
                    size="xs"
                    fw={500}
                    color="dimmed"
                    style={{ minWidth: '80px' }}
                  >
                    Client ID:
                  </Text>
                  <Text size="xs" style={{ fontFamily: 'monospace' }}>
                    {connection.client_id || 'Unknown'}
                  </Text>
                </Group>

                {connection.connected_at && (
                  <Group gap={8}>
                    <Text
                      size="xs"
                      fw={500}
                      color="dimmed"
                      style={{ minWidth: '80px' }}
                    >
                      Connected:
                    </Text>
                    <Text size="xs">{getConnectionStartTime(connection)}</Text>
                  </Group>
                )}

                {connection.duration && connection.duration > 0 && (
                  <Group gap={8}>
                    <Text
                      size="xs"
                      fw={500}
                      color="dimmed"
                      style={{ minWidth: '80px' }}
                    >
                      Watch Duration:
                    </Text>
                    <Text size="xs">
                      {dayjs
                        .duration(connection.duration, 'seconds')
                        .humanize()}
                    </Text>
                  </Group>
                )}

                {/* Seek/Position Information */}
                {(connection.last_seek_percentage > 0 ||
                  connection.last_seek_byte > 0) && (
                  <>
                    <Group gap={8}>
                      <Text
                        size="xs"
                        fw={500}
                        color="dimmed"
                        style={{ minWidth: '80px' }}
                      >
                        Last Seek:
                      </Text>
                      <Text size="xs">
                        {connection.last_seek_percentage?.toFixed(1)}%
                        {connection.total_content_size > 0 && (
                          <span
                            style={{ color: 'var(--mantine-color-dimmed)' }}
                          >
                            {' '}
                            (
                            {Math.round(
                              connection.last_seek_byte / (1024 * 1024)
                            )}
                            MB /{' '}
                            {Math.round(
                              connection.total_content_size / (1024 * 1024)
                            )}
                            MB)
                          </span>
                        )}
                      </Text>
                    </Group>

                    {Number(connection.last_seek_timestamp) > 0 && (
                      <Group gap={8}>
                        <Text
                          size="xs"
                          fw={500}
                          color="dimmed"
                          style={{ minWidth: '80px' }}
                        >
                          Seek Time:
                        </Text>
                        <Text size="xs">
                          {dayjs
                            .unix(Number(connection.last_seek_timestamp))
                            .fromNow()}
                        </Text>
                      </Group>
                    )}
                  </>
                )}

                {connection.bytes_sent > 0 && (
                  <Group gap={8}>
                    <Text
                      size="xs"
                      fw={500}
                      color="dimmed"
                      style={{ minWidth: '80px' }}
                    >
                      Data Sent:
                    </Text>
                    <Text size="xs">
                      {(connection.bytes_sent / (1024 * 1024)).toFixed(1)} MB
                    </Text>
                  </Group>
                )}
              </Stack>
            )}
          </Stack>
        )}
      </Stack>
    </Card>
  );
};

// Create a separate component for each channel card to properly handle the hook
const ChannelCard = ({
  channel,
  clients,
  stopClient,
  stopChannel,
  logos,
  channelsByUUID,
}) => {
  const location = useLocation();
  const [availableStreams, setAvailableStreams] = useState([]);
  const [isLoadingStreams, setIsLoadingStreams] = useState(false);
  const [activeStreamId, setActiveStreamId] = useState(null);
  const [currentM3UProfile, setCurrentM3UProfile] = useState(null); // Add state for current M3U profile
  const [data, setData] = useState([]);
  const [previewedStream, setPreviewedStream] = useState(null);

  // Get Date-format from localStorage
  const [dateFormatSetting] = useLocalStorage('date-format', 'mdy');
  const dateFormat = dateFormatSetting === 'mdy' ? 'MM/DD' : 'DD/MM';
  // Get M3U account data from the playlists store
  const m3uAccounts = usePlaylistsStore((s) => s.playlists);
  const [tableSize] = useLocalStorage('table-size', 'default');
  // Get settings for speed threshold
  const settings = useSettingsStore((s) => s.settings);

  // Parse proxy settings to get buffering_speed
  const getBufferingSpeedThreshold = () => {
    try {
      if (settings['proxy-settings']?.value) {
        const proxySettings = JSON.parse(settings['proxy-settings'].value);
        return parseFloat(proxySettings.buffering_speed) || 1.0;
      }
    } catch (error) {
      console.error('Error parsing proxy settings:', error);
    }
    return 1.0; // Default fallback
  };

  // Create a map of M3U account IDs to names for quick lookup
  const m3uAccountsMap = useMemo(() => {
    const map = {};
    if (m3uAccounts && Array.isArray(m3uAccounts)) {
      m3uAccounts.forEach((account) => {
        if (account.id) {
          map[account.id] = account.name;
        }
      });
    }
    return map;
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
          const streamData = await API.getChannelStreams(channelId);

          // Use streams in the order returned by the API without sorting
          setAvailableStreams(streamData);

          // If we have a channel URL, try to find the matching stream
          if (channel.url && streamData.length > 0) {
            // Try to find matching stream based on URL
            const matchingStream = streamData.find(
              (stream) =>
                channel.url.includes(stream.url) ||
                stream.url.includes(channel.url)
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

  // Handle stream switching
  const handleStreamChange = async (streamId) => {
    try {
      console.log('Switching to stream ID:', streamId);
      // Find the selected stream in availableStreams for debugging
      const selectedStream = availableStreams.find(
        (s) => s.id.toString() === streamId
      );
      console.log('Selected stream details:', selectedStream);

      // Make sure we're passing the correct ID to the API
      const response = await API.switchStream(channel.channel_id, streamId);
      console.log('Stream switch API response:', response);

      // Update the local active stream ID immediately
      setActiveStreamId(streamId);

      // Update M3U profile information if available in the response
      if (response && response.m3u_profile) {
        setCurrentM3UProfile(response.m3u_profile);
      } else if (selectedStream && selectedStream.m3u_profile) {
        // Fallback to the profile from the selected stream
        setCurrentM3UProfile(selectedStream.m3u_profile);
      }

      // Show detailed notification with stream name
      notifications.show({
        title: 'Stream switching',
        message: `Switching to "${selectedStream?.name}" for ${channel.name}`,
        color: 'blue.5',
      });

      // After a short delay, fetch streams again to confirm the switch
      setTimeout(async () => {
        try {
          const channelId = channelsByUUID[channel.channel_id];
          if (channelId) {
            const updatedStreamData = await API.getChannelStreams(channelId);
            console.log('Channel streams after switch:', updatedStreamData);

            // Update current stream information with fresh data
            const updatedStream = updatedStreamData.find(
              (s) => s.id.toString() === streamId
            );
            if (updatedStream && updatedStream.m3u_profile) {
              setCurrentM3UProfile(updatedStream.m3u_profile);
            }
          }
        } catch (error) {
          console.error('Error checking streams after switch:', error);
        }
      }, 2000);
    } catch (error) {
      console.error('Stream switch error:', error);
      notifications.show({
        title: 'Error switching stream',
        message: error.toString(),
        color: 'red.5',
      });
    }
  };
  console.log(data);

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
        accessorFn: (row) => {
          // Check for connected_since (which is seconds since connection)
          if (row.connected_since) {
            // Calculate the actual connection time by subtracting the seconds from current time
            const currentTime = dayjs();
            const connectedTime = currentTime.subtract(
              row.connected_since,
              'second'
            );
            return connectedTime.format(`${dateFormat} HH:mm:ss`);
          }

          // Fallback to connected_at if it exists
          if (row.connected_at) {
            const connectedTime = dayjs(row.connected_at * 1000);
            return connectedTime.format(`${dateFormat} HH:mm:ss`);
          }

          return 'Unknown';
        },
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
        accessorFn: (row) => {
          if (row.connected_since) {
            return dayjs.duration(row.connected_since, 'seconds').humanize();
          }

          if (row.connection_duration) {
            return dayjs
              .duration(row.connection_duration, 'seconds')
              .humanize();
          }

          return '-';
        },
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
        size: tableSize == 'compact' ? 75 : 100,
      },
    ],
    []
  );

  // This hook is now at the top level of this component
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
  const logoUrl =
    (channel.logo_id && logos && logos[channel.logo_id]
      ? logos[channel.logo_id].cache_url
      : null) ||
    (previewedStream && previewedStream.logo_url) ||
    null;

  useEffect(() => {
    let isMounted = true;
    // Only fetch if we have a stream_id and NO channel.name
    if (!channel.name && channel.stream_id) {
      API.getStreamsByIds([channel.stream_id]).then((streams) => {
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
  const streamOptions = availableStreams.map((stream) => {
    // Get account name from our mapping if it exists
    const accountName =
      stream.m3u_account && m3uAccountsMap[stream.m3u_account]
        ? m3uAccountsMap[stream.m3u_account]
        : stream.m3u_account
          ? `M3U #${stream.m3u_account}`
          : 'Unknown M3U';

    return {
      value: stream.id.toString(),
      label: `${stream.name || `Stream #${stream.id}`} [${accountName}]`,
    };
  });

  if (location.pathname != '/stats') {
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
        color: '#fff',
        backgroundColor: '#27272A',
        maxWidth: '700px',
        width: '100%',
      }}
    >
      <Stack style={{ position: 'relative' }}>
        <Group justify="space-between">
          <Box
            style={{
              width: '100px',
              height: '50px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
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

          <Group>
            <Box>
              <Tooltip label={getStartDate(uptime)}>
                <Center>
                  <Timer style={{ paddingRight: 5 }} />
                  {dayjs.duration(uptime, 'seconds').humanize()}
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

        <Flex justify="space-between" align="center">
          <Group>
            <Text fw={500}>{channelName}</Text>
          </Group>

          <Tooltip label="Active Stream Profile">
            <Group gap={5}>
              <Video size="18" />
              {streamProfileName}
            </Group>
          </Tooltip>
        </Flex>

        {/* Display M3U profile information */}
        <Flex justify="flex-end" align="center" mt={-8}>
          <Group gap={5}>
            <HardDriveUpload size="18" />
            <Tooltip label="Current M3U Profile">
              <Text size="xs">{m3uProfileName}</Text>
            </Tooltip>
          </Group>
        </Flex>

        {/* Add stream selection dropdown */}
        {availableStreams.length > 0 && (
          <Tooltip label="Switch to another stream source">
            <Select
              size="xs"
              label="Active Stream"
              placeholder={
                isLoadingStreams ? 'Loading streams...' : 'Select stream'
              }
              data={streamOptions}
              value={activeStreamId || channel.stream_id?.toString() || null}
              onChange={handleStreamChange}
              disabled={isLoadingStreams}
              style={{ marginTop: '8px' }}
            />
          </Tooltip>
        )}

        {/* Add stream information badges */}
        <Group gap="xs" mt="xs">
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
                  getBufferingSpeedThreshold()
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
                <Gauge style={{ paddingRight: 5 }} size="22" />
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

const ChannelsPage = () => {
  const channels = useChannelsStore((s) => s.channels);
  const channelsByUUID = useChannelsStore((s) => s.channelsByUUID);
  const channelStats = useChannelsStore((s) => s.stats);
  const setChannelStats = useChannelsStore((s) => s.setChannelStats);
  const logos = useLogosStore((s) => s.logos);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);

  const [clients, setClients] = useState([]);
  const [vodConnections, setVodConnections] = useState([]);
  const [channelHistory, setChannelHistory] = useState({});
  const [isPollingActive, setIsPollingActive] = useState(false);

  // Use localStorage for stats refresh interval (in seconds)
  const [refreshIntervalSeconds, setRefreshIntervalSeconds] = useLocalStorage(
    'stats-refresh-interval',
    5
  );
  const refreshInterval = refreshIntervalSeconds * 1000; // Convert to milliseconds

  const stopChannel = async (id) => {
    await API.stopChannel(id);
  };

  const stopClient = async (channelId, clientId) => {
    await API.stopClient(channelId, clientId);
  };

  // Function to fetch channel stats from API
  const fetchChannelStats = useCallback(async () => {
    try {
      const response = await API.fetchActiveChannelStats();
      if (response) {
        setChannelStats(response);
      } else {
        console.log('API response was empty or null');
      }
    } catch (error) {
      console.error('Error fetching channel stats:', error);
      console.error('Error details:', {
        message: error.message,
        status: error.status,
        body: error.body,
      });
    }
  }, [setChannelStats]);

  const fetchVODStats = useCallback(async () => {
    try {
      const response = await API.getVODStats();
      if (response) {
        setVodConnections(response.vod_connections || []);
      } else {
        console.log('VOD API response was empty or null');
      }
    } catch (error) {
      console.error('Error fetching VOD stats:', error);
      console.error('Error details:', {
        message: error.message,
        status: error.status,
        body: error.body,
      });
    }
  }, []);

  // Set up polling for stats when on stats page
  useEffect(() => {
    const location = window.location;
    const isOnStatsPage = location.pathname === '/stats';

    if (isOnStatsPage && refreshInterval > 0) {
      setIsPollingActive(true);

      // Initial fetch
      fetchChannelStats();
      fetchVODStats();

      // Set up interval
      const interval = setInterval(() => {
        fetchChannelStats();
        fetchVODStats();
      }, refreshInterval);

      return () => {
        clearInterval(interval);
        setIsPollingActive(false);
      };
    } else {
      setIsPollingActive(false);
    }
  }, [refreshInterval, fetchChannelStats, fetchVODStats]);

  // Fetch initial stats on component mount (for immediate data when navigating to page)
  useEffect(() => {
    fetchChannelStats();
    fetchVODStats();
  }, [fetchChannelStats, fetchVODStats]);

  useEffect(() => {
    console.log('Processing channel stats:', channelStats);
    if (
      !channelStats ||
      !channelStats.channels ||
      !Array.isArray(channelStats.channels) ||
      channelStats.channels.length === 0
    ) {
      console.log('No channel stats available:', channelStats);
      // Clear clients and channel history when there are no stats
      setClients([]);
      setChannelHistory({});
      return;
    }

    // Use functional update to access previous state without dependency
    setChannelHistory((prevChannelHistory) => {
      // Create a completely new object based only on current channel stats
      const stats = {};
      const newChannelHistory = {}; // Start fresh instead of preserving old channels

      channelStats.channels.forEach((ch) => {
        // Make sure we have a valid channel_id
        if (!ch.channel_id) {
          console.warn('Found channel without channel_id:', ch);
          return;
        }

        let bitrates = [];
        if (prevChannelHistory[ch.channel_id]) {
          bitrates = [...(prevChannelHistory[ch.channel_id].bitrates || [])];
          const bitrate =
            ch.total_bytes - prevChannelHistory[ch.channel_id].total_bytes;
          if (bitrate > 0) {
            bitrates.push(bitrate);
          }

          if (bitrates.length > 15) {
            bitrates = bitrates.slice(1);
          }
        }

        // Find corresponding channel data
        const channelData =
          channelsByUUID && ch.channel_id
            ? channels[channelsByUUID[ch.channel_id]]
            : null;

        // Find stream profile
        const streamProfile = streamProfiles.find(
          (profile) => profile.id == parseInt(ch.stream_profile)
        );

        const channelWithMetadata = {
          ...ch,
          ...(channelData || {}), // Safely merge channel data if available
          bitrates,
          stream_profile: streamProfile || { name: 'Unknown' },
          // Make sure stream_id is set from the active stream info
          stream_id: ch.stream_id || null,
        };

        stats[ch.channel_id] = channelWithMetadata;
        newChannelHistory[ch.channel_id] = channelWithMetadata; // Only add currently active channels
      });

      console.log('Processed active channels:', stats);

      // Update clients based on new stats
      const clientStats = Object.values(stats).reduce((acc, ch) => {
        if (ch.clients && Array.isArray(ch.clients)) {
          return acc.concat(
            ch.clients.map((client) => ({
              ...client,
              channel: ch,
            }))
          );
        }
        return acc;
      }, []);
      setClients(clientStats);

      return newChannelHistory; // Return only currently active channels
    });
  }, [channelStats, channels, channelsByUUID, streamProfiles]);

  // Combine active streams and VOD connections into a single mixed list
  const combinedConnections = useMemo(() => {
    const activeStreams = Object.values(channelHistory).map((channel) => ({
      type: 'stream',
      data: channel,
      id: channel.channel_id,
      sortKey: channel.uptime || 0, // Use uptime for sorting streams
    }));

    // Flatten VOD connections so each individual client gets its own card
    const vodItems = vodConnections.flatMap((vodContent) => {
      return (vodContent.connections || []).map((connection, index) => ({
        type: 'vod',
        data: {
          ...vodContent,
          // Override the connections array to contain only this specific connection
          connections: [connection],
          connection_count: 1, // Each card now represents a single connection
          // Add individual connection details at the top level for easier access
          individual_connection: connection,
        },
        id: `${vodContent.content_type}-${vodContent.content_uuid}-${connection.client_id}-${index}`,
        sortKey: connection.connected_at || Date.now() / 1000, // Use connection time for sorting
      }));
    });

    // Combine and sort by newest connections first (higher sortKey = more recent)
    return [...activeStreams, ...vodItems].sort(
      (a, b) => b.sortKey - a.sortKey
    );
  }, [channelHistory, vodConnections]);

  return (
    <Box style={{ overflowX: 'auto' }}>
      <Box style={{ padding: '10px', borderBottom: '1px solid #444' }}>
        <Group justify="space-between" align="center">
          <Title order={3}>Active Connections</Title>
          <Group align="center">
            <Text size="sm" c="dimmed">
              {Object.keys(channelHistory).length} stream
              {Object.keys(channelHistory).length !== 1 ? 's' : ''} •{' '}
              {vodConnections.reduce(
                (total, vodContent) =>
                  total + (vodContent.connections?.length || 0),
                0
              )}{' '}
              VOD connection
              {vodConnections.reduce(
                (total, vodContent) =>
                  total + (vodContent.connections?.length || 0),
                0
              ) !== 1
                ? 's'
                : ''}
            </Text>
            <Group align="center" gap="xs">
              <Text size="sm">Refresh Interval (seconds):</Text>
              <NumberInput
                value={refreshIntervalSeconds}
                onChange={(value) => setRefreshIntervalSeconds(value || 0)}
                min={0}
                max={300}
                step={1}
                size="xs"
                style={{ width: 120 }}
              />
              {refreshIntervalSeconds === 0 && (
                <Text size="sm" c="dimmed">
                  Refreshing disabled
                </Text>
              )}
            </Group>
            {isPollingActive && refreshInterval > 0 && (
              <Text size="sm" c="dimmed">
                Refreshing every {refreshIntervalSeconds}s
              </Text>
            )}
            <Button
              size="xs"
              variant="subtle"
              onClick={() => {
                fetchChannelStats();
                fetchVODStats();
              }}
              loading={false}
            >
              Refresh Now
            </Button>
          </Group>
        </Group>
      </Box>
      <div
        style={{
          display: 'grid',
          gap: '1rem',
          padding: '10px',
          gridTemplateColumns: 'repeat(auto-fill, minmax(500px, 1fr))',
        }}
      >
        {combinedConnections.length === 0 ? (
          <Box
            style={{
              gridColumn: '1 / -1',
              textAlign: 'center',
              padding: '40px',
            }}
          >
            <Text size="xl" color="dimmed">
              No active connections
            </Text>
          </Box>
        ) : (
          combinedConnections.map((connection) => {
            if (connection.type === 'stream') {
              return (
                <ChannelCard
                  key={connection.id}
                  channel={connection.data}
                  clients={clients}
                  stopClient={stopClient}
                  stopChannel={stopChannel}
                  logos={logos}
                  channelsByUUID={channelsByUUID}
                />
              );
            } else if (connection.type === 'vod') {
              return (
                <VODCard key={connection.id} vodContent={connection.data} />
              );
            }
            return null;
          })
        )}
      </div>
    </Box>
  );
};

export default ChannelsPage;
