import { NETWORK_ACCESS_OPTIONS } from '../../../constants.js';
import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useRef, useState } from 'react';
import { useForm } from '@mantine/form';
import {
  checkSetting,
  updateSetting,
} from '../../../utils/pages/SettingsUtils.js';
import { Alert, Button, Flex, Stack, TagsInput, Text } from '@mantine/core';
import ConfirmationDialog from '../../ConfirmationDialog.jsx';
import {
  getNetworkAccessFormInitialValues,
  getNetworkAccessFormValidation,
  getNetworkAccessDefaults,
} from '../../../utils/forms/settings/NetworkAccessFormUtils.js';

const toTags = (str) =>
  str
    ? str
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    : [];
const toStr = (tags) => (tags || []).join(',');

const NetworkAccessForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);

  const [networkAccessError, setNetworkAccessError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [restoredDefaults, setRestoredDefaults] = useState([]);
  const [networkAccessConfirmOpen, setNetworkAccessConfirmOpen] =
    useState(false);
  const [saving, setSaving] = useState(false);
  const [netNetworkAccessConfirmCIDRs, setNetNetworkAccessConfirmCIDRs] =
    useState([]);
  const [clientIpAddress, setClientIpAddress] = useState(null);
  const pendingSaveValuesRef = useRef(null);

  const networkAccessForm = useForm({
    mode: 'controlled',
    initialValues: getNetworkAccessFormInitialValues(),
    validate: getNetworkAccessFormValidation(),
  });

  useEffect(() => {
    if (!active) {
      setSaved(false);
      setRestoredDefaults([]);
    }
  }, [active]);

  useEffect(() => {
    const networkAccessSettings = settings['network_access']?.value || {};
    const defaults = getNetworkAccessDefaults();
    networkAccessForm.setValues(
      Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
        acc[key] = networkAccessSettings[key]
          ? toTags(networkAccessSettings[key])
          : defaults[key];
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
    setRestoredDefaults([]);

    const currentValues = networkAccessForm.getValues();
    const defaults = getNetworkAccessDefaults();
    const restoredLabels = [];
    const tagValues = { ...currentValues };

    Object.keys(currentValues).forEach((key) => {
      if (!currentValues[key] || currentValues[key].length === 0) {
        tagValues[key] = defaults[key];
        restoredLabels.push(NETWORK_ACCESS_OPTIONS[key]?.label || key);
      }
    });

    if (restoredLabels.length > 0) {
      networkAccessForm.setValues(tagValues);
      setRestoredDefaults(restoredLabels);
    }

    // Backend expects comma-separated strings
    const submitValues = Object.fromEntries(
      Object.entries(tagValues).map(([k, v]) => [k, toStr(v)])
    );

    pendingSaveValuesRef.current = submitValues;

    const check = await checkSetting({
      ...settings['network_access'],
      value: submitValues,
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
    const values =
      pendingSaveValuesRef.current ||
      Object.fromEntries(
        Object.entries(networkAccessForm.getValues()).map(([k, v]) => [
          k,
          toStr(v),
        ])
      );
    try {
      await updateSetting({
        ...settings['network_access'],
        value: values,
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
            <Alert variant="light" color="green" title="Saved Successfully" />
          )}
          {restoredDefaults.length > 0 && (
            <Alert variant="light" color="yellow" title="Defaults Restored">
              The following fields were empty and have been restored to their
              defaults: {restoredDefaults.join(', ')}
            </Alert>
          )}
          {networkAccessError && (
            <Alert variant="light" color="red" title={networkAccessError} />
          )}

          {Object.entries(NETWORK_ACCESS_OPTIONS).map(([key, config]) => (
            <TagsInput
              label={config.label}
              description={config.description}
              placeholder="e.g. 192.168.1.1 or 192.168.1.0/24"
              splitChars={[',', ' ']}
              {...networkAccessForm.getInputProps(key)}
              key={networkAccessForm.key(key)}
            />
          ))}

          <Flex mih={50} gap="xs" justify="space-between" align="flex-end">
            <Button variant="subtle" color="gray" onClick={resetNetworkAccessToDefaults}>
              Reset to Defaults
            </Button>
            <Button type="submit" disabled={networkAccessForm.submitting} variant="default">
              Save
            </Button>
          </Flex>
        </Stack>
      </form>

      <ConfirmationDialog
        opened={networkAccessConfirmOpen}
        onClose={() => setNetworkAccessConfirmOpen(false)}
        onConfirm={saveNetworkAccess}
        title="Confirm Network Access Blocks"
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
                <li key={cidr}>{cidr}</li>
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
