import React, { useMemo, useState, useEffect } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Card,
  Center,
  Container,
  Flex,
  Badge,
  Group,
  Image,
  Modal,
  SimpleGrid,
  Stack,
  Text,
  Title,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import {
  Gauge,
  HardDriveDownload,
  HardDriveUpload,
  AlertTriangle,
  SquarePlus,
  SquareX,
  Timer,
  Users,
  Video,
} from 'lucide-react';
import dayjs from 'dayjs';
import duration from 'dayjs/plugin/duration';
import relativeTime from 'dayjs/plugin/relativeTime';
import useChannelsStore from '../store/channels';
import useSettingsStore from '../store/settings';
import useVideoStore from '../store/useVideoStore';
import useLocalStorage from '../hooks/useLocalStorage'
import RecordingForm from '../components/forms/Recording';
import { notifications } from '@mantine/notifications';
import API from '../api';

dayjs.extend(duration);
dayjs.extend(relativeTime);

/* Handle datetime formats */
const [timeFormatSetting] = useLocalStorage('time-format', '12h');
const [dateFormatSetting] = useLocalStorage('date-format', 'mdy');
const timeFormat = timeFormatSetting === '12h' ? 'h:mm A' : 'HH:mm';
const dateFormat = dateFormatSetting === 'mdy' ? 'MMMM D' : 'D MMMM';

// Short preview that triggers the details modal when clicked
const RecordingSynopsis = ({ description, onOpen }) => {
  const truncated = description?.length > 140;
  const preview = truncated ? `${description.slice(0, 140).trim()}…` : description;
  if (!description) return null;
  return (
    <Text
      size="xs"
      c="dimmed"
      lineClamp={2}
      title={description}
      onClick={() => onOpen?.()}
      style={{ cursor: 'pointer' }}
    >
      {preview}
    </Text>
  );
};

