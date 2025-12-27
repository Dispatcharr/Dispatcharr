import useChannelsStore from '../../store/channels.jsx';
import {
  parseDate,
  RECURRING_DAY_OPTIONS,
  toTimeString,
  useDateTimeFormat,
  useTimeHelpers,
} from '../../utils/dateTimeUtils.js';
import React, { useEffect, useMemo, useState } from 'react';
import { useForm } from '@mantine/form';
import dayjs from 'dayjs';
import { notifications } from '@mantine/notifications';
import { Badge, Button, Card, Group, Modal, MultiSelect, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { DatePickerInput, TimeInput } from '@mantine/dates';
import { deleteRecordingById } from '../../utils/cards/RecordingCardUtils.js';
import {
  deleteRecurringRuleById,
  getChannelOptions,
  getUpcomingOccurrences,
  updateRecurringRule,
  updateRecurringRuleEnabled,
} from '../../utils/forms/RecurringRuleModalUtils.js';

const RecurringRuleModal = ({ opened, onClose, ruleId, onEditOccurrence }) => {
  const channels = useChannelsStore((s) => s.channels);
  const recurringRules = useChannelsStore((s) => s.recurringRules);
  const fetchRecurringRules = useChannelsStore((s) => s.fetchRecurringRules);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const recordings = useChannelsStore((s) => s.recordings);
  const { toUserTime, userNow } = useTimeHelpers();
  const [timeformat, dateformat] = useDateTimeFormat();

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [busyOccurrence, setBusyOccurrence] = useState(null);

  const rule = recurringRules.find((r) => r.id === ruleId);

  const channelOptions = useMemo(() => {
    return getChannelOptions(channels);
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
    return getUpcomingOccurrences(recordings, userNow, ruleId, toUserTime);
  }, [recordings, ruleId, toUserTime, userNow]);

  const handleSave = async (values) => {
    if (!rule) return;
    setSaving(true);
    try {
      await updateRecurringRule(ruleId, values);
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
      await deleteRecurringRuleById(ruleId);
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
      await updateRecurringRuleEnabled(ruleId, checked);
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
      await deleteRecordingById(occurrence.id);
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

  const handleEnableChange = (event) => {
    form.setFieldValue('enabled', event.currentTarget.checked);
    handleToggleEnabled(event.currentTarget.checked);
  }

  const handleStartDateChange = (value) => {
    form.setFieldValue('start_date', value || dayjs().toDate());
  }

  const handleEndDateChange = (value) => {
    form.setFieldValue('end_date', value);
  }

  const handleStartTimeChange = (value) => {
    form.setFieldValue('start_time', toTimeString(value));
  }

  const handleEndTimeChange = (value) => {
    form.setFieldValue('end_time', toTimeString(value));
  }

  const UpcomingList = () => {
    return <Stack gap="xs">
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
              <Stack gap={2} flex={1}>
                <Text fw={600} size="sm">
                  {occStart.format(`${dateformat}, YYYY`)}
                </Text>
                <Text size="xs" c="dimmed">
                  {occStart.format(timeformat)} – {occEnd.format(timeformat)}
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
    </Stack>;
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
            onChange={handleEnableChange}
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
                onChange={handleStartDateChange}
                valueFormat="MMM D, YYYY"
              />
              <DatePickerInput
                label="End date"
                value={form.values.end_date}
                onChange={handleEndDateChange}
                valueFormat="MMM D, YYYY"
                minDate={form.values.start_date || undefined}
              />
            </Group>
            <Group grow>
              <TimeInput
                label="Start time"
                value={form.values.start_time}
                onChange={handleStartTimeChange}
                withSeconds={false}
                format="12"
                amLabel="AM"
                pmLabel="PM"
              />
              <TimeInput
                label="End time"
                value={form.values.end_time}
                onChange={handleEndTimeChange}
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
          ) : <UpcomingList />}
        </Stack>
      </Stack>
    </Modal>
  );
};

export default RecurringRuleModal;