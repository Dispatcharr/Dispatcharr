// Modal.js
import React, { useEffect, useRef, useState } from 'react';
import useUserAgentsStore from '../../store/userAgents';
import useServerGroupsStore from '../../store/serverGroups';
import usePlaylistsStore from '../../store/playlists';
import M3UProfiles from './M3UProfiles';
import {
  Button,
  FileInput,
  Flex,
  Group,
  LoadingOverlay,
  Modal,
  MultiSelect,
  NumberInput,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  Text,
  Tooltip,
} from '@mantine/core';
import {
  SensitiveTextInput as TextInput,
  SensitivePasswordInput as PasswordInput,
} from '../SensitiveFields.jsx';
import M3UGroupFilter from './M3UGroupFilter';
import { isNotEmpty, useForm } from '@mantine/form';
import ScheduleInput from './ScheduleInput';
import { DateTimePicker } from '@mantine/dates';
import {
  addPlaylist,
  expDateFromPlaylist,
  expDateKey,
  prepareSubmitValues,
  updatePlaylist,
} from '../../utils/forms/M3uUtils.js';
import { M3U_HASH_KEY_OPTIONS } from '../../utils/m3uHashKey.js';
import ServerGroupsManagerModal from '../ServerGroupsManagerModal';
import {
  useDateTimeFormat,
  useTimeHelpers,
} from '../../utils/dateTimeUtils.js';
import editorClasses from './AccountEditor.module.css';
import ConfirmationDialog from '../ConfirmationDialog.jsx';
import StackedModal from '../StackedModal.jsx';
import M3USetupSteps from './M3USetupSteps.jsx';
import {
  getM3UConnectionDetails,
  getM3USourceType,
  getM3UStreamLabel,
  needsM3UConnectionCheck,
  prepareM3USourceValues,
  validateNewM3UAccount,
} from '../../utils/forms/M3uSetupUtils.js';
import { Upload } from 'lucide-react';
import M3UAccountEPG from './M3UAccountEPG.jsx';
import M3UAccountCategories from './M3UAccountCategories.jsx';
import API from '../../api.js';

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

const ScheduleStatus = ({ schedule, lastCompleted, formatDate, nextLabel }) => (
  <Text size="xs" c="dimmed">
    Last: {lastCompleted ? formatDate(lastCompleted) : 'Never'} · Next:{' '}
    {nextLabel ||
      (schedule?.enabled
        ? schedule.next_run_at
          ? formatDate(schedule.next_run_at)
          : 'Unavailable'
        : 'Not scheduled')}
  </Text>
);

const newAccountValues = () => ({
  name: '',
  server_url: '',
  user_agent: '0',
  server_group: '0',
  is_active: true,
  max_streams: 0,
  refresh_interval: 24,
  cron_expression: '',
  vod_refresh_interval: 0,
  vod_cron_expression: '',
  vod_refresh_after_live: true,
  account_type: 'XC',
  username: '',
  password: '',
  stale_stream_days: 7,
  priority: 0,
  enable_vod: false,
  hash_key: [],
});

