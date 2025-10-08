import React, { useMemo, useState, useEffect, useCallback } from 'react';
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
  Switch,
  Select,
  MultiSelect,
  TextInput,
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
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import useChannelsStore from '../store/channels';
import useSettingsStore from '../store/settings';
import useLocalStorage from '../hooks/useLocalStorage';
import useVideoStore from '../store/useVideoStore';
import RecordingForm from '../components/forms/Recording';
import { notifications } from '@mantine/notifications';
import API from '../api';
import { DatePickerInput, TimeInput } from '@mantine/dates';
import { useForm } from '@mantine/form';

dayjs.extend(duration);
dayjs.extend(relativeTime);
dayjs.extend(utc);
dayjs.extend(timezone);

const useUserTimeZone = () => {
  const settings = useSettingsStore((s) => s.settings);
  const [timeZone, setTimeZone] = useLocalStorage(
    'time-zone',
    dayjs.tz?.guess
      ? dayjs.tz.guess()
      : Intl.DateTimeFormat().resolvedOptions().timeZone
  );

  useEffect(() => {
    const tz = settings?.['system-time-zone']?.value;
    if (tz && tz !== timeZone) {
      setTimeZone(tz);
    }
  }, [settings, timeZone, setTimeZone]);

  return timeZone;
};

const useTimeHelpers = () => {
  const timeZone = useUserTimeZone();

  const toUserTime = useCallback(
    (value) => {
      if (!value) return dayjs.invalid();
      try {
        return dayjs(value).tz(timeZone);
      } catch (error) {
        return dayjs(value);
      }
    },
    [timeZone]
  );

  const userNow = useCallback(() => dayjs().tz(timeZone), [timeZone]);

  return { timeZone, toUserTime, userNow };
};

const RECURRING_DAY_OPTIONS = [
  { value: 6, label: 'Sun' },
  { value: 0, label: 'Mon' },
  { value: 1, label: 'Tue' },
  { value: 2, label: 'Wed' },
  { value: 3, label: 'Thu' },
  { value: 4, label: 'Fri' },
  { value: 5, label: 'Sat' },
];

