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
      'new_client_behind_seconds',
      'max_retries',
      'url_switch_timeout',
      'max_stream_switches',
      'connection_timeout',
      'failover_grace_period',
      'chunk_timeout',
      'initial_behind_chunks',
      'chunk_batch_size',
      'health_check_interval',
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
          : key === 'new_client_behind_seconds'
            ? 120
            : key === 'max_retries'
              ? 10
              : key === 'url_switch_timeout'
                ? 60
                : key === 'max_stream_switches'
                  ? 500
                  : key === 'connection_timeout'
                    ? 60
                    : key === 'failover_grace_period'
                      ? 60
                      : key === 'chunk_timeout'
                        ? 30
                        : key === 'initial_behind_chunks'
                          ? 20
                          : key === 'chunk_batch_size'
                            ? 20
                            : key === 'health_check_interval'
                              ? 30
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
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings) {
      if (settings['proxy_settings']?.value) {
        // Merge defaults so any newly-added keys not yet in the stored
        // settings object still show their default value rather than blank.
        proxySettingsForm.setValues({
          ...getProxySettingDefaults(),
          ...settings['proxy_settings'].value,
        });
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
        ...settings['proxy_settings'],
        value: proxySettingsForm.getValues(), // Send as object
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
