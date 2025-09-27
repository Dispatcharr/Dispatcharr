import React, { useEffect, useState } from 'react';
import API from '../api';
import useSettingsStore from '../store/settings';
import useUserAgentsStore from '../store/userAgents';
import useStreamProfilesStore from '../store/streamProfiles';
import {
  Accordion,
  Alert,
  Box,
  Button,
  Center,
  Flex,
  Group,
  MultiSelect,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  NumberInput,
} from '@mantine/core';
import { isNotEmpty, useForm } from '@mantine/form';
import UserAgentsTable from '../components/tables/UserAgentsTable';
import StreamProfilesTable from '../components/tables/StreamProfilesTable';
import BackupManager from '../components/backups/BackupManager';
import useLocalStorage from '../hooks/useLocalStorage';
import useAuthStore from '../store/auth';
import {
  USER_LEVELS,
  NETWORK_ACCESS_OPTIONS,
  PROXY_SETTINGS_OPTIONS,
  REGION_CHOICES,
} from '../constants';
import ConfirmationDialog from '../components/ConfirmationDialog';
import useWarningsStore from '../store/warnings';

const SettingsPage = () => {
  const settings = useSettingsStore((s) => s.settings);
  const userAgents = useUserAgentsStore((s) => s.userAgents);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);
  const authUser = useAuthStore((s) => s.user);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);

  const [accordianValue, setAccordianValue] = useState(null);
  const [networkAccessSaved, setNetworkAccessSaved] = useState(false);
  const [networkAccessError, setNetworkAccessError] = useState(null);
  const [networkAccessConfirmOpen, setNetworkAccessConfirmOpen] =
    useState(false);
  const [netNetworkAccessConfirmCIDRs, setNetNetworkAccessConfirmCIDRs] =
    useState([]);

  const [proxySettingsSaved, setProxySettingsSaved] = useState(false);
  const [rehashingStreams, setRehashingStreams] = useState(false);
  const [rehashSuccess, setRehashSuccess] = useState(false);
  const [rehashConfirmOpen, setRehashConfirmOpen] = useState(false);

  // Add a new state to track the dialog type
  const [rehashDialogType, setRehashDialogType] = useState(null); // 'save' or 'rehash'

  // UI / local storage settings
  const [tableSize, setTableSize] = useLocalStorage('table-size', 'default');
  const [timeFormat, setTimeFormat] = useLocalStorage('time-format', '12h');
  const [dateFormat, setDateFormat] = useLocalStorage('date-format', 'mdy');

  const regionChoices = REGION_CHOICES;

  const form = useForm({
    mode: 'controlled',
    initialValues: {
      'default-user-agent': '',
      'default-stream-profile': '',
      'preferred-region': '',
      'auto-import-mapped-files': true,
      'm3u-hash-key': [],
      'dvr-tv-template': '',
      'dvr-movie-template': '',
      'dvr-tv-fallback-template': '',
      'dvr-movie-fallback-template': '',
      'dvr-comskip-enabled': false,
      'dvr-pre-offset-minutes': 0,
      'dvr-post-offset-minutes': 0,
    },

    validate: {
      'default-user-agent': isNotEmpty('Select a user agent'),
      'default-stream-profile': isNotEmpty('Select a stream profile'),
      'preferred-region': isNotEmpty('Select a region'),
    },
  });

  const networkAccessForm = useForm({
    mode: 'controlled',
    initialValues: Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
      acc[key] = '0.0.0.0/0';
      return acc;
    }, {}),
    validate: Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
      acc[key] = (value) => {
        const cidrs = value.split(',');
        for (const cidr of cidrs) {
          if (cidr.match(/^([0-9]{1,3}\.){3}[0-9]{1,3}\/\d+$/)) {
            continue;
          }

          return 'Invalid CIDR range';
        }

        return null;
      };
      return acc;
    }, {}),
  });

  const proxySettingsForm = useForm({
    mode: 'controlled',
    initialValues: Object.keys(PROXY_SETTINGS_OPTIONS).reduce((acc, key) => {
      acc[key] = '';
      return acc;
    }, {}),
  });

  useEffect(() => {
    if (settings) {
      const formValues = Object.entries(settings).reduce(
        (acc, [key, value]) => {
          // Modify each value based on its own properties
          switch (value.value) {
            case 'true':
              value.value = true;
              break;
            case 'false':
              value.value = false;
              break;
          }

          let val = null;
          switch (key) {
            case 'm3u-hash-key':
              val = value.value.split(',');
              break;
            case 'dvr-pre-offset-minutes':
            case 'dvr-post-offset-minutes':
              val = Number.parseInt(value.value || '0', 10);
              if (Number.isNaN(val)) val = 0;
              break;
            default:
              val = value.value;
              break;
          }

          acc[key] = val;
          return acc;
        },
        {}
      );

      form.setValues(formValues);

      const networkAccessSettings = JSON.parse(
        settings['network-access'].value || '{}'
      );
      networkAccessForm.setValues(
        Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
          acc[key] = networkAccessSettings[key] || '0.0.0.0/0';
          return acc;
        }, {})
      );

      if (settings['proxy-settings']?.value) {
        try {
          const proxySettings = JSON.parse(settings['proxy-settings'].value);
          proxySettingsForm.setValues(proxySettings);
        } catch (error) {
          console.error('Error parsing proxy settings:', error);
        }
      }
    }
  }, [settings]);

  const onSubmit = async () => {
    const values = form.getValues();
    const changedSettings = {};
    let m3uHashKeyChanged = false;

    for (const settingKey in values) {
      // Only compare against existing value if the setting exists
      const existing = settings[settingKey];
      if (!existing) {
        // Create new setting on save
        changedSettings[settingKey] = `${values[settingKey]}`;
      } else if (String(values[settingKey]) !== String(existing.value)) {
        // If the user changed the setting's value from what's in the DB:
        changedSettings[settingKey] = `${values[settingKey]}`;

        // Check if M3U hash key was changed
        if (settingKey === 'm3u-hash-key') {
          m3uHashKeyChanged = true;
        }
      }
    }

    // If M3U hash key changed, show warning (unless suppressed)
    if (m3uHashKeyChanged && !isWarningSuppressed('rehash-streams')) {
      setRehashDialogType('save'); // Set dialog type to save
      setRehashConfirmOpen(true);
      return;
    }

    // Update each changed setting in the backend (create if missing)
    for (const updatedKey in changedSettings) {
      const existing = settings[updatedKey];
      if (existing && existing.id) {
        await API.updateSetting({
          ...existing,
          value: changedSettings[updatedKey],
        });
      } else {
        await API.createSetting({
          key: updatedKey,
          name: updatedKey.replace(/-/g, ' '),
          value: changedSettings[updatedKey],
        });
      }
    }
  };

  const onNetworkAccessSubmit = async () => {
    setNetworkAccessSaved(false);
    setNetworkAccessError(null);
    const check = await API.checkSetting({
      ...settings['network-access'],
      value: JSON.stringify(networkAccessForm.getValues()),
    });

    if (check.error && check.message) {
      setNetworkAccessError(`${check.message}: ${check.data}`);
      return;
    }

    // For now, only warn if we're blocking the UI
    const blockedAccess = check.UI;
    if (blockedAccess.length == 0) {
      return saveNetworkAccess();
    }

    setNetNetworkAccessConfirmCIDRs(blockedAccess);
    setNetworkAccessConfirmOpen(true);
  };

  const onProxySettingsSubmit = async () => {
    setProxySettingsSaved(false);

    await API.updateSetting({
      ...settings['proxy-settings'],
      value: JSON.stringify(proxySettingsForm.getValues()),
    });

    setProxySettingsSaved(true);
  };

  const resetProxySettingsToDefaults = () => {
    const defaultValues = {
      buffering_timeout: 15,
      buffering_speed: 1.0,
      redis_chunk_ttl: 60,
      channel_shutdown_delay: 0,
      channel_init_grace_period: 5,
    };

    proxySettingsForm.setValues(defaultValues);
  };

  const saveNetworkAccess = async () => {
    setNetworkAccessSaved(false);
    try {
      await API.updateSetting({
        ...settings['network-access'],
        value: JSON.stringify(networkAccessForm.getValues()),
      });
      setNetworkAccessSaved(true);
      setNetworkAccessConfirmOpen(false);
    } catch (e) {
      const errors = {};
      for (const key in e.body.value) {
        errors[key] = `Invalid CIDR(s): ${e.body.value[key]}`;
      }
      networkAccessForm.setErrors(errors);
    }
  };

  const onUISettingsChange = (name, value) => {
    switch (name) {
      case 'table-size':
        setTableSize(value);
        break;
      case 'time-format':
        setTimeFormat(value);
        break;
      case 'date-format':
        setDateFormat(value);
        break;
    }
  };

  const executeSettingsSaveAndRehash = async () => {
    setRehashConfirmOpen(false);

    // First save the settings
    const values = form.getValues();
    const changedSettings = {};

    for (const settingKey in values) {
      if (String(values[settingKey]) !== String(settings[settingKey].value)) {
        changedSettings[settingKey] = `${values[settingKey]}`;
      }
    }

    // Update each changed setting in the backend
    for (const updatedKey in changedSettings) {
      await API.updateSetting({
        ...settings[updatedKey],
        value: changedSettings[updatedKey],
      });
    }
  };

  const executeRehashStreamsOnly = async () => {
    setRehashingStreams(true);
    setRehashSuccess(false);
    setRehashConfirmOpen(false);

    try {
      await API.rehashStreams();
      setRehashSuccess(true);
      setTimeout(() => setRehashSuccess(false), 5000);
    } catch (error) {
      console.error('Error rehashing streams:', error);
    } finally {
      setRehashingStreams(false);
    }
  };

  const onRehashStreams = async () => {
    // Skip warning if it's been suppressed
    if (isWarningSuppressed('rehash-streams')) {
      return executeRehashStreamsOnly();
    }

    setRehashDialogType('rehash'); // Set dialog type to rehash
    setRehashConfirmOpen(true);
  };

  // Create a function to handle the confirmation based on dialog type
  const handleRehashConfirm = () => {
    if (rehashDialogType === 'save') {
      executeSettingsSaveAndRehash();
    } else {
      executeRehashStreamsOnly();
    }
  };

  return (
    <Center
      style={{
        padding: 10,
      }}
    >
      <Box style={{ width: '100%', maxWidth: 800 }}>
        <Accordion
          variant="separated"
          defaultValue="ui-settings"
          onChange={setAccordianValue}
          style={{ minWidth: 400 }}
        >
          <Accordion.Item value="ui-settings">
            <Accordion.Control>UI Settings</Accordion.Control>
            <Accordion.Panel>
              <Select
                label="Table Size"
                value={tableSize}
                onChange={(val) => onUISettingsChange('table-size', val)}
                data={[
                  {
                    value: 'default',
                    label: 'Default',
                  },
                  {
                    value: 'compact',
                    label: 'Compact',
                  },
                  {
                    value: 'large',
                    label: 'Large',
                  },
                ]}
              />
              <Select
                label="Time format"
                value={timeFormat}
                onChange={(val) => onUISettingsChange('time-format', val)}
                data={[
                  {
                    value: '12h',
                    label: '12h hour time',
                  },
                  {
                    value: '24h',
                    label: '24 hour time',
                  },
                ]}
              />
              <Select
                label="Date format"
                value={dateFormat}
                onChange={(val) => onUISettingsChange('date-format', val)}
                data={[
                  {
                    value: 'mdy',
                    label: 'MM/DD/YYYY',
                  },
                  {
                    value: 'dmy',
                    label: 'DD/MM/YYYY',
                  },
                ]}
              />
            </Accordion.Panel>
          </Accordion.Item>

          {authUser.user_level == USER_LEVELS.ADMIN && (
            <>
              <Accordion.Item value="dvr-settings">
                <Accordion.Control>DVR</Accordion.Control>
                <Accordion.Panel>
                  <form onSubmit={form.onSubmit(onSubmit)}>
                    <Stack gap="sm">
                      <Switch
                        label="Enable Comskip (remove commercials after recording)"
                        {...form.getInputProps('dvr-comskip-enabled', {
                          type: 'checkbox',
                        })}
                        key={form.key('dvr-comskip-enabled')}
                        id={
                          settings['dvr-comskip-enabled']?.id ||
                          'dvr-comskip-enabled'
                        }
                        name={
                          settings['dvr-comskip-enabled']?.key ||
                          'dvr-comskip-enabled'
                        }
                      />
                      <NumberInput
                        label="Start early (minutes)"
                        description="Begin recording this many minutes before the scheduled start."
                        min={0}
                        step={1}
                        {...form.getInputProps('dvr-pre-offset-minutes')}
                        key={form.key('dvr-pre-offset-minutes')}
                        id={
                          settings['dvr-pre-offset-minutes']?.id ||
                          'dvr-pre-offset-minutes'
                        }
                        name={
                          settings['dvr-pre-offset-minutes']?.key ||
                          'dvr-pre-offset-minutes'
                        }
                      />
                      <NumberInput
                        label="End late (minutes)"
                        description="Continue recording this many minutes after the scheduled end."
                        min={0}
                        step={1}
                        {...form.getInputProps('dvr-post-offset-minutes')}
                        key={form.key('dvr-post-offset-minutes')}
                        id={
                          settings['dvr-post-offset-minutes']?.id ||
                          'dvr-post-offset-minutes'
                        }
                        name={
                          settings['dvr-post-offset-minutes']?.key ||
                          'dvr-post-offset-minutes'
                        }
                      />
                      <TextInput
                        label="TV Path Template"
                        description="Supports {show}, {season}, {episode}, {sub_title}, {channel}, {year}, {start}, {end}. Use format specifiers like {season:02d}. Relative paths are under your library dir."
                        placeholder="TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"
                        {...form.getInputProps('dvr-tv-template')}
                        key={form.key('dvr-tv-template')}
                        id={
                          settings['dvr-tv-template']?.id || 'dvr-tv-template'
                        }
                        name={
                          settings['dvr-tv-template']?.key || 'dvr-tv-template'
                        }
                      />
                      <TextInput
                        label="TV Fallback Template"
                        description="Template used when an episode has no season/episode. Supports {show}, {start}, {end}, {channel}, {year}."
                        placeholder="TV_Shows/{show}/{start}.mkv"
                        {...form.getInputProps('dvr-tv-fallback-template')}
                        key={form.key('dvr-tv-fallback-template')}
                        id={
                          settings['dvr-tv-fallback-template']?.id ||
                          'dvr-tv-fallback-template'
                        }
                        name={
                          settings['dvr-tv-fallback-template']?.key ||
                          'dvr-tv-fallback-template'
                        }
                      />
                      <TextInput
                        label="Movie Path Template"
                        description="Supports {title}, {year}, {channel}, {start}, {end}. Relative paths are under your library dir."
                        placeholder="Movies/{title} ({year}).mkv"
                        {...form.getInputProps('dvr-movie-template')}
                        key={form.key('dvr-movie-template')}
                        id={
                          settings['dvr-movie-template']?.id ||
                          'dvr-movie-template'
                        }
                        name={
                          settings['dvr-movie-template']?.key ||
                          'dvr-movie-template'
                        }
                      />
                      <TextInput
                        label="Movie Fallback Template"
                        description="Template used when movie metadata is incomplete. Supports {start}, {end}, {channel}."
                        placeholder="Movies/{start}.mkv"
                        {...form.getInputProps('dvr-movie-fallback-template')}
                        key={form.key('dvr-movie-fallback-template')}
                        id={
                          settings['dvr-movie-fallback-template']?.id ||
                          'dvr-movie-fallback-template'
                        }
                        name={
                          settings['dvr-movie-fallback-template']?.key ||
                          'dvr-movie-fallback-template'
                        }
                      />
                      <Flex
                        mih={50}
                        gap="xs"
                        justify="flex-end"
                        align="flex-end"
                      >
                        <Button type="submit" variant="default">
                          Save
                        </Button>
                      </Flex>
                    </Stack>
                  </form>
                </Accordion.Panel>
              </Accordion.Item>
              <Accordion.Item value="stream-settings">
                <Accordion.Control>Stream Settings</Accordion.Control>
                <Accordion.Panel>
                  <form onSubmit={form.onSubmit(onSubmit)}>
                    <Select
                      searchable
                      {...form.getInputProps('default-user-agent')}
                      key={form.key('default-user-agent')}
                      id={
                        settings['default-user-agent']?.id ||
                        'default-user-agent'
                      }
                      name={
                        settings['default-user-agent']?.key ||
                        'default-user-agent'
                      }
                      label={
                        settings['default-user-agent']?.name ||
                        'Default User Agent'
                      }
                      data={userAgents.map((option) => ({
                        value: `${option.id}`,
                        label: option.name,
                      }))}
                    />
                    <Select
                      searchable
                      {...form.getInputProps('default-stream-profile')}
                      key={form.key('default-stream-profile')}
                      id={
                        settings['default-stream-profile']?.id ||
                        'default-stream-profile'
                      }
                      name={
                        settings['default-stream-profile']?.key ||
                        'default-stream-profile'
                      }
                      label={
                        settings['default-stream-profile']?.name ||
                        'Default Stream Profile'
                      }
                      data={streamProfiles.map((option) => ({
                        value: `${option.id}`,
                        label: option.name,
                      }))}
                    />
                    <Select
                      searchable
                      {...form.getInputProps('preferred-region')}
                      key={form.key('preferred-region')}
                      id={
                        settings['preferred-region']?.id || 'preferred-region'
                      }
                      name={
                        settings['preferred-region']?.key || 'preferred-region'
                      }
                      label={
                        settings['preferred-region']?.name || 'Preferred Region'
                      }
                      data={regionChoices.map((r) => ({
                        label: r.label,
                        value: `${r.value}`,
                      }))}
                    />

                    <Group justify="space-between" style={{ paddingTop: 5 }}>
                      <Text size="sm" fw={500}>
                        Auto-Import Mapped Files
                      </Text>
                      <Switch
                        {...form.getInputProps('auto-import-mapped-files', {
                          type: 'checkbox',
                        })}
                        key={form.key('auto-import-mapped-files')}
                        id={
                          settings['auto-import-mapped-files']?.id ||
                          'auto-import-mapped-files'
                        }
                      />
                    </Group>

                    <MultiSelect
                      id="m3u-hash-key"
                      name="m3u-hash-key"
                      label="M3U Hash Key"
                      data={[
                        {
                          value: 'name',
                          label: 'Name',
                        },
                        {
                          value: 'url',
                          label: 'URL',
                        },
                        {
                          value: 'tvg_id',
                          label: 'TVG-ID',
                        },
                      ]}
                      {...form.getInputProps('m3u-hash-key')}
                      key={form.key('m3u-hash-key')}
                    />

                    {rehashSuccess && (
                      <Alert
                        variant="light"
                        color="green"
                        title="Rehash task queued successfully"
                      />
                    )}

                    <Flex
                      mih={50}
                      gap="xs"
                      justify="space-between"
                      align="flex-end"
                    >
                      <Button
                        onClick={onRehashStreams}
                        loading={rehashingStreams}
                        variant="outline"
                        color="blue"
                      >
                        Rehash Streams
                      </Button>
                      <Button
                        type="submit"
                        disabled={form.submitting}
                        variant="default"
                      >
                        Save
                      </Button>
                    </Flex>
                  </form>
                </Accordion.Panel>
              </Accordion.Item>

              <Accordion.Item value="user-agents">
                <Accordion.Control>User-Agents</Accordion.Control>
                <Accordion.Panel>
                  <UserAgentsTable />
                </Accordion.Panel>
              </Accordion.Item>

              <Accordion.Item value="stream-profiles">
                <Accordion.Control>Stream Profiles</Accordion.Control>
                <Accordion.Panel>
                  <StreamProfilesTable />
                </Accordion.Panel>
              </Accordion.Item>

              <Accordion.Item value="network-access">
                <Accordion.Control>
                  <Box>Network Access</Box>
                  {accordianValue == 'network-access' && (
                    <Box>
                      <Text size="sm">Comma-Delimited CIDR ranges</Text>
                    </Box>
                  )}
                </Accordion.Control>
                <Accordion.Panel>
                  <form
                    onSubmit={networkAccessForm.onSubmit(onNetworkAccessSubmit)}
                  >
                    <Stack gap="sm">
                      {networkAccessSaved && (
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
                      {Object.entries(NETWORK_ACCESS_OPTIONS).map(
                        ([key, config]) => {
                          return (
                            <TextInput
                              label={config.label}
                              {...networkAccessForm.getInputProps(key)}
                              key={networkAccessForm.key(key)}
                              description={config.description}
                            />
                          );
                        }
                      )}

                      <Flex
                        mih={50}
                        gap="xs"
                        justify="flex-end"
                        align="flex-end"
                      >
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
                </Accordion.Panel>
              </Accordion.Item>

              <Accordion.Item value="proxy-settings">
                <Accordion.Control>
                  <Box>Proxy Settings</Box>
                </Accordion.Control>
                <Accordion.Panel>
                  <form
                    onSubmit={proxySettingsForm.onSubmit(onProxySettingsSubmit)}
                  >
                    <Stack gap="sm">
                      {proxySettingsSaved && (
                        <Alert
                          variant="light"
                          color="green"
                          title="Saved Successfully"
                        ></Alert>
                      )}
                      {Object.entries(PROXY_SETTINGS_OPTIONS).map(
                        ([key, config]) => {
                          // Determine if this field should be a NumberInput
                          const isNumericField = [
                            'buffering_timeout',
                            'redis_chunk_ttl',
                            'channel_shutdown_delay',
                            'channel_init_grace_period',
                          ].includes(key);

                          const isFloatField = key === 'buffering_speed';

                          if (isNumericField) {
                            return (
                              <NumberInput
                                key={key}
                                label={config.label}
                                {...proxySettingsForm.getInputProps(key)}
                                description={config.description || null}
                                min={0}
                                max={
                                  key === 'buffering_timeout'
                                    ? 300
                                    : key === 'redis_chunk_ttl'
                                      ? 3600
                                      : key === 'channel_shutdown_delay'
                                        ? 300
                                        : 60
                                }
                              />
                            );
                          } else if (isFloatField) {
                            return (
                              <NumberInput
                                key={key}
                                label={config.label}
                                {...proxySettingsForm.getInputProps(key)}
                                description={config.description || null}
                                min={0.0}
                                max={10.0}
                                step={0.01}
                                precision={1}
                              />
                            );
                          } else {
                            return (
                              <TextInput
                                key={key}
                                label={config.label}
                                {...proxySettingsForm.getInputProps(key)}
                                description={config.description || null}
                              />
                            );
                          }
                        }
                      )}

                      <Flex
                        mih={50}
                        gap="xs"
                        justify="space-between"
                        align="flex-end"
                      >
                        <Button
                          variant="subtle"
                          color="gray"
                          onClick={resetProxySettingsToDefaults}
                        >
                          Reset to Defaults
                        </Button>
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
                </Accordion.Panel>
              </Accordion.Item>

              <Accordion.Item value="backups">
                <Accordion.Control>Backup & Restore</Accordion.Control>
                <Accordion.Panel>
                  <BackupManager />
                </Accordion.Panel>
              </Accordion.Item>
            </>
          )}
        </Accordion>
      </Box>

      <ConfirmationDialog
        opened={rehashConfirmOpen}
        onClose={() => {
          setRehashConfirmOpen(false);
          setRehashDialogType(null);
        }}
        onConfirm={handleRehashConfirm}
        title={
          rehashDialogType === 'save'
            ? 'Save Settings and Rehash Streams'
            : 'Confirm Stream Rehash'
        }
        message={
          <div style={{ whiteSpace: 'pre-line' }}>
            {`Are you sure you want to rehash all streams?

This process may take a while depending on the number of streams.
Do not shut down Dispatcharr until the rehashing is complete.
M3U refreshes will be blocked until this process finishes.

Please ensure you have time to let this complete before proceeding.`}
          </div>
        }
        confirmLabel={
          rehashDialogType === 'save' ? 'Save and Rehash' : 'Start Rehash'
        }
        cancelLabel="Cancel"
        actionKey="rehash-streams"
        onSuppressChange={suppressWarning}
        size="md"
      />

      <ConfirmationDialog
        opened={networkAccessConfirmOpen}
        onClose={() => setNetworkAccessConfirmOpen(false)}
        onConfirm={saveNetworkAccess}
        title={`Confirm Network Access Blocks`}
        message={
          <>
            <Text>
              Your client is not included in the allowed networks for the web
              UI. Are you sure you want to proceed?
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
    </Center>
  );
};

export default SettingsPage;
