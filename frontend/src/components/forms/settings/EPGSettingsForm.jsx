import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import { Alert, Button, Flex, Stack, TagsInput, Text } from '@mantine/core';
import { useForm } from '@mantine/form';
import { getEPGSettingsFormInitialValues } from '../../../utils/forms/settings/EPGSettingsFormUtils.js';

const EPGSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);

  const [saved, setSaved] = useState(false);

  const form = useForm({
    mode: 'controlled',
    initialValues: getEPGSettingsFormInitialValues(),
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
        Configure how channel names are normalized during EPG matching.
        These settings help channels with different names match the same EPG data.
        Channel display names are never modified.
      </Text>

      <TagsInput
        {...form.getInputProps('epg_match_ignore_prefixes')}
        label="Ignore Prefixes"
        description="Removed from START of channel names during EPG matching only (e.g., Prime:, Sling:, US:)"
        placeholder="Type and press Enter"
        splitChars={[]}
        clearable
      />

      <TagsInput
        {...form.getInputProps('epg_match_ignore_suffixes')}
        label="Ignore Suffixes"
        description="Removed from END of channel names during EPG matching only (e.g., HD, 4K, +1)"
        placeholder="Type and press Enter"
        splitChars={[]}
        clearable
      />

      <TagsInput
        {...form.getInputProps('epg_match_ignore_custom')}
        label="Ignore Custom Strings"
        description="Removed from ANYWHERE in channel names during EPG matching only (e.g., 24/7, LIVE)"
        placeholder="Type and press Enter"
        splitChars={[]}
        clearable
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

export default EPGSettingsForm;
