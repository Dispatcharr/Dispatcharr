import useChannelsStore from '../../store/channels.jsx';
import useSettingsStore from '../../store/settings.jsx';
import useVideoStore from '../../store/useVideoStore.jsx';
import { useDateTimeFormat, useTimeHelpers } from '../../utils/dateTimeUtils.js';
import { notifications } from '@mantine/notifications';
import React from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Flex,
  Group,
  Image,
  Modal,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { AlertTriangle, SquareX } from 'lucide-react';
import RecordingSynopsis from '../RecordingSynopsis';
import {
  deleteRecordingById,
  deleteSeriesAndRule,
  getPosterUrl,
  getRecordingUrl,
  getSeasonLabel,
  getSeriesInfo,
  getShowVideoUrl,
  removeRecording,
  runComSkip,
} from './../../utils/cards/RecordingCardUtils.js';

const RecordingCard = ({ recording, onOpenDetails, onOpenRecurring }) => {
  const channels = useChannelsStore((s) => s.channels);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const { toUserTime, userNow } = useTimeHelpers();
  const [timeformat, dateformat] = useDateTimeFormat();

  const channel = channels?.[recording.channel];

  const customProps = recording.custom_properties || {};
  const program = customProps.program || {};
  const recordingName = program.title || 'Custom Recording';
  const subTitle = program.sub_title || '';
  const description = program.description || customProps.description || '';
  const isRecurringRule = customProps?.rule?.type === 'recurring';

  // Poster or channel logo
  const posterUrl = getPosterUrl(
    customProps.poster_logo_id, customProps, channel?.logo?.cache_url, env_mode);

  const start = toUserTime(recording.start_time);
  const end = toUserTime(recording.end_time);
  const now = userNow();
  const status = customProps.status;
  const isTimeActive = now.isAfter(start) && now.isBefore(end);
  const isInterrupted = status === 'interrupted';
  const isInProgress = isTimeActive; // Show as recording by time, regardless of status glitches
  const isUpcoming = now.isBefore(start);
  const isSeriesGroup = Boolean(
    recording._group_count && recording._group_count > 1
  );
  // Season/Episode display if present
  const season = customProps.season ?? program?.custom_properties?.season;
  const episode = customProps.episode ?? program?.custom_properties?.episode;
  const onscreen =
    customProps.onscreen_episode ??
    program?.custom_properties?.onscreen_episode;
  const seLabel = getSeasonLabel(season, episode, onscreen);

  const handleWatchLive = () => {
    if (!channel) return;
    showVideo(getShowVideoUrl(channel, env_mode), 'live');
  };

  const handleWatchRecording = () => {
    // Only enable if backend provides a playable file URL in custom properties
    const fileUrl = getRecordingUrl(customProps, env_mode);
    if (!fileUrl) return;

    showVideo(fileUrl, 'vod', {
      name: recordingName,
      logo: { url: posterUrl },
    });
  };

  const handleRunComskip = async (e) => {
    e?.stopPropagation?.();
    try {
      await runComSkip(recording);
      notifications.show({
        title: 'Removing commercials',
        message: 'Queued comskip for this recording',
        color: 'blue.5',
        autoClose: 2000,
      });
    } catch (error) {
      console.error('Failed to queue comskip for recording', error);
    }
  };

  // Cancel handling for series groups
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const handleCancelClick = (e) => {
    e.stopPropagation();
    if (isRecurringRule) {
      onOpenRecurring?.(recording, true);
      return;
    }
    if (isSeriesGroup) {
      setCancelOpen(true);
    } else {
      removeRecording(recording.id);
    }
  };

  const seriesInfo = getSeriesInfo(customProps);

  const removeUpcomingOnly = async () => {
    try {
      setBusy(true);
      await deleteRecordingById(recording.id);
    } finally {
      setBusy(false);
      setCancelOpen(false);
      try {
        await fetchRecordings();
      } catch (error) {
        console.error('Failed to refresh recordings', error);
      }
    }
  };

  const removeSeriesAndRule = async () => {
    try {
      setBusy(true);
      await deleteSeriesAndRule(seriesInfo);
    } finally {
      setBusy(false);
      setCancelOpen(false);
      try {
        await fetchRecordings();
      } catch (error) {
        console.error(
          'Failed to refresh recordings after series removal',
          error
        );
      }
    }
  };

  const handleOnMainCardClick = () => {
    if (isRecurringRule) {
      onOpenRecurring?.(recording, false);
    } else {
      onOpenDetails?.(recording);
    }
  }

  const WatchLive = () => {
    return <Button
      size="xs"
      variant="light"
      onClick={(e) => {
        e.stopPropagation();
        handleWatchLive();
      }}
    >
      Watch Live
    </Button>;
  }

  const WatchRecording = () => {
    return <Tooltip
      label={
        customProps.file_url || customProps.output_file_url
          ? 'Watch recording'
          : 'Recording playback not available yet'
      }
    >
      <Button
        size="xs"
        variant="default"
        onClick={(e) => {
          e.stopPropagation();
          handleWatchRecording();
        }}
        disabled={
          customProps.status === 'recording' || !(customProps.file_url || customProps.output_file_url)
        }
      >
        Watch
      </Button>
    </Tooltip>;
  }

  const MainCard = (
    <Card
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{
        color: '#fff',
        backgroundColor: isInterrupted ? '#2b1f20' : '#27272A',
        borderColor: isInterrupted ? '#a33' : undefined,
        height: '100%',
        cursor: 'pointer',
      }}
      onClick={handleOnMainCardClick}
    >
      <Flex justify="space-between" align="center" pb={8}>
        <Group gap={8} flex={1} miw={0}>
          <Badge
            color={
              isInterrupted
                ? 'red.7'
                : isInProgress
                  ? 'red.6'
                  : isUpcoming
                    ? 'yellow.6'
                    : 'gray.6'
            }
          >
            {isInterrupted
              ? 'Interrupted'
              : isInProgress
                ? 'Recording'
                : isUpcoming
                  ? 'Scheduled'
                  : 'Completed'}
          </Badge>
          {isInterrupted && <AlertTriangle size={16} color="#ffa94d" />}
          <Stack gap={2} flex={1} miw={0}>
            <Group gap={8} wrap="nowrap">
              <Text fw={600} lineClamp={1} title={recordingName}>
                {recordingName}
              </Text>
              {isSeriesGroup && (
                <Badge color="teal" variant="filled">
                  Series
                </Badge>
              )}
              {isRecurringRule && (
                <Badge color="blue" variant="light">
                  Recurring
                </Badge>
              )}
              {seLabel && !isSeriesGroup && (
                <Badge color="gray" variant="light">
                  {seLabel}
                </Badge>
              )}
            </Group>
          </Stack>
        </Group>

        <Center>
          <Tooltip label={isUpcoming || isInProgress ? 'Cancel' : 'Delete'}>
            <ActionIcon
              variant="transparent"
              color="red.9"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={handleCancelClick}
            >
              <SquareX size="20" />
            </ActionIcon>
          </Tooltip>
        </Center>
      </Flex>

      <Flex gap="sm" align="center">
        <Image
          src={posterUrl}
          w={64}
          h={64}
          fit="contain"
          radius="sm"
          alt={recordingName}
          fallbackSrc="/logo.png"
        />
        <Stack gap={6} flex={1}>
          {!isSeriesGroup && subTitle && (
            <Group justify="space-between">
              <Text size="sm" c="dimmed">
                Episode
              </Text>
              <Text size="sm" fw={700} title={subTitle}>
                {subTitle}
              </Text>
            </Group>
          )}
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              Channel
            </Text>
            <Text size="sm">
              {channel ? `${channel.channel_number} • ${channel.name}` : '—'}
            </Text>
          </Group>

          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              {isSeriesGroup ? 'Next recording' : 'Time'}
            </Text>
            <Text size="sm">
              {start.format(`${dateformat}, YYYY ${timeformat}`)} – {end.format(timeformat)}
            </Text>
          </Group>

          {!isSeriesGroup && description && (
            <RecordingSynopsis
              description={description}
              onOpen={() => onOpenDetails?.(recording)}
            />
          )}

          {isInterrupted && customProps.interrupted_reason && (
            <Text size="xs" c="red.4">
              {customProps.interrupted_reason}
            </Text>
          )}

          <Group justify="flex-end" gap="xs" pt={4}>
            {isInProgress && <WatchLive />}

            {!isUpcoming && <WatchRecording />}
            {!isUpcoming &&
              customProps?.status === 'completed' &&
              (!customProps?.comskip ||
                customProps?.comskip?.status !== 'completed') && (
                <Button
                  size="xs"
                  variant="light"
                  color="teal"
                  onClick={handleRunComskip}
                >
                  Remove commercials
                </Button>
              )}
          </Group>
        </Stack>
      </Flex>
      {/* If this card is a grouped upcoming series, show count */}
      {recording._group_count > 1 && (
        <Text
          size="xs"
          c="dimmed"
          style={{ position: 'absolute', bottom: 6, right: 12 }}
        >
          Next of {recording._group_count}
        </Text>
      )}
    </Card>
  );
  if (!isSeriesGroup) return MainCard;

  // Stacked look for series groups: render two shadow layers behind the main card
  return (
    <Box style={{ position: 'relative' }}>
      <Modal
        opened={cancelOpen}
        onClose={() => setCancelOpen(false)}
        title="Cancel Series"
        centered
        size="md"
        zIndex={9999}
      >
        <Stack gap="sm">
          <Text>This is a series rule. What would you like to cancel?</Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              loading={busy}
              onClick={removeUpcomingOnly}
            >
              Only this upcoming
            </Button>
            <Button color="red" loading={busy} onClick={removeSeriesAndRule}>
              Entire series + rule
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Box
        style={{
          position: 'absolute',
          inset: 0,
          transform: 'translate(10px, 10px) rotate(-1deg)',
          borderRadius: 12,
          backgroundColor: '#1f1f23',
          border: '1px solid #2f2f34',
          boxShadow: '0 6px 18px rgba(0,0,0,0.35)',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />
      <Box
        style={{
          position: 'absolute',
          inset: 0,
          transform: 'translate(5px, 5px) rotate(1deg)',
          borderRadius: 12,
          backgroundColor: '#232327',
          border: '1px solid #333',
          boxShadow: '0 4px 12px rgba(0,0,0,0.30)',
          pointerEvents: 'none',
          zIndex: 1,
        }}
      />
      <Box style={{ position: 'relative', zIndex: 2 }}>{MainCard}</Box>
    </Box>
  );
};

export default RecordingCard;