const M3U = ({
  m3uAccount = null,
  isOpen,
  onClose,
  onSaved,
  playlistCreated = false,
  setupMode = false,
  setupBusy = false,
  onSetupNext,
  onSetupBack,
}) => {
  const userAgents = useUserAgentsStore((s) => s.userAgents);
  const serverGroups = useServerGroupsStore((s) => s.serverGroups);

  const [playlist, setPlaylist] = useState(null);
  const [file, setFile] = useState(null);
  const [expDate, setExpDate] = useState(null);
  const [groupFilterModalOpen, setGroupFilterModalOpen] = useState(false);
  const [categoryPlaylist, setCategoryPlaylist] = useState(null);
  const [profileOverlayOpen, setProfileOverlayOpen] = useState(false);
  const [epgOverlayOpen, setEPGOverlayOpen] = useState(false);
  const [scheduleType, setScheduleType] = useState('interval');
  const [vodScheduleType, setVodScheduleType] = useState('interval');
  const [vodEnabled, setVodEnabled] = useState(false);
  const [vodRefreshAfterLive, setVodRefreshAfterLive] = useState(true);
  const [accountType, setAccountType] = useState('XC');
  const [sourceType, setSourceType] = useState('XC');
  const [serverGroupsManagerOpen, setServerGroupsManagerOpen] = useState(false);
  const [hasHashKeyOverride, setHasHashKeyOverride] = useState(false);
  const [activeTab, setActiveTab] = useState('account');
  const [contentAvailable, setContentAvailable] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [checkingConnection, setCheckingConnection] = useState(false);
  const [connectionFailure, setConnectionFailure] = useState(null);
  const checkingConnectionRef = useRef(false);
  const submitAttemptRef = useRef(false);
  const approvedConnection = useRef(null);
  const creatingRef = useRef(false);
  const initializedSetupAccount = useRef(null);
  const savedSourceType = useRef('XC');
  const savedExpiration = useRef(null);
  const [serverGroupsCreateOnOpen, setServerGroupsCreateOnOpen] =
    useState(false);

  const {
    timeFormat: timeformat,
    dateYearFormat,
    fullDateTimeFormat,
  } = useDateTimeFormat();
  const { toUserTime } = useTimeHelpers();

  // Keep expiration in sync when the default profile is edited (store refreshes).
  // Do not rebind the whole form to the live playlist or unsaved edits are wiped.
  const accountId = playlist?.id ?? m3uAccount?.id;
  const storedAccount = usePlaylistsStore((s) =>
    s.playlists.find((p) => p.id === accountId)
  );
  const statusPlaylist = storedAccount || playlist;
  const storeExpDate = usePlaylistsStore((s) => {
    if (!accountId) return undefined;
    const stored = s.playlists.find((p) => p.id === accountId);
    if (!stored) return undefined;
    return stored.exp_date ?? null;
  });

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: newAccountValues(),

    validate: {
      name: isNotEmpty('Please select a name'),
      user_agent: isNotEmpty('Please select a user-agent'),
    },
  });

  useEffect(() => {
    if (!isOpen) {
      initializedSetupAccount.current = null;
      return;
    }
    if (setupMode && initializedSetupAccount.current === m3uAccount?.id) {
      setActiveTab(m3uAccount.setup_step);
      return;
    }
    initializedSetupAccount.current = setupMode ? m3uAccount?.id : null;
    setFile(null);
    setCategoryPlaylist(null);
    setActiveTab(setupMode ? m3uAccount.setup_step : 'account');
    setContentAvailable(false);
    setDiscardOpen(false);
    setConnectionFailure(null);
    approvedConnection.current = null;
    savedSourceType.current = m3uAccount ? getM3USourceType(m3uAccount) : 'XC';
    savedExpiration.current = expDateKey(m3uAccount?.exp_date);
    if (m3uAccount) {
      setPlaylist(m3uAccount);
      setAccountType(m3uAccount.account_type);
      setSourceType(getM3USourceType(m3uAccount));
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
        vod_refresh_interval: m3uAccount.vod_refresh_interval ?? 0,
        vod_cron_expression: m3uAccount.vod_cron_expression || '',
        vod_refresh_after_live: m3uAccount.vod_refresh_after_live !== false,
        account_type: m3uAccount.account_type,
        username: m3uAccount.username ?? '',
        password: '',
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
      form.resetDirty();
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
      setVodScheduleType(
        m3uAccount.vod_cron_expression?.trim() ? 'cron' : 'interval'
      );
      setVodEnabled(Boolean(m3uAccount.enable_vod));
      setVodRefreshAfterLive(m3uAccount.vod_refresh_after_live !== false);
    } else {
      setPlaylist(null);
      setAccountType('XC');
      setSourceType('XC');
      // Editing changes Mantine's reset snapshot; a new account needs its own.
      form.setInitialValues(newAccountValues());
      form.reset();
      setScheduleType('interval');
      setVodScheduleType('interval');
      setVodEnabled(false);
      setVodRefreshAfterLive(true);
      setExpDate(null);
      setHasHashKeyOverride(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m3uAccount, isOpen, setupMode]);

  useEffect(() => {
    if (storeExpDate === undefined) return;
    const next = expDateFromPlaylist(storeExpDate);
    savedExpiration.current = expDateKey(next);
    setExpDate((prev) => (expDateKey(prev) === expDateKey(next) ? prev : next));
  }, [storeExpDate]);

  const connectionKey = () =>
    JSON.stringify(
      getM3UConnectionDetails(form.getValues(), sourceType, playlist)
    );

  const checkConnection = async (intent) => {
    const values = form.getValues();
    if (!needsM3UConnectionCheck(values, sourceType, playlist)) return true;
    const details = getM3UConnectionDetails(values, sourceType, playlist);
    const key = JSON.stringify(details);
    if (approvedConnection.current === key) return true;
    checkingConnectionRef.current = true;
    setCheckingConnection(true);
    try {
      const result = await API.checkM3UConnection(details);
      // A result belongs only to the exact connection that was checked.
      if (key !== connectionKey()) return false;
      if (result?.success === true) {
        approvedConnection.current = key;
        return true;
      }
      setConnectionFailure({
        intent,
        key,
        message: result?.message || 'The connection could not be verified.',
      });
      return false;
    } catch {
      if (key === connectionKey())
        setConnectionFailure({
          intent,
          key,
          message:
            'The connection check could not be completed. Try again or continue without a verified connection.',
        });
      return false;
    } finally {
      checkingConnectionRef.current = false;
      setCheckingConnection(false);
    }
  };

  const next = async () => {
    if (checkingConnectionRef.current || creatingRef.current) return false;
    const errors = validateNewM3UAccount(form.getValues(), file, {
      sourceType,
    });
    form.setErrors(errors);
    if (Object.keys(errors).length) return false;
    if (!(await checkConnection('next'))) return false;
    setContentAvailable(true);
    setActiveTab('content');
    return true;
  };

  const onSubmit = async () => {
    if (
      creatingRef.current ||
      checkingConnectionRef.current ||
      submitAttemptRef.current
    )
      return;
    submitAttemptRef.current = true;
    try {
      if (!playlist?.id && activeTab === 'account') {
        await next();
        return;
      }
      const errors = validateNewM3UAccount(form.getValues(), file, {
        sourceType,
        existingAccount: playlist,
      });
      form.setErrors(errors);
      if (Object.keys(errors).length) {
        if (setupMode && activeTab === 'content') await onSetupBack();
        else setActiveTab('account');
        return;
      }
      if (!(await checkConnection('save'))) return;
      const rawValues = form.getValues();
      const values = prepareM3USourceValues(
        prepareSubmitValues(rawValues, expDate),
        sourceType
      );
      const selectedFile = sourceType === 'M3U_FILE' ? file : null;

      if (playlist?.id) {
        // Enabled is controlled in the overview, not by a stale editor snapshot.
        delete values.is_active;
        creatingRef.current = true;
        setCreating(true);
        try {
          const updatedPlaylist = await updatePlaylist(
            playlist,
            values,
            selectedFile
          );
          if (!updatedPlaylist?.id) return;
          setFile(null);
          if (setupMode) {
            setPlaylist(updatedPlaylist);
            form.resetDirty();
            savedSourceType.current = sourceType;
            savedExpiration.current = expDateKey(expDate);
            await onSetupNext(updatedPlaylist);
          } else {
            form.reset();
            if (onSaved) onSaved(updatedPlaylist);
            else onClose();
          }
        } finally {
          creatingRef.current = false;
          setCreating(false);
        }
        return;
      }

      creatingRef.current = true;
      setCreating(true);
      try {
        const newPlaylist = await addPlaylist(
          { ...values, start_setup: true },
          selectedFile
        );
        if (!newPlaylist?.id) return;
        form.reset();
        setFile(null);
        onClose(newPlaylist);
      } finally {
        creatingRef.current = false;
        setCreating(false);
      }
    } finally {
      submitAttemptRef.current = false;
    }
  };

  const close = () => {
    form.reset();
    setFile(null);
    setPlaylist(null);
    setActiveTab('account');
    setContentAvailable(false);
    setExpDate(null);
    setDiscardOpen(false);
    onClose();
  };

  const closeGroupFilter = () => {
    setGroupFilterModalOpen(false);
    setCategoryPlaylist(null);
  };

  const requestClose = () => {
    if (
      creatingRef.current ||
      submitAttemptRef.current ||
      checkingConnectionRef.current ||
      creating ||
      setupBusy ||
      form.submitting ||
      connectionFailure
    )
      return;
    if (setupMode || hasUnsavedChanges()) {
      setDiscardOpen(true);
      return;
    }
    close();
  };

  const hasUnsavedChanges = () =>
    form.isDirty() ||
    !!file ||
    sourceType !== savedSourceType.current ||
    expDateKey(expDate) !== savedExpiration.current;

  useEffect(() => {
    if (playlistCreated) {
      setGroupFilterModalOpen(true);
    }
  }, [playlist, playlistCreated]);

  if (!isOpen) {
    return <></>;
  }

  const streamLabel = getM3UStreamLabel(accountType);

  const unsavedSetupChanges = setupMode && hasUnsavedChanges();

  return (
    <Modal.Stack>
      <StackedModal
        stackId="m3u-account-editor"
        keepVisibleInStack
        size="68vw"
        opened={isOpen}
        onClose={requestClose}
        title={
          setupMode
            ? `Set up ${m3uAccount.name}`
            : m3uAccount?.id
              ? 'Edit M3U account'
              : 'Create M3U account'
        }
        closeButtonProps={{ 'aria-label': 'Close M3U account editor' }}
        classNames={{
          content: `${editorClasses.content} ${editorClasses.accountContent} ${editorClasses.m3uContent}`,
          body: editorClasses.body,
          header: editorClasses.header,
        }}
        lockScroll={false}
        withinPortal={true}
        trapFocus={
          !groupFilterModalOpen &&
          !serverGroupsManagerOpen &&
          !profileOverlayOpen &&
          !epgOverlayOpen &&
          !connectionFailure &&
          !discardOpen
        }
        closeOnEscape={
          !groupFilterModalOpen &&
          !serverGroupsManagerOpen &&
          !profileOverlayOpen &&
          !epgOverlayOpen &&
          !discardOpen &&
          !connectionFailure &&
          !checkingConnection &&
          !creating &&
          !setupBusy
        }
        yOffset="2vh"
        xOffset="3vw"
      >
        <LoadingOverlay
          visible={form.submitting || creating || checkingConnection}
          overlayBlur={2}
        />

        <form
          onSubmit={(event) => {
            if (event.target !== event.currentTarget) return;
            return form.onSubmit(onSubmit)(event);
          }}
          className={editorClasses.form}
        >
          {(!playlist?.id || setupMode) && (
            <M3USetupSteps
              stage={activeTab}
              accountType={accountType}
              contentAvailable={contentAvailable}
              onSelect={
                setupMode
                  ? undefined
                  : (stage) => {
                      if (
                        !creating &&
                        !checkingConnection &&
                        (stage === 'account' ||
                          (stage === 'content' && contentAvailable))
                      )
                        setActiveTab(stage);
                    }
              }
            />
          )}
          <Tabs
            value={activeTab}
            inert={checkingConnection || !!connectionFailure}
            onChange={(tab) => {
              if (!checkingConnection && !creating) setActiveTab(tab);
            }}
            className={`${editorClasses.tabs} ${editorClasses.accountTabs}`}
          >
            {playlist?.id && !setupMode && (
              <TabsList className={editorClasses.tabList}>
                <TabsTab value="account">Account</TabsTab>
                <TabsTab value="content">Settings</TabsTab>
                {accountType === 'XC' && playlist.account_type === 'XC' && (
                  <TabsTab value="epg">EPG</TabsTab>
                )}
                <TabsTab value="categories">Content</TabsTab>
                <TabsTab value="profiles">Profiles</TabsTab>
              </TabsList>
            )}
            <TabsPanel
              value="account"
              className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
              data-editor-active={activeTab === 'account'}
              aria-hidden={activeTab !== 'account'}
              inert={activeTab !== 'account'}
            >
              <SimpleGrid
                className={editorClasses.accountGrid}
                cols={{ base: 1, sm: 2 }}
                spacing="md"
                verticalSpacing="xs"
              >
                <Paper withBorder p="sm">
                  <Stack
                    gap={4}
                    style={{ minWidth: 0 }}
                    role="group"
                    aria-label="Account settings"
                  >
                    <Text fw={600}>Account</Text>
                    {playlist?.is_active === false && (
                      <Text size="xs" c="dimmed">
                        Disabled — enable this account from the overview.
                      </Text>
                    )}
                    <TextInput
                      id="name"
                      name="name"
                      label="Name"
                      withAsterisk={!playlist?.id}
                      {...form.getInputProps('name')}
                      key={form.key('name')}
                    />
                    <Select
                      id="account_type"
                      name="account_type"
                      label="Account Type"
                      data={[
                        { value: 'XC', label: 'Xtream Codes' },
                        { value: 'M3U_URL', label: 'M3U URL' },
                        { value: 'M3U_FILE', label: 'M3U File' },
                      ]}
                      allowDeselect={false}
                      value={sourceType}
                      onChange={(value) => {
                        if (!value) return;
                        const type = value === 'XC' ? 'XC' : 'STD';
                        form.setFieldValue('account_type', type);
                        form.clearErrors();
                        setAccountType(type);
                        setSourceType(value);
                        setContentAvailable(false);
                      }}
                    />

                    {sourceType !== 'M3U_FILE' && (
                      <TextInput
                        id="server_url"
                        name="server_url"
                        label="URL"
                        withAsterisk
                        placeholder={
                          accountType === 'XC'
                            ? 'Xtream Codes server URL'
                            : 'M3U playlist URL'
                        }
                        {...form.getInputProps('server_url')}
                        key={form.key('server_url')}
                      />
                    )}

                    {accountType === 'XC' && (
                      <>
                        <TextInput
                          id="username"
                          name="username"
                          label="Username"
                          withAsterisk={!playlist?.id}
                          {...form.getInputProps('username')}
                          key={form.key('username')}
                        />
                        <PasswordInput
                          id="password"
                          name="password"
                          label="Password"
                          withAsterisk={!playlist?.id}
                          placeholder={
                            playlist?.id
                              ? 'Leave empty to keep existing password'
                              : undefined
                          }
                          {...form.getInputProps('password')}
                          key={form.key('password')}
                        />
                      </>
                    )}

                    {sourceType === 'M3U_FILE' && (
                      <FileInput
                        id="file"
                        label="Playlist file"
                        aria-label="Playlist file"
                        withAsterisk={!playlist?.file_path}
                        clearable
                        value={file}
                        placeholder={
                          playlist?.file_path
                            ? `Current: ${playlist.file_path.split(/[\\/]/).pop()}`
                            : 'Choose a playlist file'
                        }
                        leftSection={<Upload size={16} aria-hidden="true" />}
                        leftSectionPointerEvents="none"
                        onChange={(value) => {
                          setFile(value);
                          form.clearFieldError('file');
                        }}
                        error={form.errors.file}
                        styles={{
                          input: {
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            display: 'block',
                          },
                        }}
                      />
                    )}
                    {accountType !== 'XC' && (
                      <DateTimePicker
                        label={helpLabel(
                          'Expiration Date',
                          'Set an expiration date to receive a warning notification.'
                        )}
                        aria-label="Expiration Date"
                        placeholder="No expiration"
                        clearable
                        valueFormat={`${dateYearFormat} ${timeformat}`}
                        value={expDate}
                        onChange={(v) => setExpDate(v ? new Date(v) : null)}
                      />
                    )}
                  </Stack>
                </Paper>

                <Paper withBorder p="sm">
                  <Stack
                    gap={4}
                    style={{ minWidth: 0 }}
                    role="group"
                    aria-label="Connection settings"
                  >
                    <Text fw={600}>Connection</Text>
                    <NumberInput
                      id="max_streams"
                      name="max_streams"
                      label={helpLabel(
                        'Max Streams',
                        'Maximum concurrent streams for the default connection profile. Use 0 for unlimited.'
                      )}
                      aria-label="Max Streams"
                      placeholder="0 = Unlimited"
                      min={0}
                      {...form.getInputProps('max_streams')}
                      key={form.key('max_streams')}
                    />
                    <Select
                      id="server_group"
                      name="server_group"
                      label={helpLabel(
                        'Server Group',
                        'Link M3U and XC accounts that belong to the same provider subscription so connection limits are tracked across all imported sources. Matching effective logins share the same counter; unlimited profiles are not restricted.'
                      )}
                      aria-label="Server Group"
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
                      label={helpLabel(
                        'User-Agent',
                        'User-Agent header used when accessing this M3U source.'
                      )}
                      aria-label="User-Agent"
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
                      label={helpLabel(
                        'Hash Key Override',
                        'Fields used to identify this account’s streams. Empty inherits the global default. Changing this rehashes only this account.'
                      )}
                      aria-label="Hash Key Override"
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
                  </Stack>
                </Paper>
              </SimpleGrid>
            </TabsPanel>
            <TabsPanel
              value="content"
              className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
              data-editor-active={activeTab === 'content'}
              aria-hidden={activeTab !== 'content'}
              inert={activeTab !== 'content'}
            >
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
                <Paper withBorder p="sm">
                  <Stack
                    gap={4}
                    style={{ minWidth: 0 }}
                    role="group"
                    aria-label={`${streamLabel} settings`}
                  >
                    <Text fw={600}>{streamLabel}</Text>
                    <NumberInput
                      min={0}
                      max={365}
                      label={helpLabel(
                        'Stale Stream Retention (days)',
                        'Streams not seen for this many days will be removed.'
                      )}
                      aria-label="Stale Stream Retention (days)"
                      {...form.getInputProps('stale_stream_days')}
                      key={form.key('stale_stream_days')}
                    />
                  </Stack>
                </Paper>

                <Paper
                  withBorder
                  p="sm"
                  display={accountType !== 'XC' ? 'none' : undefined}
                >
                  <Stack
                    gap={4}
                    style={{ minWidth: 0 }}
                    role="group"
                    aria-label="VOD settings"
                  >
                    <Group justify="space-between">
                      <Text fw={600}>VOD</Text>
                      <Tooltip
                        label="Import movies and series from this Xtream Codes account."
                        multiline
                        maw={320}
                        withArrow
                        events={{ hover: true, focus: true, touch: true }}
                      >
                        <span
                          style={{ display: 'inline-flex' }}
                          tabIndex={accountType !== 'XC' ? 0 : undefined}
                        >
                          <Switch
                            id="enable_vod"
                            name="enable_vod"
                            size="sm"
                            aria-label="Enable VOD"
                            disabled={accountType !== 'XC'}
                            checked={accountType === 'XC' && vodEnabled}
                            onChange={(event) => {
                              const enabled = event.currentTarget.checked;
                              setVodEnabled(enabled);
                              form.setFieldValue('enable_vod', enabled);
                            }}
                          />
                        </span>
                      </Tooltip>
                    </Group>
                    {accountType === 'XC' ? (
                      <NumberInput
                        min={0}
                        max={999}
                        label={helpLabel(
                          'VOD Priority',
                          'Higher numbers have higher priority when multiple providers offer the same VOD content.'
                        )}
                        aria-label="VOD Priority"
                        disabled={!vodEnabled}
                        {...form.getInputProps('priority')}
                        key={form.key('priority')}
                      />
                    ) : (
                      <Text size="sm" c="dimmed">
                        VOD scanning is available for Xtream Codes accounts
                        only.
                      </Text>
                    )}
                  </Stack>
                </Paper>

                <Paper withBorder p="sm">
                  <Stack
                    gap={4}
                    role="group"
                    aria-label={`${streamLabel} refresh schedule`}
                  >
                    <Text fw={600}>{streamLabel} refresh schedule</Text>
                    <ScheduleInput
                      scheduleType={scheduleType}
                      onScheduleTypeChange={setScheduleType}
                      intervalValue={form.getValues().refresh_interval}
                      onIntervalChange={(value) =>
                        form.setFieldValue('refresh_interval', value)
                      }
                      cronValue={form.getValues().cron_expression}
                      onCronChange={(value) =>
                        form.setFieldValue('cron_expression', value)
                      }
                      intervalLabel={`${streamLabel} refresh interval (hours)`}
                      intervalDescription={`Use 0 to disable automatic ${streamLabel} refreshes.`}
                    />
                    {playlist?.id && (
                      <ScheduleStatus
                        schedule={statusPlaylist?.live_refresh_schedule}
                        lastCompleted={
                          statusPlaylist?.custom_properties?.refresh_timings
                            ?.live_completed_at || statusPlaylist?.updated_at
                        }
                        formatDate={(value) =>
                          toUserTime(value).format(fullDateTimeFormat)
                        }
                      />
                    )}
                  </Stack>
                </Paper>

                <Paper
                  withBorder
                  p="sm"
                  display={accountType !== 'XC' ? 'none' : undefined}
                >
                  <Stack gap={4} role="group" aria-label="VOD refresh schedule">
                    <Group justify="space-between">
                      <Text fw={600}>VOD refresh schedule</Text>
                      <Tooltip
                        label={
                          accountType !== 'XC'
                            ? 'VOD refresh is available for Xtream Codes accounts only.'
                            : !vodEnabled
                              ? 'Enable VOD scanning to configure automatic VOD refreshes.'
                              : 'When disabled, VOD refresh runs after a successful scheduled Live TV refresh.'
                        }
                        multiline
                        maw={320}
                        withArrow
                        events={{ hover: true, focus: true, touch: true }}
                      >
                        <span
                          style={{ display: 'inline-flex' }}
                          tabIndex={
                            accountType !== 'XC' || !vodEnabled ? 0 : undefined
                          }
                        >
                          <Switch
                            size="sm"
                            aria-label="Enable separate VOD refresh schedule"
                            disabled={accountType !== 'XC' || !vodEnabled}
                            checked={
                              accountType === 'XC' && !vodRefreshAfterLive
                            }
                            onChange={(event) => {
                              const afterLive = !event.currentTarget.checked;
                              setVodRefreshAfterLive(afterLive);
                              form.setFieldValue(
                                'vod_refresh_after_live',
                                afterLive
                              );
                            }}
                          />
                        </span>
                      </Tooltip>
                    </Group>
                    {accountType === 'XC' && vodEnabled ? (
                      !vodRefreshAfterLive ? (
                        <ScheduleInput
                          scheduleType={vodScheduleType}
                          onScheduleTypeChange={setVodScheduleType}
                          intervalValue={form.getValues().vod_refresh_interval}
                          onIntervalChange={(value) =>
                            form.setFieldValue('vod_refresh_interval', value)
                          }
                          cronValue={form.getValues().vod_cron_expression}
                          onCronChange={(value) =>
                            form.setFieldValue('vod_cron_expression', value)
                          }
                          intervalLabel="VOD refresh interval (hours)"
                          intervalDescription="Use 0 to disable automatic VOD refreshes."
                        />
                      ) : (
                        <Text size="sm" c="dimmed">
                          VOD refreshes after a successful scheduled Live TV
                          refresh.
                        </Text>
                      )
                    ) : (
                      <Text size="sm" c="dimmed">
                        {accountType !== 'XC'
                          ? 'VOD refresh is available for Xtream Codes accounts only.'
                          : 'Enable VOD scanning to configure automatic VOD refreshes.'}
                      </Text>
                    )}
                    {playlist?.id && (
                      <ScheduleStatus
                        schedule={statusPlaylist?.vod_refresh_schedule}
                        lastCompleted={
                          statusPlaylist?.custom_properties?.refresh_timings
                            ?.vod_completed_at
                        }
                        formatDate={(value) =>
                          toUserTime(value).format(fullDateTimeFormat)
                        }
                        nextLabel={
                          statusPlaylist?.account_type === 'XC' &&
                          statusPlaylist?.enable_vod &&
                          statusPlaylist?.vod_refresh_after_live !== false &&
                          statusPlaylist?.live_refresh_schedule?.enabled
                            ? 'After Live TV refresh'
                            : undefined
                        }
                      />
                    )}
                  </Stack>
                </Paper>
              </SimpleGrid>
            </TabsPanel>
            <TabsPanel
              value="epg"
              className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
              data-editor-active={activeTab === 'epg'}
              aria-hidden={activeTab !== 'epg'}
              inert={activeTab !== 'epg'}
            >
              {playlist?.account_type === 'XC' &&
                accountType === 'XC' &&
                activeTab === 'epg' && (
                  <M3UAccountEPG
                    account={playlist}
                    onOverlayChange={setEPGOverlayOpen}
                  />
                )}
            </TabsPanel>
            <TabsPanel
              value="categories"
              className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
              data-editor-active={activeTab === 'categories'}
              aria-hidden={activeTab !== 'categories'}
              inert={activeTab !== 'categories'}
            >
              {playlist?.id && !setupMode && activeTab === 'categories' && (
                <M3UAccountCategories
                  account={storedAccount || playlist}
                  onEdit={(saved) => {
                    setCategoryPlaylist(saved);
                    setGroupFilterModalOpen(true);
                  }}
                />
              )}
            </TabsPanel>
            <TabsPanel
              value="profiles"
              className={`${editorClasses.panel} ${editorClasses.accountPanel}`}
              data-editor-active={activeTab === 'profiles'}
              aria-hidden={activeTab !== 'profiles'}
              inert={activeTab !== 'profiles'}
            >
              {playlist?.id && (
                <M3UProfiles
                  playlist={playlist}
                  embedded
                  pendingExpDate={expDate}
                  onOverlayChange={setProfileOverlayOpen}
                />
              )}
            </TabsPanel>
          </Tabs>

          <Flex
            component="footer"
            aria-label="M3U account actions"
            className={`${editorClasses.footer} ${editorClasses.plainFooter}`}
            gap="md"
            justify={!playlist?.id || setupMode ? 'space-between' : 'flex-end'}
            align="center"
            wrap="nowrap"
            mih={50}
          >
            {(!playlist?.id || setupMode) && (
              <div>
                {activeTab === 'content' && (
                  <Button
                    variant="default"
                    onClick={() =>
                      setupMode ? onSetupBack() : setActiveTab('account')
                    }
                    disabled={creating || setupBusy || checkingConnection}
                  >
                    Back
                  </Button>
                )}
              </div>
            )}
            <Flex gap="xs" align="center">
              {!playlist?.id && activeTab === 'account' ? (
                <Button
                  key="next"
                  type="button"
                  disabled={checkingConnection || !!connectionFailure}
                  loading={checkingConnection}
                  onClick={(event) => {
                    event.preventDefault();
                    next();
                  }}
                >
                  {checkingConnection ? 'Checking connection…' : 'Next'}
                </Button>
              ) : (
                <Button
                  key="save"
                  type="submit"
                  variant="filled"
                  disabled={
                    form.submitting ||
                    creating ||
                    setupBusy ||
                    checkingConnection ||
                    !!connectionFailure
                  }
                  loading={creating || setupBusy || checkingConnection}
                  size="sm"
                >
                  {checkingConnection
                    ? 'Checking connection…'
                    : playlist?.id && !setupMode
                      ? 'Save'
                      : 'Next'}
                </Button>
              )}
            </Flex>
          </Flex>
        </form>
      </StackedModal>
      <ConfirmationDialog
        opened={!!connectionFailure}
        onClose={() => setConnectionFailure(null)}
        onConfirm={() => {
          const failure = connectionFailure;
          setConnectionFailure(null);
          if (!failure) return;
          if (failure.key === connectionKey())
            approvedConnection.current = failure.key;
          if (failure.intent === 'next') void next();
          else void onSubmit();
        }}
        title="Connection check failed"
        message={`${connectionFailure?.message || ''} No account changes have been saved. Continue anyway?`}
        confirmLabel={
          playlist?.id && !setupMode ? 'Save anyway' : 'Continue anyway'
        }
        confirmColor="orange"
        cancelLabel="Back to editing"
      />
      <ConfirmationDialog
        opened={discardOpen}
        onClose={() => setDiscardOpen(false)}
        onConfirm={close}
        title={
          setupMode
            ? unsavedSetupChanges
              ? 'Discard unsaved changes?'
              : 'Continue setup later?'
            : playlist?.id
              ? 'Discard unsaved changes?'
              : 'Discard new account?'
        }
        message={
          setupMode
            ? unsavedSetupChanges
              ? 'Only the unsaved changes in this editor will be discarded. Your account, EPG sources and saved setup progress will be kept. Use Continue setup to resume later.'
              : 'Your account and saved setup progress will be kept. Use Continue setup to resume. The initial import starts only when you finish setup.'
            : playlist?.id
              ? 'These account changes have not been saved. Discard them and close? Previously saved settings will be kept.'
              : 'This account has not been created. Discard the unsaved entries?'
        }
        confirmLabel={
          setupMode
            ? unsavedSetupChanges
              ? 'Discard changes & close'
              : 'Continue later'
            : 'Discard'
        }
        confirmColor={setupMode && !unsavedSetupChanges ? 'blue' : 'red'}
        cancelLabel="Keep editing"
      />
      {playlist && (
        <>
          <M3UGroupFilter
            isOpen={groupFilterModalOpen}
            playlist={categoryPlaylist || storedAccount || playlist}
            onClose={closeGroupFilter}
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
    </Modal.Stack>
  );
};

export default M3U;
