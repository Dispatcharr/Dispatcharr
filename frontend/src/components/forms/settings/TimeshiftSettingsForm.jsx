import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState, useMemo } from 'react';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import { Button, NumberInput, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { buildTimeZoneOptions } from '../../../utils/dateTimeUtils.js';
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

  const tzOptions = useMemo(
    () => buildTimeZoneOptions(form.getValues().timeshift_default_timezone || 'UTC'),
    []
  );

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings) {
      const parsed = parseSettings(settings);
      // Fall back explicitly to the neutral defaults so the Select shows
      // "UTC (now UTC+00:00)" when no setting has been saved yet.
      form.setValues({
        timeshift_default_timezone: parsed.timeshift_default_timezone || 'UTC',
        timeshift_default_language: parsed.timeshift_default_language || 'en',
        xmltv_prev_days_override: parsed.xmltv_prev_days_override ?? 0,
        timeshift_debug_logging: !!parsed.timeshift_debug_logging,
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
          XC catch-up uses these settings to convert UTC EPG timestamps into the
          provider&apos;s local time and to set the XMLTV lookback window. The
          defaults are neutral (UTC, en, off) — adjust to match your provider.
        </Text>
        <Select
          label="Default timezone"
          description="IANA timezone used for XC EPG strings (start/end) and provider timeshift URLs."
          data={tzOptions}
          searchable
          allowDeselect={false}
          {...form.getInputProps('timeshift_default_timezone')}
        />
        <TextInput
          label="Default language"
          description="ISO 639-1 language code (2 letters) emitted in EPG entries."
          maxLength={2}
          {...form.getInputProps('timeshift_default_language')}
        />
        <NumberInput
          label="XMLTV prev_days override"
          description="0 = auto-detect from provider tv_archive_duration (capped at 30). Greater than 0 forces that many days of past programmes."
          min={0}
          max={30}
          step={1}
          {...form.getInputProps('xmltv_prev_days_override')}
        />
        <Switch
          label="Verbose timeshift logging"
          description="Log catch-up request details (channel, timestamp, URL) for debugging."
          {...form.getInputProps('timeshift_debug_logging', { type: 'checkbox' })}
        />
        <Button type="submit" variant="filled" mt="sm">
          {saved ? 'Saved' : 'Save'}
        </Button>
      </Stack>
    </form>
  );
});

export default TimeshiftSettingsForm;
