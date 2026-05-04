import useChannelsStore from '../../store/channels.jsx';
import useSettingsStore from '../../store/settings.jsx';
import useVideoStore from '../../store/useVideoStore.jsx';
import {
  format,
  isAfter,
  isBefore,
  useDateTimeFormat,
  useTimeHelpers,
} from '../../utils/dateTimeUtils.js';
import { notifications } from '@mantine/notifications';
import React from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Flex,
  Group,
  Image,
  Menu,
  Modal,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { AlertTriangle, Plus, Square, SquareX } from 'lucide-react';
import defaultLogo from '../../images/logo.png';
import RecordingSynopsis from '../RecordingSynopsis';
import {
  deleteRecordingById,
  deleteSeriesAndRule,
  extendRecordingById,
  getChannelLogoUrl,
  getPosterUrl,
  getRecordingUrl,
  getSeasonLabel,
  getSeriesInfo,
  getShowVideoUrl,
  removeRecording,
  runComSkip,
  stopRecordingById,
} from './../../utils/cards/RecordingCardUtils.js';

const areRecordingPropsEqual = (prev, next) => {
  const pr = prev.recording;
  const nr = next.recording;
  if (!pr || !nr) return pr === nr;

  const pcp = pr.custom_properties || {};
  const ncp = nr.custom_properties || {};

  return (
    pr.id === nr.id &&
    pr.start_time === nr.start_time &&
    pr.end_time === nr.end_time &&
    pr._group_count === nr._group_count &&
    pcp.status === ncp.status &&
    pcp.poster_logo_id === ncp.poster_logo_id &&
    pcp.poster_url === ncp.poster_url &&
    pcp.file_url === ncp.file_url &&
    pcp.output_file_url === ncp.output_file_url &&
    pcp.comskip?.status === ncp.comskip?.status &&
    pcp.program?.title === ncp.program?.title &&
    prev.channel?.id === next.channel?.id
  );
};

