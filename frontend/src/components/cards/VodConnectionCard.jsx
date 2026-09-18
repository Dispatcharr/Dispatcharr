// Format duration for content length
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import logo from '../../images/logo.png';
import {
  ActionIcon,
  Badge,
  Box,
  Card,
  Center,
  Flex,
  Group,
  Progress,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import {
  formatDuration,
  fromNow,
  toFriendlyDuration,
  useDateTimeFormat,
} from '../../utils/dateTimeUtils.js';
import {
  ChevronDown,
  Eye,
  HardDriveUpload,
  Shuffle,
  SquareX,
  Timer,
  Video,
} from 'lucide-react';
import {
  calculateConnectionDuration,
  calculateConnectionStartTime,
  calculateProgress,
  getEpisodeDisplayTitle,
  getEpisodeSubtitle,
  getMovieDisplayTitle,
  getMovieSubtitle,
} from '../../utils/cards/VodConnectionCardUtils.js';
import useUsersStore from '../../store/users.jsx';
import VODCandidateSourcesModal from '../VODCandidateSourcesModal.jsx';

const ClientDetails = ({ connection, connectionStartTime }) => {
  const technical = connection.technical_metadata || {};
  const audio = technical.audio_languages || technical.languages || [];
  const subtitles = technical.subtitle_languages || [];
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
      {connection.user_agent && connection.user_agent !== 'Unknown' && (
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

      {typeof connection.provider_connection_active === 'boolean' && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Provider HTTP:
          </Text>
          <Text size="xs">
            {connection.provider_connection_active ? 'Connected' : 'Closed'}
          </Text>
        </Group>
      )}

      {connection.slot_reserved && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Provider slot:
          </Text>
          <Text size="xs">
            Reserved
            {connection.reconnect_seconds_remaining !== null &&
            connection.reconnect_seconds_remaining !== undefined
              ? ` · up to ${toFriendlyDuration(
                  connection.reconnect_seconds_remaining,
                  'seconds'
                )}`
              : ''}
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
                  {Math.round(connection.total_content_size / (1024 * 1024))}
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
                {fromNow(Number(connection.last_seek_timestamp) * 1000)}
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

      {connection.delivery_mode && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Delivery:
          </Text>
          <Text size="xs">
            {connection.delivery_mode === 'proxy_passthrough'
              ? 'Byte proxy (pass-through)'
              : connection.delivery_mode}
          </Text>
        </Group>
      )}

      {(connection.source_container || technical.container_extension) && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Source Format:
          </Text>
          <Text size="xs">
            {(
              connection.source_container || technical.container_extension
            ).toUpperCase()}
          </Text>
        </Group>
      )}

      {(connection.delivered_container ||
        connection.delivered_content_type) && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Delivered Format:
          </Text>
          <Text size="xs">
            {connection.delivered_container
              ? connection.delivered_container.toUpperCase()
              : connection.delivered_content_type}
            {connection.delivered_content_type &&
              connection.delivered_container &&
              ` (${connection.delivered_content_type})`}
          </Text>
        </Group>
      )}

      {(technical.resolution || technical.height) && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Resolution:
          </Text>
          <Text size="xs">
            {technical.resolution || `${technical.height}p`}
          </Text>
        </Group>
      )}

      {audio.length > 0 && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Audio:
          </Text>
          <Text size="xs">{audio.join(', ')}</Text>
        </Group>
      )}

      {subtitles.length > 0 && (
        <Group gap={8}>
          <Text size="xs" fw={500} c="dimmed" miw={80}>
            Subtitles:
          </Text>
          <Text size="xs">{subtitles.join(', ')}</Text>
        </Group>
      )}
    </Stack>
  );
};

