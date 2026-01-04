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
} from '../../../utils/forms/settings/NetworkAccessFormUtils.js';

const NetworkAccessForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);

  const [networkAccessError, setNetworkAccessError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [networkAccessConfirmOpen, setNetworkAccessConfirmOpen] =
    useState(false);
  const [netNetworkAccessConfirmCIDRs, setNetNetworkAccessConfirmCIDRs] =
    useState([]);
  const [clientIpAddress, setClientIpAddress] = useState(null);

  const networkAccessForm = useForm({
    mode: 'controlled',
    initialValues: getNetworkAccessFormInitialValues(),
    validate: getNetworkAccessFormValidation(),
  });

  useEffect(() => {
    if(!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    const networkAccessSettings = JSON.parse(
      settings['network-access'].value || '{}'
    );
    networkAccessForm.setValues(
      Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
        acc[key] = networkAccessSettings[key] || '0.0.0.0/0,::/0';
        return acc;
      }, {})
    );
  }, [settings]);

  const onNetworkAccessSubmit = async () => {
    setSaved(false);
    setNetworkAccessError(null);
    const check = await checkSetting({
      ...settings['network-access'],
      value: JSON.stringify(networkAccessForm.getValues()),
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
    try {
      await updateSetting({
        ...settings['network-access'],
        value: JSON.stringify(networkAccessForm.getValues()),
      });
      setSaved(true);
      setNetworkAccessConfirmOpen(false);
    } catch (e) {
      const errors = {};
      for (const key in e.body.value) {
        errors[key] = `Invalid CIDR(s): ${e.body.value[key]}`;
      }
      networkAccessForm.setErrors(errors);
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

          <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
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