const RecordingCard = ({
  recording,
  onOpenDetails,
  onOpenRecurring,
  channel: channelProp = null,
}) => {
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const { toUserTime, userNow } = useTimeHelpers();
  const { timeFormat: timeformat, dateFormat: dateformat } =
    useDateTimeFormat();

  const channel = channelProp;

  const customProps = recording.custom_properties || {};
  const program = customProps.program || {};
  const recordingName = program.title || 'Custom Recording';
  const subTitle = program.sub_title || '';
  const description = program.description || customProps.description || '';
  const isRecurringRule = customProps?.rule?.type === 'recurring';

  // Poster or channel logo (getPosterUrl falls back to Dispatcharr default logo)
  const posterUrl = getPosterUrl(
    customProps.poster_logo_id,
    customProps,
    getChannelLogoUrl(channel)
  );

  const start = toUserTime(recording.start_time);
  const end = toUserTime(recording.end_time);
  const now = userNow();
  const status = customProps.status;
  const isTimeActive = isAfter(now, start) && isBefore(now, end);
  const isInterrupted = status === 'interrupted';
  const isInProgress =
    isTimeActive &&
    !isInterrupted &&
    status !== 'completed' &&
    status !== 'stopped';
  const isUpcoming = isBefore(now, start);
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
    showVideo(getShowVideoUrl(channel, env_mode), 'live', {
      name: channel.name,
    });
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

  const handleExtend = async (minutes, e) => {
    e?.stopPropagation?.();
    try {
      await extendRecordingById(recording.id, minutes);
      notifications.show({
        title: 'Recording extended',
        message: `Added ${minutes} minutes to this recording`,
        color: 'teal',
        autoClose: 2000,
      });
    } catch (error) {
      console.error('Failed to extend recording', error);
      notifications.show({
        title: 'Extension failed',
        message: 'Could not extend the recording',
        color: 'red',
        autoClose: 3000,
      });
    }
  };

  // Stop / Cancel / Delete state and handlers
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [stopConfirmOpen, setStopConfirmOpen] = React.useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const handleStopClick = (e) => {
    e.stopPropagation();
    setStopConfirmOpen(true);
  };

  const handleDeleteClick = (e) => {
    e.stopPropagation();
    if (isRecurringRule) {
      onOpenRecurring?.(recording, true);
      return;
    }
    if (isSeriesGroup) {
      setCancelOpen(true);
    } else {
      setDeleteConfirmOpen(true);
    }
  };

  const confirmStop = async () => {
    try {
      setBusy(true);
      await stopRecordingById(recording.id);
    } catch (error) {
      console.error('Failed to stop recording', error);
    } finally {
      setBusy(false);
      setStopConfirmOpen(false);
      try {
        await fetchRecordings();
      } catch {}
    }
  };

  const confirmDelete = async () => {
    try {
      setBusy(true);
      removeRecording(recording.id);
    } finally {
      setBusy(false);
      setDeleteConfirmOpen(false);
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
  };

  const WatchLive = () => {
    return (
      <Button
        size="xs"
        variant="light"
        onClick={(e) => {
          e.stopPropagation();
          handleWatchLive();
        }}
      >
        Watch Live
      </Button>
    );
  };

  const WatchRecording = () => {
    return (
      <Tooltip
        label={
          customProps.file_url || customProps.output_file_url
            ? isInProgress
              ? 'Watch in progress recording'
              : 'Watch recording'
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
          disabled={!(customProps.file_url || customProps.output_file_url)}
        >
          Watch
        </Button>
      </Tooltip>
    );
  };

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
        display: 'flex',
        flexDirection: 'column',
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
            </Group>
          </Stack>
        </Group>

        <Group gap={4}>
          {isInProgress && (
            <Tooltip label="Extend recording">
              <Box display="inline-flex">
                <Menu withinPortal position="bottom-end" shadow="md">
                  <Menu.Target>
                    <ActionIcon
                      variant="transparent"
                      color="teal.5"
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Plus size={20} />
                    </ActionIcon>
                  </Menu.Target>
                  <Menu.Dropdown onClick={(e) => e.stopPropagation()}>
                    <Menu.Label>Extend recording by</Menu.Label>
                    <Menu.Item onClick={(e) => handleExtend(15, e)}>
                      +15 minutes
                    </Menu.Item>
                    <Menu.Item onClick={(e) => handleExtend(30, e)}>
                      +30 minutes
                    </Menu.Item>
                    <Menu.Item onClick={(e) => handleExtend(60, e)}>
                      +1 hour
                    </Menu.Item>
                  </Menu.Dropdown>
                </Menu>
              </Box>
            </Tooltip>
          )}
          {isInProgress && (
            <Tooltip label="Stop recording (keep partial content)">
              <ActionIcon
                variant="transparent"
                color="yellow.6"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={handleStopClick}
              >
                <Square size="20" fill="currentColor" />
              </ActionIcon>
            </Tooltip>
          )}
          <Tooltip
            label={
              isInProgress
                ? 'Cancel & delete'
                : isUpcoming
                  ? 'Cancel'
                  : 'Delete'
            }
          >
            <ActionIcon
              variant="transparent"
              color="red.9"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={handleDeleteClick}
            >
              <SquareX size="20" />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Flex>

      <Flex gap="sm" align="flex-start" style={{ flex: 1 }}>
        <Image
          src={posterUrl}
          w={64}
          h={64}
          fit="contain"
          radius="sm"
          alt={recordingName}
          fallbackSrc={getChannelLogoUrl(channel) || defaultLogo}
        />
        <Stack gap={6} flex={1} style={{ alignSelf: 'stretch' }}>
          {subTitle && (
            <Group justify="space-between">
              <Text size="sm" c="dimmed">
                Episode
              </Text>
              <Text size="sm" fw={700} title={subTitle}>
                {subTitle}
              </Text>
            </Group>
          )}
          {seLabel && (
            <Group justify="space-between">
              <Text size="sm" c="dimmed">
                Season/Episode
              </Text>
              <Text size="sm" fw={700}>
                {seLabel}
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
              {format(start, `${dateformat}, YYYY ${timeformat}`)} –{' '}
              {format(end, timeformat)}
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

          <Group
            justify="flex-end"
            gap="xs"
            pt={4}
            style={{ marginTop: 'auto' }}
          >
            {isInProgress && <WatchLive />}

            {!isUpcoming && <WatchRecording />}
            {!isUpcoming &&
              (customProps?.status === 'completed' ||
                customProps?.status === 'stopped' ||
                customProps?.status === 'interrupted') &&
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

  // Confirmation modals for stop and cancel/delete
  const ConfirmModals = (
    <>
      <Modal
        opened={stopConfirmOpen}
        onClose={() => setStopConfirmOpen(false)}
        title="Stop Recording"
        centered
        size="md"
        zIndex={9999}
      >
        <Stack gap="sm">
          <Text>
            The recording will be stopped early. The portion already recorded
            will be saved and available for playback.
          </Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setStopConfirmOpen(false)}
              disabled={busy}
            >
              Go Back
            </Button>
            <Button color="yellow" loading={busy} onClick={confirmStop}>
              Stop Recording
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
        title={
          isInProgress || isUpcoming ? 'Cancel Recording' : 'Delete Recording'
        }
        centered
        size="md"
        zIndex={9999}
      >
        <Stack gap="sm">
          <Text>
            {isInProgress
              ? 'The recording will be cancelled and all recorded content will be permanently deleted.'
              : isUpcoming
                ? 'This scheduled recording will be cancelled.'
                : 'This recording and all associated files will be permanently deleted.'}
          </Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setDeleteConfirmOpen(false)}
              disabled={busy}
            >
              Go Back
            </Button>
            <Button color="red" loading={busy} onClick={confirmDelete}>
              {isInProgress
                ? 'Cancel & Delete'
                : isUpcoming
                  ? 'Cancel'
                  : 'Delete'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );

  if (!isSeriesGroup)
    return (
      <>
        {ConfirmModals}
        {MainCard}
      </>
    );

  // Stacked look for series groups: render two shadow layers behind the main card
  return (
    <Box style={{ position: 'relative' }}>
      {ConfirmModals}
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

export default React.memo(RecordingCard, areRecordingPropsEqual);
