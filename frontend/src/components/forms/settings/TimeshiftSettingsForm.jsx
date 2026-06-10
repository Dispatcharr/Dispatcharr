import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import { Button, NumberInput, Stack, Text } from '@mantine/core';
import { useForm } from '@mantine/form';
import {
  getTimeshiftSettingsFormInitialValues,
  getTimeshiftSettingsFormValidation,
} from '../../../utils/forms/settings/TimeshiftSettingsFormUtils.js';

const TimeshiftSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const [saved, setSaved] = useState(false);

  const form = useForm({
    mode: 'controlled',
    initialValues: getTimeshiftSettingsFormInitialValues(),
    validate: getTimeshiftSettingsFormValidation(),
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings) {
      const parsed = parseSettings(settings);
      form.setValues({
        xmltv_prev_days_override: parsed.xmltv_prev_days_override ?? 0,
      });
    }
  }, [settings]);

  const onSubmit = async () => {
    setSaved(false);
    const changed = getChangedSettings(form.getValues(), settings);
    try {
      await saveChangedSettings(settings, changed);
      setSaved(true);
    } catch (error) {
      console.error('Error saving timeshift settings:', error);
    }
  };

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack>
        <Text size="sm" c="dimmed">
          XC catch-up serves EPG and archive timestamps in UTC. Each provider&apos;s
          own timezone is applied automatically at request time, so there is no
          timezone to configure here. The only setting is the XMLTV lookback
          window.
        </Text>
        <NumberInput
          label="XMLTV prev_days override"
          description="0 = auto-detect from provider tv_archive_duration (capped at 30). Greater than 0 forces that many days of past programmes."
          min={0}
          max={30}
          step={1}
          {...form.getInputProps('xmltv_prev_days_override')}
        />
        <Button type="submit" variant="filled" mt="sm">
          {saved ? 'Saved' : 'Save'}
        </Button>
      </Stack>
    </form>
  );
});

export default TimeshiftSettingsForm;
