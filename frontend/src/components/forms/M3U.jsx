// Modal.js
import { useState, useEffect } from 'react';
import API from '../../api';
import useUserAgentsStore from '../../store/userAgents';
import useServerGroupsStore from '../../store/serverGroups';
import usePlaylistsStore from '../../store/playlists';
import M3UProfiles from './M3UProfiles';
import {
  LoadingOverlay,
  MultiSelect,
  TextInput,
  Button,
  Alert,
  Checkbox,
  Modal,
  Flex,
  Select,
  FileInput,
  NumberInput,
  Divider,
  Stack,
  Group,
  Switch,
  Box,
  PasswordInput,
  Collapse,
  Text
} from '@mantine/core';
import M3UGroupFilter from './M3UGroupFilter';
import useChannelsStore from '../../store/channels';
import { notifications } from '@mantine/notifications';
import { isNotEmpty, useForm } from '@mantine/form';
import useEPGsStore from '../../store/epgs';
import useVODStore from '../../store/useVODStore';
import M3UFilters from './M3UFilters';
import ScheduleInput from './ScheduleInput';
import { DateTimePicker } from '@mantine/dates';
import { showNotification } from '../../utils/notificationUtils.js';
import { addEPG } from '../../utils/forms/DummyEpgUtils.js';
import {
  addPlaylist,
  expDateFromPlaylist,
  expDateKey,
  getPlaylist,
  prepareSubmitValues,
  updatePlaylist,
} from '../../utils/forms/M3uUtils.js';
import { M3U_HASH_KEY_OPTIONS } from '../../utils/m3uHashKey.js';
import ServerGroupsManagerModal from '../ServerGroupsManagerModal';
import { useDateTimeFormat } from '../../utils/dateTimeUtils.js';

