import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  TagsInput,
  Text,
  TextInput,
  useMantineTheme,
} from '@mantine/core';
import { Copy, Key, RotateCcwKey, X } from 'lucide-react';
import { useForm } from '@mantine/form';
import useChannelsStore from '../../store/channels';
import useOutputProfilesStore from '../../store/outputProfiles';
import { USER_LEVEL_LABELS, USER_LEVELS } from '../../constants';
import useAuthStore from '../../store/auth';
import { copyToClipboard } from '../../utils';
import {
  createUser,
  formValuesToPayload,
  generateApiKey,
  getFormInitialValues,
  getFormValidators,
  revokeApiKey,
  updateUser,
  userToFormValues,
} from '../../utils/forms/UserUtils.js';

const User = ({ user = null, isOpen, onClose }) => {
  const profiles = useChannelsStore((s) => s.profiles);
  const outputProfiles = useOutputProfilesStore((s) => s.profiles);
  const authUser = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);

  const [, setEnableXC] = useState(false);
  const [selectedProfiles, setSelectedProfiles] = useState(new Set());
  const [generating, setGenerating] = useState(false);
  const [_generatedKey, setGeneratedKey] = useState(null);
  const [userAPIKey, setUserAPIKey] = useState(user?.api_key || null);

  const theme = useMantineTheme();

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: getFormInitialValues(),
    validate: getFormValidators(user),
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
    const payload = formValuesToPayload(form.getValues(), user);

    if (!user && payload.user_level == USER_LEVELS.STREAMER) {
      payload.password = Math.random().toString(36).slice(2);
    }

    if (!user) {
      await createUser(payload);
    } else {
      if (!payload.password) delete payload.password;
      const response = await updateUser(user.id, payload, isAdmin, authUser);
      if (user.id == authUser.id) setUser(response);
    }

    form.reset();
    setUserAPIKey(null);
    onClose();
  };

  useEffect(() => {
    if (user?.id) {
      form.setValues(userToFormValues(user));

      if (user.custom_properties?.xc_password) {
        setEnableXC(true);
      }

      setUserAPIKey(user.api_key || null);
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

  const isAdmin = authUser.user_level == USER_LEVELS.ADMIN;
  const isEditingSelf = authUser.id === user?.id;
  const showPermissions = isAdmin && !isEditingSelf;

  const canGenerateKey =
    authUser.user_level == USER_LEVELS.ADMIN || authUser.id === user?.id;

  const onGenerateKey = async () => {
    if (!canGenerateKey) {
      return;
    }

    setGenerating(true);
    try {
      const payload = {};
      if (authUser.user_level == USER_LEVELS.ADMIN && user?.id) {
        payload.user_id = user.id;
      }

      const resp = await generateApiKey(payload);
      const newKey = resp && (resp.key || resp.raw_key);
      if (newKey) {
        setGeneratedKey(newKey);
        setUserAPIKey(newKey);
      }
    } catch {
      // API shows notifications
    } finally {
      setGenerating(false);
    }
  };

  const onRevokeKey = async () => {
    if (!canGenerateKey) return;

    setGenerating(true);
    try {
      const payload = {};
      if (authUser.user_level == USER_LEVELS.ADMIN && user?.id) {
        payload.user_id = user.id;
      }

      const resp = await revokeApiKey(payload);
      // backend returns { success: true } - clear local state
      if (resp && resp.success) {
        setGeneratedKey(null);
        setUserAPIKey(null);

        if (user?.id && authUser?.id === user.id) {
          setUser({ ...authUser, api_key: null });
        }
      }
    } catch {
      // API shows notifications
    } finally {
      setGenerating(false);
    }
  };

  return (
    <Modal opened={isOpen} onClose={onClose} title="User" size="xl">
      <form onSubmit={form.onSubmit(onSubmit)}>
        <Tabs defaultValue="account">
          <TabsList mb="md">
            <TabsTab value="account">Account</TabsTab>
            {showPermissions && (
              <TabsTab value="permissions">Permissions</TabsTab>
            )}
            <TabsTab value="epg">EPG Defaults</TabsTab>
            <TabsTab value="api">API &amp; XC</TabsTab>
          </TabsList>

          <TabsPanel value="account">
            <Stack gap="sm">
              <Group grow align="flex-start">
                <TextInput
                  label="Username"
                  disabled={!isAdmin}
                  {...form.getInputProps('username')}
                  key={form.key('username')}
                />
                <TextInput
                  label="E-Mail"
                  {...form.getInputProps('email')}
                  key={form.key('email')}
                />
              </Group>
              <Group grow align="flex-start">
                <TextInput
                  label="First Name"
                  {...form.getInputProps('first_name')}
                  key={form.key('first_name')}
                />
                <TextInput
                  label="Last Name"
                  {...form.getInputProps('last_name')}
                  key={form.key('last_name')}
                />
              </Group>
              <PasswordInput
                label="Password"
                description="Used for UI authentication"
                {...form.getInputProps('password')}
                key={form.key('password')}
                disabled={form.getValues().user_level == USER_LEVELS.STREAMER}
              />
            </Stack>
          </TabsPanel>

          {showPermissions && (
            <TabsPanel value="permissions">
              <Stack gap="sm">
                <Group grow align="flex-start">
                  <Select
                    label="User Level"
                    data={Object.entries(USER_LEVELS).map(([, value]) => ({
                      label: USER_LEVEL_LABELS[value],
                      value: `${value}`,
                    }))}
                    {...form.getInputProps('user_level')}
                    key={form.key('user_level')}
                  />
                  <NumberInput
                    label="Stream Limit (0 = unlimited)"
                    {...form.getInputProps('stream_limit')}
                    key={form.key('stream_limit')}
                  />
                </Group>
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
                <Switch
                  label="Hide Mature Content"
                  description="Hide channels marked as mature content (admin users not affected)"
                  {...form.getInputProps('hide_adult_content', {
                    type: 'checkbox',
                  })}
                  key={form.key('hide_adult_content')}
                />
              </Stack>
            </TabsPanel>
          )}

          <TabsPanel value="epg">
            <Stack gap="sm">
              <Text size="sm" c="dimmed">
                These defaults apply when no URL parameters are specified and
                can be useful for XC clients that cannot pass custom query
                parameters.
              </Text>
              <Group grow align="flex-start">
                <NumberInput
                  label="Days forward (0 = all)"
                  description="How many future days of EPG data to include"
                  min={0}
                  max={365}
                  {...form.getInputProps('epg_days')}
                  key={form.key('epg_days')}
                />
                <NumberInput
                  label="Days back (0 = none)"
                  description="How many past days of EPG data to include (max 30)"
                  min={0}
                  max={30}
                  {...form.getInputProps('epg_prev_days')}
                  key={form.key('epg_prev_days')}
                />
              </Group>
            </Stack>
          </TabsPanel>

          <TabsPanel value="api">
            <Stack gap="sm">
              <TextInput
                label="XC Password"
                description={
                  isAdmin
                    ? 'Clear to disable XC API'
                    : 'XC password can only be changed by an administrator'
                }
                disabled={!isAdmin}
                {...form.getInputProps('xc_password')}
                key={form.key('xc_password')}
                rightSectionWidth={30}
                rightSection={
                  <ActionIcon
                    variant="transparent"
                    size="sm"
                    color="white"
                    onClick={generateXCPassword}
                    disabled={!isAdmin}
                  >
                    <RotateCcwKey />
                  </ActionIcon>
                }
              />
              {isAdmin && (
                <Select
                  label="Output Format Override"
                  description="Override the system default output format for this user. Clear to use system default."
                  clearable
                  placeholder="System default"
                  disabled={!isAdmin}
                  data={[
                    { value: 'mpegts', label: 'MPEG-TS' },
                    { value: 'fmp4', label: 'fMP4 (fragmented MP4)' },
                    { value: 'hls', label: 'HLS' },
                  ]}
                  {...form.getInputProps('output_format')}
                  key={form.key('output_format')}
                />
              )}
              {isAdmin && (
                <Select
                  label="Output Profile Override"
                  description="Pre-delivery transcode profile applied to streams for this user. Clear to use no transcoding."
                  clearable
                  searchable
                  placeholder="No transcoding"
                  disabled={!isAdmin}
                  data={outputProfiles
                    .filter((p) => p.is_active)
                    .map((p) => ({ value: `${p.id}`, label: p.name }))}
                  {...form.getInputProps('output_profile')}
                  key={form.key('output_profile')}
                />
              )}
              {isAdmin && (
                <TagsInput
                  label="Allowed IPs"
                  description="Restrict all access for this user by IP. Leave empty to inherit global settings."
                  placeholder="e.g. 192.168.1.1 or 192.168.1.0/24"
                  splitChars={[',', ' ']}
                  {...form.getInputProps('allowed_ips')}
                  key={form.key('allowed_ips')}
                />
              )}
              {canGenerateKey && (
                <Stack gap="xs">
                  {userAPIKey && (
                    <TextInput
                      label="API Key"
                      disabled={true}
                      value={userAPIKey}
                      rightSection={
                        <ActionIcon
                          variant="transparent"
                          size="sm"
                          color="white"
                          onClick={() =>
                            copyToClipboard(userAPIKey, {
                              successTitle: 'API Key Copied!',
                              successMessage:
                                'The API Key has been copied to your clipboard.',
                            })
                          }
                        >
                          <Copy />
                        </ActionIcon>
                      }
                    />
                  )}
                  <Group gap="xs" grow>
                    <Button
                      leftSection={<Key size={14} />}
                      size="xs"
                      onClick={onGenerateKey}
                      loading={generating}
                      variant="light"
                      fullWidth
                    >
                      {userAPIKey ? 'Regenerate API Key' : 'Generate API Key'}
                    </Button>
                    {userAPIKey && (
                      <Button
                        leftSection={<X size={14} />}
                        size="xs"
                        onClick={onRevokeKey}
                        loading={generating}
                        color={theme.colors.red[5]}
                        variant="light"
                        fullWidth
                      >
                        Revoke API Key
                      </Button>
                    )}
                  </Group>
                </Stack>
              )}
            </Stack>
          </TabsPanel>
        </Tabs>

        <Group justify="flex-end" mt="md">
          <Button
            type="submit"
            variant="contained"
            disabled={form.submitting}
            size="small"
          >
            Save
          </Button>
        </Group>
      </form>
    </Modal>
  );
};

export default User;
