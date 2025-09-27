import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Collapse,
  FileInput,
  Flex,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Slider,
  NumberInput,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Tooltip,
  MultiSelect,
  Code,
} from '@mantine/core';
import {
  Download,
  PlayCircle,
  RefreshCcw,
  UploadCloud,
  ChevronDown,
  ChevronRight,
  XCircle,
  Save,
} from 'lucide-react';
import { notifications } from '@mantine/notifications';
import { useForm } from '@mantine/form';
import { TimeInput } from '@mantine/dates';

import API from '../../api';
import useBackupsStore from '../../store/backups';
import ConfirmationDialog from '../ConfirmationDialog';

const statusColor = {
  pending: 'yellow',
  running: 'blue',
  succeeded: 'green',
  failed: 'red',
  canceled: 'gray',
};
const DEFAULT_SCHEDULE = {
  preset: 'daily',
  minute: '15',
  hour: '3',
  day_of_month: '*',
  month: '*',
  day_of_week: '*',
  timezone: Intl?.DateTimeFormat?.().resolvedOptions().timeZone || 'UTC',
};

const schedulePresets = [
  { value: 'hourly', label: 'Every N hours' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'custom', label: 'Custom cron' },
];

const weekdayOptions = [
  { value: 'sun', label: 'Sun' },
  { value: 'mon', label: 'Mon' },
  { value: 'tue', label: 'Tue' },
  { value: 'wed', label: 'Wed' },
  { value: 'thu', label: 'Thu' },
  { value: 'fri', label: 'Fri' },
  { value: 'sat', label: 'Sat' },
];

const monthDayOptions = Array.from({ length: 28 }, (_, index) => {
  const value = String(index + 1);
  return { value, label: value };
});

const ensureArray = (value) => (Array.isArray(value) ? value : []);

const pad = (num) => String(num).padStart(2, '0');

const normalizeFormValues = (values) => ({
  enabled: values.enabled,
  retention: values.retention,
  path: values.path,
  include_recordings: values.include_recordings,
  preset: values.preset,
  hourlyInterval: values.hourlyInterval,
  hourlyMinute: values.hourlyMinute,
  dailyTime: values.dailyTime,
  weeklyTime: values.weeklyTime,
  weeklyDays: [...ensureArray(values.weeklyDays)].sort(),
  monthlyTime: values.monthlyTime,
  monthlyDays: [...ensureArray(values.monthlyDays)].sort(),
  customMinute: values.customMinute,
  customHour: values.customHour,
  customDayOfMonth: values.customDayOfMonth,
  customMonth: values.customMonth,
  customDayOfWeek: values.customDayOfWeek,
  timezone: values.timezone,
});

const shallowEqual = (a, b) => {
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) {
    return false;
  }
  return keysA.every((key) => {
    const valueA = a[key];
    const valueB = b[key];
    if (Array.isArray(valueA) && Array.isArray(valueB)) {
      if (valueA.length !== valueB.length) {
        return false;
      }
      return valueA.every((item, index) => item === valueB[index]);
    }
    return valueA === valueB;
  });
};

const parseTimeString = (value, fallback = '03:00') => {
  if (!value || typeof value !== 'string') {
    return fallback;
  }
  const [hour, minute] = value.split(':');
  const h = Number.parseInt(hour, 10);
  const m = Number.parseInt(minute, 10);
  if (Number.isNaN(h) || Number.isNaN(m)) {
    return fallback;
  }
  return `${pad(Math.max(0, Math.min(23, h)))}:${pad(Math.max(0, Math.min(59, m)))}`;
};

