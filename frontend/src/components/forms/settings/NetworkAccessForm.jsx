import { NETWORK_ACCESS_OPTIONS } from '../../../constants.js';
import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import { useForm } from '@mantine/form';
import {
  checkSetting,
  updateSetting,
} from '../../../utils/pages/SettingsUtils.js';
import { Alert, Button, Flex, Stack, Text, TextInput } from '@mantine/core';
import ConfirmationDialog from '../../ConfirmationDialog.jsx';
import {
  getNetworkAccessFormInitialValues,
  getNetworkAccessFormValidation,
  getNetworkAccessDefaults,
} from '../../../utils/forms/settings/NetworkAccessFormUtils.js';

const NetworkAccessForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);

  const [networkAccessError, setNetworkAccessError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [networkAccessConfirmOpen, setNetworkAccessConfirmOpen] =
    useState(false);
  const [saving, setSaving] = useState(false);
  const [netNetworkAccessConfirmCIDRs, setNetNetworkAccessConfirmCIDRs] =
    useState([]);
  const [clientIpAddress, setClientIpAddress] = useState(null);

  const networkAccessForm = useForm({
    mode: 'controlled',
    initialValues: getNetworkAccessFormInitialValues(),
    validate: getNetworkAccessFormValidation(),
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    const networkAccessSettings = settings['network_access']?.value || {};
    // M3U/EPG endpoints default to local networks only
    const m3uEpgDefaults =
      '127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7,fe80::/10';
    networkAccessForm.setValues(
      Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
        const defaultValue =
          key === 'M3U_EPG' ? m3uEpgDefaults : '0.0.0.0/0,::/0';
        acc[key] = networkAccessSettings[key] || defaultValue;
        return acc;
      }, {})
    );
  }, [settings]);

  const resetNetworkAccessToDefaults = () => {
    networkAccessForm.setValues(getNetworkAccessDefaults());
  };

  const onNetworkAccessSubmit = async () => {
    setSaved(false);
    setNetworkAccessError(null);
    const check = await checkSetting({
      ...settings['network_access'],
      value: networkAccessForm.getValues(), // Send as object
    });

    if (check.error && check.message) {
      setNetworkAccessError(`${check.message}: ${check.data}`);
      return;
    }

    // Store the client IP
    setClientIpAddress(check.client_ip);

    // For now, only warn if we're blocking the UI
    const blockedAccess = check.UI;
    if (blockedAccess.length === 0) {
      return saveNetworkAccess();
    }

    setNetNetworkAccessConfirmCIDRs(blockedAccess);
    setNetworkAccessConfirmOpen(true);
  };

  const saveNetworkAccess = async () => {
    setSaved(false);
    setSaving(true);
    try {
      await updateSetting({
        ...settings['network_access'],
        value: networkAccessForm.getValues(), // Send as object
      });
      setSaved(true);
    } catch (e) {
      const errors = {};
      for (const key in e.body.value) {
        errors[key] = `Invalid CIDR(s): ${e.body.value[key]}`;
      }
      networkAccessForm.setErrors(errors);
    } finally {
      setSaving(false);
      setNetworkAccessConfirmOpen(false);
    }
  };

  return (
    <>
      <form onSubmit={networkAccessForm.onSubmit(onNetworkAccessSubmit)}>
        <Stack gap="sm">
          {saved && (
            <Alert
              variant="light"
              color="green"
              title="Saved Successfully"
            ></Alert>
          )}
          {networkAccessError && (
            <Alert
              variant="light"
              color="red"
              title={networkAccessError}
            ></Alert>
          )}

          {Object.entries(NETWORK_ACCESS_OPTIONS).map(([key, config]) => (
            <TextInput
              label={config.label}
              {...networkAccessForm.getInputProps(key)}
              key={networkAccessForm.key(key)}
              description={config.description}
            />
          ))}

          <Flex mih={50} gap="xs" justify="space-between" align="flex-end">
            <Button
              variant="subtle"
              color="gray"
              onClick={resetNetworkAccessToDefaults}
            >
              Reset to Defaults
            </Button>
            <Button
              type="submit"
              disabled={networkAccessForm.submitting}
              variant="default"
            >
              Save
            </Button>
          </Flex>
        </Stack>
      </form>

      <ConfirmationDialog
        opened={networkAccessConfirmOpen}
        onClose={() => setNetworkAccessConfirmOpen(false)}
        onConfirm={saveNetworkAccess}
        title={`Confirm Network Access Blocks`}
        loading={saving}
        message={
          <>
            <Text>
              Your client {clientIpAddress && `(${clientIpAddress}) `}is not
              included in the allowed networks for the web UI. Are you sure you
              want to proceed?
            </Text>

            <ul>
              {netNetworkAccessConfirmCIDRs.map((cidr) => (
                <li>{cidr}</li>
              ))}
            </ul>
          </>
        }
        confirmLabel="Save"
        cancelLabel="Cancel"
        size="md"
      />
    </>
  );
});

export default NetworkAccessForm;
