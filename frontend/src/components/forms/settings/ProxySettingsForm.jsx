import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import { useForm } from '@mantine/form';
import { updateSetting } from '../../../utils/pages/SettingsUtils.js';
import {
  Alert,
  Button,
  Flex,
  NumberInput,
  Stack,
  TextInput,
} from '@mantine/core';
import { PROXY_SETTINGS_OPTIONS } from '../../../constants.js';
import {
  getProxySettingDefaults,
  getProxySettingsFormInitialValues,
} from '../../../utils/forms/settings/ProxySettingsFormUtils.js';

const ProxySettingsOptions = React.memo(({ proxySettingsForm }) => {
  const isNumericField = (key) => {
    // Determine if this field should be a NumberInput
    return [
      'buffering_timeout',
      'redis_chunk_ttl',
      'channel_shutdown_delay',
      'channel_init_grace_period',
    ].includes(key);
  };
  const isFloatField = (key) => {
    return key === 'buffering_speed';
  };
  const getNumericFieldMax = (key) => {
    return key === 'buffering_timeout'
      ? 300
      : key === 'redis_chunk_ttl'
        ? 3600
        : key === 'channel_shutdown_delay'
          ? 300
          : 60;
  };
  return (
    <>
      {Object.entries(PROXY_SETTINGS_OPTIONS).map(([key, config]) => {
        if (isNumericField(key)) {
          return (
            <NumberInput
              key={key}
              label={config.label}
              {...proxySettingsForm.getInputProps(key)}
              description={config.description || null}
              min={0}
              max={getNumericFieldMax(key)}
            />
          );
        } else if (isFloatField(key)) {
          return (
            <NumberInput
              key={key}
              label={config.label}
              {...proxySettingsForm.getInputProps(key)}
              description={config.description || null}
              min={0.0}
              max={10.0}
              step={0.01}
              precision={1}
            />
          );
        } else {
          return (
            <TextInput
              key={key}
              label={config.label}
              {...proxySettingsForm.getInputProps(key)}
              description={config.description || null}
            />
          );
        }
      })}
    </>
  );
});

const ProxySettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);

  const [saved, setSaved] = useState(false);

  const proxySettingsForm = useForm({
    mode: 'controlled',
    initialValues: getProxySettingsFormInitialValues(),
  });

  useEffect(() => {
    if(!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings) {
      if (settings['proxy-settings']?.value) {
        try {
          const proxySettings = JSON.parse(settings['proxy-settings'].value);
          proxySettingsForm.setValues(proxySettings);
        } catch (error) {
          console.error('Error parsing proxy settings:', error);
        }
      }
    }
  }, [settings]);

  const resetProxySettingsToDefaults = () => {
    proxySettingsForm.setValues(getProxySettingDefaults());
  };

  const onProxySettingsSubmit = async () => {
    setSaved(false);

    try {
      const result = await updateSetting({
        ...settings['proxy-settings'],
        value: JSON.stringify(proxySettingsForm.getValues()),
      });
      // API functions return undefined on error
      if (result) {
        setSaved(true);
      }
    } catch (error) {
      // Error notifications are already shown by API functions
      console.error('Error saving proxy settings:', error);
    }
  };

  return (
    <form onSubmit={proxySettingsForm.onSubmit(onProxySettingsSubmit)}>
      <Stack gap="sm">
        {saved && (
          <Alert
            variant="light"
            color="green"
            title="Saved Successfully"
          ></Alert>
        )}

        <ProxySettingsOptions proxySettingsForm={proxySettingsForm} />

        <Flex mih={50} gap="xs" justify="space-between" align="flex-end">
          <Button
            variant="subtle"
            color="gray"
            onClick={resetProxySettingsToDefaults}
          >
            Reset to Defaults
          </Button>
          <Button
            type="submit"
            disabled={proxySettingsForm.submitting}
            variant="default"
          >
            Save
          </Button>
        </Flex>
      </Stack>
    </form>
  );
});

export default ProxySettingsForm;