const parseScheduleToForm = (schedule = DEFAULT_SCHEDULE) => {
  const merged = { ...DEFAULT_SCHEDULE, ...schedule };
  const preset = merged.preset || 'custom';

  const formValues = {
    preset,
    hourlyInterval: 1,
    hourlyMinute: Number.parseInt(merged.minute, 10) || 0,
    dailyTime: parseTimeString(`${pad(merged.hour)}:${pad(merged.minute)}`),
    weeklyTime: parseTimeString(`${pad(merged.hour)}:${pad(merged.minute)}`),
    weeklyDays: merged.day_of_week === '*' ? weekdayOptions.map((day) => day.value) : merged.day_of_week.split(',').filter(Boolean),
    monthlyTime: parseTimeString(`${pad(merged.hour)}:${pad(merged.minute)}`),
    monthlyDays: merged.day_of_month === '*' ? ['1'] : merged.day_of_month.split(',').filter(Boolean),
    customMinute: merged.minute,
    customHour: merged.hour,
    customDayOfMonth: merged.day_of_month,
    customMonth: merged.month,
    customDayOfWeek: merged.day_of_week,
    timezone: merged.timezone || DEFAULT_SCHEDULE.timezone,
  };

  if (preset === 'hourly') {
    const match = /^\*\/(\d+)$/.exec(merged.hour);
    formValues.hourlyInterval = match ? Number.parseInt(match[1], 10) : 1;
    formValues.hourlyMinute = Number.parseInt(merged.minute, 10) || 0;
  }

  if (preset === 'daily') {
    formValues.dailyTime = parseTimeString(`${pad(merged.hour)}:${pad(merged.minute)}`, '03:00');
  }

  if (preset === 'weekly') {
    formValues.weeklyTime = parseTimeString(`${pad(merged.hour)}:${pad(merged.minute)}`, '03:00');
    formValues.weeklyDays = merged.day_of_week === '*' ? weekdayOptions.map((day) => day.value) : merged.day_of_week.split(',').filter(Boolean);
  }

  if (preset === 'monthly') {
    formValues.monthlyTime = parseTimeString(`${pad(merged.hour)}:${pad(merged.minute)}`, '03:00');
    formValues.monthlyDays = merged.day_of_month === '*' ? ['1'] : merged.day_of_month.split(',').filter(Boolean);
  }

  return formValues;
};

const buildScheduleFromForm = (values) => {
  const timezone = values.timezone?.trim() || DEFAULT_SCHEDULE.timezone;
  const preset = values.preset || 'custom';

  const base = {
    preset,
    minute: DEFAULT_SCHEDULE.minute,
    hour: DEFAULT_SCHEDULE.hour,
    day_of_month: DEFAULT_SCHEDULE.day_of_month,
    month: DEFAULT_SCHEDULE.month,
    day_of_week: DEFAULT_SCHEDULE.day_of_week,
    timezone,
  };

  const safeMinute = (minute) => pad(Math.max(0, Math.min(59, Number.parseInt(minute, 10) || 0)));

  if (preset === 'hourly') {
    const interval = Math.max(1, Math.min(24, Number.parseInt(values.hourlyInterval, 10) || 1));
    return {
      ...base,
      minute: safeMinute(values.hourlyMinute ?? 0),
      hour: interval === 1 ? '*' : `*/${interval}`,
      day_of_month: '*',
      month: '*',
      day_of_week: '*',
    };
  }

  if (preset === 'daily') {
    const time = parseTimeString(values.dailyTime, '03:00');
    const [hour, minute] = time.split(':');
    return {
      ...base,
      minute,
      hour,
      day_of_month: '*',
      month: '*',
      day_of_week: '*',
    };
  }

  if (preset === 'weekly') {
    const time = parseTimeString(values.weeklyTime, '03:00');
    const [hour, minute] = time.split(':');
    const days = ensureArray(values.weeklyDays);
    const selected = days.length ? days : ['mon'];
    return {
      ...base,
      minute,
      hour,
      day_of_month: '*',
      month: '*',
      day_of_week: selected.join(','),
    };
  }

  if (preset === 'monthly') {
    const time = parseTimeString(values.monthlyTime, '03:00');
    const [hour, minute] = time.split(':');
    const days = ensureArray(values.monthlyDays).map((day) => String(day));
    const selected = days.length ? days : ['1'];
    return {
      ...base,
      minute,
      hour,
      day_of_month: selected.join(','),
      month: '*',
      day_of_week: '*',
    };
  }

  const cronValue = (field, fallback) => {
    const value = (values[field] || '').trim();
    return value || fallback;
  };

  return {
    ...base,
    minute: cronValue('customMinute', DEFAULT_SCHEDULE.minute),
    hour: cronValue('customHour', DEFAULT_SCHEDULE.hour),
    day_of_month: cronValue('customDayOfMonth', DEFAULT_SCHEDULE.day_of_month),
    month: cronValue('customMonth', DEFAULT_SCHEDULE.month),
    day_of_week: cronValue('customDayOfWeek', DEFAULT_SCHEDULE.day_of_week),
    preset: 'custom',
  };
};