const RecordingDetailsModal = ({ opened, onClose, recording, channel, posterUrl, onWatchLive, onWatchRecording, env_mode }) => {
  if (!recording) return null;

  const customProps = recording.custom_properties || {};
  const program = customProps.program || {};
  const recordingName = program.title || 'Custom Recording';
  const subTitle = program.sub_title || '';
  const description = program.description || customProps.description || '';
  const start = dayjs(recording.start_time);
  const end = dayjs(recording.end_time);
  const stats = customProps.stream_info || {};

  const statRows = [
    ['Video Codec', stats.video_codec],
    ['Resolution', stats.resolution || (stats.width && stats.height ? `${stats.width}x${stats.height}` : null)],
    ['FPS', stats.source_fps],
    ['Video Bitrate', stats.video_bitrate && `${stats.video_bitrate} kb/s`],
    ['Audio Codec', stats.audio_codec],
    ['Audio Channels', stats.audio_channels],
    ['Sample Rate', stats.sample_rate && `${stats.sample_rate} Hz`],
    ['Audio Bitrate', stats.audio_bitrate && `${stats.audio_bitrate} kb/s`],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');

  // Rating (if available)
  const rating = customProps.rating || customProps.rating_value || (program && program.custom_properties && program.custom_properties.rating);
  const ratingSystem = customProps.rating_system || 'MPAA';

  const fileUrl = customProps.file_url || customProps.output_file_url;
  const canWatchRecording = (customProps.status === 'completed' || customProps.status === 'interrupted') && Boolean(fileUrl);

  // Prefix in dev (Vite) if needed
  let resolvedPosterUrl = posterUrl;
  if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.DEV) {
    if (resolvedPosterUrl && resolvedPosterUrl.startsWith('/')) {
      resolvedPosterUrl = `${window.location.protocol}//${window.location.hostname}:5656${resolvedPosterUrl}`;
    }
  }

  // If this card represented a grouped series (next of N), show a series modal listing episodes
  const allRecordings = useChannelsStore((s) => s.recordings);
  const channels = useChannelsStore((s) => s.channels);
  const [childOpen, setChildOpen] = React.useState(false);
  const [childRec, setChildRec] = React.useState(null);
  const isSeriesGroup = Boolean(recording._group_count && recording._group_count > 1);
  const upcomingEpisodes = React.useMemo(() => {
    if (!isSeriesGroup) return [];
    const arr = Array.isArray(allRecordings) ? allRecordings : Object.values(allRecordings || {});
    const tvid = program.tvg_id || '';
    const titleKey = (program.title || '').toLowerCase();
    const filtered = arr.filter((r) => {
        const cp = r.custom_properties || {};
        const pr = cp.program || {};
        if ((pr.tvg_id || '') !== tvid) return false;
        if ((pr.title || '').toLowerCase() !== titleKey) return false;
        const st = dayjs(r.start_time);
        return st.isAfter(dayjs());
      });
    // Deduplicate by program.id if present, else by time+title
    const seen = new Set();
    const deduped = [];
    for (const r of filtered) {
      const cp = r.custom_properties || {};
      const pr = cp.program || {};
      // Prefer season/episode or onscreen code; else fall back to sub_title; else program id/slot
      const season = cp.season ?? pr?.custom_properties?.season;
      const episode = cp.episode ?? pr?.custom_properties?.episode;
      const onscreen = cp.onscreen_episode ?? pr?.custom_properties?.onscreen_episode;
      let key = null;
      if (season != null && episode != null) key = `se:${season}:${episode}`;
      else if (onscreen) key = `onscreen:${String(onscreen).toLowerCase()}`;
      else if (pr.sub_title) key = `sub:${(pr.sub_title || '').toLowerCase()}`;
      else if (pr.id != null) key = `id:${pr.id}`;
      else key = `slot:${r.channel}|${r.start_time}|${r.end_time}|${(pr.title||'')}`;
      if (seen.has(key)) continue;
      seen.add(key);
      deduped.push(r);
    }
    return deduped.sort((a, b) => dayjs(a.start_time) - dayjs(b.start_time));
  }, [allRecordings, isSeriesGroup, program.tvg_id, program.title]);

  const EpisodeRow = ({ rec }) => {
    const cp = rec.custom_properties || {};
    const pr = cp.program || {};
    const start = dayjs(rec.start_time);
    const end = dayjs(rec.end_time);
    const season = cp.season ?? pr?.custom_properties?.season;
    const episode = cp.episode ?? pr?.custom_properties?.episode;
    const onscreen = cp.onscreen_episode ?? pr?.custom_properties?.onscreen_episode;
    const se = season && episode ? `S${String(season).padStart(2,'0')}E${String(episode).padStart(2,'0')}` : (onscreen || null);
    const posterLogoId = cp.poster_logo_id;
    let purl = posterLogoId ? `/api/channels/logos/${posterLogoId}/cache/` : cp.poster_url || posterUrl || '/logo.png';
    if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.DEV && purl && purl.startsWith('/')) {
      purl = `${window.location.protocol}//${window.location.hostname}:5656${purl}`;
    }
    const onRemove = async (e) => {
      e?.stopPropagation?.();
      try { await API.deleteRecording(rec.id); } catch {}
      try { await useChannelsStore.getState().fetchRecordings(); } catch {}
    };
    return (
      <Card withBorder radius="md" padding="sm" style={{ backgroundColor: '#27272A', cursor: 'pointer' }} onClick={() => { setChildRec(rec); setChildOpen(true); }}>
        <Flex gap="sm" align="center">
          <Image src={purl} w={64} h={64} fit="contain" radius="sm" alt={pr.title || recordingName} fallbackSrc="/logo.png" />
          <Stack gap={4} style={{ flex: 1 }}>
            <Group justify="space-between">
              <Text fw={600} size="sm" lineClamp={1} title={pr.sub_title || pr.title}>{pr.sub_title || pr.title}</Text>
              {se && <Badge color="gray" variant="light">{se}</Badge>}
            </Group>
            <Text size="xs">{start.format(`${dateFormat}, YYYY ${timeFormat}`)} – {end.format(timeFormat)}</Text>
          </Stack>
          <Group gap={6}>
            <Button size="xs" color="red" variant="light" onClick={onRemove}>Remove</Button>
          </Group>
        </Flex>
      </Card>
    );
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={isSeriesGroup ? `Series: ${recordingName}` : `${recordingName}${program.sub_title ? ` - ${program.sub_title}` : ''}`}
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
      {isSeriesGroup ? (
        <Stack gap={10}>
          {upcomingEpisodes.length === 0 && (
            <Text size="sm" c="dimmed">No upcoming episodes found</Text>
          )}
          {upcomingEpisodes.map((ep) => (
            <EpisodeRow key={`ep-${ep.id}`} rec={ep} />
          ))}
          {childOpen && childRec && (
            <RecordingDetailsModal
              opened={childOpen}
              onClose={() => setChildOpen(false)}
              recording={childRec}
              channel={channels[childRec.channel]}
              posterUrl={(
                childRec.custom_properties?.poster_logo_id
                  ? `/api/channels/logos/${childRec.custom_properties.poster_logo_id}/cache/`
                  : childRec.custom_properties?.poster_url || channels[childRec.channel]?.logo?.cache_url
              ) || '/logo.png'}
              env_mode={env_mode}
              onWatchLive={() => {
                const rec = childRec;
                const now = dayjs();
                const s = dayjs(rec.start_time);
                const e = dayjs(rec.end_time);
                if (now.isAfter(s) && now.isBefore(e)) {
                  const ch = channels[rec.channel];
                  if (!ch) return;
                  let url = `/proxy/ts/stream/${ch.uuid}`;
                  if (env_mode === 'dev') {
                    url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
                  }
                  useVideoStore.getState().showVideo(url, 'live');
                }
              }}
              onWatchRecording={() => {
                let fileUrl = childRec.custom_properties?.file_url || childRec.custom_properties?.output_file_url;
                if (!fileUrl) return;
                if (env_mode === 'dev' && fileUrl.startsWith('/')) {
                  fileUrl = `${window.location.protocol}//${window.location.hostname}:5656${fileUrl}`;
                }
                useVideoStore.getState().showVideo(fileUrl, 'vod', { name: childRec.custom_properties?.program?.title || 'Recording', logo: { url: (childRec.custom_properties?.poster_logo_id ? `/api/channels/logos/${childRec.custom_properties.poster_logo_id}/cache/` : channels[childRec.channel]?.logo?.cache_url) || '/logo.png' } });
              }}
            />
          )}
        </Stack>
      ) : (
      <Flex gap="lg" align="flex-start">
        <Image src={resolvedPosterUrl} w={180} h={240} fit="contain" radius="sm" alt={recordingName} fallbackSrc="/logo.png" />
        <Stack gap={8} style={{ flex: 1 }}>
          <Group justify="space-between" align="center">
            <Text c="dimmed" size="sm">{channel ? `${channel.channel_number} • ${channel.name}` : '—'}</Text>
            <Group gap={8}>
              {onWatchLive && (
                <Button size="xs" variant="light" onClick={(e) => { e.stopPropagation?.(); onWatchLive(); }}>Watch Live</Button>
              )}
              {onWatchRecording && (
                <Button size="xs" variant="default" onClick={(e) => { e.stopPropagation?.(); onWatchRecording(); }} disabled={!canWatchRecording}>Watch</Button>
              )}
              {customProps.status === 'completed' && (!customProps?.comskip || customProps?.comskip?.status !== 'completed') && (
                <Button size="xs" variant="light" color="teal" onClick={async (e) => {
                  e.stopPropagation?.();
                  try { await API.runComskip(recording.id); notifications.show({ title: 'Removing commercials', message: 'Queued comskip for this recording', color: 'blue.5', autoClose: 2000 }); } catch {}
                }}>Remove commercials</Button>
              )}
            </Group>
          </Group>
          <Text size="sm">{start.format(`${dateFormat}, YYYY ${timeFormat}`)} – {end.format(timeFormat)}</Text>
          {rating && (
            <Group gap={8}>
              <Badge color="yellow" title={ratingSystem}>{rating}</Badge>
            </Group>
          )}
          {description && (
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{description}</Text>
          )}
          {statRows.length > 0 && (
            <Stack gap={4} pt={6}>
              <Text fw={600} size="sm">Stream Stats</Text>
              {statRows.map(([k, v]) => (
                <Group key={k} justify="space-between">
                  <Text size="xs" c="dimmed">{k}</Text>
                  <Text size="xs">{v}</Text>
                </Group>
              ))}
            </Stack>
          )}
        </Stack>
      </Flex>
      )}
    </Modal>
  );
};

