import useChannelsStore from '../../store/channels.jsx';
import API from '../../api';
import {
  useDateTimeFormat,
  useTimeHelpers,
} from '../../utils/dateTimeUtils.js';
import React from 'react';
import {
  Badge,
  Button,
  Card,
  Flex,
  Group,
  Image,
  Modal,
  Stack,
  Text,
} from '@mantine/core';
import useVideoStore from '../../store/useVideoStore.jsx';
import { notifications } from '@mantine/notifications';
import {
  deleteRecordingById,
  getPosterUrl,
  getRecordingUrl,
  getSeasonLabel,
  getShowVideoUrl,
  runComSkip,
} from '../../utils/cards/RecordingCardUtils.js';
import {
  getRating,
  getStatRows,
  getUpcomingEpisodes,
} from '../../utils/forms/RecordingDetailsModalUtils.js';

const RecordingDetailsModal = ({
  opened,
  onClose,
  recording,
  channel,
  posterUrl,
  onWatchLive,
  onWatchRecording,
  env_mode,
  onEdit,
}) => {
  const allRecordings = useChannelsStore((s) => s.recordings);
  // Local channel cache to avoid the global channels map
  const [channelsById, setChannelsById] = React.useState({});
  const { toUserTime, userNow } = useTimeHelpers();
  const [childOpen, setChildOpen] = React.useState(false);
  const [childRec, setChildRec] = React.useState(null);
  const { timeFormat: timeformat, dateFormat: dateformat } =
    useDateTimeFormat();

  const safeRecording = recording || {};
  const customProps = safeRecording.custom_properties || {};
  const program = customProps.program || {};
  const recordingName = program.title || 'Custom Recording';
  const description = program.description || customProps.description || '';
  const start = toUserTime(safeRecording.start_time);
  const end = toUserTime(safeRecording.end_time);
  const stats = customProps.stream_info || {};

  const statRows = getStatRows(stats);

  // Rating (if available)
  const rating = getRating(customProps, program);
  const ratingSystem = customProps.rating_system || 'MPAA';

  const fileUrl = customProps.file_url || customProps.output_file_url;
  const canWatchRecording =
    (customProps.status === 'completed' ||
      customProps.status === 'interrupted') &&
    Boolean(fileUrl);

  const isSeriesGroup = Boolean(
    safeRecording._group_count && safeRecording._group_count > 1
  );
  const upcomingEpisodes = React.useMemo(() => {
    return getUpcomingEpisodes(
      isSeriesGroup,
      allRecordings,
      program,
      toUserTime,
      userNow
    );
  }, [
    allRecordings,
    isSeriesGroup,
    program.tvg_id,
    program.title,
    toUserTime,
    userNow,
  ]);

  // Ensure channel is available for a given id
  const loadChannel = React.useCallback(
    async (id) => {
      if (!id) {
        return null;
      }

      const existing = channelsById[id];
      if (existing) {
        return existing;
      }

      try {
        const ch = await API.getChannel(id);
        if (ch && ch.id === id) {
          setChannelsById((prev) => ({ ...prev, [id]: ch }));
          return ch;
        }
      } catch (e) {
        console.warn(
          'Failed to fetch channel for RecordingDetailsModal',
          id,
          e
        );
      }
      return null;
    },
    [channelsById]
  );

  // When opening a child episode, fetch that episode's channel
  React.useEffect(() => {
    if (!childOpen || !childRec) return;
    loadChannel(childRec.channel);
  }, [childOpen, childRec, loadChannel]);

  const handleOnWatchLive = () => {
    const rec = childRec;
    const now = userNow();
    const s = toUserTime(rec.start_time);
    const e = toUserTime(rec.end_time);

    if (now.isAfter(s) && now.isBefore(e)) {
      const ch =
        channelsById[rec.channel] ||
        (rec.channel === recording?.channel ? channel : null);
      if (!ch) return;
      useVideoStore.getState().showVideo(getShowVideoUrl(ch, env_mode), 'live');
    }
  };

  const handleOnWatchRecording = () => {
    let fileUrl = getRecordingUrl(childRec.custom_properties, env_mode);
    if (!fileUrl) return;

    const ch =
      channelsById[childRec.channel] ||
      (childRec.channel === recording?.channel ? channel : null);
    useVideoStore.getState().showVideo(fileUrl, 'vod', {
      name: childRec.custom_properties?.program?.title || 'Recording',
      logo: {
        url: getPosterUrl(
          childRec.custom_properties?.poster_logo_id,
          undefined,
          ch?.logo?.cache_url
        ),
      },
    });
  };

  const handleRunComskip = async (e) => {
    e.stopPropagation?.();
    try {
      await runComSkip(recording);
      notifications.show({
        title: 'Removing commercials',
        message: 'Queued comskip for this recording',
        color: 'blue.5',
        autoClose: 2000,
      });
    } catch (error) {
      console.error('Failed to run comskip', error);
    }
  };

  if (!recording) return null;

  const EpisodeRow = ({ rec }) => {
    const cp = rec.custom_properties || {};
    const pr = cp.program || {};
    const start = toUserTime(rec.start_time);
    const end = toUserTime(rec.end_time);
    const season = cp.season ?? pr?.custom_properties?.season;
    const episode = cp.episode ?? pr?.custom_properties?.episode;
    const onscreen =
      cp.onscreen_episode ?? pr?.custom_properties?.onscreen_episode;
    const se = getSeasonLabel(season, episode, onscreen);
    const posterLogoId = cp.poster_logo_id;
    const purl = getPosterUrl(posterLogoId, cp, posterUrl);

    const onRemove = async (e) => {
      e?.stopPropagation?.();
      try {
        await deleteRecordingById(rec.id);
      } catch (error) {
        console.error('Failed to delete upcoming recording', error);
      }
      try {
        await useChannelsStore.getState().fetchRecordings();
      } catch (error) {
        console.error('Failed to refresh recordings after delete', error);
      }
    };

    const handleOnMainCardClick = () => {
      setChildRec(rec);
      setChildOpen(true);
    };

    return (
      <Card
        withBorder
        radius="md"
        padding="sm"
        style={{ backgroundColor: '#27272A', cursor: 'pointer' }}
        onClick={handleOnMainCardClick}
      >
        <Flex gap="sm" align="center">
          <Image
            src={purl}
            w={64}
            h={64}
            fit="contain"
            radius="sm"
            alt={pr.title || recordingName}
            fallbackSrc="/logo.png"
          />
          <Stack gap={4} flex={1}>
            <Group justify="space-between">
              <Text
                fw={600}
                size="sm"
                lineClamp={1}
                title={pr.sub_title || pr.title}
              >
                {pr.sub_title || pr.title}
              </Text>
              {se && (
                <Badge color="gray" variant="light">
                  {se}
                </Badge>
              )}
            </Group>
            <Text size="xs">
              {start.format(`${dateformat}, YYYY ${timeformat}`)} –{' '}
              {end.format(timeformat)}
            </Text>
          </Stack>
          <Group gap={6}>
            <Button size="xs" color="red" variant="light" onClick={onRemove}>
              Remove
            </Button>
          </Group>
        </Flex>
      </Card>
    );
  };

  const WatchLive = () => {
    return (
      <Button
        size="xs"
        variant="light"
        onClick={(e) => {
          e.stopPropagation?.();
          onWatchLive();
        }}
      >
        Watch Live
      </Button>
    );
  };

  const WatchRecording = () => {
    return (
      <Button
        size="xs"
        variant="default"
        onClick={(e) => {
          e.stopPropagation?.();
          onWatchRecording();
        }}
        disabled={!canWatchRecording}
      >
        Watch
      </Button>
    );
  };

  const Edit = () => {
    return (
      <Button
        size="xs"
        variant="light"
        color="blue"
        onClick={(e) => {
          e.stopPropagation?.();
          onEdit(recording);
        }}
      >
        Edit
      </Button>
    );
  };

  const Series = () => {
    return (
      <Stack gap={10}>
        {upcomingEpisodes.length === 0 && (
          <Text size="sm" c="dimmed">
            No upcoming episodes found
          </Text>
        )}
        {upcomingEpisodes.map((ep) => (
          <EpisodeRow key={`ep-${ep.id}`} rec={ep} />
        ))}
        {childOpen && childRec && (
          <RecordingDetailsModal
            opened={childOpen}
            onClose={() => setChildOpen(false)}
            recording={childRec}
            channel={channelsById[childRec.channel]}
            posterUrl={getPosterUrl(
              childRec.custom_properties?.poster_logo_id,
              childRec.custom_properties,
              channelsById[childRec.channel]?.logo?.cache_url
            )}
            env_mode={env_mode}
            onWatchLive={handleOnWatchLive}
            onWatchRecording={handleOnWatchRecording}
          />
        )}
      </Stack>
    );
  };

  const Movie = () => {
    return (
      <Flex gap="lg" align="flex-start">
        <Image
          src={posterUrl}
          w={180}
          h={240}
          fit="contain"
          radius="sm"
          alt={recordingName}
          fallbackSrc="/logo.png"
        />
        <Stack gap={8} style={{ flex: 1 }}>
          <Group justify="space-between" align="center">
            <Text c="dimmed" size="sm">
              {channel ? `${channel.channel_number} • ${channel.name}` : '—'}
            </Text>
            <Group gap={8}>
              {onWatchLive && <WatchLive />}
              {onWatchRecording && <WatchRecording />}
              {onEdit && start.isAfter(userNow()) && <Edit />}
              {customProps.status === 'completed' &&
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
          </Group>
          <Text size="sm">
            {start.format(`${dateformat}, YYYY ${timeformat}`)} –{' '}
            {end.format(timeformat)}
          </Text>
          {rating && (
            <Group gap={8}>
              <Badge color="yellow" title={ratingSystem}>
                {rating}
              </Badge>
            </Group>
          )}
          {description && (
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
              {description}
            </Text>
          )}
          {statRows.length > 0 && (
            <Stack gap={4} pt={6}>
              <Text fw={600} size="sm">
                Stream Stats
              </Text>
              {statRows.map(([k, v]) => (
                <Group key={k} justify="space-between">
                  <Text size="xs" c="dimmed">
                    {k}
                  </Text>
                  <Text size="xs">{v}</Text>
                </Group>
              ))}
            </Stack>
          )}
        </Stack>
      </Flex>
    );
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        isSeriesGroup
          ? `Series: ${recordingName}`
          : `${recordingName}${program.sub_title ? ` - ${program.sub_title}` : ''}`
      }
      size="lg"
      centered
      radius="md"
      zIndex={9999}
      overlayProps={{ color: '#000', backgroundOpacity: 0.55, blur: 0 }}
      styles={{
        content: { backgroundColor: '#18181B', color: 'white' },
        header: { backgroundColor: '#18181B', color: 'white' },
        title: { color: 'white' },
      }}
    >
      {isSeriesGroup ? <Series /> : <Movie />}
    </Modal>
  );
};

export default RecordingDetailsModal;
