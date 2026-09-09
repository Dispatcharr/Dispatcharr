import React, { useEffect, useState } from 'react';
import { useForm } from '@mantine/form';
import { Alert, Button, Flex, Stack, Switch, TextInput } from '@mantine/core';
import useSettingsStore from '../../../store/settings.jsx';
import {
  createSetting,
  updateSetting,
} from '../../../utils/pages/SettingsUtils.js';

const SETTING_KEY = 'reverse_proxy_auth';
const HEADER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9-]{0,63}$/;

const ReverseProxyAuthForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const fetchSettings = useSettingsStore((s) => s.fetchSettings);

  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const form = useForm({
    mode: 'controlled',
    initialValues: { enabled: false, header: '' },
    validate: {
      header: (value, values) => {
        const header = (value || '').trim();
        if (values.enabled && !header) {
          return 'A header name is required to enable reverse proxy auth.';
        }
        if (header && !HEADER_PATTERN.test(header)) {
          return 'Use letters, digits and dashes only (for example X-Forwarded-User).';
        }
        return null;
      },
    },
  });

  useEffect(() => {
    if (!active) {
      setSaved(false);
      setError(null);
    }
  }, [active]);

  useEffect(() => {
    const value = settings[SETTING_KEY]?.value || {};
    form.setValues({
      enabled: Boolean(value.enabled),
      header: value.header || '',
    });
  }, [settings]);

  const onSubmit = async () => {
    setSaved(false);
    setError(null);
    setSaving(true);

    const values = form.getValues();
    const value = {
      enabled: Boolean(values.enabled),
      header: (values.header || '').trim(),
    };

    try {
      const existing = settings[SETTING_KEY];
      if (existing?.id) {
        await updateSetting({ ...existing, value });
      } else {
        await createSetting({
          key: SETTING_KEY,
          name: 'Reverse Proxy Auth',
          value,
        });
      }
      await fetchSettings();
      setSaved(true);
    } catch (e) {
      setError(
        e?.body?.message || 'Failed to save reverse proxy auth settings.'
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap="md">
      {saved && (
        <Alert variant="light" color="green" title="Saved Successfully" />
      )}
      {error && (
        <Alert variant="light" color="red" title="Save Failed">
          {error}
        </Alert>
      )}
      <Alert variant="light" color="yellow" title="Trust your proxy first">
        Anything that can reach Dispatcharr directly can send this header. It is
        only honored when the request arrives from a trusted proxy — private and
        loopback ranges by default, or the list in DISPATCHARR_TRUSTED_PROXIES.
        Make sure your proxy strips the header from inbound requests and sets it
        itself.
      </Alert>
      <Switch
        label="Enable Reverse Proxy Authentication"
        description="Sign users in from an identity header set by an authenticating proxy such as Cloudflare Access, oauth2-proxy, or Authelia, instead of showing the login form."
        {...form.getInputProps('enabled', { type: 'checkbox' })}
        id="reverse_proxy_auth_enabled"
      />
      <TextInput
        label="Identity Header"
        description="Header carrying the authenticated username. An email address is also accepted when it matches exactly one account. Examples: X-Forwarded-User, X-Auth-Request-User, Cf-Access-Authenticated-User-Email."
        placeholder="X-Forwarded-User"
        {...form.getInputProps('header')}
        id="reverse_proxy_auth_header"
      />
      <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
        <Button
          onClick={form.onSubmit(onSubmit)}
          disabled={saving}
          variant="default"
        >
          Save
        </Button>
      </Flex>
    </Stack>
  );
});

export default ReverseProxyAuthForm;