// Short preview that triggers the details modal when clicked
const RecordingSynopsis = ({ description, onOpen }) => {
  const truncated = description?.length > 140;
  const preview = truncated
    ? `${description.slice(0, 140).trim()}...`
    : description;
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
  const channelMap = useChannelsStore((s) => s.channels);
  const { toUserTime, userNow } = useTimeHelpers();
  const [childOpen, setChildOpen] = React.useState(false);
  const [childRec, setChildRec] = React.useState(null);

  const safeRecording = recording || {};
  const customProps = safeRecording.custom_properties || {};
  const program = customProps.program || {};
  const recordingName = program.title || 'Custom Recording';
  const description = program.description || customProps.description || '';
  const start = toUserTime(safeRecording.start_time);
  const end = toUserTime(safeRecording.end_time);
  const stats = customProps.stream_info || {};

  const statRows = [
    ['Video Codec', stats.video_codec],
    [
      'Resolution',
      stats.resolution ||
        (stats.width && stats.height ? `${stats.width}x${stats.height}` : null),
    ],
    ['FPS', stats.source_fps],
    ['Video Bitrate', stats.video_bitrate && `${stats.video_bitrate} kb/s`],
    ['Audio Codec', stats.audio_codec],
    ['Audio Channels', stats.audio_channels],
    ['Sample Rate', stats.sample_rate && `${stats.sample_rate} Hz`],
    ['Audio Bitrate', stats.audio_bitrate && `${stats.audio_bitrate} kb/s`],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');

  // Rating (if available)
  const rating =
    customProps.rating ||
    customProps.rating_value ||
    (program && program.custom_properties && program.custom_properties.rating);
  const ratingSystem = customProps.rating_system || 'MPAA';

  const fileUrl = customProps.file_url || customProps.output_file_url;
  const canWatchRecording =
    (customProps.status === 'completed' ||
      customProps.status === 'interrupted') &&
    Boolean(fileUrl);

  // Prefix in dev (Vite) if needed
  let resolvedPosterUrl = posterUrl;
  if (
    typeof import.meta !== 'undefined' &&
    import.meta.env &&
    import.meta.env.DEV
  ) {
    if (resolvedPosterUrl && resolvedPosterUrl.startsWith('/')) {
      resolvedPosterUrl = `${window.location.protocol}//${window.location.hostname}:5656${resolvedPosterUrl}`;
    }
  }

  const isSeriesGroup = Boolean(
    safeRecording._group_count && safeRecording._group_count > 1
  );
  const upcomingEpisodes = React.useMemo(() => {
    if (!isSeriesGroup) return [];
    const arr = Array.isArray(allRecordings)
      ? allRecordings
      : Object.values(allRecordings || {});
    const tvid = program.tvg_id || '';
    const titleKey = (program.title || '').toLowerCase();
    const filtered = arr.filter((r) => {
      const cp = r.custom_properties || {};
      const pr = cp.program || {};
      if ((pr.tvg_id || '') !== tvid) return false;
      if ((pr.title || '').toLowerCase() !== titleKey) return false;
      const st = toUserTime(r.start_time);
      return st.isAfter(userNow());
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
      const onscreen =
        cp.onscreen_episode ?? pr?.custom_properties?.onscreen_episode;
      let key = null;
      if (season != null && episode != null) key = `se:${season}:${episode}`;
      else if (onscreen) key = `onscreen:${String(onscreen).toLowerCase()}`;
      else if (pr.sub_title) key = `sub:${(pr.sub_title || '').toLowerCase()}`;
      else if (pr.id != null) key = `id:${pr.id}`;
      else
        key = `slot:${r.channel}|${r.start_time}|${r.end_time}|${pr.title || ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      deduped.push(r);
    }
    return deduped.sort(
      (a, b) => toUserTime(a.start_time) - toUserTime(b.start_time)
    );
  }, [
    allRecordings,
    isSeriesGroup,
    program.tvg_id,
    program.title,
    toUserTime,
    userNow,
  ]);

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
    const se =
      season && episode
        ? `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`
        : onscreen || null;
    const posterLogoId = cp.poster_logo_id;
    let purl = posterLogoId
      ? `/api/channels/logos/${posterLogoId}/cache/`
      : cp.poster_url || posterUrl || '/logo.png';
    if (
      typeof import.meta !== 'undefined' &&
      import.meta.env &&
      import.meta.env.DEV &&
      purl &&
      purl.startsWith('/')
    ) {
      purl = `${window.location.protocol}//${window.location.hostname}:5656${purl}`;
    }
    const onRemove = async (e) => {
      e?.stopPropagation?.();
      try {
        await API.deleteRecording(rec.id);
      } catch (error) {
        console.error('Failed to delete upcoming recording', error);
      }
      try {
        await useChannelsStore.getState().fetchRecordings();
      } catch (error) {
        console.error('Failed to refresh recordings after delete', error);
      }
    };
    return (
      <Card
        withBorder
        radius="md"
        padding="sm"
        style={{ backgroundColor: '#27272A', cursor: 'pointer' }}
        onClick={() => {
          setChildRec(rec);
          setChildOpen(true);
        }}
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
          <Stack gap={4} style={{ flex: 1 }}>
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
              {start.format('MMM D, YYYY h:mma')} – {end.format('h:mma')}
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
      {isSeriesGroup ? (
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
              channel={channelMap[childRec.channel]}
              posterUrl={
                (childRec.custom_properties?.poster_logo_id
                  ? `/api/channels/logos/${childRec.custom_properties.poster_logo_id}/cache/`
                  : childRec.custom_properties?.poster_url ||
                    channelMap[childRec.channel]?.logo?.cache_url) ||
                '/logo.png'
              }
              env_mode={env_mode}
              onWatchLive={() => {
                const rec = childRec;
                const now = userNow();
                const s = toUserTime(rec.start_time);
                const e = toUserTime(rec.end_time);
                if (now.isAfter(s) && now.isBefore(e)) {
                  const ch = channelMap[rec.channel];
                  if (!ch) return;
                  let url = `/proxy/ts/stream/${ch.uuid}`;
                  if (env_mode === 'dev') {
                    url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
                  }
                  useVideoStore.getState().showVideo(url, 'live');
                }
              }}
              onWatchRecording={() => {
                let fileUrl =
                  childRec.custom_properties?.file_url ||
                  childRec.custom_properties?.output_file_url;
                if (!fileUrl) return;
                if (env_mode === 'dev' && fileUrl.startsWith('/')) {
                  fileUrl = `${window.location.protocol}//${window.location.hostname}:5656${fileUrl}`;
                }
                useVideoStore.getState().showVideo(fileUrl, 'vod', {
                  name:
                    childRec.custom_properties?.program?.title || 'Recording',
                  logo: {
                    url:
                      (childRec.custom_properties?.poster_logo_id
                        ? `/api/channels/logos/${childRec.custom_properties.poster_logo_id}/cache/`
                        : channelMap[childRec.channel]?.logo?.cache_url) ||
                      '/logo.png',
                  },
                });
              }}
            />
          )}
        </Stack>
      ) : (
        <Flex gap="lg" align="flex-start">
          <Image
            src={resolvedPosterUrl}
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
                {onWatchLive && (
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
                )}
                {onWatchRecording && (
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
                )}
                {onEdit && start.isAfter(userNow()) && (
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
                )}
                {customProps.status === 'completed' &&
                  (!customProps?.comskip ||
                    customProps?.comskip?.status !== 'completed') && (
                    <Button
                      size="xs"
                      variant="light"
                      color="teal"
                      onClick={async (e) => {
                        e.stopPropagation?.();
                        try {
                          await API.runComskip(recording.id);
                          notifications.show({
                            title: 'Removing commercials',
                            message: 'Queued comskip for this recording',
                            color: 'blue.5',
                            autoClose: 2000,
                          });
                        } catch (error) {
                          console.error('Failed to run comskip', error);
                        }
                      }}
                    >
                      Remove commercials
                    </Button>
                  )}
              </Group>
            </Group>
            <Text size="sm">
              {start.format('MMM D, YYYY h:mma')} – {end.format('h:mma')}
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
      )}
    </Modal>
  );
};

const toTimeString = (value) => {
  if (!value) return '00:00';
  if (typeof value === 'string') {
    const parsed = dayjs(value, ['HH:mm', 'HH:mm:ss', 'h:mm A'], true);
    if (parsed.isValid()) return parsed.format('HH:mm');
    return value;
  }
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format('HH:mm') : '00:00';
};

const parseDate = (value) => {
  if (!value) return null;
  const parsed = dayjs(value, ['YYYY-MM-DD', dayjs.ISO_8601], true);
  return parsed.isValid() ? parsed.toDate() : null;
};

const RecurringRuleModal = ({ opened, onClose, ruleId, onEditOccurrence }) => {
  const channels = useChannelsStore((s) => s.channels);
  const recurringRules = useChannelsStore((s) => s.recurringRules);
  const fetchRecurringRules = useChannelsStore((s) => s.fetchRecurringRules);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const recordings = useChannelsStore((s) => s.recordings);
  const { toUserTime, userNow } = useTimeHelpers();

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [busyOccurrence, setBusyOccurrence] = useState(null);

  const rule = recurringRules.find((r) => r.id === ruleId);

  const channelOptions = useMemo(() => {
    const list = Object.values(channels || {});
    list.sort((a, b) => {
      const aNum = Number(a.channel_number) || 0;
      const bNum = Number(b.channel_number) || 0;
      if (aNum === bNum) {
        return (a.name || '').localeCompare(b.name || '');
      }
      return aNum - bNum;
    });
    return list.map((item) => ({
      value: `${item.id}`,
      label: item.name || `Channel ${item.id}`,
    }));
  }, [channels]);

  const form = useForm({
    mode: 'controlled',
    initialValues: {
      channel_id: '',
      days_of_week: [],
      rule_name: '',
      start_time: dayjs().startOf('hour').format('HH:mm'),
      end_time: dayjs().startOf('hour').add(1, 'hour').format('HH:mm'),
      start_date: dayjs().toDate(),
      end_date: dayjs().toDate(),
      enabled: true,
    },
    validate: {
      channel_id: (value) => (value ? null : 'Select a channel'),
      days_of_week: (value) =>
        value && value.length ? null : 'Pick at least one day',
      end_time: (value, values) => {
        if (!value) return 'Select an end time';
        const startValue = dayjs(
          values.start_time,
          ['HH:mm', 'hh:mm A', 'h:mm A'],
          true
        );
        const endValue = dayjs(value, ['HH:mm', 'hh:mm A', 'h:mm A'], true);
        if (
          startValue.isValid() &&
          endValue.isValid() &&
          endValue.diff(startValue, 'minute') === 0
        ) {
          return 'End time must differ from start time';
        }
        return null;
      },
      end_date: (value, values) => {
        const endDate = dayjs(value);
        const startDate = dayjs(values.start_date);
        if (!value) return 'Select an end date';
        if (startDate.isValid() && endDate.isBefore(startDate, 'day')) {
          return 'End date cannot be before start date';
        }
        return null;
      },
    },
  });

  useEffect(() => {
    if (opened && rule) {
      form.setValues({
        channel_id: `${rule.channel}`,
        days_of_week: (rule.days_of_week || []).map((d) => String(d)),
        rule_name: rule.name || '',
        start_time: toTimeString(rule.start_time),
        end_time: toTimeString(rule.end_time),
        start_date: parseDate(rule.start_date) || dayjs().toDate(),
        end_date: parseDate(rule.end_date),
        enabled: Boolean(rule.enabled),
      });
    } else {
      form.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, ruleId, rule]);

  const upcomingOccurrences = useMemo(() => {
    const list = Array.isArray(recordings)
      ? recordings
      : Object.values(recordings || {});
    const now = userNow();
    return list
      .filter(
        (rec) =>
          rec?.custom_properties?.rule?.id === ruleId &&
          toUserTime(rec.start_time).isAfter(now)
      )
      .sort(
        (a, b) =>
          toUserTime(a.start_time).valueOf() -
          toUserTime(b.start_time).valueOf()
      );
  }, [recordings, ruleId, toUserTime, userNow]);

  const handleSave = async (values) => {
    if (!rule) return;
    setSaving(true);
    try {
      await API.updateRecurringRule(ruleId, {
        channel: values.channel_id,
        days_of_week: (values.days_of_week || []).map((d) => Number(d)),
        start_time: toTimeString(values.start_time),
        end_time: toTimeString(values.end_time),
        start_date: values.start_date
          ? dayjs(values.start_date).format('YYYY-MM-DD')
          : null,
        end_date: values.end_date
          ? dayjs(values.end_date).format('YYYY-MM-DD')
          : null,
        name: values.rule_name?.trim() || '',
        enabled: Boolean(values.enabled),
      });
      await Promise.all([fetchRecurringRules(), fetchRecordings()]);
      notifications.show({
        title: 'Recurring rule updated',
        message: 'Schedule adjustments saved',
        color: 'green',
        autoClose: 2500,
      });
      onClose();
    } catch (error) {
      console.error('Failed to update recurring rule', error);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!rule) return;
    setDeleting(true);
    try {
      await API.deleteRecurringRule(ruleId);
      await Promise.all([fetchRecurringRules(), fetchRecordings()]);
      notifications.show({
        title: 'Recurring rule removed',
        message: 'All future occurrences were cancelled',
        color: 'red',
        autoClose: 2500,
      });
      onClose();
    } catch (error) {
      console.error('Failed to delete recurring rule', error);
    } finally {
      setDeleting(false);
    }
  };

  const handleToggleEnabled = async (checked) => {
    if (!rule) return;
    setSaving(true);
    try {
      await API.updateRecurringRule(ruleId, { enabled: checked });
      await Promise.all([fetchRecurringRules(), fetchRecordings()]);
      notifications.show({
        title: checked ? 'Recurring rule enabled' : 'Recurring rule paused',
        message: checked
          ? 'Future occurrences will resume'
          : 'Upcoming occurrences were removed',
        color: checked ? 'green' : 'yellow',
        autoClose: 2500,
      });
    } catch (error) {
      console.error('Failed to toggle recurring rule', error);
      form.setFieldValue('enabled', !checked);
    } finally {
      setSaving(false);
    }
  };

  const handleCancelOccurrence = async (occurrence) => {
    setBusyOccurrence(occurrence.id);
    try {
      await API.deleteRecording(occurrence.id);
      await fetchRecordings();
      notifications.show({
        title: 'Occurrence cancelled',
        message: 'The selected airing was removed',
        color: 'yellow',
        autoClose: 2000,
      });
    } catch (error) {
      console.error('Failed to cancel occurrence', error);
    } finally {
      setBusyOccurrence(null);
    }
  };

  if (!rule) {
    return (
      <Modal opened={opened} onClose={onClose} title="Recurring Rule" centered>
        <Text size="sm">Recurring rule not found.</Text>
      </Modal>
    );
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={rule.name || 'Recurring Rule'}
      size="lg"
      centered
    >
      <Stack gap="md">
        <Group justify="space-between" align="center">
          <Text fw={600}>
            {channels?.[rule.channel]?.name || `Channel ${rule.channel}`}
          </Text>
          <Switch
            size="sm"
            checked={form.values.enabled}
            onChange={(event) => {
              form.setFieldValue('enabled', event.currentTarget.checked);
              handleToggleEnabled(event.currentTarget.checked);
            }}
            label={form.values.enabled ? 'Enabled' : 'Paused'}
            disabled={saving}
          />
        </Group>
        <form onSubmit={form.onSubmit(handleSave)}>
          <Stack gap="md">
            <Select
              {...form.getInputProps('channel_id')}
              label="Channel"
              data={channelOptions}
              searchable
            />
            <TextInput
              {...form.getInputProps('rule_name')}
              label="Rule name"
              placeholder="Morning News, Football Sundays, ..."
            />
            <MultiSelect
              {...form.getInputProps('days_of_week')}
              label="Every"
              data={RECURRING_DAY_OPTIONS.map((opt) => ({
                value: String(opt.value),
                label: opt.label,
              }))}
              searchable
              clearable
            />
            <Group grow>
              <DatePickerInput
                label="Start date"
                value={form.values.start_date}
                onChange={(value) =>
                  form.setFieldValue('start_date', value || dayjs().toDate())
                }
                valueFormat="MMM D, YYYY"
              />
              <DatePickerInput
                label="End date"
                value={form.values.end_date}
                onChange={(value) => form.setFieldValue('end_date', value)}
                valueFormat="MMM D, YYYY"
                minDate={form.values.start_date || undefined}
              />
            </Group>
            <Group grow>
              <TimeInput
                label="Start time"
                value={form.values.start_time}
                onChange={(value) =>
                  form.setFieldValue('start_time', toTimeString(value))
                }
                withSeconds={false}
                format="12"
                amLabel="AM"
                pmLabel="PM"
              />
              <TimeInput
                label="End time"
                value={form.values.end_time}
                onChange={(value) =>
                  form.setFieldValue('end_time', toTimeString(value))
                }
                withSeconds={false}
                format="12"
                amLabel="AM"
                pmLabel="PM"
              />
            </Group>
            <Group justify="space-between">
              <Button type="submit" loading={saving}>
                Save changes
              </Button>
              <Button
                color="red"
                variant="light"
                loading={deleting}
                onClick={handleDelete}
              >
                Delete rule
              </Button>
            </Group>
          </Stack>
        </form>
        <Stack gap="sm">
          <Group justify="space-between" align="center">
            <Text fw={600} size="sm">
              Upcoming occurrences
            </Text>
            <Badge color="blue.6">{upcomingOccurrences.length}</Badge>
          </Group>
          {upcomingOccurrences.length === 0 ? (
            <Text size="sm" c="dimmed">
              No future airings currently scheduled.
            </Text>
          ) : (
            <Stack gap="xs">
              {upcomingOccurrences.map((occ) => {
                const occStart = toUserTime(occ.start_time);
                const occEnd = toUserTime(occ.end_time);
                return (
                  <Card
                    key={`occ-${occ.id}`}
                    withBorder
                    padding="sm"
                    radius="md"
                  >
                    <Group justify="space-between" align="center">
                      <Stack gap={2} style={{ flex: 1 }}>
                        <Text fw={600} size="sm">
                          {occStart.format('MMM D, YYYY')}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {occStart.format('h:mma')} – {occEnd.format('h:mma')}
                        </Text>
                      </Stack>
                      <Group gap={6}>
                        <Button
                          size="xs"
                          variant="subtle"
                          onClick={() => {
                            onClose();
                            onEditOccurrence?.(occ);
                          }}
                        >
                          Edit
                        </Button>
                        <Button
                          size="xs"
                          color="red"
                          variant="light"
                          loading={busyOccurrence === occ.id}
                          onClick={() => handleCancelOccurrence(occ)}
                        >
                          Cancel
                        </Button>
                      </Group>
                    </Group>
                  </Card>
                );
              })}
            </Stack>
          )}
        </Stack>
      </Stack>
    </Modal>
  );
};

const RecordingCard = ({ recording, onOpenDetails, onOpenRecurring }) => {
  const channels = useChannelsStore((s) => s.channels);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const { toUserTime, userNow } = useTimeHelpers();

  const channel = channels?.[recording.channel];

  const deleteRecording = (id) => {
    // Optimistically remove immediately from UI
    try {
      useChannelsStore.getState().removeRecording(id);
    } catch (error) {
      console.error('Failed to optimistically remove recording', error);
    }
    // Fire-and-forget server delete; websocket will keep others in sync
    API.deleteRecording(id).catch(() => {
      // On failure, fallback to refetch to restore state
      try {
        useChannelsStore.getState().fetchRecordings();
      } catch (error) {
        console.error('Failed to refresh recordings after delete', error);
      }
    });
  };

  const customProps = recording.custom_properties || {};
  const program = customProps.program || {};
  const recordingName = program.title || 'Custom Recording';
  const subTitle = program.sub_title || '';
  const description = program.description || customProps.description || '';
  const isRecurringRule = customProps?.rule?.type === 'recurring';

  // Poster or channel logo
  const posterLogoId = customProps.poster_logo_id;
  let posterUrl = posterLogoId
    ? `/api/channels/logos/${posterLogoId}/cache/`
    : customProps.poster_url || channel?.logo?.cache_url || '/logo.png';
  // Prefix API host in dev if using a relative path
  if (env_mode === 'dev' && posterUrl && posterUrl.startsWith('/')) {
    posterUrl = `${window.location.protocol}//${window.location.hostname}:5656${posterUrl}`;
  }

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
  const seLabel =
    season && episode
      ? `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`
      : onscreen || null;

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
    showVideo(fileUrl, 'vod', {
      name: recordingName,
      logo: { url: posterUrl },
    });
  };

  const handleRunComskip = async (e) => {
    e?.stopPropagation?.();
    try {
      await API.runComskip(recording.id);
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
      deleteRecording(recording.id);
    }
  };

  const seriesInfo = (() => {
    const cp = customProps || {};
    const pr = cp.program || {};
    return { tvg_id: pr.tvg_id, title: pr.title };
  })();

  const removeUpcomingOnly = async () => {
    try {
      setBusy(true);
      await API.deleteRecording(recording.id);
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
      const { tvg_id, title } = seriesInfo;
      if (tvg_id) {
        try {
          await API.bulkRemoveSeriesRecordings({
            tvg_id,
            title,
            scope: 'title',
          });
        } catch (error) {
          console.error('Failed to remove series recordings', error);
        }
        try {
          await API.deleteSeriesRule(tvg_id);
        } catch (error) {
          console.error('Failed to delete series rule', error);
        }
      }
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
      onClick={() => {
        if (isRecurringRule) {
          onOpenRecurring?.(recording, false);
        } else {
          onOpenDetails?.(recording);
        }
      }}
    >
      <Flex justify="space-between" align="center" style={{ paddingBottom: 8 }}>
        <Group gap={8} style={{ flex: 1, minWidth: 0 }}>
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
          <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
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
        <Stack gap={6} style={{ flex: 1 }}>
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
              {start.format('MMM D, YYYY h:mma')} – {end.format('h:mma')}
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
            {isInProgress && (
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
            )}

            {!isUpcoming && (
              <Tooltip
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
                    customProps.status === 'recording' ||
                    !(customProps.file_url || customProps.output_file_url)
                  }
                >
                  Watch
                </Button>
              </Tooltip>
            )}
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

const DVRPage = () => {
  const theme = useMantineTheme();
  const recordings = useChannelsStore((s) => s.recordings);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const channels = useChannelsStore((s) => s.channels);
  const fetchChannels = useChannelsStore((s) => s.fetchChannels);
  const fetchRecurringRules = useChannelsStore((s) => s.fetchRecurringRules);
  const { toUserTime, userNow } = useTimeHelpers();

  const [recordingModalOpen, setRecordingModalOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsRecording, setDetailsRecording] = useState(null);
  const [ruleModal, setRuleModal] = useState({ open: false, ruleId: null });
  const [editRecording, setEditRecording] = useState(null);

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

  const openRuleModal = (recording) => {
    const ruleId = recording?.custom_properties?.rule?.id;
    if (!ruleId) {
      openDetails(recording);
      return;
    }
    setDetailsOpen(false);
    setDetailsRecording(null);
    setEditRecording(null);
    setRuleModal({ open: true, ruleId });
  };

  const closeRuleModal = () => setRuleModal({ open: false, ruleId: null });

  useEffect(() => {
    if (!channels || Object.keys(channels).length === 0) {
      fetchChannels();
    }
    fetchRecordings();
    fetchRecurringRules();
  }, [channels, fetchChannels, fetchRecordings, fetchRecurringRules]);

  // Re-render every second so time-based bucketing updates without a refresh
  const [now, setNow] = useState(userNow());
  useEffect(() => {
    const interval = setInterval(() => setNow(userNow()), 1000);
    return () => clearInterval(interval);
  }, [userNow]);

  useEffect(() => {
    setNow(userNow());
  }, [userNow]);

  // Categorize recordings
  const { inProgress, upcoming, completed } = useMemo(() => {
    const inProgress = [];
    const upcoming = [];
    const completed = [];
    const list = Array.isArray(recordings)
      ? recordings
      : Object.values(recordings || {});

    // ID-based dedupe guard in case store returns duplicates
    const seenIds = new Set();
    for (const rec of list) {
      if (rec && rec.id != null) {
        const k = String(rec.id);
        if (seenIds.has(k)) continue;
        seenIds.add(k);
      }
      const s = toUserTime(rec.start_time);
      const e = toUserTime(rec.end_time);
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
        const sig =
          pr?.id != null
            ? `id:${pr.id}`
            : `slot:${r.channel}|${r.start_time}|${r.end_time}|${pr.title || ''}`;
        if (sigs.has(sig)) continue;
        sigs.add(sig);
        out.push(r);
      }
      return out;
    };

    const inProgressDedup = dedupeByProgramOrSlot(inProgress).sort(
      (a, b) => toUserTime(b.start_time) - toUserTime(a.start_time)
    );

    // Group upcoming by series title+tvg_id (keep only next episode)
    const grouped = new Map();
    const upcomingDedup = dedupeByProgramOrSlot(upcoming).sort(
      (a, b) => toUserTime(a.start_time) - toUserTime(b.start_time)
    );
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
    completed.sort((a, b) => toUserTime(b.end_time) - toUserTime(a.end_time));
    return {
      inProgress: inProgressDedup,
      upcoming: upcomingGrouped,
      completed,
    };
  }, [recordings, now, toUserTime]);

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
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {inProgress.map((rec) => (
              <RecordingCard
                key={`rec-${rec.id}`}
                recording={rec}
                onOpenDetails={openDetails}
                onOpenRecurring={openRuleModal}
              />
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
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {upcoming.map((rec) => (
              <RecordingCard
                key={`rec-${rec.id}`}
                recording={rec}
                onOpenDetails={openDetails}
                onOpenRecurring={openRuleModal}
              />
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
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {completed.map((rec) => (
              <RecordingCard
                key={`rec-${rec.id}`}
                recording={rec}
                onOpenDetails={openDetails}
                onOpenRecurring={openRuleModal}
              />
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

      <RecordingForm
        isOpen={Boolean(editRecording)}
        recording={editRecording}
        onClose={() => setEditRecording(null)}
      />

      <RecurringRuleModal
        opened={ruleModal.open}
        onClose={closeRuleModal}
        ruleId={ruleModal.ruleId}
        onEditOccurrence={(occ) => {
          setRuleModal({ open: false, ruleId: null });
          setEditRecording(occ);
        }}
      />

      {/* Details Modal */}
      {detailsRecording && (
        <RecordingDetailsModal
          opened={detailsOpen}
          onClose={closeDetails}
          recording={detailsRecording}
          channel={channels[detailsRecording.channel]}
          posterUrl={
            (detailsRecording.custom_properties?.poster_logo_id
              ? `/api/channels/logos/${detailsRecording.custom_properties.poster_logo_id}/cache/`
              : detailsRecording.custom_properties?.poster_url ||
                channels[detailsRecording.channel]?.logo?.cache_url) ||
            '/logo.png'
          }
          env_mode={useSettingsStore.getState().environment.env_mode}
          onWatchLive={() => {
            const rec = detailsRecording;
            const now = userNow();
            const s = toUserTime(rec.start_time);
            const e = toUserTime(rec.end_time);
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
            let fileUrl =
              detailsRecording.custom_properties?.file_url ||
              detailsRecording.custom_properties?.output_file_url;
            if (!fileUrl) return;
            if (
              useSettingsStore.getState().environment.env_mode === 'dev' &&
              fileUrl.startsWith('/')
            ) {
              fileUrl = `${window.location.protocol}//${window.location.hostname}:5656${fileUrl}`;
            }
            useVideoStore.getState().showVideo(fileUrl, 'vod', {
              name:
                detailsRecording.custom_properties?.program?.title ||
                'Recording',
              logo: {
                url:
                  (detailsRecording.custom_properties?.poster_logo_id
                    ? `/api/channels/logos/${detailsRecording.custom_properties.poster_logo_id}/cache/`
                    : channels[detailsRecording.channel]?.logo?.cache_url) ||
                  '/logo.png',
              },
            });
          }}
          onEdit={(rec) => {
            setEditRecording(rec);
            closeDetails();
          }}
        />
      )}
    </Box>
  );
};

export default DVRPage;
