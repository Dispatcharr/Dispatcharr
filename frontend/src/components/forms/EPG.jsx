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

const EPG = ({ epg = null, isOpen, onClose }) => {
  const [sourceType, setSourceType] = useState('xmltv');

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      name: '',
      source_type: 'xmltv',
      url: '',
      api_key: '',
      is_active: true,
      refresh_interval: 24,
    },

    validate: {
      name: isNotEmpty('Please select a name'),
      source_type: isNotEmpty('Source type cannot be empty'),
    },
  });

  const onSubmit = async () => {
    const values = form.getValues();

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
      };
      form.setValues(values);
      setSourceType(epg.source_type);
    } else {
      form.reset();
      setSourceType('xmltv');
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

            <NumberInput
              label="Refresh Interval (hours)"
              description="How often to refresh EPG data (0 to disable)"
              {...form.getInputProps('refresh_interval')}
              key={form.key('refresh_interval')}
              min={0}
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

            <TextInput
              id="api_key"
              name="api_key"
              label="API Key"
              description="API key for services that require authentication"
              {...form.getInputProps('api_key')}
              key={form.key('api_key')}
              disabled={sourceType !== 'schedules_direct'}
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
  );
};

export default EPG;
