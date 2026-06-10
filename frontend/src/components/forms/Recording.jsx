import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  MultiSelect,
  SegmentedControl,
  Select,
  Stack,
  TextInput,
} from '@mantine/core';
import { DatePickerInput, DateTimePicker, TimeInput } from '@mantine/dates';
import { CircleAlert } from 'lucide-react';
import { useForm } from '@mantine/form';
import useChannelsStore from '../../store/channels';
import {
  RECURRING_DAY_OPTIONS,
  toTimeString,
} from '../../utils/dateTimeUtils.js';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  buildRecurringPayload,
  buildSinglePayload,
  createRecording,
  createRecurringRule,
  getChannelsSummary,
  getRecurringFormDefaults,
  getSingleFormDefaults,
  numberedChannelLabel,
  recurringFormValidators,
  singleFormValidators,
  sortedChannelOptions,
  timeChange,
  updateRecording,
} from '../../utils/forms/RecordingUtils.js';

const RecordingModal = ({
  recording = null,
  channel = null,
  isOpen,
  onClose,
}) => {
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const fetchRecurringRules = useChannelsStore((s) => s.fetchRecurringRules);

  // All channels loaded via lightweight summary API
  const [allChannels, setAllChannels] = useState([]);
  const [isChannelsLoading, setIsChannelsLoading] = useState(false);

  const [mode, setMode] = useState('single');
  const [submitting, setSubmitting] = useState(false);

  const singleForm = useForm({
    mode: 'controlled',
    initialValues: getSingleFormDefaults(recording, channel),
    validate: singleFormValidators,
  });

  const recurringForm = useForm({
    mode: 'controlled',
    validateInputOnChange: false,
    validateInputOnBlur: true,
    initialValues: getRecurringFormDefaults(channel),
    validate: recurringFormValidators,
  });

  useEffect(() => {
    if (!isOpen) return;

    if (recording?.id) {
      setMode('single');
      singleForm.setValues(getSingleFormDefaults(recording, channel));
    } else {
      singleForm.setValues(getSingleFormDefaults(null, channel));
      recurringForm.setValues(getRecurringFormDefaults(channel));
      setMode('single');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, recording, channel]);

  // Load all channels via lightweight summary API when modal opens
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!isOpen) return;
      try {
        setIsChannelsLoading(true);
        const chans = await getChannelsSummary();
        if (cancelled) return;
        setAllChannels(Array.isArray(chans) ? chans : []);
      } catch (e) {
        console.warn('Failed to load channels for recording form', e);
        if (!cancelled) setAllChannels([]);
      } finally {
        if (!cancelled) setIsChannelsLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const channelOptions = useMemo(() => {
    return sortedChannelOptions(allChannels, numberedChannelLabel);
  }, [allChannels]);

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
      const payload = buildSinglePayload(values);
      if (recording && recording.id) {
        await updateRecording(recording.id, payload);
        showNotification({
          title: 'Recording updated',
          message: 'Recording schedule updated successfully',
          color: 'green',
          autoClose: 2500,
        });
      } else {
        await createRecording(payload);
        showNotification({
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
      await createRecurringRule(buildRecurringPayload(values));

      await Promise.all([fetchRecurringRules(), fetchRecordings()]);
      showNotification({
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
        Recordings may fail if active streams or overlapping recordings use up
        all available tuners.
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
                disabled={isChannelsLoading}
                rightSection={
                  isChannelsLoading ? <Loader size="xs" color="blue" /> : null
                }
              />
            ) : (
              <Select
                {...recurringForm.getInputProps('channel_id')}
                key={recurringForm.key('channel_id')}
                label="Channel"
                placeholder="Select channel"
                searchable
                data={channelOptions}
                rightSection={isChannelsLoading ? 'Loading…' : null}
              />
            )}

            {mode === 'single' ? (
              <>
                <DateTimePicker
                  {...singleForm.getInputProps('start_time')}
                  key={singleForm.key('start_time')}
                  label="Start"
                  valueFormat="MMM D, YYYY h:mm A"
                  timeInputProps={{
                    format: '12',
                    withSeconds: false,
                    amLabel: 'AM',
                    pmLabel: 'PM',
                  }}
                />
                <DateTimePicker
                  {...singleForm.getInputProps('end_time')}
                  key={singleForm.key('end_time')}
                  label="End"
                  valueFormat="MMM D, YYYY h:mm A"
                  timeInputProps={{
                    format: '12',
                    withSeconds: false,
                    amLabel: 'AM',
                    pmLabel: 'PM',
                  }}
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
                  data={RECURRING_DAY_OPTIONS.map((opt) => ({
                    value: String(opt.value),
                    label: opt.label,
                  }))}
                  searchable
                  clearable
                  nothingFoundMessage="No match"
                />

                <Group grow>
                  <DatePickerInput
                    label="Start date"
                    value={recurringForm.values.start_date}
                    onChange={(value) =>
                      recurringForm.setFieldValue(
                        'start_date',
                        value || new Date()
                      )
                    }
                    valueFormat="MMM D, YYYY"
                  />
                  <DatePickerInput
                    label="End date"
                    value={recurringForm.values.end_date}
                    onChange={(value) =>
                      recurringForm.setFieldValue('end_date', value)
                    }
                    valueFormat="MMM D, YYYY"
                    minDate={recurringForm.values.start_date || undefined}
                  />
                </Group>

                <Group grow>
                  <TimeInput
                    label="Start time"
                    value={recurringForm.values.start_time}
                    onChange={timeChange((val) =>
                      recurringForm.setFieldValue(
                        'start_time',
                        toTimeString(val)
                      )
                    )}
                    onBlur={() => recurringForm.validateField('start_time')}
                    withSeconds={false}
                    format="12" // shows 12-hour (so "00:00" renders "12:00 AM")
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
