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
  NumberInput,
  Select,
  Stack,
  Switch,
} from '@mantine/core';
import ConnectionSecurityPanel from './ConnectionSecurityPanel.jsx';
import ConfirmationDialog from '../../ConfirmationDialog.jsx';
import { PluginRestartWarning } from '../../PluginWarnings.jsx';
import { useForm } from '@mantine/form';
import { getSystemSettingsFormInitialValues } from '../../../utils/forms/settings/SystemSettingsFormUtils.js';
import { REGION_CHOICES } from '../../../constants.js';

const CELERY_SCALE_FIELDS = ['celery_max_workers'];

const SystemSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const isModular =
    useSettingsStore((s) => s.environment.env_mode) === 'modular';
  const ipLookupEnvDisabled = useSettingsStore(
    (s) => s.environment.ip_lookup_env_disabled
  );

  const [saved, setSaved] = useState(false);
  const [pendingChanges, setPendingChanges] = useState(null);
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);

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

  const applyChanges = async (changedSettings) => {
    setSaved(false);
    try {
      await saveChangedSettings(settings, changedSettings);
      setSaved(true);
    } catch (error) {
      // Error notifications are already shown by API functions
      // Just don't show the success message
      console.error('Error saving settings:', error);
    }
  };

  const onSubmit = async () => {
    const changedSettings = getChangedSettings(form.getValues(), settings);

    if (CELERY_SCALE_FIELDS.some((field) => field in changedSettings)) {
      setPendingChanges(changedSettings);
      setRestartConfirmOpen(true);
      return;
    }

    await applyChanges(changedSettings);
  };

  const onConfirmRestart = async () => {
    setRestartConfirmOpen(false);
    if (pendingChanges) {
      await applyChanges(pendingChanges);
      setPendingChanges(null);
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
      <Switch
        label="Auto-Import Mapped Files"
        description="Automatically import media files when they are mapped to a channel."
        {...form.getInputProps('auto_import_mapped_files', {
          type: 'checkbox',
        })}
        id="auto_import_mapped_files"
      />
      {!ipLookupEnvDisabled && (
        <Switch
          label="Enable IP Lookup"
          description="Fetch and display the instance's public IP and country flag in the sidebar."
          {...form.getInputProps('enable_ip_lookup', { type: 'checkbox' })}
          id="enable_ip_lookup"
        />
      )}
      <Switch
        label="Enable Catchup"
        description="When disabled, timeshift and catchup endpoints are blocked for all users, and channels are not advertised as supporting catchup to clients. Catchup capability is still shown in the web UI."
        {...form.getInputProps('catchup_enabled', { type: 'checkbox' })}
        id="catchup_enabled"
      />
      <Divider my="md" label="Background Task Workers" labelPosition="left" />
      <NumberInput
        label="Worker Max Concurrency"
        description="Autoscale ceiling for the background task worker (handles core tasks and plugin tasks alike). Requires a restart to take effect."
        value={form.values['celery_max_workers'] || 8}
        onChange={(value) => {
          form.setFieldValue('celery_max_workers', value);
        }}
        min={1}
        max={64}
        step={1}
      />
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
      <ConfirmationDialog
        opened={restartConfirmOpen}
        onClose={() => {
          setRestartConfirmOpen(false);
          setPendingChanges(null);
        }}
        onConfirm={onConfirmRestart}
        title="Restart Required"
        message={
          <PluginRestartWarning>
            Worker concurrency changes only take effect after restarting the
            container. Save anyway?
          </PluginRestartWarning>
        }
        confirmLabel="Save"
        confirmColor="blue"
      />
    </Stack>
  );
});

export default SystemSettingsForm;