const describeSchedule = (schedule) => {
  const { preset, minute, hour, day_of_month: dom, month, day_of_week: dow } = schedule;
  const cron = `${minute} ${hour} ${dom} ${month} ${dow}`;
  const time = `${pad(Number.parseInt(hour, 10) || 0)}:${pad(Number.parseInt(minute, 10) || 0)}`;

  if (preset === 'hourly') {
    const match = /^\*\/(\d+)$/.exec(hour);
    const every = match ? Number.parseInt(match[1], 10) : 1;
    return every === 1
      ? `Runs every hour at minute ${minute}`
      : `Runs every ${every} hours at minute ${minute}`;
  }
  if (preset === 'daily') {
    return `Runs daily at ${time}`;
  }
  if (preset === 'weekly') {
    if (dow === '*') {
      return `Runs daily at ${time}`;
    }
    const labels = dow.split(',').map((value) => {
      const option = weekdayOptions.find((entry) => entry.value === value);
      return option ? option.label : value;
    });
    return `Runs weekly on ${labels.join(', ')} at ${time}`;
  }
  if (preset === 'monthly') {
    const days = dom === '*' ? 'day 1' : dom.split(',').join(', ');
    return `Runs monthly on day(s) ${days} at ${time}`;
  }
  return `Cron: ${cron}`;
};

const cronExpression = (schedule) =>
  `${schedule.minute} ${schedule.hour} ${schedule.day_of_month} ${schedule.month} ${schedule.day_of_week}`;

