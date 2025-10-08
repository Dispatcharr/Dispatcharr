import React, { useEffect, useMemo, useState } from 'react';
import dayjs from 'dayjs';
import API from '../../api';
import {
  Alert,
  Button,
  Modal,
  Select,
  Stack,
  SegmentedControl,
  MultiSelect,
  Group,
  TextInput,
} from '@mantine/core';
import { DateTimePicker, TimeInput, DatePickerInput } from '@mantine/dates';
import { CircleAlert } from 'lucide-react';
import { isNotEmpty, useForm } from '@mantine/form';
import useChannelsStore from '../../store/channels';
import { notifications } from '@mantine/notifications';

const DAY_OPTIONS = [
  { value: '6', label: 'Sun' },
  { value: '0', label: 'Mon' },
  { value: '1', label: 'Tue' },
  { value: '2', label: 'Wed' },
  { value: '3', label: 'Thu' },
  { value: '4', label: 'Fri' },
  { value: '5', label: 'Sat' },
];

const asDate = (value) => {
  if (!value) return null;
  if (value instanceof Date) return value;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const toIsoIfDate = (value) => {
  const dt = asDate(value);
  return dt ? dt.toISOString() : value;
};

// Accepts "h:mm A"/"hh:mm A"/"HH:mm"/Date, returns "HH:mm"
const toTimeString = (value) => {
  if (!value) return '00:00';
  if (typeof value === 'string') {
    const parsed = dayjs(value, ['HH:mm', 'hh:mm A', 'h:mm A', 'HH:mm:ss'], true);
    if (parsed.isValid()) return parsed.format('HH:mm');
    return value;
  }
  const dt = asDate(value);
  if (!dt) return '00:00';
  return dayjs(dt).format('HH:mm');
};

const toDateString = (value) => {
  const dt = asDate(value);
  if (!dt) return null;
  const year = dt.getFullYear();
  const month = String(dt.getMonth() + 1).padStart(2, '0');
  const day = String(dt.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const createRoundedDate = (minutesAhead = 0) => {
  const dt = new Date();
  dt.setSeconds(0);
  dt.setMilliseconds(0);
  dt.setMinutes(Math.ceil(dt.getMinutes() / 30) * 30);
  if (minutesAhead) dt.setMinutes(dt.getMinutes() + minutesAhead);
  return dt;
};

// robust onChange for TimeInput (string or event)
const timeChange = (setter) => (valOrEvent) => {
  if (typeof valOrEvent === 'string') setter(valOrEvent);
  else if (valOrEvent?.currentTarget) setter(valOrEvent.currentTarget.value);
};

const RecordingModal = ({ recording = null, channel = null, isOpen, onClose }) => {
  const channels = useChannelsStore((s) => s.channels);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const fetchRecurringRules = useChannelsStore((s) => s.fetchRecurringRules);

  const [mode, setMode] = useState('single');
  const [submitting, setSubmitting] = useState(false);

  const defaultStart = createRoundedDate();
  const defaultEnd = createRoundedDate(60);
  const defaultDate = new Date();

  // One-time form
  const singleForm = useForm({
    mode: 'controlled',
    initialValues: {
      channel_id: recording ? `${recording.channel}` : channel ? `${channel.id}` : '',
      start_time: recording ? asDate(recording.start_time) || defaultStart : defaultStart,
      end_time: recording ? asDate(recording.end_time) || defaultEnd : defaultEnd,
    },
    validate: {
      channel_id: isNotEmpty('Select a channel'),
      start_time: isNotEmpty('Select a start time'),
      end_time: (value, values) => {
        const start = asDate(values.start_time);
        const end = asDate(value);
        if (!end) return 'Select an end time';
        if (start && end <= start) return 'End time must be after start time';
        return null;
      },
    },
  });

  // Recurring form stores times as "HH:mm" strings for stable editing
  const recurringForm = useForm({
    mode: 'controlled',
    validateInputOnChange: false,
    validateInputOnBlur: true,
    initialValues: {
      channel_id: channel ? `${channel.id}` : '',
      days_of_week: [],
      start_time: dayjs(defaultStart).format('HH:mm'),
      end_time: dayjs(defaultEnd).format('HH:mm'),
      rule_name: '',
      start_date: defaultDate,
      end_date: defaultDate,
    },
    validate: {
      channel_id: isNotEmpty('Select a channel'),
      days_of_week: (value) => (value && value.length ? null : 'Pick at least one day'),
      start_time: (value) => (value ? null : 'Select a start time'),
      end_time: (value, values) => {
        if (!value) return 'Select an end time';
        const start = dayjs(values.start_time, ['HH:mm', 'hh:mm A', 'h:mm A'], true);
        const end = dayjs(value, ['HH:mm', 'hh:mm A', 'h:mm A'], true);
        if (start.isValid() && end.isValid() && end.diff(start, 'minute') === 0) {
          return 'End time must differ from start time';
        }
        return null;
      },
      end_date: (value, values) => {
        const end = asDate(value);
        const start = asDate(values.start_date);
        if (!end) return 'Select an end date';
        if (start && end < start) return 'End date cannot be before start date';
        return null;
      },
    },
  });

  useEffect(() => {
    if (!isOpen) return;

    const freshStart = createRoundedDate();
    const freshEnd = createRoundedDate(60);
    const freshDate = new Date();

    if (recording && recording.id) {
      setMode('single');
      singleForm.setValues({
        channel_id: `${recording.channel}`,
        start_time: asDate(recording.start_time) || defaultStart,
        end_time: asDate(recording.end_time) || defaultEnd,
      });
    } else {
      // Reset forms for fresh open
      singleForm.setValues({
        channel_id: channel ? `${channel.id}` : '',
        start_time: freshStart,
        end_time: freshEnd,
      });

      const startStr = dayjs(freshStart).format('HH:mm');
      recurringForm.setValues({
        channel_id: channel ? `${channel.id}` : '',
        days_of_week: [],
        start_time: startStr,
        end_time: dayjs(freshEnd).format('HH:mm'),
        rule_name: channel?.name || '',
        start_date: freshDate,
        end_date: freshDate,
      });
      setMode('single');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, recording, channel]);

  const channelOptions = useMemo(() => {
    const list = Object.values(channels || {});
    list.sort((a, b) => {
      const aNum = Number(a.channel_number) || 0;
      const bNum = Number(b.channel_number) || 0;
      if (aNum === bNum) return (a.name || '').localeCompare(b.name || '');
      return aNum - bNum;
    });
    return list.map((item) => ({ value: `${item.id}`, label: item.name || `Channel ${item.id}` }));
  }, [channels]);

  const resetForms = () => {
    singleForm.reset();
    recurringForm.reset();
    setMode('single');
  };

  const handleClose = () => {
    resetForms();
    onClose?.();
  };

  const handleSingleSubmit = async (values) => {
    try {
      setSubmitting(true);
      if (recording && recording.id) {
        await API.updateRecording(recording.id, {
          channel: values.channel_id,
          start_time: toIsoIfDate(values.start_time),
          end_time: toIsoIfDate(values.end_time),
        });
        notifications.show({
          title: 'Recording updated',
          message: 'Recording schedule updated successfully',
          color: 'green',
          autoClose: 2500,
        });
      } else {
        await API.createRecording({
          channel: values.channel_id,
          start_time: toIsoIfDate(values.start_time),
          end_time: toIsoIfDate(values.end_time),
        });
        notifications.show({
          title: 'Recording scheduled',
          message: 'One-time recording added to DVR queue',
          color: 'green',
          autoClose: 2500,
        });
      }
      await fetchRecordings();
      handleClose();
    } catch (error) {
      console.error('Failed to create recording', error);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRecurringSubmit = async (values) => {
    try {
      setSubmitting(true);
      await API.createRecurringRule({
        channel: values.channel_id,
        days_of_week: (values.days_of_week || []).map((d) => Number(d)),
        start_time: toTimeString(values.start_time),
        end_time: toTimeString(values.end_time),
        start_date: toDateString(values.start_date),
        end_date: toDateString(values.end_date),
        name: values.rule_name?.trim() || '',
      });

      await Promise.all([fetchRecurringRules(), fetchRecordings()]);
      notifications.show({
        title: 'Recurring rule saved',
        message: 'Future slots will be scheduled automatically',
        color: 'green',
        autoClose: 2500,
      });
      handleClose();
    } catch (error) {
      console.error('Failed to create recurring rule', error);
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmit =
    mode === 'single'
      ? singleForm.onSubmit(handleSingleSubmit)
      : recurringForm.onSubmit(handleRecurringSubmit);

  if (!isOpen) return null;

  return (
    <Modal opened={isOpen} onClose={handleClose} title="Channel Recording">
      <Alert
        variant="light"
        color="yellow"
        title="Scheduling Conflicts"
        icon={<CircleAlert />}
        style={{ paddingBottom: 5, marginBottom: 12 }}
      >
        Recordings may fail if active streams or overlapping recordings use up all available tuners.
      </Alert>

      <Stack gap="md">
        <SegmentedControl
          value={mode}
          onChange={setMode}
          disabled={Boolean(recording && recording.id)}
          data={[
            { value: 'single', label: 'One-time' },
            { value: 'recurring', label: 'Recurring' },
          ]}
        />

        <form onSubmit={onSubmit}>
          <Stack gap="md">
            {mode === 'single' ? (
              <Select
                {...singleForm.getInputProps('channel_id')}
                key={singleForm.key('channel_id')}
                label="Channel"
                placeholder="Select channel"
                searchable
                data={channelOptions}
              />
            ) : (
              <Select
                {...recurringForm.getInputProps('channel_id')}
                key={recurringForm.key('channel_id')}
                label="Channel"
                placeholder="Select channel"
                searchable
                data={channelOptions}
              />
            )}

            {mode === 'single' ? (
              <>
                <DateTimePicker
                  {...singleForm.getInputProps('start_time')}
                  key={singleForm.key('start_time')}
                  label="Start"
                  valueFormat="MMM D, YYYY h:mm A"
                  timeInputProps={{ format: '12', withSeconds: false, amLabel: 'AM', pmLabel: 'PM' }}
                />
                <DateTimePicker
                  {...singleForm.getInputProps('end_time')}
                  key={singleForm.key('end_time')}
                  label="End"
                  valueFormat="MMM D, YYYY h:mm A"
                  timeInputProps={{ format: '12', withSeconds: false, amLabel: 'AM', pmLabel: 'PM' }}
                />
              </>
            ) : (
              <>
                <TextInput
                  {...recurringForm.getInputProps('rule_name')}
                  key={recurringForm.key('rule_name')}
                  label="Rule name"
                  placeholder="Morning News, Football Sundays, ..."
                />
                <MultiSelect
                  {...recurringForm.getInputProps('days_of_week')}
                  key={recurringForm.key('days_of_week')}
                  label="Every"
                  placeholder="Select days"
                  data={DAY_OPTIONS}
                  searchable
                  clearable
                  nothingFoundMessage="No match"
                />

                <Group grow>
                  <DatePickerInput
                    label="Start date"
                    value={recurringForm.values.start_date}
                    onChange={(value) =>
                      recurringForm.setFieldValue('start_date', value || new Date())
                    }
                    valueFormat="MMM D, YYYY"
                  />
                  <DatePickerInput
                    label="End date"
                    value={recurringForm.values.end_date}
                    onChange={(value) => recurringForm.setFieldValue('end_date', value)}
                    valueFormat="MMM D, YYYY"
                    minDate={recurringForm.values.start_date || undefined}
                  />
                </Group>

                <Group grow>
                  <TimeInput
                    label="Start time"
                    value={recurringForm.values.start_time}
                    onChange={timeChange((val) =>
                      recurringForm.setFieldValue('start_time', toTimeString(val))
                    )}
                    onBlur={() => recurringForm.validateField('start_time')}
                    withSeconds={false}
                    format="12"                     // shows 12-hour (so "00:00" renders "12:00 AM")
                    inputMode="numeric"
                    amLabel="AM"
                    pmLabel="PM"
                  />

                  <TimeInput
                    label="End time"
                    value={recurringForm.values.end_time}
                    onChange={timeChange((val) =>
                      recurringForm.setFieldValue('end_time', toTimeString(val))
                    )}
                    onBlur={() => recurringForm.validateField('end_time')}
                    withSeconds={false}
                    format="12"
                    inputMode="numeric"
                    amLabel="AM"
                    pmLabel="PM"
                  />
                </Group>
              </>
            )}

            <Group justify="flex-end">
              <Button type="submit" loading={submitting}>
                {mode === 'single' ? 'Schedule Recording' : 'Save Rule'}
              </Button>
            </Group>
          </Stack>
        </form>
      </Stack>
    </Modal>
  );
};

export default RecordingModal;
