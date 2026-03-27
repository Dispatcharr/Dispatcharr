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
  Checkbox,
} from '@mantine/core';
import { USER_LIMITS_OPTIONS } from '../../../constants.js';

const USER_LIMIT_DEFAULTS = Object.keys(USER_LIMITS_OPTIONS).reduce(
  (acc, key) => {
    acc[key] = USER_LIMITS_OPTIONS[key].default;
    return acc;
  },
  {}
);

const UserLimitsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);

  const [saved, setSaved] = useState(false);

  const userLimitSettingsForm = useForm({
    mode: 'controlled',
    initialValues: USER_LIMIT_DEFAULTS,
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings) {
      if (settings['user_limit_settings']?.value) {
        userLimitSettingsForm.setValues({
          ...USER_LIMIT_DEFAULTS,
          ...settings['user_limit_settings'].value,
        });
      }
    }
  }, [settings]);

  const resetUserLimitsToDefaults = () => {
    userLimitSettingsForm.setValues(USER_LIMIT_DEFAULTS);
  };

  const onUserLimitsSubmit = async () => {
    setSaved(false);

    try {
      const result = await updateSetting({
        ...settings['user_limit_settings'],
        value: userLimitSettingsForm.getValues(),
      });
      if (result) {
        setSaved(true);
      }
    } catch (error) {
      console.error('Error saving user limit settings:', error);
    }
  };

  return (
    <form onSubmit={userLimitSettingsForm.onSubmit(onUserLimitsSubmit)}>
      <Stack gap="sm">
        {saved && (
          <Alert
            variant="light"
            color="green"
            title="Saved Successfully"
          ></Alert>
        )}

        {Object.keys(USER_LIMITS_OPTIONS).reduce((acc, key) => {
          const option = USER_LIMITS_OPTIONS[key];
          acc.push(
            <Checkbox
              key={key}
              label={option.label}
              description={option.description}
              {...userLimitSettingsForm.getInputProps(key, {
                type: 'checkbox',
              })}
            />
          );
          return acc;
        }, [])}

        <Flex mih={50} gap="xs" justify="space-between" align="flex-end">
          <Button
            variant="subtle"
            color="gray"
            onClick={resetUserLimitsToDefaults}
          >
            Reset to Defaults
          </Button>
          <Button
            type="submit"
            disabled={userLimitSettingsForm.submitting}
            variant="default"
          >
            Save
          </Button>
        </Flex>
      </Stack>
    </form>
  );
});

export default UserLimitsForm;
