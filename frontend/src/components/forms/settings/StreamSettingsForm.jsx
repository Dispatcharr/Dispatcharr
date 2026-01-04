import useSettingsStore from '../../../store/settings.jsx';
import useWarningsStore from '../../../store/warnings.jsx';
import useUserAgentsStore from '../../../store/userAgents.jsx';
import useStreamProfilesStore from '../../../store/streamProfiles.jsx';
import { REGION_CHOICES } from '../../../constants.js';
import React, { useEffect, useState } from 'react';
import {
  getChangedSettings,
  parseSettings,
  rehashStreams,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import {
  Alert,
  Button,
  Flex,
  Group,
  MultiSelect,
  Select,
  Switch,
  Text,
} from '@mantine/core';
import ConfirmationDialog from '../../ConfirmationDialog.jsx';
import { useForm } from '@mantine/form';
import {
  getStreamSettingsFormInitialValues,
  getStreamSettingsFormValidation,
} from '../../../utils/forms/settings/StreamSettingsFormUtils.js';

const StreamSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const userAgents = useUserAgentsStore((s) => s.userAgents);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);
  const regionChoices = REGION_CHOICES;

  // Store pending changed settings when showing the dialog
  const [pendingChangedSettings, setPendingChangedSettings] = useState(null);

  const [saved, setSaved] = useState(false);
  const [rehashingStreams, setRehashingStreams] = useState(false);
  const [rehashSuccess, setRehashSuccess] = useState(false);
  const [rehashConfirmOpen, setRehashConfirmOpen] = useState(false);

  // Add a new state to track the dialog type
  const [rehashDialogType, setRehashDialogType] = useState(null); // 'save' or 'rehash'

  const form = useForm({
    mode: 'controlled',
    initialValues: getStreamSettingsFormInitialValues(),
    validate: getStreamSettingsFormValidation(),
  });

  useEffect(() => {
    if (!active) {
      setSaved(false);
      setRehashSuccess(false);
    }
  }, [active]);

  useEffect(() => {
    if (settings) {
      const formValues = parseSettings(settings);

      form.setValues(formValues);
    }
  }, [settings]);

  const executeSettingsSaveAndRehash = async () => {
    setRehashConfirmOpen(false);
    setSaved(false);

    // Use the stored pending values that were captured before the dialog was shown
    const changedSettings = pendingChangedSettings || {};

    // Update each changed setting in the backend (create if missing)
    try {
      await saveChangedSettings(settings, changedSettings);

      // Clear the pending values
      setPendingChangedSettings(null);
      setSaved(true);
    } catch (error) {
      // Error notifications are already shown by API functions
      // Just don't show the success message
      console.error('Error saving settings:', error);
      setPendingChangedSettings(null);
    }
  };

  const executeRehashStreamsOnly = async () => {
    setRehashingStreams(true);
    setRehashSuccess(false);
    setRehashConfirmOpen(false);

    try {
      await rehashStreams();
      setRehashSuccess(true);
      setTimeout(() => setRehashSuccess(false), 5000);
    } catch (error) {
      console.error('Error rehashing streams:', error);
    } finally {
      setRehashingStreams(false);
    }
  };

  const onRehashStreams = async () => {
    // Skip warning if it's been suppressed
    if (isWarningSuppressed('rehash-streams')) {
      return executeRehashStreamsOnly();
    }

    setRehashDialogType('rehash'); // Set dialog type to rehash
    setRehashConfirmOpen(true);
  };

  const handleRehashConfirm = () => {
    if (rehashDialogType === 'save') {
      executeSettingsSaveAndRehash();
    } else {
      executeRehashStreamsOnly();
    }
  };

  const onSubmit = async () => {
    setSaved(false);

    const values = form.getValues();
    const changedSettings = getChangedSettings(values, settings);

    const m3uHashKeyChanged =
      settings['m3u-hash-key']?.value !== values['m3u-hash-key'].join(',');

    // If M3U hash key changed, show warning (unless suppressed)
    if (m3uHashKeyChanged && !isWarningSuppressed('rehash-streams')) {
      // Store the changed settings before showing dialog
      setPendingChangedSettings(changedSettings);
      setRehashDialogType('save'); // Set dialog type to save
      setRehashConfirmOpen(true);
      return;
    }

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
    <>
      <form onSubmit={form.onSubmit(onSubmit)}>
        {saved && (
          <Alert variant="light" color="green" title="Saved Successfully" />
        )}
        <Select
          searchable
          {...form.getInputProps('default-user-agent')}
          id={settings['default-user-agent']?.id || 'default-user-agent'}
          name={settings['default-user-agent']?.key || 'default-user-agent'}
          label={settings['default-user-agent']?.name || 'Default User Agent'}
          data={userAgents.map((option) => ({
            value: `${option.id}`,
            label: option.name,
          }))}
        />
        <Select
          searchable
          {...form.getInputProps('default-stream-profile')}
          id={
            settings['default-stream-profile']?.id || 'default-stream-profile'
          }
          name={
            settings['default-stream-profile']?.key || 'default-stream-profile'
          }
          label={
            settings['default-stream-profile']?.name || 'Default Stream Profile'
          }
          data={streamProfiles.map((option) => ({
            value: `${option.id}`,
            label: option.name,
          }))}
        />
        <Select
          searchable
          {...form.getInputProps('preferred-region')}
          id={settings['preferred-region']?.id || 'preferred-region'}
          name={settings['preferred-region']?.key || 'preferred-region'}
          label={settings['preferred-region']?.name || 'Preferred Region'}
          data={regionChoices.map((r) => ({
            label: r.label,
            value: `${r.value}`,
          }))}
        />

        <Group justify="space-between" pt={5}>
          <Text size="sm" fw={500}>
            Auto-Import Mapped Files
          </Text>
          <Switch
            {...form.getInputProps('auto-import-mapped-files', {
              type: 'checkbox',
            })}
            id={
              settings['auto-import-mapped-files']?.id ||
              'auto-import-mapped-files'
            }
          />
        </Group>

        <MultiSelect
          id="m3u-hash-key"
          name="m3u-hash-key"
          label="M3U Hash Key"
          data={[
            {
              value: 'name',
              label: 'Name',
            },
            {
              value: 'url',
              label: 'URL',
            },
            {
              value: 'tvg_id',
              label: 'TVG-ID',
            },
            {
              value: 'm3u_id',
              label: 'M3U ID',
            },
            {
              value: 'group',
              label: 'Group',
            },
          ]}
          {...form.getInputProps('m3u-hash-key')}
        />

        {rehashSuccess && (
          <Alert
            variant="light"
            color="green"
            title="Rehash task queued successfully"
          />
        )}

        <Flex mih={50} gap="xs" justify="space-between" align="flex-end">
          <Button
            onClick={onRehashStreams}
            loading={rehashingStreams}
            variant="outline"
            color="blue"
          >
            Rehash Streams
          </Button>
          <Button type="submit" disabled={form.submitting} variant="default">
            Save
          </Button>
        </Flex>
      </form>

      <ConfirmationDialog
        opened={rehashConfirmOpen}
        onClose={() => {
          setRehashConfirmOpen(false);
          setRehashDialogType(null);
          // Clear pending values when dialog is cancelled
          setPendingChangedSettings(null);
        }}
        onConfirm={handleRehashConfirm}
        title={
          rehashDialogType === 'save'
            ? 'Save Settings and Rehash Streams'
            : 'Confirm Stream Rehash'
        }
        message={
          <div style={{ whiteSpace: 'pre-line' }}>
            {`Are you sure you want to rehash all streams?

This process may take a while depending on the number of streams.
Do not shut down Dispatcharr until the rehashing is complete.
M3U refreshes will be blocked until this process finishes.

Please ensure you have time to let this complete before proceeding.`}
          </div>
        }
        confirmLabel={
          rehashDialogType === 'save' ? 'Save and Rehash' : 'Start Rehash'
        }
        cancelLabel="Cancel"
        actionKey="rehash-streams"
        onSuppressChange={suppressWarning}
        size="md"
      />
    </>
  );
});

export default StreamSettingsForm;