const M3U = ({
  m3uAccount = null,
  isOpen,
  onClose,
  playlistCreated = false,
}) => {
  const userAgents = useUserAgentsStore((s) => s.userAgents);
  const serverGroups = useServerGroupsStore((s) => s.serverGroups);
  const fetchChannelGroups = useChannelsStore((s) => s.fetchChannelGroups);
  const fetchEPGs = useEPGsStore((s) => s.fetchEPGs);
  const fetchCategories = useVODStore((s) => s.fetchCategories);

  const [playlist, setPlaylist] = useState(null);
  const [file, setFile] = useState(null);
  const [expDate, setExpDate] = useState(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [groupFilterModalOpen, setGroupFilterModalOpen] = useState(false);
  const [filterModalOpen, setFilterModalOpen] = useState(false);
  const loadingText = '';
  const [showCredentialFields, setShowCredentialFields] = useState(false);
  const [scheduleType, setScheduleType] = useState('interval');
  const [showAdvancedDeviceFields, setShowAdvancedDeviceFields] = useState(false);
  const [serverGroupsManagerOpen, setServerGroupsManagerOpen] = useState(false);
  const [hasHashKeyOverride, setHasHashKeyOverride] = useState(false);
  const [serverGroupsCreateOnOpen, setServerGroupsCreateOnOpen] =
    useState(false);

  const { timeFormat: timeformat, dateYearFormat } = useDateTimeFormat();

  // Keep expiration in sync when the default profile is edited (store refreshes).
  // Do not rebind the whole form to the live playlist or unsaved edits are wiped.
  const accountId = playlist?.id ?? m3uAccount?.id;
  const storeExpDate = usePlaylistsStore((s) => {
    if (!accountId) return undefined;
    const stored = s.playlists.find((p) => p.id === accountId);
    if (!stored) return undefined;
    return stored.exp_date ?? null;
  });

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      name: '',
      server_url: '',
      user_agent: '0',
      server_group: '0',
      is_active: true,
      max_streams: 0,
      refresh_interval: 24,
      cron_expression: '',
      account_type: 'XC',
      create_epg: false,
      username: '',
      password: '',
      mac: '',
      model: '',
      serial_number: '',
      device_id: '',
      device_id2: '',
      signature: '',
      timezone: '',
      stale_stream_days: 7,
      priority: 0,
      enable_vod: false,
      hash_key: [],
    },

    validate: {
      name: isNotEmpty('Please select a name'),
      user_agent: isNotEmpty('Please select a user-agent'),
    },
  });

  useEffect(() => {
    if (m3uAccount) {
      setPlaylist(m3uAccount);
      form.setValues({
        name: m3uAccount.name,
        server_url: m3uAccount.server_url,
        max_streams: m3uAccount.max_streams,
        user_agent: m3uAccount.user_agent ? `${m3uAccount.user_agent}` : '0',
        server_group: m3uAccount.server_group
          ? `${m3uAccount.server_group}`
          : '0',
        is_active: m3uAccount.is_active,
        refresh_interval: m3uAccount.refresh_interval,
        cron_expression: m3uAccount.cron_expression || '',
        account_type: m3uAccount.account_type,
        username: m3uAccount.username ?? '',
        password: '',
        mac: m3uAccount.mac ?? '',
        model: m3uAccount.model ?? '',
        serial_number: m3uAccount.serial_number ?? '',
        device_id: m3uAccount.device_id ?? '',
        device_id2: m3uAccount.device_id2 ?? '',
        signature: m3uAccount.signature ?? '',
        timezone: m3uAccount.timezone ?? '',
        stale_stream_days:
          m3uAccount.stale_stream_days !== undefined &&
          m3uAccount.stale_stream_days !== null
            ? m3uAccount.stale_stream_days
            : 7,
        priority:
          m3uAccount.priority !== undefined && m3uAccount.priority !== null
            ? m3uAccount.priority
            : 0,
        enable_vod: m3uAccount.enable_vod || false,
        hash_key: m3uAccount.hash_key
          ? m3uAccount.hash_key.split(',').filter(Boolean)
          : [],
      });
      setHasHashKeyOverride(
        !!(
          m3uAccount.hash_key &&
          m3uAccount.hash_key.split(',').filter(Boolean).length
        )
      );
      setExpDate(expDateFromPlaylist(m3uAccount.exp_date));

      // Determine schedule type from existing data
      setScheduleType(
        m3uAccount.cron_expression && m3uAccount.cron_expression.trim() !== ''
          ? 'cron'
          : 'interval'
      );

      setShowCredentialFields(
        m3uAccount.account_type === 'XC' ||
          m3uAccount.account_type === 'STALKER'
      );
      setShowAdvancedDeviceFields(
        Boolean(
          m3uAccount.model ||
            m3uAccount.serial_number ||
            m3uAccount.device_id ||
            m3uAccount.device_id2 ||
            m3uAccount.signature ||
            m3uAccount.timezone
        )
      );
    } else {
      setPlaylist(null);
      form.reset();
      setScheduleType('interval');
      setExpDate(null);
      setShowCredentialFields(false);
      setShowAdvancedDeviceFields(false);
      setHasHashKeyOverride(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m3uAccount]);

  useEffect(() => {
    setShowCredentialFields(
      form.values.account_type === 'XC' ||
        form.values.account_type === 'STALKER'
    );
    if (form.values.account_type !== 'STD') {
      setFile(null);
    }
    if (form.values.account_type !== 'STALKER') {
      setShowAdvancedDeviceFields(false);
    }
  }, [form.values.account_type]);

  useEffect(() => {
    if (storeExpDate === undefined) return;
    const next = expDateFromPlaylist(storeExpDate);
    setExpDate((prev) =>
      expDateKey(prev) === expDateKey(next) ? prev : next
    );
  }, [storeExpDate]);

  const handleNewPlaylist = async (newPlaylist, values, create_epg) => {
    if (create_epg && values.account_type === 'XC') {
      addEPG({
        name: values.name,
        source_type: 'xmltv',
        url: `${new URL(values.server_url).origin}/xmltv.php?username=${values.username}&password=${values.password}`,
        api_key: '',
        is_active: true,
        refresh_interval: 24,
      });
    }

    if (values.account_type === 'STD') {
      showNotification({
        title: 'Fetching M3U Groups',
        message:
          'Configure group filters and auto sync settings once complete.',
      });
      close();
      return;
    }

    // Fetch the updated playlist details (this also updates the store via API).
    // We don't call fetchPlaylists() here because addPlaylist() already added
    // the playlist to the store; refetching races with the websocket updates
    // arriving for the new playlist's refresh task.
    const updatedPlaylist = await getPlaylist(newPlaylist);
    await Promise.all([fetchChannelGroups(), fetchEPGs()]);

    if (
      (values.account_type === 'XC' || values.account_type === 'STALKER') &&
      values.enable_vod
    ) {
      await fetchCategories({ includeEmpty: true });
    }

    setPlaylist(updatedPlaylist);

    const hasLiveSetupData = (updatedPlaylist?.channel_groups || []).length > 0;
    const hasVodSetupData =
      values.enable_vod &&
      Object.values(useVODStore.getState().categories || {}).some((category) =>
        (category.m3u_accounts || []).some(
          (account) => account.m3u_account == updatedPlaylist.id
        )
      );

    if (values.account_type === 'XC' || hasLiveSetupData || hasVodSetupData) {
      setGroupFilterModalOpen(true);
    }
  };

  const onSubmit = async () => {
    const { create_epg, ...rawValues } = form.getValues();
    const values = prepareSubmitValues(rawValues, expDate);

    if (playlist?.id) {
      const updated = await updatePlaylist(playlist, values, file);
      if (updated) {
        setPlaylist(updated);
      }
      form.reset();
      setFile(null);
      onClose(updated);
      return;
    }

    const newPlaylist = await addPlaylist(values, file);
    await handleNewPlaylist(newPlaylist, values, create_epg);
  };

  const close = () => {
    form.reset();
    setFile(null);
    setPlaylist(null);
    onClose();
  };

  const closeGroupFilter = () => {
    setGroupFilterModalOpen(false);
    // After group filter setup for a new account, reset everything
    form.reset();
    setFile(null);
    setPlaylist(null);
    onClose();
  };

  const closeFilter = () => {
    setFilterModalOpen(false);
  };

  useEffect(() => {
    if (playlistCreated) {
      setGroupFilterModalOpen(true);
    }
  }, [playlist, playlistCreated]);

  if (!isOpen) {
    return <></>;
  }

  const accountType = form.getValues().account_type;
  const isXC = accountType === 'XC';
  const isStalker = accountType === 'STALKER';
  const isStandard = accountType === 'STD';

  return (
    <>
      <Modal
        size={700}
        opened={isOpen}
        onClose={close}
        title="M3U Account"
        scrollAreaComponent={Modal.NativeScrollArea}
        lockScroll={false}
        withinPortal={true}
        trapFocus={false}
        yOffset="2vh"
      >
        <LoadingOverlay
          visible={form.submitting}
          overlayBlur={2}
          loaderProps={loadingText ? { children: loadingText } : {}}
        />

        <form onSubmit={form.onSubmit(onSubmit)}>
          <Group justify="space-between" align="top">
            <Stack gap="5" style={{ flex: 1 }}>
              <TextInput
                style={{ width: '100%' }}
                id="name"
                name="name"
                label="Name"
                description="Unique identifier for this M3U account"
                {...form.getInputProps('name')}
                key={form.key('name')}
              />
              <TextInput
                style={{ width: '100%' }}
                id="server_url"
                name="server_url"
                label={isStalker ? 'Portal URL' : 'URL'}
                description={
                  isStalker
                    ? 'Base Stalker portal URL'
                    : 'Direct URL to the M3U playlist or server'
                }
                {...form.getInputProps('server_url')}
                key={form.key('server_url')}
              />

              <Select
                id="account_type"
                name="account_type"
                label="Account Type"
                description={
                  <>
                    Standard for direct M3U URLs, <br />
                    Xtream Codes for panel-based services, <br />
                    Stalker for portal-based live TV services
                  </>
                }
                data={[
                  {
                    value: 'STD',
                    label: 'Standard',
                  },
                  {
                    value: 'XC',
                    label: 'Xtream Codes',
                  },
                  {
                    value: 'STALKER',
                    label: 'Stalker',
                  },
                ]}
                key={form.key('account_type')}
                {...form.getInputProps('account_type')}
              />

              {(isXC || isStalker) && (
                <Box>
                  {isXC && !m3uAccount && (
                    <Group justify="space-between">
                      <Box>Create EPG</Box>
                      <Switch
                        id="create_epg"
                        name="create_epg"
                        description="Automatically create matching EPG source for this Xtream account"
                        key={form.key('create_epg')}
                        {...form.getInputProps('create_epg', {
                          type: 'checkbox',
                        })}
                      />
                    </Group>
                  )}

                  <Group justify="space-between">
                    <Box>Enable VOD Scanning</Box>
                    <Switch
                      id="enable_vod"
                      name="enable_vod"
                      description="Scan and import VOD content (movies/series) from this provider account"
                      key={form.key('enable_vod')}
                      {...form.getInputProps('enable_vod', {
                        type: 'checkbox',
                      })}
                    />
                  </Group>

                  {isXC && (
                    <>
                      <TextInput
                        id="username"
                        name="username"
                        label="Username"
                        description="Username for Xtream Codes authentication"
                        {...form.getInputProps('username')}
                      />

                      <PasswordInput
                        id="password"
                        name="password"
                        label="Password"
                        description="Password for Xtream Codes authentication (leave empty to keep existing)"
                        {...form.getInputProps('password')}
                      />
                    </>
                  )}
                </Box>
              )}

              {isStalker && (
                <Stack gap="sm">
                  <TextInput
                    id="mac"
                    name="mac"
                    label="MAC Address"
                    description="Portal device MAC address"
                    placeholder="00:1A:79:00:00:00"
                    {...form.getInputProps('mac')}
                  />

                  {showCredentialFields && (
                    <>
                      <TextInput
                        id="username"
                        name="username"
                        label="Username"
                        description="Optional portal username"
                        {...form.getInputProps('username')}
                      />

                      <PasswordInput
                        id="password"
                        name="password"
                        label="Password"
                        description="Optional portal password"
                        {...form.getInputProps('password')}
                      />
                    </>
                  )}

                  <Button
                    type="button"
                    variant="subtle"
                    size="xs"
                    style={{ alignSelf: 'flex-start' }}
                    onClick={() =>
                      setShowAdvancedDeviceFields((current) => !current)
                    }
                  >
                    {showAdvancedDeviceFields
                      ? 'Hide Advanced Device Fields'
                      : 'Show Advanced Device Fields'}
                  </Button>

                  <Collapse in={showAdvancedDeviceFields}>
                    <Stack gap="sm">
                      <TextInput
                        id="model"
                        name="model"
                        label="Model"
                        description="Optional device model"
                        {...form.getInputProps('model')}
                      />
                      <TextInput
                        id="serial_number"
                        name="serial_number"
                        label="Serial Number"
                        description="Optional device serial number"
                        {...form.getInputProps('serial_number')}
                      />
                      <TextInput
                        id="device_id"
                        name="device_id"
                        label="Device ID"
                        description="Optional device identifier"
                        {...form.getInputProps('device_id')}
                      />
                      <TextInput
                        id="device_id2"
                        name="device_id2"
                        label="Device ID 2"
                        description="Optional secondary device identifier"
                        {...form.getInputProps('device_id2')}
                      />
                      <TextInput
                        id="signature"
                        name="signature"
                        label="Signature"
                        description="Optional device signature"
                        {...form.getInputProps('signature')}
                      />
                      <TextInput
                        id="timezone"
                        name="timezone"
                        label="Timezone"
                        description="Optional portal timezone"
                        {...form.getInputProps('timezone')}
                      />
                    </Stack>
                  </Collapse>

                  {playlist?.last_message && playlist.status === 'error' && (
                    <Alert
                      color="red"
                      variant="light"
                    >
                      <Text size="sm">{playlist.last_message}</Text>
                    </Alert>
                  )}
                </Stack>
              )}

              {isStandard && (
                <>
                  <FileInput
                    id="file"
                    label="Upload files"
                    placeholder="Upload files"
                    description="Upload a local M3U file instead of using URL"
                    onChange={setFile}
                  />

                  <DateTimePicker
                    label="Expiration Date"
                    description="Set an expiration date to receive a warning notification"
                    placeholder="No expiration"
                    clearable
                    valueFormat={`${dateYearFormat} ${timeformat}`}
                    value={expDate}
                    onChange={(v) => setExpDate(v ? new Date(v) : null)}
                  />
                </>
              )}
            </Stack>

            <Divider size="sm" orientation="vertical" />

            <Stack gap="5" style={{ flex: 1 }}>
              <NumberInput
                style={{ width: '100%' }}
                id="max_streams"
                name="max_streams"
                label="Max Streams"
                placeholder="0 = Unlimited"
                description="Maximum number of concurrent streams (0 for unlimited)"
                min={0}
                {...form.getInputProps('max_streams')}
                key={form.key('max_streams')}
              />

              <Select
                id="server_group"
                name="server_group"
                label="Server Group"
                description="Share login limits across accounts in a server group. Set max streams on each profile (unlimited profiles skip group enforcement)."
                key={form.key('server_group')}
                value={form.getValues().server_group}
                onChange={(value) => {
                  if (value === '__new__') {
                    setServerGroupsCreateOnOpen(true);
                    setServerGroupsManagerOpen(true);
                    return;
                  }
                  form.setFieldValue('server_group', value);
                }}
                data={[
                  { value: '0', label: '(None)' },
                  ...serverGroups.map((group) => ({
                    label: group.name,
                    value: `${group.id}`,
                  })),
                  { value: '__new__', label: '+ Add server group...' },
                ]}
              />

              <Button
                variant="subtle"
                size="compact-xs"
                onClick={() => {
                  setServerGroupsCreateOnOpen(false);
                  setServerGroupsManagerOpen(true);
                }}
                style={{ alignSelf: 'flex-start' }}
              >
                Manage server groups
              </Button>

              <Select
                id="user_agent"
                name="user_agent"
                label="User-Agent"
                description="User-Agent header to use when accessing this M3U source"
                {...form.getInputProps('user_agent')}
                key={form.key('user_agent')}
                data={[{ value: '0', label: '(Use Default)' }].concat(
                  userAgents.map((ua) => ({
                    label: ua.name,
                    value: `${ua.id}`,
                  }))
                )}
              />
              <MultiSelect
                id="hash_key"
                name="hash_key"
                label="Hash Key Override"
                description="Fields used to identify this account's streams. Empty inherits the global default. Changing this rehashes only this account."
                placeholder={
                  hasHashKeyOverride ? undefined : 'Use global default'
                }
                clearable
                data={M3U_HASH_KEY_OPTIONS}
                {...form.getInputProps('hash_key')}
                onChange={(value) => {
                  form.getInputProps('hash_key').onChange(value);
                  setHasHashKeyOverride(!!(value && value.length));
                }}
                key={form.key('hash_key')}
              />

              <ScheduleInput
                scheduleType={scheduleType}
                onScheduleTypeChange={setScheduleType}
                intervalValue={form.getValues().refresh_interval}
                onIntervalChange={(v) =>
                  form.setFieldValue('refresh_interval', v)
                }
                cronValue={form.getValues().cron_expression}
                onCronChange={(expr) =>
                  form.setFieldValue('cron_expression', expr)
                }
                intervalLabel="Refresh Interval (hours)"
                intervalDescription={
                  <>
                    How often to automatically refresh M3U data
                    <br />
                    (0 to disable automatic refreshes)
                  </>
                }
              />

              <NumberInput
                min={0}
                max={365}
                label="Stale Stream Retention (days)"
                description="Streams not seen for this many days will be removed"
                {...form.getInputProps('stale_stream_days')}
              />

              <NumberInput
                min={0}
                max={999}
                label="VOD Priority"
                description="Priority for VOD provider selection (higher numbers = higher priority). Used when multiple providers offer the same content."
                {...form.getInputProps('priority')}
                key={form.key('priority')}
                disabled={!isXC && !isStalker}
              />

              <Checkbox
                label="Is Active"
                description="Enable or disable this M3U account"
                {...form.getInputProps('is_active', { type: 'checkbox' })}
                key={form.key('is_active')}
              />
            </Stack>
          </Group>

          <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
            {playlist && (
              <>
                <Button
                  variant="filled"
                  size="sm"
                  onClick={() => setFilterModalOpen(true)}
                >
                  Filters
                </Button>
                <Button
                  variant="filled"
                  size="sm"
                  onClick={() => {
                    if (
                      (playlist?.account_type === 'XC' ||
                        playlist?.account_type === 'STALKER') &&
                      playlist?.enable_vod
                    ) {
                      fetchCategories({ includeEmpty: true });
                    }
                    setGroupFilterModalOpen(true);
                  }}
                >
                  Groups
                </Button>
                <Button
                  variant="filled"
                  size="sm"
                  onClick={() => setProfileModalOpen(true)}
                >
                  Profiles
                </Button>
              </>
            )}

            <Button
              type="submit"
              variant="filled"
              disabled={form.submitting}
              size="sm"
            >
              Save
            </Button>
          </Flex>
        </form>
      </Modal>
      {playlist && (
        <>
          <M3UProfiles
            playlist={playlist}
            isOpen={profileModalOpen}
            onClose={() => setProfileModalOpen(false)}
            pendingExpDate={expDate}
          />
          <M3UGroupFilter
            isOpen={groupFilterModalOpen}
            playlist={playlist}
            onClose={closeGroupFilter}
          />
          <M3UFilters
            isOpen={filterModalOpen}
            playlist={playlist}
            onClose={closeFilter}
          />
        </>
      )}
      <ServerGroupsManagerModal
        isOpen={serverGroupsManagerOpen}
        onClose={() => {
          setServerGroupsManagerOpen(false);
          setServerGroupsCreateOnOpen(false);
        }}
        openCreateOnMount={serverGroupsCreateOnOpen}
        onGroupCreated={(group) => {
          if (group?.id) {
            form.setFieldValue('server_group', `${group.id}`);
          }
        }}
      />
    </>
  );
};

export default M3U;