const ConnectionProgress = ({ connection, durationSecs }) => {
  const { totalTime, currentTime, percentage } = calculateProgress(
    connection,
    durationSecs
  );
  return totalTime > 0 ? (
    <Stack gap="xs" mt="sm">
      <Group justify="space-between" align="center">
        <Text size="xs" fw={500} c="dimmed">
          Progress
        </Text>
        <Text size="xs" c="dimmed">
          {formatDuration(currentTime)} / {formatDuration(totalTime)}
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
};

// Create a VOD Card component similar to ChannelCard
const VodConnectionCard = ({
  vodContent,
  stopVODClient,
  switchVODSource,
  openVODDetails,
}) => {
  const { fullDateTimeFormat } = useDateTimeFormat();
  const [isClientExpanded, setIsClientExpanded] = useState(false);
  const [sourceOrderOpen, setSourceOrderOpen] = useState(false);
  const users = useUsersStore((s) => s.users);
  const usersMap = useMemo(() => {
    const map = {};
    users.forEach((u) => {
      map[String(u.id)] = u.username;
    });
    return map;
  }, [users]);
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
  const source = connection?.source || {};
  const technical = connection?.technical_metadata || {};
  const reconnectSecondsRemaining = connection?.reconnect_expires_at
    ? Math.max(
        0,
        Math.ceil(connection.reconnect_expires_at - Date.now() / 1000)
      )
    : connection?.reconnect_seconds_remaining;
  const canInspectSources = Boolean(
    connection?.client_id &&
    source.access_policy_id &&
    source.access_policy_export_mode === 'compact' &&
    source.canonical_id &&
    source.relation_id
  );
  const detailContentType =
    source.detail_content_type || (isMovie ? 'movie' : null);
  const detailCanonicalId =
    source.detail_canonical_id || (isMovie ? source.canonical_id : null);
  const canOpenDetails = Boolean(
    openVODDetails && detailContentType && detailCanonicalId
  );

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

  // Calculate duration for connection
  const getConnectionDuration = useCallback((connection) => {
    return calculateConnectionDuration(connection);
  }, []);

  // Get connection start time for tooltip
  const getConnectionStartTime = useCallback(
    (connection) => {
      return calculateConnectionStartTime(connection, fullDateTimeFormat);
    },
    [fullDateTimeFormat]
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
      color="#FFF"
      maw={700}
      w={'100%'}
    >
      <Stack pos="relative">
        {/* Header with poster and basic info */}
        <Group justify="space-between">
          <Box
            h={100}
            display="flex"
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
            {connection?.connection_state === 'reconnecting' && (
              <Tooltip
                multiline
                maw={360}
                label={`The provider HTTP connection is closed. Dispatcharr keeps only the logical source and provider slot reserved for the player's next Range request${Number.isFinite(reconnectSecondsRemaining) ? ` for up to ${toFriendlyDuration(reconnectSecondsRemaining, 'seconds')}` : ''}.`}
              >
                <Badge color="yellow" variant="light">
                  Buffered / reconnecting
                  {Number.isFinite(reconnectSecondsRemaining)
                    ? ` · ${toFriendlyDuration(reconnectSecondsRemaining, 'seconds')}`
                    : ''}
                </Badge>
              </Tooltip>
            )}
            {connection?.source_switch_pending && (
              <Badge color="orange" variant="light">
                Source switch pending
              </Badge>
            )}
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
            {canInspectSources && switchVODSource && (
              <Center>
                <Tooltip label="View or switch Compact source">
                  <ActionIcon
                    variant="transparent"
                    color="blue"
                    aria-label="View or switch Compact source"
                    onClick={() => setSourceOrderOpen(true)}
                  >
                    <Shuffle size="22" />
                  </ActionIcon>
                </Tooltip>
              </Center>
            )}
            {canOpenDetails && (
              <Center>
                <Tooltip label="Open VOD details">
                  <ActionIcon
                    variant="transparent"
                    color="blue"
                    aria-label={`Open details for ${getDisplayTitle()}`}
                    onClick={() =>
                      openVODDetails({
                        id: detailCanonicalId,
                        name: getDisplayTitle(),
                        contentType: detailContentType,
                        content_type: detailContentType,
                        relation_id: source.detail_relation_id,
                      })
                    }
                  >
                    <Eye size="22" />
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
          (source.label ||
            connection.m3u_profile?.profile_name ||
            connection.m3u_profile?.account_name) && (
            <Flex justify="flex-end" align="flex-start" mt={-8}>
              <Group gap={5} align="flex-start">
                <HardDriveUpload size="18" mt={2} />
                <Stack gap={0}>
                  <Tooltip label="M3U account and VOD category">
                    <Text size="xs" fw={500}>
                      {source.label ||
                        connection.m3u_profile?.account_name ||
                        'Unknown Account'}
                    </Text>
                  </Tooltip>
                  {connection.m3u_profile?.profile_name && (
                    <Tooltip label="M3U Profile">
                      <Text size="xs" c="dimmed">
                        {connection.m3u_profile.profile_name}
                      </Text>
                    </Tooltip>
                  )}
                  {source.stream_id && (
                    <Text size="xs" c="dimmed">
                      Stream ID: {source.stream_id}
                    </Text>
                  )}
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
                {formatDuration(metadata.duration_secs, {
                  zeroValue: 'Unknown',
                  precision: 'human',
                })}
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
          {(technical.resolution || technical.height) && (
            <Badge size="sm" variant="light" color="cyan">
              {technical.resolution || `${technical.height}p`}
            </Badge>
          )}
          {(technical.audio_languages || technical.languages || []).map(
            (language) => (
              <Badge key={`audio-${language}`} size="sm" variant="light">
                Audio {language}
              </Badge>
            )
          )}
          {(technical.subtitle_languages || []).map((language) => (
            <Badge key={`subtitle-${language}`} size="sm" variant="outline">
              Subs {language}
            </Badge>
          ))}
        </Group>

        {/* Progress bar - show current position in content */}
        {connection && metadata.duration_secs && (
          <ConnectionProgress
            connection={connection}
            durationSecs={metadata.duration_secs}
          />
        )}

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
                  Client IP:
                </Text>
                <Text size="sm" ff={'monospace'}>
                  {connection.client_ip || 'Unknown IP'}
                </Text>
                {usersMap[String(connection.user_id)] && (
                  <>
                    <Text size="sm" c="dimmed">
                      User:
                    </Text>
                    <Text size="sm">
                      {usersMap[String(connection.user_id)]}
                    </Text>
                  </>
                )}
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
                connectionStartTime={getConnectionStartTime(connection)}
              />
            )}
          </Stack>
        )}
      </Stack>
      <VODCandidateSourcesModal
        opened={sourceOrderOpen}
        onClose={() => setSourceOrderOpen(false)}
        profileId={source.access_policy_id}
        contentType={contentType}
        canonicalId={source.canonical_id}
        currentRelationId={source.relation_id}
        title={getDisplayTitle()}
        onSwitch={(relationId, mode) =>
          switchVODSource(connection.client_id, relationId, mode)
        }
      />
    </Card>
  );
};

export default VodConnectionCard;
