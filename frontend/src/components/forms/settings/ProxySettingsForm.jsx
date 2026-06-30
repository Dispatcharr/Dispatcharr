import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import { useForm } from '@mantine/form';
import { updateSetting } from '../../../utils/pages/SettingsUtils.js';
import {
  Alert,
  Button,
  Collapse,
  Flex,
  NumberInput,
  Stack,
  TextInput,
} from '@mantine/core';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { PROXY_SETTINGS_OPTIONS } from '../../../constants.js';
import {
  getProxySettingDefaults,
  getProxySettingsFormInitialValues,
} from '../../../utils/forms/settings/ProxySettingsFormUtils.js';

const isNumericField = (key) => {
  return [
    'buffering_timeout',
    'redis_chunk_ttl',
    'channel_shutdown_delay',
    'channel_init_grace_period',
    'channel_client_wait_period',
    'new_client_behind_seconds',
  ].includes(key);
};

const isFloatField = (key) => key === 'buffering_speed';

const getNumericFieldMax = (key) => {
  if (key === 'buffering_timeout') return 300;
  if (key === 'redis_chunk_ttl') return 3600;
  if (key === 'channel_shutdown_delay') return 300;
  if (key === 'channel_client_wait_period') return 300;
  if (key === 'new_client_behind_seconds') return 120;
  return 300;
};

const renderProxySettingField = (key, config, proxySettingsForm) => {
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
  }

  if (isFloatField(key)) {
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
  }

  return (
    <TextInput
      key={key}
      label={config.label}
      {...proxySettingsForm.getInputProps(key)}
      description={config.description || null}
    />
  );
};

const ProxySettingsOptions = React.memo(({ proxySettingsForm }) => {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const entries = Object.entries(PROXY_SETTINGS_OPTIONS);
  const mainEntries = entries.filter(([, config]) => !config.advanced);
  const advancedEntries = entries.filter(([, config]) => config.advanced);

  return (
    <>
      {mainEntries.map(([key, config]) =>
        renderProxySettingField(key, config, proxySettingsForm)
      )}

      {advancedEntries.length > 0 && (
        <>
          <Button
            variant="subtle"
            size="xs"
            leftSection={
              advancedOpen ? (
                <ChevronDown size={12} />
              ) : (
                <ChevronRight size={12} />
              )
            }
            onClick={() => setAdvancedOpen((open) => !open)}
            c="dimmed"
            styles={{ root: { alignSelf: 'flex-start' } }}
          >
            {advancedOpen ? 'Hide' : 'Show'} Advanced Settings
          </Button>
          <Collapse in={advancedOpen}>
            <Stack gap="sm">
              {advancedEntries.map(([key, config]) =>
                renderProxySettingField(key, config, proxySettingsForm)
              )}
            </Stack>
          </Collapse>
        </>
      )}
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
