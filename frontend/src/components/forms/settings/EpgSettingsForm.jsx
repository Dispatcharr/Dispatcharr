import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import { useForm } from '@mantine/form';
import { Alert, Button, Flex, NumberInput, Stack, Text } from '@mantine/core';
import { EPG_SETTINGS_OPTIONS } from '../../../constants.js';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import { getEpgSettingsFormInitialValues } from '../../../utils/forms/settings/EpgSettingsFormUtils.js';

const EpgSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const [saved, setSaved] = useState(false);

  const form = useForm({
    mode: 'controlled',
    initialValues: getEpgSettingsFormInitialValues(),
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings) {
      const parsed = parseSettings(settings);
      form.setFieldValue(
        'xmltv_prev_days_override',
        parsed.xmltv_prev_days_override ?? 0
      );
    }
  }, [settings]);

  const onSubmit = async () => {
    setSaved(false);
    const changedSettings = getChangedSettings(form.getValues(), settings);
    try {
      await saveChangedSettings(settings, changedSettings);
      setSaved(true);
    } catch (error) {
      console.error('Error saving EPG settings:', error);
    }
  };

  const prevDaysConfig = EPG_SETTINGS_OPTIONS.xmltv_prev_days_override;

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="md">
        {saved && (
          <Alert variant="light" color="green" title="Saved Successfully" />
        )}
        <NumberInput
          label={prevDaysConfig.label}
          description={prevDaysConfig.description}
          min={0}
          max={30}
          {...form.getInputProps('xmltv_prev_days_override')}
        />
        <Text size="xs" c="dimmed">
          Per-user defaults and URL parameters still override this global value.
          EPG channel matching options are configured from the Channels page.
        </Text>
        <Flex justify="flex-end">
          <Button type="submit">Save</Button>
        </Flex>
      </Stack>
    </form>
  );
});

export default EpgSettingsForm;
