import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  TagsInput,
  Text,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import {
  SensitiveTextInput as TextInput,
  SensitivePasswordInput as PasswordInput,
} from '../SensitiveFields.jsx';
import { Copy, Key, RotateCcwKey, Trash2, X } from 'lucide-react';
import { useForm } from '@mantine/form';
import useChannelsStore from '../../store/channels';
import usePlaylistsStore from '../../store/playlists';
import useOutputProfilesStore from '../../store/outputProfiles';
import { USER_LEVEL_LABELS, USER_LEVELS } from '../../constants';
import { DVR_ACCESS } from '../../utils/dvrAccess';
import useAuthStore from '../../store/auth';
import useSettingsStore from '../../store/settings';
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
import ApiKeyQrPopover from './ApiKeyQrPopover';
import UserAppData from './UserAppData';
import editorClasses from './AccountEditor.module.css';

const helpLabel = (label, help) => (
  <Group gap={5} wrap="nowrap">
    <Text span inherit>
      {label}
    </Text>
    <Tooltip
      label={help}
      multiline
      maw={360}
      withArrow
      events={{ hover: true, focus: true, touch: true }}
    >
      <Text
        span
        size="xs"
        c="dimmed"
        tabIndex={0}
        aria-label={`${label} help`}
        style={{ cursor: 'help' }}
      >
        ⓘ
      </Text>
    </Tooltip>
  </Group>
);

