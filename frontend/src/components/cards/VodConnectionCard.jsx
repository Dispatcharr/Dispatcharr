// Format duration for content length
import useLocalStorage from '../../hooks/useLocalStorage.jsx';
import React, { useCallback, useEffect, useState } from 'react';
import logo from '../../images/logo.png';
import { ActionIcon, Badge, Box, Card, Center, Flex, Group, Progress, Stack, Text, Tooltip } from '@mantine/core';
import { convertToSec, fromNow, toFriendlyDuration } from '../../utils/dateTimeUtils.js';
import { ChevronDown, HardDriveUpload, SquareX, Timer, Video } from 'lucide-react';
import {
  calculateConnectionDuration,
  calculateConnectionStartTime,
  calculateProgress,
  formatDuration,
  formatTime,
  getEpisodeDisplayTitle,
  getEpisodeSubtitle,
  getMovieDisplayTitle,
  getMovieSubtitle,
} from '../../utils/cards/VodConnectionCardUtils.js';

const ClientDetails = ({ connection, connectionStartTime }) => {
  return (
    <Stack
      gap="xs"
      style={{
        backgroundColor: 'rgba(255, 255, 255, 0.02)',
      }}
      p={12}
      bdrs={6}
      bd={'1px solid rgba(255, 255, 255, 0.08)'}
    >
      {connection.user_agent &&
        connection.user_agent !== 'Unknown' && (
          <Group gap={8} align="flex-start">
            <Text size="xs" fw={500} c="dimmed" miw={80}>
              User Agent:
            </Text>
            <Text size="xs" ff={'monospace'} flex={1}>
              {connection.user_agent.length > 100
                ? `${connection.user_agent.substring(0, 100)}...`
                : connection.user_agent}
            </Text>
          </Group>
        )}

      <Group gap={8}>
        <Text size="xs" fw={500} c="dimmed" miw={80}>
          Client ID:
        </Text>
        <Text size="xs" ff={'monospace'}>
          {connection.client_id || 'Unknown'}
        </Text>
      </Group>

      {connection.connected_at && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Connected:
          </Text>
          <Text size="xs">{connectionStartTime}</Text>
        </Group>
      )}

      {connection.duration && connection.duration > 0 && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Watch Duration:
          </Text>
          <Text size="xs">
            {toFriendlyDuration(connection.duration, 'seconds')}
          </Text>
        </Group>
      )}

      {/* Seek/Position Information */}
      {(connection.last_seek_percentage > 0 ||
        connection.last_seek_byte > 0) && (
        <>
          <Group gap={8}>
            <Text size="xs" fw={500} c="dimmed" miw={80}>
              Last Seek:
            </Text>
            <Text size="xs">
              {connection.last_seek_percentage?.toFixed(1)}%
              {connection.total_content_size > 0 && (
                <span style={{ color: 'var(--mantine-color-dimmed)' }}>
                  {' '}
                  ({Math.round(connection.last_seek_byte / (1024 * 1024))}
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
              <Text size="xs" fw={500} c="dimmed" miw={80}>
                Seek Time:
              </Text>
              <Text size="xs">
                {fromNow(convertToSec(Number(connection.last_seek_timestamp)))}
              </Text>
            </Group>
          )}
        </>
      )}

      {connection.bytes_sent > 0 && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Data Sent:
          </Text>
          <Text size="xs">
            {(connection.bytes_sent / (1024 * 1024)).toFixed(1)} MB
          </Text>
        </Group>
      )}
    </Stack>
  );
}

// Create a VOD Card component similar to ChannelCard
const VodConnectionCard = ({ vodContent, stopVODClient }) => {
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

  // Get display title
  const getDisplayTitle = () => {
    if (isMovie) {
      return getMovieDisplayTitle(vodContent);
    } else if (isEpisode) {
      return getEpisodeDisplayTitle(metadata);
    }
    return vodContent.content_name;
  };

  // Get subtitle info
  const getSubtitle = () => {
    if (isMovie) {
      return getMovieSubtitle(metadata);
    } else if (isEpisode) {
      return getEpisodeSubtitle(metadata);
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
  const getProgressInfo = useCallback(() => {
    return calculateProgress(connection, metadata.duration_secs);
  }, [connection, metadata.duration_secs]);

  // Calculate duration for connection
  const getConnectionDuration = useCallback((connection) => {
    return calculateConnectionDuration(connection);
  }, []);

  // Get connection start time for tooltip
  const getConnectionStartTime = useCallback(
    (connection) => {
      return calculateConnectionStartTime(connection, dateFormat);
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
        backgroundColor: '#27272A',
      }}
      color='#FFF'
      maw={700}
      w={'100%'}
    >
      <Stack pos='relative' >
        {/* Header with poster and basic info */}
        <Group justify="space-between">
          <Box h={100} display='flex'
            style={{
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
                  <Timer pr={5} />
                  {getConnectionDuration(connection)}
                </Center>
              </Tooltip>
            )}
            {connection && stopVODClient && (
              <Center>
                <Tooltip label="Stop VOD Connection">
                  <ActionIcon
                    variant="transparent"
                    color="red.9"
                    onClick={() => stopVODClient(connection.client_id)}
                  >
                    <SquareX size="24" />
                  </ActionIcon>
                </Tooltip>
              </Center>
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
                <HardDriveUpload size="18" mt={2} />
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
            const { totalTime, currentTime, percentage} = getProgressInfo();
            return totalTime > 0 ? (
              <Stack gap="xs" mt="sm">
                <Group justify="space-between" align="center">
                  <Text size="xs" fw={500} c="dimmed">
                    Progress
                  </Text>
                  <Text size="xs" c="dimmed">
                    {formatTime(currentTime)} /{' '}
                    {formatTime(totalTime)}
                  </Text>
                </Group>
                <Progress
                  value={percentage}
                  size="sm"
                  color="blue"
                  style={{
                    backgroundColor: 'rgba(255, 255, 255, 0.1)',
                  }}
                />
                <Text size="xs" c="dimmed" ta="center">
                  {percentage.toFixed(1)}% watched
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
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
              }}
              p={'8px 12px'}
              bdrs={6}
              bd={'1px solid rgba(255, 255, 255, 0.1)'}
              onClick={() => setIsClientExpanded(!isClientExpanded)}
            >
              <Group gap={8}>
                <Text size="sm" fw={500} color="dimmed">
                  Client:
                </Text>
                <Text size="sm" ff={'monospace'}>
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
                      ? 'rotate(0deg)'
                      : 'rotate(180deg)',
                    transition: 'transform 0.2s',
                  }}
                />
              </Group>
            </Group>

            {/* Expanded client details */}
            {isClientExpanded && (
              <ClientDetails
                connection={connection}
                connectionStartTime={getConnectionStartTime(connection)} />
            )}
          </Stack>
        )}
      </Stack>
    </Card>
  );
};

export default VodConnectionCard;