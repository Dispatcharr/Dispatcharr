// Modal.js
import React, { useEffect, useState } from 'react';
import useUserAgentsStore from '../../store/userAgents';
import useServerGroupsStore from '../../store/serverGroups';
import usePlaylistsStore from '../../store/playlists';
import M3UProfiles from './M3UProfiles';
import {
  Button,
  Divider,
  FileInput,
  FileButton,
  Flex,
  Group,
  LoadingOverlay,
  Modal,
  NumberInput,
  PasswordInput,
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
  Textarea,
  TextInput,
  Tooltip,
} from '@mantine/core';
import M3UGroupFilter from './M3UGroupFilter';
import useChannelsStore from '../../store/channels';
import { isNotEmpty, useForm } from '@mantine/form';
import useEPGsStore from '../../store/epgs';
import useVODStore from '../../store/useVODStore';
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
import ServerGroupsManagerModal from '../ServerGroupsManagerModal';
import ConfirmationDialog from '../ConfirmationDialog';
import API from '../../api';

const formatScheduleDate = (value) =>
  value ? new Date(value).toLocaleString() : 'Never';

const ScheduleStatus = ({ schedule, lastRun }) => (
  <Text size="xs" c="dimmed">
    Last: {formatScheduleDate(lastRun || schedule?.last_run_at)} · Next:{' '}
    {schedule?.enabled
      ? formatScheduleDate(schedule?.next_run_at)
      : 'Not scheduled'}
  </Text>
);

