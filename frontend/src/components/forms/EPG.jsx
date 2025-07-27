// Modal.js
import React, { useState, useEffect } from 'react';
import API from '../../api';
import useEPGsStore from '../../store/epgs';
import {
  LoadingOverlay,
  TextInput,
  Button,
  Checkbox,
  Modal,
  Flex,
  NativeSelect,
  NumberInput,
  Space,
  Grid,
  Group,
  FileInput,
  Title,
  Text,
  Divider,
  Stack,
  Box,
} from '@mantine/core';
import { isNotEmpty, useForm } from '@mantine/form';

const EPG = ({ epg = null, isOpen, onClose }) => {
  const epgs = useEPGsStore((state) => state.epgs);
  // Remove the file state and handler since we're not supporting file uploads
  const [sourceType, setSourceType] = useState('xmltv');

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      name: '',
      source_type: 'xmltv',
      url: '',
      api_key: '',
      username: '',
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
      // Remove file from API call
      await API.updateEPG({ id: epg.id, ...values });
    } else {
      // Remove file from API call
      await API.addEPG({
        ...values,
      });
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
        username: epg.username,
        is_active: epg.is_active,
        refresh_interval: epg.refresh_interval,
      };
      form.setValues(values);
      setSourceType(epg.source_type); // Update source type state
    } else {
      form.reset();
      setSourceType('xmltv'); // Reset to xmltv
    }
  }, [epg]);

  // Function to handle source type changes
  const handleSourceTypeChange = (value) => {
    console.log('handleSourceTypeChange called with:', value);
    form.setFieldValue('source_type', value);
    setSourceType(value);
    console.log('sourceType state updated to:', value);
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
              value={sourceType}
              error={form.getInputProps('source_type').error}
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
              disabled={sourceType === 'schedules_direct'}
            />

            {/* Debug info */}
            <Text size="xs" c="dimmed">Debug: sourceType = "{sourceType}"</Text>
            
            {sourceType === 'schedules_direct' && (
              <>
                <TextInput
                  id="username"
                  name="username"
                  label="Username"
                  description="Schedules Direct username"
                  {...form.getInputProps('username')}
                  key={form.key('username')}
                />

                <TextInput
                  id="api_key"
                  name="api_key"
                  label="Password"
                  description="Schedules Direct password"
                  type="password"
                  {...form.getInputProps('api_key')}
                  key={form.key('api_key')}
                />
              </>
            )}

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
                  height: '30px', // Reduced height
                  marginTop: '-4px', // Slight negative margin to move it up
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