const User = ({ user = null, isOpen, onClose }) => {
  const profiles = useChannelsStore((s) => s.profiles);
  const m3uProfiles = usePlaylistsStore((s) => s.profiles);
  const outputProfiles = useOutputProfilesStore((s) => s.profiles);
  const authUser = useAuthStore((s) => s.user);
  const epgHistoryMaxDays = useSettingsStore((s) => {
    const raw = s.settings?.epg_settings?.value?.epg_history_max_days;
    const number = Number(raw);
    if (!Number.isFinite(number)) {
      return 30;
    }
    return Math.max(0, Math.min(365, Math.trunc(number)));
  });
  const setUser = useAuthStore((s) => s.setUser);

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
  const [activeTab, setActiveTab] = useState('account');
  const [clearAllAppData, setClearAllAppData] = useState(null);

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

  // Start on the Account tab each time the modal opens or switches users. Keyed
  // on the id, not the user object, so a refreshed copy of the same user (for
  // example after revoking an API key) does not yank the current tab away.
  useEffect(() => {
    if (isOpen) {
      setActiveTab('account');
    }
  }, [isOpen, user?.id]);

  useEffect(() => {
    if (user?.id) {
      const values = userToFormValues(user);
      form.setValues(values);
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
      setSelectedAllowedM3uProfiles([]);
      setAllowedM3uProfilesUnrestricted(true);
    }
    // form is from useForm; only re-sync when the edited user changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    setActiveTab('account');
  }, [isOpen, user?.id]);

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
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={user?.id ? 'Edit user' : 'Create user'}
      closeButtonProps={{ 'aria-label': 'Close user editor' }}
      size="min(880px, 94vw)"
      classNames={{
        content: `${editorClasses.content} ${editorClasses.userContent}`,
        body: editorClasses.body,
        header: editorClasses.header,
      }}
      yOffset="2vh"
      xOffset="3vw"
    >
      <form onSubmit={form.onSubmit(onSubmit)} className={editorClasses.form}>
        <Tabs
          value={activeTab}
          onChange={setActiveTab}
          className={`${editorClasses.tabs} ${editorClasses.accountTabs}`}
        >
          <TabsList className={editorClasses.tabList}>
            <TabsTab value="account">Account</TabsTab>
            {showPermissions && (
              <TabsTab value="permissions">Permissions</TabsTab>
            )}
            <TabsTab value="epg">EPG Defaults</TabsTab>
            <TabsTab value="api">API &amp; XC</TabsTab>
            {user?.id && <TabsTab value="app-data">App Data</TabsTab>}
          </TabsList>

          <TabsPanel
            value="account"
            className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
            data-editor-active={activeTab === 'account'}
            aria-hidden={activeTab !== 'account'}
            inert={activeTab !== 'account'}
          >
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
                label={helpLabel(
                  'Password',
                  'Used for UI authentication. Leave empty to keep the existing password when editing a user.'
                )}
                aria-label="Password"
                {...form.getInputProps('password')}
                key={form.key('password')}
                disabled={form.getValues().user_level == USER_LEVELS.STREAMER}
              />
            </Stack>
          </TabsPanel>

          {showPermissions && (
            <TabsPanel
              value="permissions"
              className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
              data-editor-active={activeTab === 'permissions'}
              aria-hidden={activeTab !== 'permissions'}
              inert={activeTab !== 'permissions'}
            >
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
                    label={helpLabel(
                      'Allowed Provider Profiles',
                      'Limit which M3U account profiles this user may use when Dispatcharr hands them a provider URL (Redirect live/catchup via the channel’s effective profile, and VOD when the system default is Redirect). Unrestricted allows all profiles. Clearing the list denies all provider profiles.'
                    )}
                    aria-label="Allowed Provider Profiles"
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
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                  <Switch
                    label={helpLabel(
                      'Hide Mature Content',
                      'Hide channels marked as mature content. Admin users are not affected.'
                    )}
                    aria-label="Hide Mature Content"
                    {...form.getInputProps('hide_adult_content', {
                      type: 'checkbox',
                    })}
                    key={form.key('hide_adult_content')}
                  />
                  <Switch
                    label={helpLabel(
                      'Enable Catchup',
                      'When disabled, this user cannot access timeshift or catchup endpoints, and their channels are not advertised as supporting catchup.'
                    )}
                    aria-label="Enable Catchup"
                    {...form.getInputProps('catchup_enabled', {
                      type: 'checkbox',
                    })}
                    key={form.key('catchup_enabled')}
                  />
                  <Switch
                    label={helpLabel(
                      'Enable Movies',
                      'When disabled, this user cannot list or play movies via the API or Xtream Codes.'
                    )}
                    aria-label="Enable Movies"
                    {...form.getInputProps('vod_movies_enabled', {
                      type: 'checkbox',
                    })}
                    key={form.key('vod_movies_enabled')}
                  />
                  <Switch
                    label={helpLabel(
                      'Enable Series',
                      'When disabled, this user cannot list or play series/episodes via the API or Xtream Codes.'
                    )}
                    aria-label="Enable Series"
                    {...form.getInputProps('vod_series_enabled', {
                      type: 'checkbox',
                    })}
                    key={form.key('vod_series_enabled')}
                  />
                </SimpleGrid>
                {form.getValues().user_level != USER_LEVELS.STREAMER && (
                  <Select
                    label={helpLabel(
                      'DVR Access',
                      'None: no DVR page or playback. View: watch recordings for channels they can access (default). Manage: create, delete, and manage recordings and rules like an admin for DVR endpoints.'
                    )}
                    aria-label="DVR Access"
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

          <TabsPanel
            value="epg"
            className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
            data-editor-active={activeTab === 'epg'}
            aria-hidden={activeTab !== 'epg'}
            inert={activeTab !== 'epg'}
          >
            <Stack gap="sm">
              <Text size="sm" c="dimmed">
                These defaults apply when no URL parameters are specified and
                can be useful for XC clients that cannot pass custom query
                parameters.
              </Text>
              <Group grow align="flex-start">
                <NumberInput
                  label={helpLabel(
                    'Days forward',
                    'Future days of EPG to include. Empty uses the system default. 0 means all stored future programmes.'
                  )}
                  aria-label="Days forward"
                  placeholder="System default"
                  min={0}
                  max={365}
                  allowDecimal={false}
                  {...form.getInputProps('epg_days')}
                  key={form.key('epg_days')}
                />
                <NumberInput
                  label={helpLabel(
                    'Days back',
                    'Past days of EPG to include. Empty uses the system default. 0 means none.'
                  )}
                  aria-label="Days back"
                  placeholder="System default"
                  min={0}
                  max={epgHistoryMaxDays}
                  allowDecimal={false}
                  {...form.getInputProps('epg_prev_days')}
                  key={form.key('epg_prev_days')}
                />
              </Group>
            </Stack>
          </TabsPanel>

          <TabsPanel
            value="api"
            className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
            data-editor-active={activeTab === 'api'}
            aria-hidden={activeTab !== 'api'}
            inert={activeTab !== 'api'}
          >
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
                    aria-label="Generate XC password"
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
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                  <Select
                    label={helpLabel(
                      'Output Format Override',
                      'Override the system default output format for this user. Clear to use the system default.'
                    )}
                    aria-label="Output Format Override"
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
                  <Select
                    label={helpLabel(
                      'Output Profile Override',
                      'Pre-delivery transcode profile applied to streams for this user. Clear to use no transcoding.'
                    )}
                    aria-label="Output Profile Override"
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
                </SimpleGrid>
              )}
              {isAdmin && (
                <TagsInput
                  label={helpLabel(
                    'Allowed IPs',
                    'Further restrict this user by IP/CIDR within global Network Access. Leave empty to inherit global settings only.'
                  )}
                  aria-label="Allowed IPs"
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
                      rightSectionWidth={56}
                      rightSectionPointerEvents="auto"
                      rightSection={
                        <Group gap={4} wrap="nowrap">
                          <ApiKeyQrPopover apiKey={userAPIKey} user={user} />
                          <ActionIcon
                            variant="transparent"
                            size="sm"
                            color="white"
                            aria-label="Copy API key"
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
                        </Group>
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

          {user?.id && (
            <TabsPanel
              value="app-data"
              className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
              data-editor-active={activeTab === 'app-data'}
              aria-hidden={activeTab !== 'app-data'}
              inert={activeTab !== 'app-data'}
            >
              {activeTab === 'app-data' && (
                <UserAppData
                  // Non-admins may only call /me/app-data/; numeric ids are
                  // for admins managing another user (own id also works).
                  userId={authUser?.id === user.id ? 'me' : user.id}
                  username={user.username}
                  onClearAllChange={setClearAllAppData}
                />
              )}
            </TabsPanel>
          )}
        </Tabs>

        <Group
          justify="flex-end"
          className={`${editorClasses.footer} ${editorClasses.plainFooter}`}
        >
          {activeTab === 'app-data' && clearAllAppData && (
            <Button
              type="button"
              variant="light"
              color="red"
              size="sm"
              leftSection={<Trash2 size={16} />}
              onClick={clearAllAppData.clear}
            >
              Clear all
            </Button>
          )}
          <Button
            type="submit"
            variant="filled"
            disabled={form.submitting}
            size="sm"
          >
            {user?.id ? 'Save' : 'Create'}
          </Button>
        </Group>
      </form>
    </Modal>
  );
};

export default User;
