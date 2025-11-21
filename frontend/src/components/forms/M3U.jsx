// Modal.js
import React, { useState, useEffect } from 'react';
import API from '../../api';
import useUserAgentsStore from '../../store/userAgents';
import M3UProfiles from './M3UProfiles';
import {
  LoadingOverlay,
  TextInput,
  Textarea,
  Button,
  Checkbox,
  Modal,
  Flex,
  Select,
  FileInput,
  useMantineTheme,
  NumberInput,
  Divider,
  Stack,
  Group,
  Switch,
  Box,
  PasswordInput,
  Table,
  Badge,
  ActionIcon,
} from '@mantine/core';
import M3UGroupFilter from './M3UGroupFilter';
import useChannelsStore from '../../store/channels';
import { notifications } from '@mantine/notifications';
import { isNotEmpty, useForm } from '@mantine/form';
import useEPGsStore from '../../store/epgs';
import useVODStore from '../../store/useVODStore';
import M3UFilters from './M3UFilters';

const M3U = ({
  m3uAccount = null,
  isOpen,
  onClose,
  playlistCreated = false,
}) => {
  const theme = useMantineTheme();

  const userAgents = useUserAgentsStore((s) => s.userAgents);
  const fetchChannelGroups = useChannelsStore((s) => s.fetchChannelGroups);
  const fetchEPGs = useEPGsStore((s) => s.fetchEPGs);
  const fetchCategories = useVODStore((s) => s.fetchCategories);

  const [playlist, setPlaylist] = useState(null);
  const [file, setFile] = useState(null);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [groupFilterModalOpen, setGroupFilterModalOpen] = useState(false);
  const [filterModalOpen, setFilterModalOpen] = useState(false);
  const [loadingText, setLoadingText] = useState('');
  const [showCredentialFields, setShowCredentialFields] = useState(false);

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      name: '',
      server_url: '',
      user_agent: '0',
      is_active: true,
      max_streams: 0,
      refresh_interval: 24,
      account_type: 'XC',
      create_epg: false,
      username: '',
      password: '',
      stale_stream_days: 7,
      priority: 0,
      enable_vod: false,
      mac_address: '',
      custom_properties: {},
      proxy: '',
      multi_proxy_enabled: false,
    },

    validate: {
      name: isNotEmpty('Please select a name'),
      user_agent: isNotEmpty('Please select a user-agent'),
      refresh_interval: isNotEmpty('Please specify a refresh interval'),
    },
  });

  useEffect(() => {
    if (m3uAccount) {
      setPlaylist(m3uAccount);

      const proxy =
        m3uAccount.custom_properties &&
        typeof m3uAccount.custom_properties === 'object' &&
        m3uAccount.custom_properties.proxy
          ? m3uAccount.custom_properties.proxy
          : '';

      const proxies = (proxy || '')
        .replace(/\r/g, '\n')
        .split(/[\n,]/)
        .map((p) => p.trim())
        .filter(Boolean);

      const multiProxyEnabled = proxies.length > 1;

      form.setValues({
        name: m3uAccount.name,
        server_url: m3uAccount.server_url,
        max_streams: m3uAccount.max_streams,
        user_agent: m3uAccount.user_agent ? `${m3uAccount.user_agent}` : '0',
        is_active: m3uAccount.is_active,
        refresh_interval: m3uAccount.refresh_interval,
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
        mac_address: m3uAccount.mac_address ?? '',
        proxy,
        multi_proxy_enabled: multiProxyEnabled,
      });

      if (m3uAccount.account_type === 'XC') {
        setShowCredentialFields(true);
      } else {
        setShowCredentialFields(false);
      }
    } else {
      setPlaylist(null);
      form.reset();
    }
  }, [m3uAccount]);

  useEffect(() => {
    if (form.values.account_type === 'XC') {
      setShowCredentialFields(true);
    }
  }, [form.values.account_type]);

  // Auto-detect multi-proxy: if more than one proxy is configured, enable it
  useEffect(() => {
    if (form.values.account_type !== 'MAC') {
      form.setFieldValue('multi_proxy_enabled', false);
      return;
    }

    const proxy = form.values.proxy || '';

    const proxies = proxy
      .replace(/\r/g, '\n')
      .split(/[\n,]/)
      .map((p) => p.trim())
      .filter(Boolean);

    form.setFieldValue('multi_proxy_enabled', proxies.length > 1);
  }, [form.values.proxy, form.values.account_type]);

  const onSubmit = async () => {
    const { create_epg, proxy, multi_proxy_enabled, ...values } = form.getValues();

    let custom_properties = {
      ...(playlist?.custom_properties || {}),
      ...(values.custom_properties || {}),
    };

    if (values.account_type === 'MAC') {
      if (proxy && proxy.trim() !== '') {
        custom_properties.proxy = proxy.trim();
      } else {
        delete custom_properties.proxy;
      }

      if (multi_proxy_enabled) {
        custom_properties.multi_proxy_enabled = true;
      } else {
        delete custom_properties.multi_proxy_enabled;
      }
    } else {
      // For non-MAC accounts we never keep multi-proxy enabled
      delete custom_properties.multi_proxy_enabled;
    }

    values.custom_properties = custom_properties;

    if (values.account_type === 'XC' && values.password === '') {
      // If account XC and no password input, assuming no password change
      // from previously stored value.
      delete values.password;
    }

    if (values.user_agent === '0') {
      values.user_agent = null;
    }

    let newPlaylist;
    if (playlist?.id) {
      await API.updatePlaylist({
        id: playlist.id,
        ...values,
        file,
      });
    } else {
      newPlaylist = await API.addPlaylist({
        ...values,
        file,
      });

      if (create_epg && values.account_type === 'XC') {
        API.addEPG({
          name: values.name,
          source_type: 'xmltv',
          url: `${values.server_url}/xmltv.php?username=${values.username}&password=${values.password}`,
          api_key: '',
          is_active: true,
          refresh_interval: 24,
        });
      }

      if (values.account_type !== 'XC' && values.account_type !== 'MAC') {
        notifications.show({
          title: 'Fetching M3U Groups',
          message:
            'Configure group filters and auto sync settings once complete.',
        });

        newPlaylist = null;
        close();
        return;
      }

      // Fetch the updated playlist details (this also updates the store via API)
      const updatedPlaylist = await API.getPlaylist(newPlaylist.id);

      // Note: We don't call fetchPlaylists() here because API.addPlaylist()
      // already added the playlist to the store. Calling fetchPlaylists() creates
      // a race condition where the store is temporarily cleared/replaced while
      // websocket updates for the new playlist's refresh task are arriving.
      await Promise.all([fetchChannelGroups(), fetchEPGs()]);

      // If this is an XC account with VOD enabled, also fetch VOD categories
      if (values.account_type === 'XC' && values.enable_vod) {
        fetchCategories();
      }

      setPlaylist(updatedPlaylist);
      setGroupFilterModalOpen(true);
      return;
    }

    form.reset();
    setFile(null);
    onClose(newPlaylist);
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

  const handleDeleteExpiredMacs = async () => {
    if (!playlist?.id) {
      return;
    }
    try {
      // Du brauchst im API-Client eine Methode API.deleteExpiredMacs (siehe Kommentar unten)
      const res = await API.deleteExpiredMacs(playlist.id);
      const account = res.account || res; // falls du direkt account zurückgibst

      setPlaylist(account);
      form.setFieldValue('mac_address', account.mac_address ?? '');

      const deleted = res.deleted ?? 0;
      notifications.show({
        title: 'MACs aktualisiert',
        message: `${deleted} abgelaufene MAC(s) gelöscht.`,
      });
    } catch (e) {
      console.error(e);
      notifications.show({
        color: 'red',
        title: 'Fehler',
        message: 'Abgelaufene MACs konnten nicht gelöscht werden.',
      });
    }
  };


  const handleDeleteMac = async (macId) => {
    if (!playlist?.id) return;

    try {
      const res = await API.deleteAccountMac(playlist.id, macId);
      const account = res.account || res;

      setPlaylist(account);
      form.setFieldValue('mac_address', account.mac_address ?? '');
    } catch (e) {
      console.error(e);
      notifications.show({
        color: 'red',
        title: 'Fehler',
        message: 'MAC konnte nicht gelöscht werden.',
      });
    }
  };

  const handleMoveMac = async (macId, direction) => {
    if (!playlist?.id) return;

    const macs = playlist?.macs || [];
    const ids = macs.map((m) => m.id);
    const index = ids.indexOf(macId);
    if (index === -1) return;

    if (direction === 'up' && index > 0) {
      [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
    } else if (direction === 'down' && index < ids.length - 1) {
      [ids[index + 1], ids[index]] = [ids[index], ids[index + 1]];
    } else {
      return;
    }

    try {
      const res = await API.reorderAccountMacs(playlist.id, ids);
      const account = res.account || res;

      setPlaylist(account);
      form.setFieldValue('mac_address', account.mac_address ?? '');
    } catch (e) {
      console.error(e);
      notifications.show({
        color: 'red',
        title: 'Fehler',
        message: 'Reihenfolge konnte nicht aktualisiert werden.',
      });
    }
  };

  const macs = playlist?.macs || [];

  if (!isOpen) {
    return <></>;
  }

  return (
    <>
      <Modal size={900} opened={isOpen} onClose={close} title="M3U Account">
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
                label="URL"
                description="Direct URL to the M3U playlist or server"
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
                    MAC / STB-Portal for MAC-based STB portals
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
                    value: 'MAC',
                    label: 'MAC / STB-Portal',
                  },
                ]}
                key={form.key('account_type')}
                {...form.getInputProps('account_type')}
              />

              {form.getValues().account_type === 'MAC' && (
                <>
                  <TextInput
                    style={{ width: '100%' }}
                    id="mac_address"
                    name="mac_address"
                    label="MAC Address(es)"
                    description="Eine oder mehrere MACs (z.B. AA:BB:CC:DD:EE:FF, 11:22:33:44:55:66 oder jede MAC in neuer Zeile)"
                    {...form.getInputProps('mac_address')}
                    key={form.key('mac_address')}
                  />
                  <Textarea
                    autosize
                    minRows={2}
                    style={{ width: '100%' }}
                    id="proxy"
                    name="proxy"
                    label="HTTP Proxy"
                    description="Optional HTTP proxies for MAC account requests. Mehrere Proxies mit Leerzeichen, Komma oder Zeilenumbruch trennen."
                    placeholder="http://proxy1:port1, http://proxy2:port2"
                    {...form.getInputProps('proxy')}
                    key={form.key('proxy')}
                  />
                  <Checkbox
                    mt="xs"
                    id="multi_proxy_enabled"
                    name="multi_proxy_enabled"
                    label="Multi-Proxy aktivieren"
                    description="Wird automatisch aktiv, wenn mehr als ein Proxy im Feld definiert ist."
                    {...form.getInputProps('multi_proxy_enabled', { type: 'checkbox' })}
                    key={form.key('multi_proxy_enabled')}
                    readOnly
                  />
                </>
              )}

              {form.getValues().account_type === 'XC' && (
                <Box>
                  {!m3uAccount && (
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
                      description="Scan and import VOD content (movies/series) from this Xtream account"
                      key={form.key('enable_vod')}
                      {...form.getInputProps('enable_vod', {
                        type: 'checkbox',
                      })}
                    />
                  </Group>

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
                </Box>
              )}

              {form.getValues().account_type !== 'XC' && (
                <>
                  <FileInput
                    id="file"
                    label="Upload files"
                    placeholder="Upload files"
                    description="Upload a local M3U file instead of using URL"
                    onChange={setFile}
                  />

                  {form.getValues().account_type === 'MAC' && macs.length > 0 && (
                    <Box mt="sm">
                      <Group justify="space-between" align="center" mb={4}>
                        <Box fw={500}>MAC-Status</Box>
                        <Button
                          size="xs"
                          variant="outline"
                          color="red"
                          onClick={handleDeleteExpiredMacs}
                        >
                          Abgelaufene MACs löschen
                        </Button>
                      </Group>
                      <Table striped highlightOnHover withTableBorder withColumnBorders>
                        <Table.Thead>
                          <Table.Tr>
                            <Table.Th>#</Table.Th>
                            <Table.Th>MAC</Table.Th>
                            <Table.Th>Status</Table.Th>
                            <Table.Th>Gültig bis</Table.Th>
                            <Table.Th>Aktionen</Table.Th>
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {macs.map((mac, idx) => {
                            let color = 'gray';
                            if (mac.status === 'valid') color = 'green';
                            if (mac.status === 'expired') color = 'red';
                            if (mac.status === 'error') color = 'orange';

                            return (
                              <Table.Tr
                                key={mac.id || idx}
                                style={
                                  mac.status === 'expired'
                                    ? { color: theme.colors.red[6] }
                                    : undefined
                                }
                              >
                                <Table.Td>{mac.priority + 1}</Table.Td>
                                <Table.Td>{mac.address}</Table.Td>
                                <Table.Td>
                                  <Badge color={color} size="sm">
                                    {mac.status}
                                  </Badge>
                                </Table.Td>
                                <Table.Td>
                                  {mac.expires_text ||
                                    mac.expires_at ||
                                    'unbekannt'}
                                </Table.Td>
                                <Table.Td>
                                  <Group gap="xs" justify="flex-end">
                                    <ActionIcon
                                      color="red"
                                      variant="subtle"
                                      onClick={() => handleDeleteMac(mac.id)}
                                      title="MAC löschen"
                                    >
                                      ❌
                                    </ActionIcon>
                                    <ActionIcon
                                      variant="subtle"
                                      onClick={() => handleMoveMac(mac.id, 'up')}
                                      disabled={idx === 0}
                                      title="Nach oben"
                                    >
                                      ↑
                                    </ActionIcon>
                                    <ActionIcon
                                      variant="subtle"
                                      onClick={() => handleMoveMac(mac.id, 'down')}
                                      disabled={idx === macs.length - 1}
                                      title="Nach unten"
                                    >
                                      ↓
                                    </ActionIcon>
                                  </Group>
                                </Table.Td>
                              </Table.Tr>
                            );
                          })}
                        </Table.Tbody>
                      </Table>
                    </Box>
                  )}
                </>
              )}
            </Stack>

            <Divider size="sm" orientation="vertical" />

            <Stack gap="5" style={{ flex: 1 }}>
              <TextInput
                style={{ width: '100%' }}
                id="max_streams"
                name="max_streams"
                label="Max Streams"
                placeholder="0 = Unlimited"
                description="Maximum number of concurrent streams (0 for unlimited)"
                {...form.getInputProps('max_streams')}
                key={form.key('max_streams')}
              />

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

              <NumberInput
                label="Refresh Interval (hours)"
                description={
                  <>
                    How often to automatically refresh M3U data
                    <br />
                    (0 to disable automatic refreshes)
                  </>
                }
                {...form.getInputProps('refresh_interval')}
                key={form.key('refresh_interval')}
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
    </>
  );
};

export default M3U;
