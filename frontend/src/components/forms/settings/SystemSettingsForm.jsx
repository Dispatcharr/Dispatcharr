import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import {
  Alert,
  Button,
  Divider,
  Flex,
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
} from '@mantine/core';
import ConnectionSecurityPanel from './ConnectionSecurityPanel.jsx';
import { useForm } from '@mantine/form';
import { getSystemSettingsFormInitialValues } from '../../../utils/forms/settings/SystemSettingsFormUtils.js';
import { REGION_CHOICES } from '../../../constants.js';

const SystemSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const isModular =
    useSettingsStore((s) => s.environment.env_mode) === 'modular';

  const [saved, setSaved] = useState(false);

  const form = useForm({
    mode: 'controlled',
    initialValues: getSystemSettingsFormInitialValues(),
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings) {
      const formValues = parseSettings(settings);

      form.setValues(formValues);
    }
  }, [settings]);

  const onSubmit = async () => {
    setSaved(false);

    const changedSettings = getChangedSettings(form.getValues(), settings);

    // Update each changed setting in the backend (create if missing)
    try {
      await saveChangedSettings(settings, changedSettings);

      setSaved(true);
    } catch (error) {
      // Error notifications are already shown by API functions
      // Just don't show the success message
      console.error('Error saving settings:', error);
    }
  };

  return (
    <Stack gap="md">
      {saved && (
        <Alert variant="light" color="green" title="Saved Successfully" />
      )}
      <NumberInput
        label="Maximum System Events"
        description="Number of events to retain (minimum: 10, maximum: 1000). Events are displayed on the Stats page."
        value={form.values['max_system_events'] || 100}
        onChange={(value) => {
          form.setFieldValue('max_system_events', value);
        }}
        min={10}
        max={1000}
        step={10}
      />
      <Select
        searchable
        clearable
        {...form.getInputProps('preferred_region')}
        id="preferred_region"
        name="preferred_region"
        label="Preferred Region"
        description="Used when matching EPG data to channels. Prioritizes guide entries from the selected region."
        data={REGION_CHOICES.map((r) => ({
          label: r.label,
          value: `${r.value}`,
        }))}
      />
      <Group justify="space-between" pt={5}>
        <div>
          <Text size="sm" fw={500}>
            Auto-Import Mapped Files
          </Text>
          <Text size="xs" c="dimmed">
            Automatically import media files when they are mapped to a channel.
          </Text>
        </div>
        <Switch
          {...form.getInputProps('auto_import_mapped_files', {
            type: 'checkbox',
          })}
          id="auto_import_mapped_files"
        />
      </Group>
      {isModular && (
        <>
          <Divider my="md" label="Connection Security" labelPosition="left" />
          <ConnectionSecurityPanel />
        </>
      )}
      <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
        <Button
          onClick={form.onSubmit(onSubmit)}
          disabled={form.submitting}
          variant="default"
        >
          Save
        </Button>
      </Flex>
    </Stack>
  );
});

export default SystemSettingsForm;
