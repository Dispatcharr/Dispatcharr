import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import logo from '../../images/logo.png';
import {
  ActionIcon,
  Badge,
  Box,
  Card,
  Center,
  Group,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import {
  ChevronDown,
  HardDriveUpload,
  History,
  SquareX,
  Timer,
} from 'lucide-react';
import ProgramPreview from '../ProgramPreview.jsx';
import {
  calculateConnectionDuration,
  calculateConnectionStartTime,
  computeCatchupPlaybackSeconds,
  getConnectionDurationSeconds,
} from '../../utils/cards/TimeshiftConnectionCardUtils.js';
import { useDateTimeFormat } from '../../utils/dateTimeUtils.js';
import { getLogoUrl } from '../../utils/cards/StreamConnectionCardUtils.js';
import useUsersStore from '../../store/users.jsx';

const ClientDetails = ({ connection, connectionStartTime }) => (
  <Stack
    gap="xs"
    style={{ backgroundColor: 'rgba(255, 255, 255, 0.02)' }}
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
        Session ID:
      </Text>
      <Text size="xs" ff={'monospace'}>
        {connection.session_id || connection.client_id || 'Unknown'}
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

    {connection.duration > 0 && (
      <Group gap={8}>
        <Text size="xs" fw={500} c="dimmed" miw={80}>
          Watch Duration:
        </Text>
        <Text size="xs">
          {calculateConnectionDuration(connection)}
        </Text>
      </Group>
    )}

    {connection.bytes_streamed > 0 && (
      <Group gap={8}>
        <Text size="xs" fw={500} c="dimmed" miw={80}>
          Data Sent:
        </Text>
        <Text size="xs">
          {(connection.bytes_streamed / (1024 * 1024)).toFixed(1)} MB
        </Text>
      </Group>
    )}

    {connection.avg_bitrate_kbps > 0 && (
      <Group gap={8}>
        <Text size="xs" fw={500} c="dimmed" miw={80}>
          Avg Bitrate:
        </Text>
        <Text size="xs">
          {connection.avg_bitrate_kbps > 1000
            ? `${(connection.avg_bitrate_kbps / 1000).toFixed(2)} Mbps`
            : `${connection.avg_bitrate_kbps.toFixed(0)} Kbps`}
        </Text>
      </Group>
    )}
  </Stack>
);

const TimeshiftConnectionCard = ({
  timeshiftSession,
  currentProgram,
  stopTimeshiftSession,
  logos,
}) => {
  const { fullDateTimeFormat } = useDateTimeFormat();
  const [isClientExpanded, setIsClientExpanded] = useState(false);
  const users = useUsersStore((s) => s.users);
  const [, setUpdateTrigger] = useState(0);

  const usersMap = useMemo(() => {
    const map = {};
    users.forEach((u) => {
      map[String(u.id)] = u.username;
    });
    return map;
  }, [users]);

  useEffect(() => {
    const interval = setInterval(() => {
      setUpdateTrigger((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const connection =
    timeshiftSession.individual_connection ||
    (timeshiftSession.connections && timeshiftSession.connections[0]);

  const logoUrl =
    timeshiftSession.logo_url ||
    getLogoUrl(timeshiftSession.logo_id, logos) ||
    logo;

  const programmePreview = useMemo(() => {
    if (currentProgram?.title) {
      return {
        title: currentProgram.title,
        description: currentProgram.description,
        start_time: currentProgram.start_time,
        end_time: currentProgram.end_time,
        duration_secs: currentProgram.duration_secs,
      };
    }
    if (timeshiftSession.programme_start) {
      return {
        title: `Catch-up @ ${timeshiftSession.programme_start}`,
      };
    }
    return null;
  }, [currentProgram, timeshiftSession.programme_start]);

  const m3uProfileName =
    connection?.m3u_profile?.profile_name ||
    connection?.m3u_profile?.account_name ||
    null;

  // Play position from URL timestamp + EPG window + stream-open anchor.
  const playbackBaseRef = useRef({ base: null, receivedAtMs: 0, paused: false });
  useEffect(() => {
    const computed = computeCatchupPlaybackSeconds({
      programmeStart: timeshiftSession.programme_start,
      programStartTime: programmePreview?.start_time,
      programDurationSecs: programmePreview?.duration_secs,
      positionAnchorAt: timeshiftSession.position_anchor_at,
      playbackBaseSecs: timeshiftSession.playback_base_secs,
      paused: Boolean(timeshiftSession.paused),
      nowMs: Date.now(),
    });
    if (computed != null) {
      playbackBaseRef.current = {
        base: computed,
        receivedAtMs: Date.now(),
        paused: Boolean(timeshiftSession.paused),
      };
    }
  }, [
    timeshiftSession.programme_start,
    timeshiftSession.position_anchor_at,
    timeshiftSession.playback_base_secs,
    timeshiftSession.paused,
    programmePreview?.start_time,
    programmePreview?.duration_secs,
  ]);

  const {
    base: playbackBase,
    receivedAtMs: playbackReceivedAtMs,
    paused: playbackPaused,
  } = playbackBaseRef.current;
  const playbackElapsedSeconds =
    playbackBase != null
      ? playbackPaused
        ? playbackBase
        : playbackBase + (Date.now() - playbackReceivedAtMs) / 1000
      : getConnectionDurationSeconds(connection);

  const getConnectionStartTime = useCallback(
    (conn) => calculateConnectionStartTime(conn, fullDateTimeFormat),
    [fullDateTimeFormat]
  );

  return (
    <Card
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{ backgroundColor: '#27272A' }}
      color="#FFF"
      maw={700}
      w={'100%'}
    >
      <Stack pos="relative">
        <Group justify="space-between" align="flex-start">
          <Box
            style={{ alignItems: 'center', justifyContent: 'center' }}
            w={140}
            h={70}
            display="flex"
          >
            <img
              src={logoUrl}
              style={{
                maxWidth: '100%',
                maxHeight: '100%',
                objectFit: 'contain',
              }}
              alt="channel logo"
            />
          </Box>

          <Group mt={10}>
            {connection && (
              <Tooltip
                label={`Connected at ${getConnectionStartTime(connection)}`}
              >
                <Center>
                  <Timer pr={5} />
                  {calculateConnectionDuration(connection)}
                </Center>
              </Tooltip>
            )}
            {connection && stopTimeshiftSession && (
              <Center>
                <Tooltip label="Stop Catch-up Session">
                  <ActionIcon
                    variant="transparent"
                    color="red.9"
                    onClick={() =>
                      stopTimeshiftSession(
                        connection.session_id || connection.client_id,
                      )
                    }
                  >
                    <SquareX size="24" />
                  </ActionIcon>
                </Tooltip>
              </Center>
            )}
          </Group>
        </Group>

        {m3uProfileName && (
          <Box pos="absolute" top={95} right={16} style={{ zIndex: 1 }}>
            <Group gap={5}>
              <HardDriveUpload size="18" />
              <Tooltip label="Current M3U Profile">
                <Text size="xs">{m3uProfileName}</Text>
              </Tooltip>
            </Group>
          </Box>
        )}

        <Group gap={6} mt={4} align="center" wrap="nowrap">
          <Text fw={500}>{timeshiftSession.channel_name || 'Catch-up'}</Text>
          <Tooltip label="Catch-up session">
            <Box
              component="span"
              role="img"
              aria-label="Catch-up session"
              style={{ display: 'inline-flex' }}
            >
              <History size={16} color="#9ca3af" aria-hidden="true" />
            </Box>
          </Tooltip>
        </Group>

        {programmePreview && (
          <Box mt={-9}>
            <ProgramPreview
              program={programmePreview}
              timelineMode="catchup"
              label={timeshiftSession.paused ? 'Paused:' : 'Watching:'}
              accentColor={timeshiftSession.paused ? 'yellow.5' : 'green.5'}
              accentIconColor={timeshiftSession.paused ? '#eab308' : '#22c55e'}
              playbackElapsedSeconds={playbackElapsedSeconds}
            />
          </Box>
        )}

        <Group gap="xs" mt="5">
          {timeshiftSession.resolution && (
            <Tooltip label="Video resolution">
              <Badge size="sm" variant="light" color="red">
                {timeshiftSession.resolution}
              </Badge>
            </Tooltip>
          )}
          {timeshiftSession.source_fps && (
            <Tooltip label="Source frames per second">
              <Badge size="sm" variant="light" color="orange">
                {timeshiftSession.source_fps} FPS
              </Badge>
            </Tooltip>
          )}
          {timeshiftSession.video_codec && (
            <Tooltip label="Video codec">
              <Badge size="sm" variant="light" color="blue">
                {timeshiftSession.video_codec.toUpperCase()}
              </Badge>
            </Tooltip>
          )}
          {timeshiftSession.audio_codec && (
            <Tooltip label="Audio codec">
              <Badge size="sm" variant="light" color="pink">
                {timeshiftSession.audio_codec.toUpperCase()}
              </Badge>
            </Tooltip>
          )}
          {timeshiftSession.audio_channels && (
            <Tooltip label="Audio channel configuration">
              <Badge size="sm" variant="light" color="pink">
                {timeshiftSession.audio_channels}
              </Badge>
            </Tooltip>
          )}
          {timeshiftSession.stream_type && (
            <Tooltip label="Stream type">
              <Badge size="sm" variant="light" color="cyan">
                {timeshiftSession.stream_type.toUpperCase()}
              </Badge>
            </Tooltip>
          )}
        </Group>

        {connection && (
          <Stack gap="xs" mt="xs">
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
                  {connection.ip_address || 'Unknown IP'}
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
                    transform: isClientExpanded ? 'rotate(0deg)' : 'rotate(180deg)',
                    transition: 'transform 0.2s',
                  }}
                />
              </Group>
            </Group>

            {isClientExpanded && (
              <ClientDetails
                connection={connection}
                connectionStartTime={getConnectionStartTime(connection)}
              />
            )}
          </Stack>
        )}
      </Stack>
    </Card>
  );
};

export default TimeshiftConnectionCard;
