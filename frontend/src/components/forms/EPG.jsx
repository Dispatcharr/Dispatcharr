// Modal.js
import React, { useState, useEffect } from 'react';
import API from '../../api';
import {
  TextInput,
  Button,
  Checkbox,
  Modal,
  NativeSelect,
  NumberInput,
  Stack,
  Group,
  Divider,
  Box,
  Text,
} from '@mantine/core';
import { isNotEmpty, useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import ScheduleInput from './ScheduleInput';

const EPG = ({ epg = null, isOpen, onClose }) => {
  const [sourceType, setSourceType] = useState('xmltv');
  const [scheduleType, setScheduleType] = useState('interval');

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      name: '',
      source_type: 'xmltv',
      url: '',
      api_key: '',
      is_active: true,
      refresh_interval: 24,
      cron_expression: '',
      priority: 0,
    },

    validate: {
      name: isNotEmpty('Please select a name'),
      source_type: isNotEmpty('Source type cannot be empty'),
    },
  });

  const onSubmit = async () => {
    const values = form.getValues();

    // Determine which schedule type is active based on field values
    const hasCronExpression =
      values.cron_expression && values.cron_expression.trim() !== '';

    // Clear the field that isn't active based on actual field values
    if (hasCronExpression) {
      values.refresh_interval = 0;
    } else {
      values.cron_expression = '';
    }

    if (epg?.id) {
      // Validate that we have a valid EPG object before updating
      if (!epg || typeof epg !== 'object' || !epg.id) {
        notifications.show({
          title: 'Error',
          message: 'Invalid EPG data. Please close and reopen this form.',
          color: 'red',
        });
        return;
      }

      await API.updateEPG({ id: epg.id, ...values });
    } else {
      await API.addEPG(values);
    }

    form.reset();
    onClose();
  };

  useEffect(() => {
    if (epg) {
      const values = {
        name: epg.name,
        source_type: epg.source_type,
        url: epg.url,
        api_key: epg.api_key,
        is_active: epg.is_active,
        refresh_interval: epg.refresh_interval,
        cron_expression: epg.cron_expression || '',
        priority: epg.priority ?? 0,
      };
      form.setValues(values);
      setSourceType(epg.source_type);
      // Determine schedule type from existing data - check both fields
      setScheduleType(
        epg.cron_expression && epg.cron_expression.trim() !== ''
          ? 'cron'
          : 'interval'
      );
    } else {
      form.reset();
      setSourceType('xmltv');
      setScheduleType('interval');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epg]);

  // Function to handle source type changes
  const handleSourceTypeChange = (value) => {
    form.setFieldValue('source_type', value);
    setSourceType(value);
  };

  if (!isOpen) {
    return <></>;
  }

  return (
    <>
      <Modal opened={isOpen} onClose={onClose} title="EPG Source" size={700}>
        <form onSubmit={form.onSubmit(onSubmit)}>
          <Group justify="space-between" align="top">
            {/* Left Column */}
            <Stack gap="md" style={{ flex: 1 }}>
              <TextInput
                id="name"
                name="name"
                label="Name"
                description="Unique identifier for this EPG source"
                {...form.getInputProps('name')}
                key={form.key('name')}
              />

              <NativeSelect
                id="source_type"
                name="source_type"
                label="Source Type"
                description="Format of the EPG data source"
                {...form.getInputProps('source_type')}
                key={form.key('source_type')}
                data={[
                  {
                    label: 'XMLTV',
                    value: 'xmltv',
                  },
                  {
                    label: 'Schedules Direct',
                    value: 'schedules_direct',
                  },
                ]}
                onChange={(event) =>
                  handleSourceTypeChange(event.currentTarget.value)
                }
              />

              <ScheduleInput
                scheduleType={scheduleType}
                onScheduleTypeChange={setScheduleType}
                intervalValue={form.getValues().refresh_interval}
                onIntervalChange={(v) =>
                  form.setFieldValue('refresh_interval', v)
                }
                cronValue={form.getValues().cron_expression}
                onCronChange={(expr) =>
                  form.setFieldValue('cron_expression', expr)
                }
                intervalLabel="Refresh Interval (hours)"
                intervalDescription="How often to refresh EPG data (0 to disable)"
              />
            </Stack>

            <Divider size="sm" orientation="vertical" />

            {/* Right Column */}
            <Stack gap="md" style={{ flex: 1 }}>
              <TextInput
                id="url"
                name="url"
                label="URL"
                description="Direct URL to the XMLTV file or API endpoint"
                {...form.getInputProps('url')}
                key={form.key('url')}
              />

              {sourceType === 'schedules_direct' && (
                <TextInput
                  id="api_key"
                  name="api_key"
                  label="API Key"
                  description="API key for services that require authentication"
                  {...form.getInputProps('api_key')}
                  key={form.key('api_key')}
                />
              )}

              <NumberInput
                min={0}
                max={999}
                label="Priority"
                description="Priority for EPG matching (higher numbers = higher priority). Used when multiple EPG sources have matching entries for a channel."
                {...form.getInputProps('priority')}
                key={form.key('priority')}
              />

              {/* Put checkbox at the same level as Refresh Interval */}
              <Box style={{ marginTop: 0 }}>
                <Text size="sm" fw={500} mb={3}>
                  Status
                </Text>
                <Text size="xs" c="dimmed" mb={12}>
                  When enabled, this EPG source will auto update.
                </Text>
                <Box
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    height: '30px',
                    marginTop: '-4px',
                  }}
                >
                  <Checkbox
                    id="is_active"
                    name="is_active"
                    label="Enable this EPG source"
                    {...form.getInputProps('is_active', { type: 'checkbox' })}
                    key={form.key('is_active')}
                  />
                </Box>
              </Box>
            </Stack>
          </Group>

          {/* Full Width Section */}
          <Box mt="md">
            <Divider my="sm" />

            <Group justify="end" mt="xl">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" variant="filled" disabled={form.submitting}>
                {epg?.id ? 'Update' : 'Create'} EPG Source
              </Button>
            </Group>
          </Box>
        </form>
      </Modal>
    </>
  );
};

export default EPG;
