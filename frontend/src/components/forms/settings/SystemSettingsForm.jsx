import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import { Alert, Button, Flex, NumberInput, Stack, Text } from '@mantine/core';
import { useForm } from '@mantine/form';
import { getSystemSettingsFormInitialValues } from '../../../utils/forms/settings/SystemSettingsFormUtils.js';

const SystemSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);

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
      <Text size="sm" c="dimmed">
        Configure how many system events (channel start/stop, buffering, etc.)
        to keep in the database. Events are displayed on the Stats page.
      </Text>
      <NumberInput
        label="Maximum System Events"
        description="Number of events to retain (minimum: 10, maximum: 1000)"
        value={form.values['max-system-events'] || 100}
        onChange={(value) => {
          form.setFieldValue('max-system-events', value);
        }}
        min={10}
        max={1000}
        step={10}
      />
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