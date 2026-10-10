import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import {
  getChangedGroupSettings,
  parseGroupSettings,
  saveGroupSettings,
} from '../../../utils/pages/SettingsUtils.js';
import useSettingsSaveGuard from '../../../hooks/useSettingsSaveGuard.jsx';
import { Alert, Button, Flex, NumberInput, Stack } from '@mantine/core';
import { useForm } from '@mantine/form';

const EPG_GROUP = 'epg_settings';
const ABSOLUTE_MAX_DAYS = 365;

// epg_settings is shared with the EPG match dialog. Load and save only the
// fields this form owns so it never rewrites the match settings.
const OWN_FIELDS = [
  'epg_history_min_days',
  'epg_history_max_days',
  'epg_default_prev_days',
  'epg_default_days',
];

const toFormValues = (settings) => {
  const parsed = parseGroupSettings(settings, EPG_GROUP);
  return Object.fromEntries(OWN_FIELDS.map((field) => [field, parsed[field]]));
};

// An emptied field would be saved as null and silently fall back to the default.
const requireDays = (value) =>
  value === '' || value == null || !Number.isInteger(Number(value))
    ? 'Enter a whole number of days'
    : null;

const EpgSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const [saved, setSaved] = useState(false);
  const { isSavingRef, runSave } = useSettingsSaveGuard();

  const form = useForm({
    mode: 'controlled',
    initialValues: {
      epg_history_min_days: 1,
      epg_history_max_days: 30,
      epg_default_prev_days: 0,
      epg_default_days: 0,
    },
    validate: {
      epg_history_min_days: (value, values) =>
        requireDays(value) ??
        (Number(value) > Number(values.epg_history_max_days)
          ? 'Minimum cannot be greater than the maximum'
          : null),
      epg_history_max_days: requireDays,
      epg_default_prev_days: (value, values) =>
        requireDays(value) ??
        (Number(value) > Number(values.epg_history_max_days)
          ? 'Cannot be greater than the maximum guide history'
          : null),
      epg_default_days: requireDays,
    },
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings && !isSavingRef.current) {
      form.setValues(toFormValues(settings));
    }
    // form / isSavingRef are stable; re-running on every form identity would
    // wipe in-progress edits whenever Mantine recreates the form object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  const onSubmit = async () => {
    setSaved(false);
    const changedSettings = getChangedGroupSettings(
      form.getValues(),
      settings,
      EPG_GROUP
    );

    try {
      await runSave(async () => {
        await saveGroupSettings(settings, EPG_GROUP, changedSettings);
        const latestSettings = useSettingsStore.getState().settings;
        if (latestSettings) {
          form.setValues(toFormValues(latestSettings));
        }
        setSaved(true);
      });
    } catch (error) {
      console.error('Error saving EPG settings:', error);
    }
  };

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="sm">
        {saved && (
          <Alert variant="light" color="green" title="Saved Successfully" />
        )}
        <NumberInput
          label="Minimum guide history (days)"
          description="Every channel keeps at least this many days of programmes that have already ended. 0 keeps none, unless that channel's catch-up days are higher."
          min={0}
          max={ABSOLUTE_MAX_DAYS}
          allowDecimal={false}
          {...form.getInputProps('epg_history_min_days')}
        />
        <NumberInput
          label="Maximum guide history (days)"
          description="Hard cap on how many days of ended programmes are kept, and how far back an EPG client can request."
          min={0}
          max={ABSOLUTE_MAX_DAYS}
          allowDecimal={false}
          {...form.getInputProps('epg_history_max_days')}
        />
        <NumberInput
          label="Default days back"
          description="Past days included when a client does not ask and the user has not set Days back. 0 means no past programmes. Cannot exceed the maximum."
          min={0}
          max={Number(form.values.epg_history_max_days) || 0}
          allowDecimal={false}
          {...form.getInputProps('epg_default_prev_days')}
        />
        <NumberInput
          label="Default days forward"
          description="Future days included when a client does not ask and the user has not set Days forward. 0 means all stored future programmes."
          min={0}
          max={ABSOLUTE_MAX_DAYS}
          allowDecimal={false}
          {...form.getInputProps('epg_default_days')}
        />
        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            type="submit"
            disabled={form.submitting}
            variant="default"
          >
            Save
          </Button>
        </Flex>
      </Stack>
    </form>
  );
});

EpgSettingsForm.displayName = 'EpgSettingsForm';

export default EpgSettingsForm;