const BackupManager = () => {
  const {
    jobs,
    settings,
    loading,
    saving,
    fetchSettings,
    fetchJobs,
    runBackup,
    restoreBackup,
    uploadAndRestore,
    updateSettings,
    cancelJob,
    deleteJob,
  } = useBackupsStore();

  const [uploadFile, setUploadFile] = useState(null);
  const [downloadingIds, setDownloadingIds] = useState([]);
  const downloadingRef = useRef(new Set());
  const [expandedJobId, setExpandedJobId] = useState(null);
  const [restoreModal, setRestoreModal] = useState({ open: false, mode: null, job: null });
  const [dangerInput, setDangerInput] = useState('');
  const [confirmState, setConfirmState] = useState({ open: false, mode: null, job: null });
  const [activeSection, setActiveSection] = useState('automation');

  const initialScheduleConfig = useMemo(
    () => parseScheduleToForm(settings.schedule || DEFAULT_SCHEDULE),
    [settings.schedule]
  );

  const form = useForm({
    initialValues: {
      enabled: settings.enabled,
      retention: settings.retention,
      path: settings.path,
      include_recordings: settings.include_recordings,
      preset: initialScheduleConfig.preset,
      hourlyInterval: initialScheduleConfig.hourlyInterval,
      hourlyMinute: initialScheduleConfig.hourlyMinute,
      dailyTime: initialScheduleConfig.dailyTime,
      weeklyTime: initialScheduleConfig.weeklyTime,
      weeklyDays: initialScheduleConfig.weeklyDays,
      monthlyTime: initialScheduleConfig.monthlyTime,
      monthlyDays: initialScheduleConfig.monthlyDays,
      customMinute: initialScheduleConfig.customMinute,
      customHour: initialScheduleConfig.customHour,
      customDayOfMonth: initialScheduleConfig.customDayOfMonth,
      customMonth: initialScheduleConfig.customMonth,
      customDayOfWeek: initialScheduleConfig.customDayOfWeek,
      timezone: initialScheduleConfig.timezone,
    },
  });

  useEffect(() => {
    fetchSettings();
    fetchJobs();
    const id = useBackupsStore.getState().pollUntilSettled?.();
    return () => {
      if (id) {
        clearInterval(id);
      }
    };
  }, []);

  useEffect(() => {
    const scheduleValues = parseScheduleToForm(settings.schedule || DEFAULT_SCHEDULE);
    const nextValues = {
      enabled: settings.enabled,
      retention: settings.retention,
      path: settings.path,
      include_recordings: settings.include_recordings,
      preset: scheduleValues.preset,
      hourlyInterval: scheduleValues.hourlyInterval,
      hourlyMinute: scheduleValues.hourlyMinute,
      dailyTime: scheduleValues.dailyTime,
      weeklyTime: scheduleValues.weeklyTime,
      weeklyDays: scheduleValues.weeklyDays,
      monthlyTime: scheduleValues.monthlyTime,
      monthlyDays: scheduleValues.monthlyDays,
      customMinute: scheduleValues.customMinute,
      customHour: scheduleValues.customHour,
      customDayOfMonth: scheduleValues.customDayOfMonth,
      customMonth: scheduleValues.customMonth,
      customDayOfWeek: scheduleValues.customDayOfWeek,
      timezone: scheduleValues.timezone,
    };

    const current = normalizeFormValues(form.getValues());
    const normalizedNext = normalizeFormValues(nextValues);
    if (shallowEqual(current, normalizedNext)) {
      return;
    }
    form.setValues(nextValues);
  }, [settings.schedule, settings.enabled, settings.retention, settings.path, settings.include_recordings]);

  const schedulePreview = useMemo(
    () => buildScheduleFromForm(form.values),
    [form.values]
  );
  const scheduleSummary = useMemo(
    () => describeSchedule(schedulePreview),
    [schedulePreview]
  );

  const timezoneOptions = useMemo(() => {
    if (typeof Intl?.supportedValuesOf === 'function') {
      return Intl.supportedValuesOf('timeZone').map((tz) => ({ value: tz, label: tz }));
    }
    return [];
  }, []);

  const timezoneData = useMemo(() => {
    if (!timezoneOptions.length) {
      return [];
    }
    const data = [...timezoneOptions];
    const current = form.values.timezone;
    if (current && !data.some((item) => item.value === current)) {
      data.push({ value: current, label: current });
    }
    return data;
  }, [timezoneOptions, form.values.timezone]);

  const onPresetChange = (value) => {
    const preset = value || 'custom';
    const previousPreset = form.values.preset;
    form.setFieldValue('preset', preset);
    if (preset === 'weekly' && previousPreset !== 'weekly') {
      form.setFieldValue('weeklyDays', ['mon']);
    }
    if (preset === 'monthly' && previousPreset !== 'monthly') {
      form.setFieldValue('monthlyDays', ['1']);
    }
  };

  const cronPreview = cronExpression(schedulePreview);

  const hasRunningJob = useMemo(
    () => jobs.some((job) => ['pending', 'running'].includes(job.status)),
    [jobs]
  );

  const onSaveSettings = async () => {
    try {
      const values = form.getValues();
      const schedule = buildScheduleFromForm(values);
      await updateSettings({
        enabled: values.enabled,
        retention: values.retention,
        path: values.path,
        include_recordings: values.include_recordings,
        schedule,
      });
    } catch (error) {
      // handled by store notifications
    }
  };

  const renderPresetControls = () => {
    if (form.values.preset === 'hourly') {
      return (
        <Stack gap="xs">
          <Text size="sm" fw={500}>
            Interval (hours)
          </Text>
          <Slider
            min={1}
            max={24}
            step={1}
            marks={[
              { value: 1, label: '1' },
              { value: 6, label: '6' },
              { value: 12, label: '12' },
              { value: 24, label: '24' },
            ]}
            value={form.values.hourlyInterval}
            onChange={(value) => form.setFieldValue('hourlyInterval', value)}
          />
          <NumberInput
            label="Minute"
            description="0 – 59"
            min={0}
            max={59}
            value={form.values.hourlyMinute}
            onChange={(value) => form.setFieldValue('hourlyMinute', value ?? 0)}
            maw={220}
          />
        </Stack>
      );
    }

    if (form.values.preset === 'daily') {
      return (
        <TimeInput
          label="Backup time"
          value={form.values.dailyTime}
          onChange={(event) => form.setFieldValue('dailyTime', event.currentTarget.value)}
          format="24"
          maw={220}
        />
      );
    }

    if (form.values.preset === 'weekly') {
      return (
        <Flex gap="sm" direction={{ base: 'column', sm: 'row' }}>
          <TimeInput
            label="Backup time"
            value={form.values.weeklyTime}
            onChange={(event) => form.setFieldValue('weeklyTime', event.currentTarget.value)}
            format="24"
            maw={220}
          />
          <MultiSelect
            label="Days of week"
            data={weekdayOptions}
            value={form.values.weeklyDays}
            onChange={(value) => form.setFieldValue('weeklyDays', value)}
            searchable
            clearable
            nothingFoundMessage="No matches"
            withinPortal
            style={{ flex: 1 }}
          />
        </Flex>
      );
    }

    if (form.values.preset === 'monthly') {
      return (
        <Flex gap="sm" direction={{ base: 'column', sm: 'row' }}>
          <TimeInput
            label="Backup time"
            value={form.values.monthlyTime}
            onChange={(event) => form.setFieldValue('monthlyTime', event.currentTarget.value)}
            format="24"
            maw={220}
          />
          <MultiSelect
            label="Day(s) of month"
            data={monthDayOptions}
            value={form.values.monthlyDays}
            onChange={(value) => form.setFieldValue('monthlyDays', value)}
            searchable
            withinPortal
            style={{ flex: 1 }}
          />
        </Flex>
      );
    }

    return (
      <Flex gap="sm" direction={{ base: 'column', md: 'row' }}>
        <TextInput
          label="Minute"
          value={form.values.customMinute}
          onChange={(event) => form.setFieldValue('customMinute', event.currentTarget.value)}
        />
        <TextInput
          label="Hour"
          value={form.values.customHour}
          onChange={(event) => form.setFieldValue('customHour', event.currentTarget.value)}
        />
        <TextInput
          label="Day of month"
          value={form.values.customDayOfMonth}
          onChange={(event) => form.setFieldValue('customDayOfMonth', event.currentTarget.value)}
        />
        <TextInput
          label="Month"
          value={form.values.customMonth}
          onChange={(event) => form.setFieldValue('customMonth', event.currentTarget.value)}
        />
        <TextInput
          label="Day of week"
          value={form.values.customDayOfWeek}
          onChange={(event) => form.setFieldValue('customDayOfWeek', event.currentTarget.value)}
        />
      </Flex>
    );
  };

  const markDownloading = (jobId) => {
    if (downloadingRef.current.has(jobId)) {
      return false;
    }
    downloadingRef.current.add(jobId);
    setDownloadingIds(Array.from(downloadingRef.current));
    return true;
  };

  const clearDownloading = (jobId) => {
    if (!downloadingRef.current.has(jobId)) {
      return;
    }
    downloadingRef.current.delete(jobId);
    setDownloadingIds(Array.from(downloadingRef.current));
  };

  const onDownload = async (jobId) => {
    if (!markDownloading(jobId)) {
      return;
    }
    try {
      const { blob, filename } = await API.downloadBackupJob(jobId);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      // notification already shown
    } finally {
      clearDownloading(jobId);
    }
  };

  const onUpload = () => {
    if (!uploadFile) {
      notifications.show({
        title: 'Restore',
        message: 'Select a backup archive to upload',
        color: 'yellow',
      });
      return;
    }
    setRestoreModal({ open: true, mode: 'upload', job: null });
    setDangerInput('');
  };

  const handleRestoreConfirm = async () => {
    if (dangerInput !== 'I UNDERSTAND') {
      notifications.show({
        title: 'Restore',
        message: 'Type I UNDERSTAND to confirm the restore.',
        color: 'red',
      });
      return;
    }

    try {
      if (restoreModal.mode === 'job' && restoreModal.job) {
        await restoreBackup(restoreModal.job.id);
      }
      if (restoreModal.mode === 'upload' && uploadFile) {
        await uploadAndRestore(uploadFile);
        setUploadFile(null);
      }
    } finally {
      setRestoreModal({ open: false, mode: null, job: null });
      setDangerInput('');
    }
  };

  const handleCancelJob = (job) => {
    setConfirmState({ open: true, mode: 'cancel', job });
  };

  const handleDeleteJob = (job) => {
    setConfirmState({ open: true, mode: 'delete', job });
  };

  const handleConfirmAction = async () => {
    const { mode, job } = confirmState;
    if (!job) {
      setConfirmState({ open: false, mode: null, job: null });
      return;
    }

    try {
      if (mode === 'cancel') {
        await cancelJob(job.id);
      } else if (mode === 'delete') {
        await deleteJob(job.id);
      }
    } finally {
      setConfirmState({ open: false, mode: null, job: null });
    }
  };

  const renderJobDetails = (job) => (
    <Stack gap={4} maw="100%">
      <Text size="sm">
        <Text span fw={500}>Original file:</Text> {job.original_filename || '—'}
      </Text>
      <Text size="sm">
        <Text span fw={500}>Celery task ID:</Text> {job.celery_task_id || '—'}
      </Text>
      <Text size="sm">
        <Text span fw={500}>Scheduled job:</Text> {job.scheduled ? 'Yes' : 'No'}
      </Text>
      {job.error_message && (
        <Text size="sm" c="red">
          <Text span fw={500}>Error:</Text> {job.error_message}
        </Text>
      )}
      {job.file_path && (
        <Text size="sm">
          <Text span fw={500}>Archive path:</Text> /data/backups/{job.file_path}
        </Text>
      )}
    </Stack>
  );

  return (
    <Stack gap="md">
      <Accordion value={activeSection} onChange={(value) => setActiveSection(value || 'automation')}>
        <Accordion.Item value="automation">
          <Accordion.Control>Automation</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm" mt="sm">
              <Switch
                label="Enable scheduled backups"
                checked={form.values.enabled}
                onChange={(event) => form.setFieldValue('enabled', event.currentTarget.checked)}
              />
              <Flex
                gap="sm"
                direction={{ base: 'column', sm: 'row' }}
                align={{ base: 'stretch', sm: 'flex-end' }}
              >
                <NumberInput
                  label="Retention"
                  description="Successful backups to keep"
                  min={0}
                  value={form.values.retention}
                  onChange={(value) => form.setFieldValue('retention', value || 0)}
                  style={{ flex: 1 }}
                />
                <TextInput
                  label="Backup path"
                  value={form.values.path}
                  onChange={(event) => form.setFieldValue('path', event.currentTarget.value)}
                  style={{ flex: 1 }}
                />
              </Flex>
              <Stack gap="sm">
                <SegmentedControl
                  data={schedulePresets}
                  value={form.values.preset}
                  onChange={onPresetChange}
                />
                {renderPresetControls()}
                {timezoneData.length ? (
                  <Select
                    label="Timezone"
                    data={timezoneData}
                    searchable
                    value={form.values.timezone}
                    onChange={(value) =>
                      form.setFieldValue('timezone', value || form.values.timezone)
                    }
                  />
                ) : (
                  <TextInput
                    label="Timezone"
                    value={form.values.timezone}
                    onChange={(event) => form.setFieldValue('timezone', event.currentTarget.value)}
                  />
                )}
                <Alert color="blue" variant="light" title="Schedule preview">
                  <Text size="sm">{scheduleSummary}</Text>
                  <Code mt="xs">{cronPreview}</Code>
                </Alert>
              </Stack>
              <Switch
                label="Include recordings directory"
                checked={form.values.include_recordings}
                onChange={(event) =>
                  form.setFieldValue('include_recordings', event.currentTarget.checked)
                }
              />
              <Group gap="sm">
                <Button onClick={onSaveSettings} loading={saving} leftSection={<Save size={16} />}>
                  Save settings
                </Button>
              </Group>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="manual">
          <Accordion.Control>Manual backup</Accordion.Control>
          <Accordion.Panel>
            <Group gap="sm" mt="sm">
              <Button
                variant="outline"
                onClick={runBackup}
                leftSection={<PlayCircle size={16} />}
                loading={hasRunningJob}
              >
                Run backup now
              </Button>
            </Group>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="restore">
          <Accordion.Control>Restore</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm" mt="sm">
              <FileInput
                placeholder="Select backup archive"
                value={uploadFile}
                onChange={setUploadFile}
                accept=".gz,.tar,.tgz"
                leftSection={<UploadCloud size={16} />}
              />
              <Button
                onClick={onUpload}
                disabled={!uploadFile}
                leftSection={<UploadCloud size={16} />}
              >
                Upload & Restore
              </Button>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Box>
        <Stack gap="sm">
          <Text fw={600}>History</Text>
          {loading ? (
            <Flex justify="center" py="xl">
              <Loader />
            </Flex>
          ) : (
            <Table striped highlightOnHover withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th style={{ width: 36 }}></Table.Th>
                  <Table.Th>ID</Table.Th>
                  <Table.Th>Type</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Created</Table.Th>
                  <Table.Th>Finished</Table.Th>
                  <Table.Th>Size (MB)</Table.Th>
                  <Table.Th>Triggered By</Table.Th>
                  <Table.Th style={{ width: 220 }}>Actions</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {jobs.map((job) => (
                  <Fragment key={job.id}>
                    <Table.Tr style={{ verticalAlign: 'middle' }}>
                      <Table.Td>
                        <Tooltip label={expandedJobId === job.id ? 'Hide details' : 'Show details'}>
                          <ActionIcon
                            variant="subtle"
                            onClick={() =>
                              setExpandedJobId(expandedJobId === job.id ? null : job.id)
                            }
                          >
                            {expandedJobId === job.id ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          </ActionIcon>
                        </Tooltip>
                      </Table.Td>
                      <Table.Td>{job.id}</Table.Td>
                      <Table.Td>{job.job_type}</Table.Td>
                      <Table.Td>
                        <Badge
                          color={statusColor[job.status] || 'gray'}
                          variant="filled"
                          radius="sm"
                          size="md"
                          style={{
                            minWidth: 96,
                            justifyContent: 'center',
                            textTransform: 'capitalize',
                          }}
                        >
                          {job.status}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{new Date(job.created_at).toLocaleString()}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">
                          {job.completed_at ? new Date(job.completed_at).toLocaleString() : '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">
                          {job.file_size ? (job.file_size / (1024 * 1024)).toFixed(2) : '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{job.requested_by || 'System'}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap="xs" wrap="wrap">
                          {job.can_cancel && (
                            <Tooltip label="Cancel running backup">
                              <Button
                                variant="outline"
                                color="red"
                                size="xs"
                                onClick={() => handleCancelJob(job)}
                                leftSection={<XCircle size={14} />}
                              >
                                Cancel
                              </Button>
                            </Tooltip>
                          )}
                          {job.job_type === 'backup' && job.status === 'succeeded' && (
                            <Tooltip label="Download archive">
                              <Button
                                variant="light"
                                size="xs"
                                onClick={() => onDownload(job.id)}
                                loading={downloadingIds.includes(job.id)}
                                leftSection={<Download size={14} />}
                                style={{ minWidth: 96 }}
                              >
                                Download
                              </Button>
                            </Tooltip>
                          )}
                          {job.job_type === 'backup' && job.status === 'succeeded' && (
                            <Tooltip label="Restore configuration">
                              <Button
                                variant="outline"
                                size="xs"
                                onClick={() => {
                                  setRestoreModal({ open: true, mode: 'job', job });
                                  setDangerInput('');
                                }}
                                leftSection={<RefreshCcw size={14} />}
                                style={{ minWidth: 96 }}
                              >
                                Restore
                              </Button>
                            </Tooltip>
                          )}
                          {job.can_delete && (
                            <Tooltip label="Remove job and archive">
                              <Button
                                variant="subtle"
                                size="xs"
                                color="red"
                                onClick={() => handleDeleteJob(job)}
                              >
                                Delete
                              </Button>
                            </Tooltip>
                          )}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                    <Table.Tr style={{ display: expandedJobId === job.id ? 'table-row' : 'none' }}>
                      <Table.Td colSpan={9}>
                        <Collapse in={expandedJobId === job.id}>{renderJobDetails(job)}</Collapse>
                      </Table.Td>
                    </Table.Tr>
                  </Fragment>
                ))}
                {!jobs.length && (
                  <Table.Tr>
                    <Table.Td colSpan={9}>
                      <Text c="dimmed" ta="center">
                        No backups yet. Run a manual backup to get started.
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                )}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Box>

      <Modal
        opened={restoreModal.open}
        onClose={() => {
          setRestoreModal({ open: false, mode: null, job: null });
          setDangerInput('');
        }}
        title={<Text c="red" fw={600}>Confirm restore</Text>}
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Restoring will overwrite the Dispatcharr database and all data under the configured `/data`
            directories. Ensure no critical tasks are running and you have a recent backup.
          </Text>
          <Text size="sm" fw={500}>
            Type <Text span c="red">I UNDERSTAND</Text> to continue.
          </Text>
          <TextInput
            value={dangerInput}
            onChange={(event) => setDangerInput(event.currentTarget.value)}
            placeholder="I UNDERSTAND"
          />
          <Group justify="flex-end" gap="sm">
            <Button
              variant="default"
              onClick={() => {
                setRestoreModal({ open: false, mode: null, job: null });
                setDangerInput('');
              }}
            >
              Cancel
            </Button>
            <Button
              color="red"
              onClick={handleRestoreConfirm}
              disabled={dangerInput !== 'I UNDERSTAND'}
            >
              Confirm restore
            </Button>
          </Group>
        </Stack>
      </Modal>

      <ConfirmationDialog
        opened={confirmState.open}
        onClose={() => setConfirmState({ open: false, mode: null, job: null })}
        onConfirm={handleConfirmAction}
        title={confirmState.mode === 'cancel' ? 'Cancel backup job' : 'Delete backup job'}
        message={
          confirmState.mode === 'cancel'
            ? 'Canceling stops the running backup and removes any partial archive.'
            : 'Deleting removes the backup archive and job history permanently.'
        }
        confirmLabel={confirmState.mode === 'cancel' ? 'Cancel job' : 'Delete job'}
        confirmColor={confirmState.mode === 'cancel' ? 'yellow' : 'red'}
      />
    </Stack>
  );
};

export default BackupManager;