const RecordingCard = ({ recording, category, onOpenDetails }) => {
  const channels = useChannelsStore((s) => s.channels);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);

  const channel = channels?.[recording.channel];

  const deleteRecording = (id) => {
    // Optimistically remove immediately from UI
    try { useChannelsStore.getState().removeRecording(id); } catch {}
    // Fire-and-forget server delete; websocket will keep others in sync
    API.deleteRecording(id).catch(() => {
      // On failure, fallback to refetch to restore state
      try { useChannelsStore.getState().fetchRecordings(); } catch {}
    });
  };

  const customProps = recording.custom_properties || {};
  const program = customProps.program || {};
  const recordingName = program.title || 'Custom Recording';
  const subTitle = program.sub_title || '';
  const description = program.description || customProps.description || '';

  // Poster or channel logo
  const posterLogoId = customProps.poster_logo_id;
  let posterUrl = posterLogoId
    ? `/api/channels/logos/${posterLogoId}/cache/`
    : customProps.poster_url || channel?.logo?.cache_url || '/logo.png';
  // Prefix API host in dev if using a relative path
  if (env_mode === 'dev' && posterUrl && posterUrl.startsWith('/')) {
    posterUrl = `${window.location.protocol}//${window.location.hostname}:5656${posterUrl}`;
  }

  const start = dayjs(recording.start_time);
  const end = dayjs(recording.end_time);
  const now = dayjs();
  const status = customProps.status;
  const isTimeActive = now.isAfter(start) && now.isBefore(end);
  const isInterrupted = status === 'interrupted';
  const isInProgress = isTimeActive; // Show as recording by time, regardless of status glitches
  const isUpcoming = now.isBefore(start);
  const isSeriesGroup = Boolean(recording._group_count && recording._group_count > 1);
  // Season/Episode display if present
  const season = customProps.season ?? program?.custom_properties?.season;
  const episode = customProps.episode ?? program?.custom_properties?.episode;
  const onscreen = customProps.onscreen_episode ?? program?.custom_properties?.onscreen_episode;
  const seLabel = season && episode ? `S${String(season).padStart(2,'0')}E${String(episode).padStart(2,'0')}` : (onscreen || null);

  const handleWatchLive = () => {
    if (!channel) return;
    let url = `/proxy/ts/stream/${channel.uuid}`;
    if (env_mode === 'dev') {
      url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
    }
    showVideo(url, 'live');
  };

  const handleWatchRecording = () => {
    // Only enable if backend provides a playable file URL in custom properties
    let fileUrl = customProps.file_url || customProps.output_file_url;
    if (!fileUrl) return;
    if (env_mode === 'dev' && fileUrl.startsWith('/')) {
      fileUrl = `${window.location.protocol}//${window.location.hostname}:5656${fileUrl}`;
    }
    showVideo(fileUrl, 'vod', { name: recordingName, logo: { url: posterUrl } });
  };

  const handleRunComskip = async (e) => {
    e?.stopPropagation?.();
    try {
      await API.runComskip(recording.id);
      notifications.show({ title: 'Removing commercials', message: 'Queued comskip for this recording', color: 'blue.5', autoClose: 2000 });
    } catch {}
  };

  // Cancel handling for series groups
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const handleCancelClick = (e) => {
    e.stopPropagation();
    if (isSeriesGroup) {
      setCancelOpen(true);
    } else {
      deleteRecording(recording.id);
    }
  };

  const seriesInfo = React.useMemo(() => {
    const cp = customProps || {};
    const pr = cp.program || {};
    return { tvg_id: pr.tvg_id, title: pr.title };
  }, [customProps]);

  const removeUpcomingOnly = async () => {
    try {
      setBusy(true);
      await API.deleteRecording(recording.id);
    } finally {
      setBusy(false);
      setCancelOpen(false);
      try { await fetchRecordings(); } catch {}
    }
  };

  const removeSeriesAndRule = async () => {
    try {
      setBusy(true);
      const { tvg_id, title } = seriesInfo;
      if (tvg_id) {
        try { await API.bulkRemoveSeriesRecordings({ tvg_id, title, scope: 'title' }); } catch {}
        try { await API.deleteSeriesRule(tvg_id); } catch {}
      }
    } finally {
      setBusy(false);
      setCancelOpen(false);
      try { await fetchRecordings(); } catch {}
    }
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
        cursor: 'pointer',
      }}
      onClick={() => onOpenDetails?.(recording)}
    >
      <Flex justify="space-between" align="center" style={{ paddingBottom: 8 }}>
        <Group gap={8} style={{ flex: 1, minWidth: 0 }}>
          <Badge color={isInterrupted ? 'red.7' : isInProgress ? 'red.6' : isUpcoming ? 'yellow.6' : 'gray.6'}>
            {isInterrupted ? 'Interrupted' : isInProgress ? 'Recording' : isUpcoming ? 'Scheduled' : 'Completed'}
          </Badge>
          {isInterrupted && <AlertTriangle size={16} color="#ffa94d" />}
          <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
            <Group gap={8} wrap="nowrap">
              <Text fw={600} lineClamp={1} title={recordingName}>
                {recordingName}
              </Text>
              {isSeriesGroup && (
                <Badge color="teal" variant="filled">Series</Badge>
              )}
              {seLabel && !isSeriesGroup && (
                <Badge color="gray" variant="light">{seLabel}</Badge>
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
        <Stack gap={6} style={{ flex: 1 }}>
          {!isSeriesGroup && subTitle && (
            <Group justify="space-between">
              <Text size="sm" c="dimmed">Episode</Text>
              <Text size="sm" fw={700} title={subTitle}>{subTitle}</Text>
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
            <Text size="sm">{start.format(`${dateFormat}, YYYY ${timeFormat}`)} – {end.format(timeFormat)}</Text>
          </Group>

          {!isSeriesGroup && description && (
            <RecordingSynopsis description={description} onOpen={() => onOpenDetails?.(recording)} />
          )}

          {isInterrupted && customProps.interrupted_reason && (
            <Text size="xs" c="red.4">{customProps.interrupted_reason}</Text>
          )}

          <Group justify="flex-end" gap="xs" pt={4}>
            {isInProgress && (
              <Button size="xs" variant="light" onClick={(e) => { e.stopPropagation(); handleWatchLive(); }}>
                Watch Live
              </Button>
            )}

            {!isUpcoming && (
              <Tooltip label={customProps.file_url || customProps.output_file_url ? 'Watch recording' : 'Recording playback not available yet'}>
                <Button
                  size="xs"
                  variant="default"
                  onClick={(e) => { e.stopPropagation(); handleWatchRecording(); }}
                  disabled={customProps.status === 'recording' || !(customProps.file_url || customProps.output_file_url)}
                >
                  Watch
                </Button>
              </Tooltip>
            )}
            {!isUpcoming && customProps?.status === 'completed' && (!customProps?.comskip || customProps?.comskip?.status !== 'completed') && (
              <Button size="xs" variant="light" color="teal" onClick={handleRunComskip}>
                Remove commercials
              </Button>
            )}
          </Group>
        </Stack>
      </Flex>
      {/* If this card is a grouped upcoming series, show count */}
      {recording._group_count > 1 && (
        <Text size="xs" c="dimmed" style={{ position: 'absolute', bottom: 6, right: 12 }}>
          Next of {recording._group_count}
        </Text>
      )}
    </Card>
  );
  if (!isSeriesGroup) return MainCard;

  // Stacked look for series groups: render two shadow layers behind the main card
  return (
    <Box style={{ position: 'relative' }}>
      <Modal opened={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel Series" centered size="md" zIndex={9999}>
        <Stack gap="sm">
          <Text>This is a series rule. What would you like to cancel?</Text>
          <Group justify="flex-end">
            <Button variant="default" loading={busy} onClick={removeUpcomingOnly}>Only this upcoming</Button>
            <Button color="red" loading={busy} onClick={removeSeriesAndRule}>Entire series + rule</Button>
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

const DVRPage = () => {
  const theme = useMantineTheme();
  const recordings = useChannelsStore((s) => s.recordings);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const channels = useChannelsStore((s) => s.channels);
  const fetchChannels = useChannelsStore((s) => s.fetchChannels);

  const [recordingModalOpen, setRecordingModalOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsRecording, setDetailsRecording] = useState(null);

  const openRecordingModal = () => {
    setRecordingModalOpen(true);
  };

  const closeRecordingModal = () => {
    setRecordingModalOpen(false);
  };

  const openDetails = (recording) => {
    setDetailsRecording(recording);
    setDetailsOpen(true);
  };
  const closeDetails = () => setDetailsOpen(false);

  useEffect(() => {
    // Ensure channels and recordings are loaded for this view
    if (!channels || Object.keys(channels).length === 0) {
      fetchChannels();
    }
    fetchRecordings();
  }, []);

  // Re-render every second so time-based bucketing updates without a refresh
  const [now, setNow] = useState(dayjs());
  useEffect(() => {
    const interval = setInterval(() => setNow(dayjs()), 1000);
    return () => clearInterval(interval);
  }, []);

  // Categorize recordings
  const { inProgress, upcoming, completed } = useMemo(() => {
    const inProgress = [];
    const upcoming = [];
    const completed = [];
    const list = Array.isArray(recordings) ? recordings : Object.values(recordings || {});

    // ID-based dedupe guard in case store returns duplicates
    const seenIds = new Set();
    for (const rec of list) {
      if (rec && rec.id != null) {
        const k = String(rec.id);
        if (seenIds.has(k)) continue;
        seenIds.add(k);
      }
      const s = dayjs(rec.start_time);
      const e = dayjs(rec.end_time);
      const status = rec.custom_properties?.status;
      if (status === 'interrupted' || status === 'completed') {
        completed.push(rec);
      } else {
        if (now.isAfter(s) && now.isBefore(e)) inProgress.push(rec);
        else if (now.isBefore(s)) upcoming.push(rec);
        else completed.push(rec);
      }
    }

    // Deduplicate in-progress and upcoming by program id or channel+slot
    const dedupeByProgramOrSlot = (arr) => {
      const out = [];
      const sigs = new Set();
      for (const r of arr) {
        const cp = r.custom_properties || {};
        const pr = cp.program || {};
        const sig = pr?.id != null ? `id:${pr.id}` : `slot:${r.channel}|${r.start_time}|${r.end_time}|${(pr.title||'')}`;
        if (sigs.has(sig)) continue;
        sigs.add(sig);
        out.push(r);
      }
      return out;
    };

    const inProgressDedup = dedupeByProgramOrSlot(inProgress).sort((a, b) => dayjs(b.start_time) - dayjs(a.start_time));

    // Group upcoming by series title+tvg_id (keep only next episode)
    const grouped = new Map();
    const upcomingDedup = dedupeByProgramOrSlot(upcoming).sort((a, b) => dayjs(a.start_time) - dayjs(b.start_time));
    for (const rec of upcomingDedup) {
      const cp = rec.custom_properties || {};
      const prog = cp.program || {};
      const key = `${prog.tvg_id || ''}|${(prog.title || '').toLowerCase()}`;
      if (!grouped.has(key)) {
        grouped.set(key, { rec, count: 1 });
      } else {
        const entry = grouped.get(key);
        entry.count += 1;
      }
    }
    const upcomingGrouped = Array.from(grouped.values()).map((e) => {
      const item = { ...e.rec };
      item._group_count = e.count;
      return item;
    });
    completed.sort((a, b) => dayjs(b.end_time) - dayjs(a.end_time));
    return { inProgress: inProgressDedup, upcoming: upcomingGrouped, completed };
  }, [recordings]);

  return (
    <Box style={{ padding: 10 }}>
      <Button
        leftSection={<SquarePlus size={18} />}
        variant="light"
        size="sm"
        onClick={openRecordingModal}
        p={5}
        color={theme.tailwind.green[5]}
        style={{
          borderWidth: '1px',
          borderColor: theme.tailwind.green[5],
          color: 'white',
        }}
      >
        New Recording
      </Button>
      <Stack gap="lg" style={{ paddingTop: 12 }}>
        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Currently Recording</Title>
            <Badge color="red.6">{inProgress.length}</Badge>
          </Group>
          <SimpleGrid cols={3} spacing="md" breakpoints={[{ maxWidth: '62rem', cols: 2 }, { maxWidth: '36rem', cols: 1 }]}>
            {inProgress.map((rec) => (
              <RecordingCard key={`rec-${rec.id}`} recording={rec} category="in_progress" onOpenDetails={openDetails} />
            ))}
            {inProgress.length === 0 && (
              <Text size="sm" c="dimmed">
                Nothing recording right now.
              </Text>
            )}
          </SimpleGrid>
        </div>

        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Upcoming Recordings</Title>
            <Badge color="yellow.6">{upcoming.length}</Badge>
          </Group>
          <SimpleGrid cols={3} spacing="md" breakpoints={[{ maxWidth: '62rem', cols: 2 }, { maxWidth: '36rem', cols: 1 }]}>
            {upcoming.map((rec) => (
              <RecordingCard key={`rec-${rec.id}`} recording={rec} category="upcoming" onOpenDetails={openDetails} />
            ))}
            {upcoming.length === 0 && (
              <Text size="sm" c="dimmed">
                No upcoming recordings.
              </Text>
            )}
          </SimpleGrid>
        </div>

        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Previously Recorded</Title>
            <Badge color="gray.6">{completed.length}</Badge>
          </Group>
          <SimpleGrid cols={3} spacing="md" breakpoints={[{ maxWidth: '62rem', cols: 2 }, { maxWidth: '36rem', cols: 1 }]}>
            {completed.map((rec) => (
              <RecordingCard key={`rec-${rec.id}`} recording={rec} category="completed" onOpenDetails={openDetails} />
            ))}
            {completed.length === 0 && (
              <Text size="sm" c="dimmed">
                No completed recordings yet.
              </Text>
            )}
          </SimpleGrid>
        </div>
      </Stack>

      <RecordingForm
        isOpen={recordingModalOpen}
        onClose={closeRecordingModal}
      />

      {/* Details Modal */}
      {detailsRecording && (
        <RecordingDetailsModal
          opened={detailsOpen}
          onClose={closeDetails}
          recording={detailsRecording}
          channel={channels[detailsRecording.channel]}
          posterUrl={(
            detailsRecording.custom_properties?.poster_logo_id
              ? `/api/channels/logos/${detailsRecording.custom_properties.poster_logo_id}/cache/`
              : detailsRecording.custom_properties?.poster_url || channels[detailsRecording.channel]?.logo?.cache_url
          ) || '/logo.png'}
          env_mode={useSettingsStore.getState().environment.env_mode}
          onWatchLive={() => {
            const rec = detailsRecording;
            const now = dayjs();
            const s = dayjs(rec.start_time);
            const e = dayjs(rec.end_time);
            if (now.isAfter(s) && now.isBefore(e)) {
              // call into child RecordingCard behavior by constructing a URL like there
              const channel = channels[rec.channel];
              if (!channel) return;
              let url = `/proxy/ts/stream/${channel.uuid}`;
              if (useSettingsStore.getState().environment.env_mode === 'dev') {
                url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
              }
              useVideoStore.getState().showVideo(url, 'live');
            }
          }}
          onWatchRecording={() => {
            let fileUrl = detailsRecording.custom_properties?.file_url || detailsRecording.custom_properties?.output_file_url;
            if (!fileUrl) return;
            if (useSettingsStore.getState().environment.env_mode === 'dev' && fileUrl.startsWith('/')) {
              fileUrl = `${window.location.protocol}//${window.location.hostname}:5656${fileUrl}`;
            }
            useVideoStore.getState().showVideo(fileUrl, 'vod', { name: detailsRecording.custom_properties?.program?.title || 'Recording', logo: { url: (detailsRecording.custom_properties?.poster_logo_id ? `/api/channels/logos/${detailsRecording.custom_properties.poster_logo_id}/cache/` : channels[detailsRecording.channel]?.logo?.cache_url) || '/logo.png' } });
          }}
        />
      )}
    </Box>
  );
};

export default DVRPage;
