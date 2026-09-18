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
import usePlaylistsStore from '../../store/playlists';
import useOutputProfilesStore from '../../store/outputProfiles';
import useVODStore from '../../store/useVODStore';
import { USER_LEVEL_LABELS, USER_LEVELS } from '../../constants';
import { DVR_ACCESS } from '../../utils/dvrAccess';
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
  const m3uProfiles = usePlaylistsStore((s) => s.profiles);
  const outputProfiles = useOutputProfilesStore((s) => s.profiles);
  const authUser = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const vodProfiles = useVODStore((s) => s.accessPolicies);
  const fetchVODProfiles = useVODStore((s) => s.fetchAccessPolicies);

  const [, setEnableXC] = useState(false);
  const [selectedProfiles, setSelectedProfiles] = useState(new Set());
  const [selectedAllowedM3uProfiles, setSelectedAllowedM3uProfiles] = useState(
    []
  );
  // true when allowed_m3u_profile_ids is null (key absent / ALL).
  const [allowedM3uProfilesUnrestricted, setAllowedM3uProfilesUnrestricted] =
    useState(true);
  const [generating, setGenerating] = useState(false);
  const [_generatedKey, setGeneratedKey] = useState(null);
  const [userAPIKey, setUserAPIKey] = useState(user?.api_key || null);
  const [vodPolicyId, setVODPolicyId] = useState('');

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
      const values = userToFormValues(user);
      form.setValues(values);
      setVODPolicyId(values.vod_policy_id || '');
      const unrestricted = values.allowed_m3u_profile_ids === null;
      setAllowedM3uProfilesUnrestricted(unrestricted);
      setSelectedAllowedM3uProfiles(
        unrestricted ? [] : values.allowed_m3u_profile_ids || []
      );

      if (user.custom_properties?.xc_password) {
        setEnableXC(true);
      }

      setUserAPIKey(user.api_key || null);
    } else {
      form.reset();
      setVODPolicyId('');
      setSelectedAllowedM3uProfiles([]);
      setAllowedM3uProfilesUnrestricted(true);
    }
    // The form object is intentionally excluded: this initialization must only
    // run when the edited user changes, not when Mantine refreshes form state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    if (isOpen) fetchVODProfiles();
  }, [fetchVODProfiles, isOpen]);

  const onAllowedM3uProfilesChange = (values) => {
    // Any MultiSelect change (including clear to []) is an explicit allowlist.
    // Never escalate to ALL from an empty chip list.
    setAllowedM3uProfilesUnrestricted(false);
    setSelectedAllowedM3uProfiles(values);
    form.setFieldValue('allowed_m3u_profile_ids', values);
  };

  const allowAllM3uProfiles = () => {
    setAllowedM3uProfilesUnrestricted(true);
    setSelectedAllowedM3uProfiles([]);
    form.setFieldValue('allowed_m3u_profile_ids', null);
  };

  const generateXCPassword = () => {
    form.setValues({
      xc_password: Math.random().toString(36).slice(2),
    });
  };

  const effectiveVODProfile = vodPolicyId
    ? (vodProfiles || []).find(
        (profile) => String(profile.id) === String(vodPolicyId)
      )
    : (vodProfiles || []).find((profile) => profile.is_default);

  if (!isOpen) {
    return <></>;
  }

  const isAdmin = authUser.user_level == USER_LEVELS.ADMIN;
  const isEditingSelf = authUser.id === user?.id;
  const showPermissions = isAdmin && !isEditingSelf;
  const allowedM3uProfileOptions = Object.values(m3uProfiles)
    .flat()
    .filter(
      (profile, index, all) =>
        profile.is_active &&
        all.findIndex((item) => item.id === profile.id) === index
    )
    .map((profile) => {
      const providerName = profile.account?.name || 'Unknown provider';
      const profileName = profile.name.startsWith(providerName)
        ? profile.name.slice(providerName.length).trim()
        : profile.name;
      const resolvedProfileName = profileName || profile.name;

      return {
        value: `${profile.id}`,
        // Full label for pills and search; dropdown uses renderOption.
        label: `${providerName}: ${resolvedProfileName}`,
        providerName,
        profileName: resolvedProfileName,
      };
    })
    .sort((a, b) => {
      const byProvider = a.providerName.localeCompare(
        b.providerName,
        undefined,
        {
          sensitivity: 'base',
        }
      );
      if (byProvider !== 0) {
        return byProvider;
      }
      return a.profileName.localeCompare(b.profileName, undefined, {
        sensitivity: 'base',
      });
    });
  // Keep orphaned allowlist IDs visible as chips until an admin clears them
  // or the scrub-on-delete signal has removed them from the user.
  const orphanAllowedM3uOptions = selectedAllowedM3uProfiles
    .filter(
      (id) => !allowedM3uProfileOptions.some((option) => option.value === id)
    )
    .map((id) => ({
      value: id,
      label: `Missing profile #${id}`,
    }));
  const allowedM3uSelectData = [
    ...allowedM3uProfileOptions,
    ...orphanAllowedM3uOptions,
  ];
  const renderAllowedM3uOption = ({ option }) => {
    if (!option.providerName) {
      return option.label;
    }

    return (
      <Group gap={6} wrap="nowrap">
        <Text span size="sm" c="dimmed">
          {option.providerName}:
        </Text>
        <Text span size="sm" fw={500}>
          {option.profileName}
        </Text>
      </Group>
    );
  };

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
    <Modal opened={isOpen} onClose={onClose} title="User" size={1120}>
      <form onSubmit={form.onSubmit(onSubmit)}>
        <Tabs defaultValue="account" style={{ minHeight: 500 }}>
          <TabsList mb="md" style={{ flexWrap: 'nowrap', overflowX: 'auto' }}>
            <TabsTab value="account">Account</TabsTab>
            {showPermissions && (
              <TabsTab value="permissions">Permissions</TabsTab>
            )}
            <TabsTab value="epg">EPG Defaults</TabsTab>
            <TabsTab value="api">API &amp; XC</TabsTab>
            {isAdmin && <TabsTab value="live-refresh">Live refresh</TabsTab>}
            <TabsTab value="vod">VOD Profile</TabsTab>
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
                <Stack gap="xs">
                  <MultiSelect
                    label="Allowed Provider Profiles"
                    searchable
                    clearable
                    placeholder={
                      allowedM3uProfilesUnrestricted
                        ? 'All profiles'
                        : selectedAllowedM3uProfiles.length
                          ? ''
                          : 'No profiles allowed'
                    }
                    data={allowedM3uSelectData}
                    renderOption={renderAllowedM3uOption}
                    {...form.getInputProps('allowed_m3u_profile_ids')}
                    value={selectedAllowedM3uProfiles}
                    onChange={onAllowedM3uProfilesChange}
                    key={form.key('allowed_m3u_profile_ids')}
                  />
                  {!allowedM3uProfilesUnrestricted && (
                    <Button
                      variant="subtle"
                      size="compact-sm"
                      onClick={allowAllM3uProfiles}
                      style={{ alignSelf: 'flex-start' }}
                    >
                      Allow all profiles
                    </Button>
                  )}
                </Stack>
                <Group grow align="flex-start">
                  <Stack gap="sm">
                    <Switch
                      label="Hide Mature Content"
                      {...form.getInputProps('hide_adult_content', {
                        type: 'checkbox',
                      })}
                      key={form.key('hide_adult_content')}
                    />
                    <Switch
                      label="Enable Catchup"
                      {...form.getInputProps('catchup_enabled', {
                        type: 'checkbox',
                      })}
                      key={form.key('catchup_enabled')}
                    />
                  </Stack>
                  <Stack gap="sm">
                    <Switch
                      label="Enable Movies"
                      {...form.getInputProps('vod_movies_enabled', {
                        type: 'checkbox',
                      })}
                      key={form.key('vod_movies_enabled')}
                    />
                    <Switch
                      label="Enable Series"
                      {...form.getInputProps('vod_series_enabled', {
                        type: 'checkbox',
                      })}
                      key={form.key('vod_series_enabled')}
                    />
                  </Stack>
                </Group>
                {form.getValues().user_level != USER_LEVELS.STREAMER && (
                  <Select
                    label="DVR Access"
                    data={[
                      { value: DVR_ACCESS.NONE, label: 'None' },
                      { value: DVR_ACCESS.VIEW, label: 'View' },
                      { value: DVR_ACCESS.MANAGE, label: 'Manage' },
                    ]}
                    {...form.getInputProps('dvr_access')}
                    key={form.key('dvr_access')}
                  />
                )}
              </Stack>
            </TabsPanel>
          )}

          <TabsPanel value="epg">
            <Stack gap="sm">
              <Group grow align="flex-start">
                <NumberInput
                  label="Days forward (0 = all)"
                  min={0}
                  max={365}
                  {...form.getInputProps('epg_days')}
                  key={form.key('epg_days')}
                />
                <NumberInput
                  label="Days back (0 = none)"
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
                <Group grow align="flex-start">
                  <Select
                    label="Output Format Override"
                    clearable
                    placeholder="System default"
                    disabled={!isAdmin}
                    data={[
                      { value: 'mpegts', label: 'MPEG-TS' },
                      { value: 'fmp4', label: 'fMP4 (fragmented MP4)' },
                    ]}
                    {...form.getInputProps('output_format')}
                    key={form.key('output_format')}
                  />
                  <Select
                    label="Output Profile Override"
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
                </Group>
              )}
              {isAdmin && (
                <TagsInput
                  label="Allowed IPs"
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

          {isAdmin && (
            <TabsPanel value="live-refresh">
              <Stack gap="sm">
                <Group grow align="flex-start">
                  <Stack gap="sm">
                    <Switch
                      label="Refresh Live TV providers after XC catalog requests"
                      {...form.getInputProps('xc_live_refresh_on_request', {
                        type: 'checkbox',
                      })}
                      key={form.key('xc_live_refresh_on_request')}
                    />
                    <NumberInput
                      min={0}
                      max={10080}
                      allowDecimal={false}
                      label="User request interval (minutes)"
                      {...form.getInputProps(
                        'xc_live_refresh_request_interval_minutes'
                      )}
                      key={form.key('xc_live_refresh_request_interval_minutes')}
                    />
                  </Stack>
                  <Stack gap="sm">
                    <Switch
                      label="Wait for a fresh XC Live catalog"
                      {...form.getInputProps(
                        'xc_live_refresh_wait_for_completion',
                        { type: 'checkbox' }
                      )}
                      key={form.key('xc_live_refresh_wait_for_completion')}
                    />
                    <NumberInput
                      min={1}
                      max={60}
                      allowDecimal={false}
                      label="Maximum wait for a fresh catalog (seconds)"
                      {...form.getInputProps(
                        'xc_live_refresh_wait_timeout_seconds'
                      )}
                      key={form.key('xc_live_refresh_wait_timeout_seconds')}
                    />
                  </Stack>
                </Group>
              </Stack>
            </TabsPanel>
          )}

          <TabsPanel value="vod">
            <Stack gap="sm">
              <Select
                label="VOD output profile"
                placeholder="Use default profile"
                clearable
                searchable
                data={(vodProfiles || [])
                  .filter((profile) => profile.is_active)
                  .map((profile) => ({
                    value: String(profile.id),
                    label: `${profile.name}${profile.is_default ? ' (default)' : ''}`,
                  }))}
                value={vodPolicyId || null}
                onChange={(value) => {
                  const next = value || '';
                  setVODPolicyId(next);
                  form.setFieldValue('vod_policy_id', next);
                }}
              />
              <Text size="xs" c="dimmed">
                {effectiveVODProfile
                  ? `${Number(
                      effectiveVODProfile.selection_counts?.movies
                        ?.output_entries || 0
                    ).toLocaleString()} movies · ${Number(
                      effectiveVODProfile.selection_counts?.series
                        ?.output_entries || 0
                    ).toLocaleString()} series are currently prepared for this profile.`
                  : 'No active default VOD profile is available.'}
              </Text>
            </Stack>
          </TabsPanel>
        </Tabs>

        <Group justify="flex-end" mt="md">
          <Button
            type="submit"
            variant="filled"
            disabled={form.submitting}
            size="sm"
          >
            Save
          </Button>
        </Group>
      </form>
    </Modal>
  );
};

export default User;