const helpLabel = (label, help) => (
  <Group gap={5} wrap="nowrap">
    <Text span inherit>
      {label}
    </Text>
    <Tooltip label={help} multiline maw={360} withArrow>
      <Text
        span
        size="xs"
        c="dimmed"
        style={{ cursor: 'help', lineHeight: 1 }}
        aria-label={`${label} help`}
      >
        ⓘ
      </Text>
    </Tooltip>
  </Group>
);

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
  const updatePlaylistInStore = usePlaylistsStore((s) => s.updatePlaylist);

  const [playlist, setPlaylist] = useState(null);
  const [file, setFile] = useState(null);
  const [expDate, setExpDate] = useState(null);
  const [groupFilterModalOpen, setGroupFilterModalOpen] = useState(false);
  const [scheduleType, setScheduleType] = useState('interval');
  const [vodScheduleType, setVodScheduleType] = useState('interval');
  const [vodRefreshAfterLive, setVodRefreshAfterLive] = useState(true);
  const [vodEnabled, setVodEnabled] = useState(false);
  const [serverGroupsManagerOpen, setServerGroupsManagerOpen] = useState(false);
  const [serverGroupsCreateOnOpen, setServerGroupsCreateOnOpen] =
    useState(false);
  const [templates, setTemplates] = useState([]);
  const [templateId, setTemplateId] = useState('');
  const [templateSavingOpen, setTemplateSavingOpen] = useState(false);
  const [templateDeleteOpen, setTemplateDeleteOpen] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [templateDescription, setTemplateDescription] = useState('');
  const [templateBusy, setTemplateBusy] = useState(false);

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
      xc_live_refresh_min_age_minutes: 55,
      cron_expression: '',
      vod_refresh_interval: 0,
      vod_cron_expression: '',
      vod_refresh_after_live: true,
      account_type: 'XC',
      create_epg: false,
      username: '',
      password: '',
      stale_stream_days: 7,
      priority: 0,
      enable_vod: false,
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
        xc_live_refresh_min_age_minutes:
          m3uAccount.xc_live_refresh_min_age_minutes ?? 55,
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
      });
      setExpDate(expDateFromPlaylist(m3uAccount.exp_date));

      // Determine schedule type from existing data
      setScheduleType(
        m3uAccount.cron_expression && m3uAccount.cron_expression.trim() !== ''
          ? 'cron'
          : 'interval'
      );
      setVodScheduleType(
        m3uAccount.vod_cron_expression &&
          m3uAccount.vod_cron_expression.trim() !== ''
          ? 'cron'
          : 'interval'
      );
      setVodRefreshAfterLive(m3uAccount.vod_refresh_after_live !== false);
      setVodEnabled(Boolean(m3uAccount.enable_vod));
    } else {
      setPlaylist(null);
      form.reset();
      setScheduleType('interval');
      setVodScheduleType('interval');
      setVodRefreshAfterLive(true);
      setVodEnabled(false);
      setExpDate(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m3uAccount]);

  useEffect(() => {
    if (!isOpen) return;
    API.getM3UAccountTemplates().then((items) => setTemplates(items || []));
  }, [isOpen]);

  const selectedTemplate = templates.find(
    (template) => String(template.id) === templateId
  );

  const applyTemplateValues = (template) => {
    if (!template) return;
    const settings = template.account_settings || {};
    form.setValues({
      account_type: template.account_type || form.getValues().account_type,
      max_streams: settings.max_streams ?? form.getValues().max_streams,
      refresh_interval:
        settings.refresh_interval ?? form.getValues().refresh_interval,
      xc_live_refresh_min_age_minutes:
        settings.xc_live_refresh_min_age_minutes ??
        form.getValues().xc_live_refresh_min_age_minutes,
      cron_expression:
        settings.cron_expression ?? form.getValues().cron_expression,
      vod_refresh_interval:
        settings.vod_refresh_interval ?? form.getValues().vod_refresh_interval,
      vod_cron_expression:
        settings.vod_cron_expression ?? form.getValues().vod_cron_expression,
      vod_refresh_after_live:
        settings.vod_refresh_after_live ??
        form.getValues().vod_refresh_after_live,
      stale_stream_days:
        settings.stale_stream_days ?? form.getValues().stale_stream_days,
      priority: settings.priority ?? form.getValues().priority,
      enable_vod: settings.enable_vod ?? form.getValues().enable_vod,
    });
    setVodRefreshAfterLive(
      settings.vod_refresh_after_live ?? form.getValues().vod_refresh_after_live
    );
    setVodEnabled(settings.enable_vod ?? form.getValues().enable_vod);
    setScheduleType(
      (settings.cron_expression ?? form.getValues().cron_expression)?.trim()
        ? 'cron'
        : 'interval'
    );
    setVodScheduleType(
      (
        settings.vod_cron_expression ?? form.getValues().vod_cron_expression
      )?.trim()
        ? 'cron'
        : 'interval'
    );
  };

  const applyTemplate = async () => {
    if (!selectedTemplate) return;
    if (!playlist?.id) {
      applyTemplateValues(selectedTemplate);
      showNotification({
        title: 'Template selected',
        message:
          'Settings, group selections, Auto Sync, filters, and import rules will be applied when the account is created.',
        color: 'green',
      });
      return;
    }
    setTemplateBusy(true);
    try {
      const updated = await API.applyM3UAccountTemplate(
        selectedTemplate.id,
        playlist.id
      );
      setPlaylist(updated);
      updatePlaylistInStore(updated);
      applyTemplateValues(selectedTemplate);
      showNotification({
        title: 'Template applied',
        message:
          'Portable settings, group selections, Auto Sync, filters, and import rules were copied.',
        color: 'green',
      });
    } finally {
      setTemplateBusy(false);
    }
  };

  const saveTemplate = async () => {
    if (!playlist?.id || !templateName.trim()) return;
    setTemplateBusy(true);
    try {
      const created = await API.saveM3UAccountAsTemplate(playlist.id, {
        name: templateName.trim(),
        description: templateDescription.trim(),
      });
      setTemplates((current) => [...current, created]);
      setTemplateId(String(created.id));
      setTemplateSavingOpen(false);
      setTemplateName('');
      setTemplateDescription('');
    } finally {
      setTemplateBusy(false);
    }
  };

  const exportTemplate = () => {
    if (!selectedTemplate) return;
    const portable = {
      name: selectedTemplate.name,
      description: selectedTemplate.description || '',
      account_type: selectedTemplate.account_type,
      account_settings: selectedTemplate.account_settings || {},
      filters: selectedTemplate.filters || [],
      group_rules: selectedTemplate.group_rules || [],
    };
    const blob = new Blob([JSON.stringify(portable, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${selectedTemplate.name.replace(/[^a-z0-9_-]+/gi, '-')}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const deleteTemplate = async () => {
    if (!selectedTemplate) return;
    setTemplateBusy(true);
    try {
      await API.deleteM3UAccountTemplate(selectedTemplate.id);
      setTemplates((current) =>
        current.filter((template) => template.id !== selectedTemplate.id)
      );
      setTemplateId('');
      setTemplateDeleteOpen(false);
      showNotification({
        title: 'Template deleted',
        message: `${selectedTemplate.name} was deleted.`,
        color: 'green',
      });
    } finally {
      setTemplateBusy(false);
    }
  };

  const importTemplate = async (file) => {
    if (!file) return;
    setTemplateBusy(true);
    try {
      const values = JSON.parse(await file.text());
      const created = await API.createM3UAccountTemplate(values);
      setTemplates((current) => [...current, created]);
      setTemplateId(String(created.id));
      showNotification({
        title: 'Template imported',
        message:
          'No provider URL, username, or password is stored in templates.',
        color: 'green',
      });
    } catch (error) {
      showNotification({
        title: 'Template could not be imported',
        message: error?.message || 'The JSON file is invalid.',
        color: 'red',
      });
    } finally {
      setTemplateBusy(false);
    }
  };

  useEffect(() => {
    if (storeExpDate === undefined) return;
    const next = expDateFromPlaylist(storeExpDate);
    setExpDate((prev) => (expDateKey(prev) === expDateKey(next) ? prev : next));
  }, [storeExpDate]);

  const handleNewPlaylist = async (newPlaylist, values, create_epg) => {
    if (create_epg) {
      addEPG({
        name: values.name,
        source_type: 'xmltv',
        url: `${new URL(values.server_url).origin}/xmltv.php?username=${values.username}&password=${values.password}`,
        api_key: '',
        is_active: true,
        refresh_interval: 24,
      });
    }

    if (values.account_type != 'XC') {
      showNotification({
        title: 'Fetching M3U Groups',
        message:
          'Configure group filters and auto sync settings once complete.',
      });
      close();
      return;
    }

    const updatedPlaylist = await getPlaylist(newPlaylist);
    await Promise.all([fetchChannelGroups(), fetchEPGs()]);

    if (values.enable_vod) {
      fetchCategories();
    }

    setPlaylist(updatedPlaylist);
    setGroupFilterModalOpen(true);
  };

  const onSubmit = async () => {
    const { create_epg, ...rawValues } = form.getValues();
    const values = prepareSubmitValues(rawValues, expDate);
    if (!playlist?.id && templateId)
      values.account_template = Number(templateId);

    if (playlist?.id) {
      await updatePlaylist(playlist, values, file);
      form.reset();
      setFile(null);
      onClose();
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
  };

  useEffect(() => {
    if (playlistCreated) {
      setGroupFilterModalOpen(true);
    }
  }, [playlist, playlistCreated]);

  if (!isOpen) {
    return <></>;
  }

  return (
    <>
      <Modal
        size={1040}
        opened={isOpen}
        onClose={close}
        title="M3U Account"
        scrollAreaComponent={Modal.NativeScrollArea}
        lockScroll={false}
        withinPortal={true}
        trapFocus={false}
        yOffset="2vh"
      >
        <LoadingOverlay visible={form.submitting} overlayBlur={2} />

        <form onSubmit={form.onSubmit(onSubmit)}>
          <Stack gap={5} mb="md">
            {helpLabel(
              'Account template',
              'Templates copy portable settings, Live and VOD group selections, Auto Sync, stream filters, and import rules. Provider URLs and credentials are never included.'
            )}
            <Group align="flex-end" wrap="wrap">
              <Select
                placeholder="No template"
                searchable
                clearable
                data={templates.map((template) => ({
                  value: String(template.id),
                  label: template.name,
                }))}
                value={templateId || null}
                onChange={(value) => setTemplateId(value || '')}
                style={{ flex: 1, minWidth: 240 }}
              />
              <Button
                variant="default"
                disabled={!selectedTemplate}
                loading={templateBusy}
                onClick={applyTemplate}
              >
                Apply
              </Button>
              {playlist?.id && (
                <Button
                  variant="default"
                  onClick={() => setTemplateSavingOpen(true)}
                >
                  Save current
                </Button>
              )}
              <Button
                variant="default"
                disabled={!selectedTemplate}
                onClick={exportTemplate}
              >
                Export
              </Button>
              <Button
                variant="default"
                color="red"
                disabled={!selectedTemplate || templateBusy}
                onClick={() => setTemplateDeleteOpen(true)}
              >
                Delete
              </Button>
              <FileButton onChange={importTemplate} accept="application/json">
                {(props) => (
                  <Button variant="default" {...props}>
                    Import
                  </Button>
                )}
              </FileButton>
            </Group>
          </Stack>

          <Tabs defaultValue="account" style={{ minHeight: 560 }}>
            <TabsList>
              <TabsTab value="account">Account</TabsTab>
              <TabsTab value="content">Content</TabsTab>
              <TabsTab value="profiles" disabled={!playlist?.id}>
                Connection Profiles
              </TabsTab>
            </TabsList>

            <TabsPanel value="account" pt="md">
              <Group align="flex-start" gap="md" wrap="nowrap">
                <Stack gap="xs" style={{ flex: 1, minWidth: 0 }}>
                  <TextInput
                    id="name"
                    name="name"
                    label="Name"
                    {...form.getInputProps('name')}
                    key={form.key('name')}
                  />
                  <Select
                    id="account_type"
                    name="account_type"
                    label="Account Type"
                    data={[
                      { value: 'STD', label: 'Standard' },
                      { value: 'XC', label: 'Xtream Codes' },
                    ]}
                    key={form.key('account_type')}
                    {...form.getInputProps('account_type')}
                  />
                  <TextInput
                    id="server_url"
                    name="server_url"
                    label="URL"
                    {...form.getInputProps('server_url')}
                    key={form.key('server_url')}
                  />

                  {form.getValues().account_type == 'XC' && (
                    <>
                      <TextInput
                        id="username"
                        name="username"
                        label="Username"
                        {...form.getInputProps('username')}
                      />
                      <PasswordInput
                        id="password"
                        name="password"
                        label="Password"
                        placeholder={
                          playlist?.id ? 'Leave empty to keep existing' : ''
                        }
                        {...form.getInputProps('password')}
                      />
                    </>
                  )}

                  {form.getValues().account_type != 'XC' && (
                    <>
                      <FileInput
                        id="file"
                        label="Upload files"
                        placeholder="Upload files"
                        onChange={setFile}
                        styles={{
                          input: {
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            display: 'block',
                          },
                        }}
                      />
                      <DateTimePicker
                        label="Expiration Date"
                        placeholder="No expiration"
                        clearable
                        valueFormat="MMM D, YYYY h:mm A"
                        value={expDate}
                        onChange={(v) => setExpDate(v ? new Date(v) : null)}
                      />
                    </>
                  )}
                </Stack>

                <Divider size="sm" orientation="vertical" />

                <Stack gap="xs" style={{ flex: 1, minWidth: 0 }}>
                  <NumberInput
                    id="max_streams"
                    name="max_streams"
                    aria-label="Max Streams"
                    label={helpLabel(
                      'Max Streams',
                      'Maximum concurrent streams for the default connection profile. Use 0 for unlimited.'
                    )}
                    placeholder="0 = Unlimited"
                    min={0}
                    {...form.getInputProps('max_streams')}
                    key={form.key('max_streams')}
                  />
                  <Select
                    id="server_group"
                    name="server_group"
                    aria-label="Server Group"
                    label={helpLabel(
                      'Server Group',
                      'Link M3U and XC accounts that belong to the same provider subscription so connection limits are tracked across all imported sources. Matching effective logins share the same counter; unlimited profiles are not restricted.'
                    )}
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
                    aria-label="User-Agent"
                    label={helpLabel(
                      'User-Agent',
                      'HTTP User-Agent sent when Dispatcharr accesses this source.'
                    )}
                    {...form.getInputProps('user_agent')}
                    key={form.key('user_agent')}
                    data={[{ value: '0', label: '(Use Default)' }].concat(
                      userAgents.map((ua) => ({
                        label: ua.name,
                        value: `${ua.id}`,
                      }))
                    )}
                  />
                </Stack>
              </Group>
            </TabsPanel>

            <TabsPanel value="content" pt="md">
              <Stack gap="md">
                <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                  <Paper withBorder p="md" radius="md">
                    <Stack gap="sm">
                      <Text fw={600}>Live TV</Text>
                      {form.getValues().account_type == 'XC' && (
                        <NumberInput
                          min={0}
                          max={10080}
                          allowDecimal={false}
                          label={helpLabel(
                            'Provider refresh age (minutes)',
                            'Suppress XC client-triggered refreshes for this long after any successful Live TV refresh. Use 0 to always permit them.'
                          )}
                          {...form.getInputProps(
                            'xc_live_refresh_min_age_minutes'
                          )}
                          key={form.key('xc_live_refresh_min_age_minutes')}
                        />
                      )}
                      <NumberInput
                        min={0}
                        max={365}
                        label={helpLabel(
                          'Stale stream retention (days)',
                          'Remove Live TV streams that have not appeared in a provider refresh for this many days.'
                        )}
                        {...form.getInputProps('stale_stream_days')}
                      />
                      {!m3uAccount && form.getValues().account_type == 'XC' && (
                        <Switch
                          id="create_epg"
                          name="create_epg"
                          label="Create matching EPG source"
                          key={form.key('create_epg')}
                          {...form.getInputProps('create_epg', {
                            type: 'checkbox',
                          })}
                        />
                      )}
                    </Stack>
                  </Paper>

                  <Paper withBorder p="md" radius="md">
                    {form.getValues().account_type == 'XC' ? (
                      <Stack gap="sm">
                        <Group justify="space-between" align="center">
                          <Text fw={600}>VOD</Text>
                          <Switch
                            id="enable_vod"
                            name="enable_vod"
                            label="Enabled"
                            checked={vodEnabled}
                            onChange={(event) => {
                              const checked = event.currentTarget.checked;
                              setVodEnabled(checked);
                              form.setFieldValue('enable_vod', checked);
                            }}
                          />
                        </Group>

                        <NumberInput
                          min={0}
                          max={999}
                          label={helpLabel(
                            'Provider priority',
                            'Higher values rank this provider ahead of lower-priority providers when the same VOD title is available from multiple sources.'
                          )}
                          {...form.getInputProps('priority')}
                          key={form.key('priority')}
                          disabled={!vodEnabled}
                        />
                      </Stack>
                    ) : (
                      <Stack gap="xs">
                        <Text fw={600}>VOD</Text>
                        <Text size="sm" c="dimmed">
                          Available for Xtream Codes accounts.
                        </Text>
                      </Stack>
                    )}
                  </Paper>
                </SimpleGrid>

                <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                  <Paper withBorder p="md" radius="md">
                    <Stack gap="sm">
                      <Text fw={600}>Live TV refresh schedule</Text>
                      <ScheduleInput
                        scheduleType={scheduleType}
                        onScheduleTypeChange={setScheduleType}
                        intervalValue={form.getValues().refresh_interval}
                        onIntervalChange={(value) =>
                          form.setFieldValue('refresh_interval', value)
                        }
                        cronValue={form.getValues().cron_expression}
                        onCronChange={(expression) =>
                          form.setFieldValue('cron_expression', expression)
                        }
                        intervalLabel="Refresh interval (hours)"
                        intervalDescription="Refresh Live TV and run auto sync; 0 disables the schedule."
                      />
                      <ScheduleStatus
                        schedule={playlist?.live_refresh_schedule}
                        lastRun={playlist?.updated_at}
                      />
                    </Stack>
                  </Paper>

                  <Paper withBorder p="md" radius="md">
                    <Stack gap="sm">
                      <Group justify="space-between" align="center">
                        <Text fw={600}>VOD refresh schedule</Text>
                        <Tooltip
                          label="When disabled, VOD refresh runs after a successful Live TV refresh."
                          multiline
                          maw={320}
                          withArrow
                        >
                          <Switch
                            id="vod_refresh_schedule_enabled"
                            name="vod_refresh_schedule_enabled"
                            label="Enabled"
                            checked={!vodRefreshAfterLive}
                            onChange={(event) => {
                              const refreshAfterLive =
                                !event.currentTarget.checked;
                              setVodRefreshAfterLive(refreshAfterLive);
                              form.setFieldValue(
                                'vod_refresh_after_live',
                                refreshAfterLive
                              );
                            }}
                            disabled={
                              form.getValues().account_type != 'XC' ||
                              !vodEnabled
                            }
                          />
                        </Tooltip>
                      </Group>
                      {form.getValues().account_type != 'XC' ? (
                        <Text size="sm" c="dimmed">
                          Available for Xtream Codes accounts.
                        </Text>
                      ) : !vodEnabled ? (
                        <Text size="sm" c="dimmed">
                          Enable VOD above to configure its refresh schedule.
                        </Text>
                      ) : vodRefreshAfterLive ? (
                        <Text size="sm" c="dimmed">
                          Runs after the Live TV refresh · Last:{' '}
                          {formatScheduleDate(
                            playlist?.custom_properties?.refresh_timings
                              ?.vod_completed_at
                          )}
                        </Text>
                      ) : (
                        <>
                          <ScheduleInput
                            scheduleType={vodScheduleType}
                            onScheduleTypeChange={setVodScheduleType}
                            intervalValue={
                              form.getValues().vod_refresh_interval
                            }
                            onIntervalChange={(value) =>
                              form.setFieldValue('vod_refresh_interval', value)
                            }
                            cronValue={form.getValues().vod_cron_expression}
                            onCronChange={(expression) =>
                              form.setFieldValue(
                                'vod_cron_expression',
                                expression
                              )
                            }
                            intervalLabel="Refresh interval (hours)"
                            intervalDescription="Use 0 to disable the separate VOD schedule."
                          />
                          <ScheduleStatus
                            schedule={playlist?.vod_refresh_schedule}
                            lastRun={
                              playlist?.custom_properties?.refresh_timings
                                ?.vod_completed_at
                            }
                          />
                        </>
                      )}
                    </Stack>
                  </Paper>
                </SimpleGrid>
              </Stack>
            </TabsPanel>

            <TabsPanel value="profiles" pt="md">
              {playlist?.id && (
                <M3UProfiles
                  playlist={playlist}
                  embedded
                  pendingExpDate={expDate}
                />
              )}
            </TabsPanel>
          </Tabs>

          <Divider my="md" />

          <Flex
            gap="md"
            justify="space-between"
            align="center"
            wrap="wrap"
            mih={50}
          >
            <Switch
              id="is_active"
              name="is_active"
              label="Is Active"
              key={form.key('is_active')}
              {...form.getInputProps('is_active', { type: 'checkbox' })}
            />

            <Flex gap="xs" align="center">
              {playlist && (
                <>
                  <Button
                    variant="filled"
                    // color={theme.custom.colors.buttonPrimary}
                    size="sm"
                    onClick={() => {
                      // If this is an XC account with VOD enabled, fetch VOD categories
                      if (
                        m3uAccount?.account_type === 'XC' &&
                        m3uAccount?.enable_vod
                      ) {
                        fetchCategories();
                      }
                      setGroupFilterModalOpen(true);
                    }}
                  >
                    Groups
                  </Button>
                </>
              )}

              <Button
                type="submit"
                aria-label={
                  playlist?.id ? 'Save M3U account' : 'Create M3U account'
                }
                variant="filled"
                disabled={form.submitting}
                size="sm"
              >
                {playlist?.id ? 'Save' : 'Create'}
              </Button>
            </Flex>
          </Flex>
        </form>
      </Modal>
      {playlist && (
        <M3UGroupFilter
          isOpen={groupFilterModalOpen}
          playlist={playlist}
          onClose={closeGroupFilter}
        />
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
      <Modal
        opened={templateSavingOpen}
        onClose={() => setTemplateSavingOpen(false)}
        title="Save M3U account template"
      >
        <Stack>
          <TextInput
            label="Template name"
            required
            value={templateName}
            onChange={(event) => setTemplateName(event.currentTarget.value)}
          />
          <Textarea
            label="Description"
            value={templateDescription}
            onChange={(event) =>
              setTemplateDescription(event.currentTarget.value)
            }
          />
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setTemplateSavingOpen(false)}
            >
              Cancel
            </Button>
            <Button loading={templateBusy} onClick={saveTemplate}>
              Save template
            </Button>
          </Group>
        </Stack>
      </Modal>
      <ConfirmationDialog
        opened={templateDeleteOpen}
        onClose={() => setTemplateDeleteOpen(false)}
        onConfirm={deleteTemplate}
        loading={templateBusy}
        title="Delete M3U account template"
        message={
          selectedTemplate
            ? `Delete the template “${selectedTemplate.name}”? Existing accounts are not changed.`
            : 'Delete this template? Existing accounts are not changed.'
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
      />
    </>
  );
};

export default M3U;
