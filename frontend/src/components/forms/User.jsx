// Modal.js
import React, { useState, useEffect } from 'react';
import API from '../../api';
import {
  TextInput,
  Button,
  Modal,
  Flex,
  Select,
  PasswordInput,
  Group,
  Stack,
  MultiSelect,
  ActionIcon,
  Switch,
  Box,
  Tooltip,
} from '@mantine/core';
import { RotateCcwKey, X } from 'lucide-react';
import { useForm } from '@mantine/form';
import useChannelsStore from '../../store/channels';
import { USER_LEVELS, USER_LEVEL_LABELS } from '../../constants';
import useAuthStore from '../../store/auth';

const User = ({ user = null, isOpen, onClose }) => {
  const profiles = useChannelsStore((s) => s.profiles);
  const authUser = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);

  const [, setEnableXC] = useState(false);
  const [selectedProfiles, setSelectedProfiles] = useState(new Set());

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      username: '',
      first_name: '',
      last_name: '',
      email: '',
      user_level: '0',
      password: '',
      xc_password: '',
      channel_profiles: [],
      hide_adult_content: false,
    },

    validate: (values) => ({
      username: !values.username
        ? 'Username is required'
        : values.user_level == USER_LEVELS.STREAMER &&
            !values.username.match(/^[a-z0-9]+$/i)
          ? 'Streamer username must be alphanumeric'
          : null,
      password:
        !user && !values.password && values.user_level != USER_LEVELS.STREAMER
          ? 'Password is requried'
          : null,
      xc_password:
        values.xc_password && !values.xc_password.match(/^[a-z0-9]+$/i)
          ? 'XC password must be alphanumeric'
          : null,
    }),
  });

  const onChannelProfilesChange = (values) => {
    let newValues = new Set(values);
    if (selectedProfiles.has('0')) {
      newValues.delete('0');
    } else if (newValues.has('0')) {
      newValues = new Set(['0']);
    }

    setSelectedProfiles(newValues);

    form.setFieldValue('channel_profiles', [...newValues]);
  };

  const onSubmit = async () => {
    const values = form.getValues();

    const customProps = user?.custom_properties || {};

    // Always save xc_password, even if it's empty (to allow clearing)
    customProps.xc_password = values.xc_password || '';
    delete values.xc_password;

    // Save hide_adult_content in custom_properties
    customProps.hide_adult_content = values.hide_adult_content || false;
    delete values.hide_adult_content;

    values.custom_properties = customProps;

    // If 'All' is included, clear this and we assume access to all channels
    if (values.channel_profiles.includes('0')) {
      values.channel_profiles = [];
    }

    if (!user && values.user_level == USER_LEVELS.STREAMER) {
      // Generate random password - they can't log in, but user can't be created without a password
      values.password = Math.random().toString(36).slice(2);
    }

    if (!user) {
      await API.createUser(values);
    } else {
      if (!values.password) {
        delete values.password;
      }

      const response = await API.updateUser(user.id, values);

      if (user.id == authUser.id) {
        setUser(response);
      }
    }

    form.reset();
    onClose();
  };

  useEffect(() => {
    if (user?.id) {
      const customProps = user.custom_properties || {};

      form.setValues({
        username: user.username,
        first_name: user.first_name || '',
        last_name: user.last_name || '',
        email: user.email,
        user_level: `${user.user_level}`,
        channel_profiles:
          user.channel_profiles.length > 0
            ? user.channel_profiles.map((id) => `${id}`)
            : ['0'],
        xc_password: customProps.xc_password || '',
        hide_adult_content: customProps.hide_adult_content || false,
      });

      if (customProps.xc_password) {
        setEnableXC(true);
      }
    } else {
      form.reset();
    }
  }, [user]);

  const generateXCPassword = () => {
    form.setValues({
      xc_password: Math.random().toString(36).slice(2),
    });
  };

  if (!isOpen) {
    return <></>;
  }

  const showPermissions =
    authUser.user_level == USER_LEVELS.ADMIN && authUser.id !== user?.id;

  return (
    <Modal opened={isOpen} onClose={onClose} title="User" size="xl">
      <form onSubmit={form.onSubmit(onSubmit)}>
        <Group justify="space-between" align="top">
          <Stack gap="xs" style={{ flex: 1 }}>
            <TextInput
              id="username"
              name="username"
              label="Username"
              {...form.getInputProps('username')}
              key={form.key('username')}
            />

            <TextInput
              id="first_name"
              name="first_name"
              label="First Name"
              {...form.getInputProps('first_name')}
              key={form.key('first_name')}
            />

            <PasswordInput
              label="Password"
              description="Used for UI authentication"
              {...form.getInputProps('password')}
              key={form.key('password')}
              disabled={form.getValues().user_level == USER_LEVELS.STREAMER}
            />

            {showPermissions && (
              <Select
                label="User Level"
                data={Object.entries(USER_LEVELS).map(([, value]) => {
                  return {
                    label: USER_LEVEL_LABELS[value],
                    value: `${value}`,
                  };
                })}
                {...form.getInputProps('user_level')}
                key={form.key('user_level')}
              />
            )}
          </Stack>

          <Stack gap="xs" style={{ flex: 1 }}>
            <TextInput
              id="email"
              name="email"
              label="E-Mail"
              {...form.getInputProps('email')}
              key={form.key('email')}
            />

            <TextInput
              id="last_name"
              name="last_name"
              label="Last Name"
              {...form.getInputProps('last_name')}
              key={form.key('last_name')}
            />

            <Group align="flex-end">
              <TextInput
                label="XC Password"
                description="Clear to disable XC API"
                {...form.getInputProps('xc_password')}
                key={form.key('xc_password')}
                style={{ flex: 1 }}
                rightSectionWidth={30}
                rightSection={
                  <ActionIcon
                    variant="transparent"
                    size="sm"
                    color="white"
                    onClick={generateXCPassword}
                  >
                    <RotateCcwKey />
                  </ActionIcon>
                }
              />
            </Group>

            {showPermissions && (
              <MultiSelect
                label="Channel Profiles"
                {...form.getInputProps('channel_profiles')}
                key={form.key('channel_profiles')}
                onChange={onChannelProfilesChange}
                data={Object.values(profiles).map((profile) => ({
                  label: profile.name,
                  value: `${profile.id}`,
                }))}
              />
            )}

            {showPermissions && (
              <Box>
                <Tooltip
                  label="Hide channels marked as mature content (admin users not affected)"
                  position="top"
                  withArrow
                >
                  <Switch
                    label="Hide Mature Content"
                    {...form.getInputProps('hide_adult_content', {
                      type: 'checkbox',
                    })}
                    key={form.key('hide_adult_content')}
                  />
                </Tooltip>
              </Box>
            )}
          </Stack>
        </Group>

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            type="submit"
            variant="contained"
            disabled={form.submitting}
            size="small"
          >
            Save
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default User;
