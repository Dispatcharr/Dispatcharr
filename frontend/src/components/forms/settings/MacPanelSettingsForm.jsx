import React, { useEffect, useState } from 'react';
import { useForm } from '@mantine/form';
import { Alert, Button, Flex, Stack, Text, TextInput } from '@mantine/core';
import {
  createSetting,
  updateSetting,
} from '../../../utils/pages/SettingsUtils.js';
import useSettingsStore from '../../../store/settings.jsx';
import {
  getMacPanelSettingsFormInitialValues,
  getMacPanelSettingsFormValidation,
} from '../../../utils/forms/settings/MacPanelSettingsFormUtils.js';

const MAC_PANEL_SETTINGS_KEY = 'mac_panel_settings';

const MacPanelSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);

  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const form = useForm({
    mode: 'controlled',
    initialValues: getMacPanelSettingsFormInitialValues(),
    validate: getMacPanelSettingsFormValidation(),
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    const value = settings[MAC_PANEL_SETTINGS_KEY]?.value;
    if (value) {
      form.setValues({ public_url: value.public_url || '' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  const onSubmit = async (values) => {
    setSaved(false);
    setSaving(true);
    try {
      const existing = settings[MAC_PANEL_SETTINGS_KEY];
      // public_url is stored trimmed of a trailing slash server-side too,
      // but strip it here as well so the field reflects what's actually
      // saved rather than surprising the admin after a page refresh.
      const value = {
        public_url: (values.public_url || '').replace(/\/+$/, ''),
      };

      const result = existing?.id
        ? await updateSetting({ ...existing, value })
        : await createSetting({
            key: MAC_PANEL_SETTINGS_KEY,
            name: 'MAC Panel Settings',
            value,
          });

      if (result) {
        setSaved(true);
        form.setValues(value);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="sm">
        {saved && (
          <Alert variant="light" color="green" title="Saved Successfully" />
        )}

        <TextInput
          label="Public URL"
          description="The URL customer devices can actually reach — used as the playlist host when pushing XC credentials to a MAC panel (e.g. https://teve.example.com). Leave blank to fall back to the admin browser's own request origin, which is almost never what a customer's device can reach — a warning is shown on every push until this is set."
          placeholder="https://your-public-domain.example.com"
          {...form.getInputProps('public_url')}
        />

        <Text size="xs" c="dimmed">
          Enter the same public URL customers use to reach this Dispatcharr
          instance's XC API — no trailing slash needed, it's stripped
          automatically.
        </Text>

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button type="submit" disabled={saving} variant="default">
            Save
          </Button>
        </Flex>
      </Stack>
    </form>
  );
});

export default MacPanelSettingsForm;
