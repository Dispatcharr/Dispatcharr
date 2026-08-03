import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Divider,
  Flex,
  Group,
  Loader,
  Modal,
  MultiSelect,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CircleCheckBig,
  Folder,
  FolderKanban,
  HardDrive,
  Pencil,
  RefreshCw,
  RotateCcwKey,
  ScanSearch,
  Server,
  SquarePlus,
  Trash2,
} from 'lucide-react';

import API from '../api';
import embyLogo from '../assets/media-providers/emby.svg';
import jellyfinLogo from '../assets/media-providers/jellyfin.svg';
import plexLogo from '../assets/media-providers/plex.svg';
import MediaLibraryRunDrawer from '../components/MediaLibraryRunDrawer';
import SafeDirectoryBrowser from '../components/SafeDirectoryBrowser';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';

const emptySource = {
  name: '',
  provider_type: 'local',
  auth_mode: 'token',
  base_url: '',
  api_token: '',
  username: '',
  password: '',
  clear_api_token: false,
  clear_password: false,
  verify_ssl: true,
  enabled: true,
  add_to_vod: true,
  sync_interval: 0,
  sync_interval_value: 0,
  sync_interval_unit: 'hours',
  include_libraries: [],
  library_content_types: {},
  locations: [
    {
      name: '',
      path: '',
      content_type: 'mixed',
      include_subdirectories: true,
      enabled: true,
    },
  ],
};

const intervalMultipliers = { hours: 1, days: 24, weeks: 168 };

const decomposeInterval = (hours) => {
  const value = Math.max(0, Number(hours) || 0);
  if (value && value % 168 === 0) {
    return { sync_interval_value: value / 168, sync_interval_unit: 'weeks' };
  }
  if (value && value % 24 === 0) {
    return { sync_interval_value: value / 24, sync_interval_unit: 'days' };
  }
  return { sync_interval_value: value, sync_interval_unit: 'hours' };
};

const composeInterval = (value, unit) =>
  Math.max(0, Number(value) || 0) * (intervalMultipliers[unit] || 1);

const formatInterval = (hours) => {
  const decomposed = decomposeInterval(hours);
  if (!decomposed.sync_interval_value) return 'Disabled';
  const unit = decomposed.sync_interval_unit.replace(/s$/, '');
  return `${decomposed.sync_interval_value} ${unit}${
    decomposed.sync_interval_value === 1 ? '' : 's'
  }`;
};

const emptyTarget = {
  name: '',
  target_type: 'jellyfin',
  enabled: true,
  output_root: '/data/media/strm',
  playback_base_url: '',
  playback_cidrs: '',
  playback_stream_limit: 0,
  include_nfo: true,
  auto_export_on_vod_change: true,
};

const errorText = (error) => {
  const body = error?.body;
  if (typeof body === 'string') return body;
  if (body?.detail) return body.detail;
  if (body && typeof body === 'object') {
    return Object.entries(body)
      .map(([key, value]) => `${key}: ${[].concat(value).join(', ')}`)
      .join(' · ');
  }
  return error?.message || 'The request failed.';
};

const notifyError = (title, error) =>
  notifications.show({
    title,
    message: errorText(error),
    color: 'red',
    autoClose: 10000,
  });

const statusColor = (value) =>
  value === 'completed' || value === 'success'
    ? 'green'
    : value === 'failed' || value === 'error'
      ? 'red'
      : value === 'running'
        ? 'blue'
        : value === 'cancelled'
          ? 'orange'
          : 'gray';

const providerLabel = (provider) => {
  const normalized = String(provider || '').toLowerCase();
  if (normalized === 'plex') return 'Plex';
  if (normalized === 'jellyfin_emby') return 'Jellyfin/Emby';
  if (normalized === 'emby') return 'Emby';
  if (normalized === 'jellyfin') return 'Jellyfin';
  if (normalized === 'local') return 'Local';
  return provider || 'Unknown';
};

const mediaTypeLabel = (contentType) => {
  if (contentType === 'movie') return 'Movies';
  if (contentType === 'series') return 'TV shows';
  return 'Movies and TV';
};

const mediaTypeOptions = [
  { value: 'movie', label: 'Movies' },
  { value: 'series', label: 'TV shows' },
  { value: 'mixed', label: 'Movies and TV' },
];

function ProviderBadge({ provider }) {
  return (
    <Badge variant="light" color="indigo">
      {providerLabel(provider)}
    </Badge>
  );
}

const providerLogos = {
  plex: plexLogo,
  jellyfin: jellyfinLogo,
  emby: embyLogo,
};

function ImportProviderLogo({ provider }) {
  const logo = providerLogos[String(provider || '').toLowerCase()];

  return (
    <Box
      w={44}
      h={44}
      style={{
        alignItems: 'center',
        backgroundColor: '#18181b',
        border: '1px solid #3f3f46',
        borderRadius: 8,
        display: 'flex',
        flex: '0 0 44px',
        justifyContent: 'center',
      }}
    >
      {logo ? (
        <img
          src={logo}
          alt={`${providerLabel(provider)} logo`}
          style={{ display: 'block', height: 28, width: 28 }}
        />
      ) : (
        <Server aria-label="Local filesystem" size={24} />
      )}
    </Box>
  );
}

function SourceEditor({ opened, source, tmdbSettings, onClose, onSaved }) {
  const [form, setForm] = useState(emptySource);
  const [saving, setSaving] = useState(false);
  const [libraries, setLibraries] = useState([]);
  const [loadingLibraries, setLoadingLibraries] = useState(false);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browseIndex, setBrowseIndex] = useState(null);
  const [plexAuth, setPlexAuth] = useState(null);
  const [plexServers, setPlexServers] = useState([]);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (!opened) return;
    setForm(
      source
        ? {
            ...emptySource,
            ...source,
            ...decomposeInterval(source.sync_interval),
            auth_mode:
              ['emby', 'jellyfin'].includes(source.provider_type) &&
              source.username &&
              !source.has_api_token
                ? 'credentials'
                : 'token',
            api_token: '',
            password: '',
            locations: source.locations?.length
              ? source.locations
              : emptySource.locations,
          }
        : structuredClone(emptySource)
    );
    setLibraries([]);
    setPlexAuth(null);
    setPlexServers([]);
  }, [opened, source]);

  useEffect(() => {
    if (!opened || !source?.id || source.provider_type === 'local') return;
    let active = true;
    setLoadingLibraries(true);
    API.getMediaLibrarySourceLibraries(source.id)
      .then((result) => {
        if (active) setLibraries(result || []);
      })
      .catch((error) => {
        if (active) notifyError('Unable to load provider libraries', error);
      })
      .finally(() => {
        if (active) setLoadingLibraries(false);
      });
    return () => {
      active = false;
    };
  }, [opened, source]);

  const update = (key, value) =>
    setForm((current) => ({ ...current, [key]: value }));

  const updateLocation = (index, key, value) =>
    setForm((current) => ({
      ...current,
      locations: current.locations.map((location, itemIndex) =>
        itemIndex === index ? { ...location, [key]: value } : location
      ),
    }));

  const updateLibraryContentType = (libraryId, contentType) =>
    setForm((current) => ({
      ...current,
      library_content_types: {
        ...(current.library_content_types || {}),
        [String(libraryId)]: contentType,
      },
    }));

  const loadLibraries = async () => {
    if (!form.id) return;
    setLoadingLibraries(true);
    try {
      setLibraries(await API.getMediaLibrarySourceLibraries(form.id));
    } catch (error) {
      notifyError('Unable to load provider libraries', error);
    } finally {
      setLoadingLibraries(false);
    }
  };

  const openBrowser = (index) => {
    setBrowseIndex(index);
    setBrowserOpen(true);
  };

  const startPlex = async () => {
    try {
      const auth = await API.startPlexMediaLibraryAuth();
      setPlexAuth(auth);
      window.open(auth.auth_url, '_blank', 'noopener,noreferrer');
    } catch (error) {
      notifyError('Unable to start Plex authorization', error);
    }
  };

  const checkPlex = useCallback(
    async (quiet = false) => {
      if (!plexAuth) return false;
      try {
        const result = await API.checkPlexMediaLibraryAuth(plexAuth);
        if (!result.claimed) {
          if (!quiet) {
            notifications.show({
              title: 'Plex authorization',
              message: 'Plex has not completed authorization yet.',
              color: 'yellow',
            });
          }
          return false;
        }
        const serverResult = await API.getPlexMediaLibraryServers(
          result.credential_handle
        );
        const servers = serverResult.servers || [];
        setPlexServers(servers);
        if (servers.length === 1) {
          setForm((current) => ({
            ...current,
            base_url: servers[0].base_url,
            plex_credential_handle: servers[0].credential_handle,
            clear_api_token: false,
          }));
        }
        setPlexAuth(null);
        notifications.show({
          title: 'Plex account linked',
          message:
            servers.length === 1
              ? 'The Plex server was selected automatically.'
              : 'Select a Plex server to continue.',
          color: 'green',
        });
        return true;
      } catch (error) {
        notifyError('Unable to complete Plex authorization', error);
        return false;
      }
    },
    [plexAuth]
  );

  useEffect(() => {
    if (!plexAuth) return undefined;
    const timer = window.setInterval(() => checkPlex(true), 2500);
    return () => window.clearInterval(timer);
  }, [checkPlex, plexAuth]);

  const testConfiguration = async () => {
    setTesting(true);
    try {
      const payload = {
        ...form,
        sync_interval: composeInterval(
          form.sync_interval_value,
          form.sync_interval_unit
        ),
      };
      delete payload.auth_mode;
      if (!payload.api_token) delete payload.api_token;
      if (!payload.password) delete payload.password;
      if (payload.provider_type !== 'local') delete payload.locations;
      const result = await API.testMediaLibrarySourceConfiguration(payload);
      setLibraries(result.libraries || []);
      notifications.show({
        title:
          form.provider_type === 'local'
            ? 'Local paths are accessible'
            : 'Connection successful',
        message: `${result.library_count || 0} supported ${
          result.library_count === 1 ? 'library' : 'libraries'
        } found.`,
        color: 'green',
      });
    } catch (error) {
      notifyError('Configuration test failed', error);
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...form };
      delete payload.auth_mode;
      payload.sync_interval = composeInterval(
        payload.sync_interval_value,
        payload.sync_interval_unit
      );
      delete payload.sync_interval_value;
      delete payload.sync_interval_unit;
      if (!payload.api_token) delete payload.api_token;
      if (!payload.password) delete payload.password;
      if (payload.provider_type !== 'local') delete payload.locations;
      await API.saveMediaLibrarySource(payload);
      notifications.show({
        title: 'Media source saved',
        message: 'The source configuration was saved.',
        color: 'green',
      });
      onSaved();
    } catch (error) {
      notifyError('Unable to save media source', error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={source ? 'Edit media source' : 'Add media source'}
        size="xl"
      >
        <Stack>
          <TextInput
            label="Name"
            value={form.name}
            onChange={(event) => update('name', event.currentTarget.value)}
            required
          />
          <Select
            label="Provider"
            value={form.provider_type}
            onChange={(value) => {
              if (value !== form.provider_type) setLibraries([]);
              setForm((current) => ({
                ...current,
                provider_type: value,
                include_libraries:
                  value === current.provider_type
                    ? current.include_libraries
                    : [],
                library_content_types:
                  value === current.provider_type
                    ? current.library_content_types
                    : {},
                auth_mode:
                  ['emby', 'jellyfin'].includes(value) &&
                  ['emby', 'jellyfin'].includes(current.provider_type)
                    ? current.auth_mode
                    : 'token',
              }));
            }}
            data={[
              { value: 'local', label: 'Local filesystem' },
              { value: 'plex', label: 'Plex' },
              { value: 'emby', label: 'Emby' },
              { value: 'jellyfin', label: 'Jellyfin' },
            ]}
          />

          {form.provider_type === 'local' ? (
            <Stack gap="sm">
              <Text size="sm" c="dimmed">
                Paths are limited to the media roots configured for both the web
                and Celery containers. Local imports prefer NFO metadata and use
                filenames as a fallback.
              </Text>
              {!tmdbSettings?.tmdb_configured && (
                <Alert color="yellow">
                  TMDB enrichment is not configured. Imports will still use NFO
                  and filename metadata, but automatic posters and missing
                  metadata will be limited.
                </Alert>
              )}
              {form.locations.map((location, index) => (
                <Card key={location.id || index} withBorder>
                  <Stack gap="xs">
                    <TextInput
                      label="Location name"
                      value={location.name}
                      onChange={(event) =>
                        updateLocation(index, 'name', event.currentTarget.value)
                      }
                    />
                    <Group align="end" wrap="nowrap">
                      <TextInput
                        style={{ flex: 1 }}
                        label="Container path"
                        value={location.path}
                        onChange={(event) =>
                          updateLocation(
                            index,
                            'path',
                            event.currentTarget.value
                          )
                        }
                        required
                      />
                      <Button
                        variant="light"
                        leftSection={<Folder size={16} />}
                        onClick={() => openBrowser(index, location.path)}
                      >
                        Browse
                      </Button>
                    </Group>
                    <Select
                      label="Content"
                      value={location.content_type}
                      onChange={(value) =>
                        updateLocation(index, 'content_type', value)
                      }
                      data={mediaTypeOptions}
                    />
                    <Switch
                      label="Include subdirectories"
                      checked={location.include_subdirectories}
                      onChange={(event) =>
                        updateLocation(
                          index,
                          'include_subdirectories',
                          event.currentTarget.checked
                        )
                      }
                    />
                    <Switch
                      label="Location enabled"
                      checked={location.enabled !== false}
                      onChange={(event) =>
                        updateLocation(
                          index,
                          'enabled',
                          event.currentTarget.checked
                        )
                      }
                    />
                    <Button
                      color="red"
                      variant="subtle"
                      onClick={() =>
                        update(
                          'locations',
                          form.locations.filter(
                            (_, itemIndex) => itemIndex !== index
                          )
                        )
                      }
                      disabled={form.locations.length === 1}
                    >
                      Remove location
                    </Button>
                  </Stack>
                </Card>
              ))}
              <Button
                variant="light"
                onClick={() =>
                  update('locations', [
                    ...form.locations,
                    structuredClone(emptySource.locations[0]),
                  ])
                }
              >
                Add location
              </Button>
            </Stack>
          ) : (
            <>
              <TextInput
                label="Server URL"
                value={form.base_url}
                onChange={(event) =>
                  update('base_url', event.currentTarget.value)
                }
                required
              />
              {form.provider_type === 'plex' && (
                <Group>
                  <Button variant="light" onClick={startPlex}>
                    Authorize with Plex
                  </Button>
                  {plexAuth && (
                    <>
                      <Text size="sm" c="dimmed">
                        Waiting for Plex authorization…
                      </Text>
                      <Button onClick={() => checkPlex(false)}>
                        Check now
                      </Button>
                    </>
                  )}
                </Group>
              )}
              {plexServers.length > 0 && (
                <Select
                  label="Plex server"
                  data={plexServers.map((server) => ({
                    value: server.base_url,
                    label: server.name,
                  }))}
                  onChange={(value) => {
                    const server = plexServers.find(
                      (item) => item.base_url === value
                    );
                    update('base_url', value);
                    if (server?.credential_handle) {
                      update(
                        'plex_credential_handle',
                        server.credential_handle
                      );
                      update('clear_api_token', false);
                    }
                  }}
                />
              )}
              {['emby', 'jellyfin'].includes(form.provider_type) && (
                <Select
                  label="Authentication"
                  value={form.auth_mode}
                  data={[
                    { value: 'token', label: 'API key / token' },
                    {
                      value: 'credentials',
                      label: 'Account login (username + password)',
                    },
                  ]}
                  onChange={(value) =>
                    setForm((current) => ({
                      ...current,
                      auth_mode: value,
                      api_token:
                        value === 'credentials' ? '' : current.api_token,
                      clear_api_token:
                        value === 'credentials'
                          ? Boolean(current.has_api_token)
                          : false,
                      username: value === 'token' ? '' : current.username,
                      password: value === 'token' ? '' : current.password,
                      clear_password:
                        value === 'token'
                          ? Boolean(current.has_password)
                          : false,
                    }))
                  }
                />
              )}
              {(form.provider_type === 'plex' ||
                form.auth_mode === 'token') && (
                <>
                  <PasswordInput
                    label={
                      form.has_api_token
                        ? 'API token (leave blank to preserve)'
                        : 'API token'
                    }
                    value={form.api_token}
                    disabled={form.clear_api_token}
                    onChange={(event) => {
                      update('api_token', event.currentTarget.value);
                      if (event.currentTarget.value)
                        update('clear_api_token', false);
                    }}
                  />
                  {form.has_api_token && (
                    <Switch
                      label="Explicitly clear the saved API token"
                      checked={form.clear_api_token}
                      onChange={(event) =>
                        update('clear_api_token', event.currentTarget.checked)
                      }
                    />
                  )}
                </>
              )}
              {['emby', 'jellyfin'].includes(form.provider_type) &&
                form.auth_mode === 'credentials' && (
                  <>
                    <TextInput
                      label="Username"
                      value={form.username}
                      onChange={(event) =>
                        update('username', event.currentTarget.value)
                      }
                    />
                    <PasswordInput
                      label={
                        form.has_password
                          ? 'Password (leave blank to preserve)'
                          : 'Password'
                      }
                      value={form.password}
                      disabled={form.clear_password}
                      onChange={(event) => {
                        update('password', event.currentTarget.value);
                        if (event.currentTarget.value)
                          update('clear_password', false);
                      }}
                    />
                    {form.has_password && (
                      <Switch
                        label="Explicitly clear the saved password"
                        checked={form.clear_password}
                        onChange={(event) =>
                          update('clear_password', event.currentTarget.checked)
                        }
                      />
                    )}
                  </>
                )}
              <Switch
                label="Verify TLS certificates"
                checked={form.verify_ssl}
                onChange={(event) =>
                  update('verify_ssl', event.currentTarget.checked)
                }
              />
              {(form.id || libraries.length > 0) && (
                <>
                  {form.id && (
                    <Button
                      variant="light"
                      loading={loadingLibraries}
                      onClick={loadLibraries}
                    >
                      Reload libraries
                    </Button>
                  )}
                  {libraries.length > 0 && (
                    <Stack gap="sm">
                      <MultiSelect
                        label="Libraries (empty selects all)"
                        description="Choose which provider libraries are included in synchronization."
                        data={libraries.map((library) => ({
                          value: String(library.id),
                          label: `${library.name} (${mediaTypeLabel(
                            library.content_type
                          )})`,
                        }))}
                        value={(form.include_libraries || []).map(String)}
                        onChange={(value) => update('include_libraries', value)}
                        searchable
                      />
                      <Text size="sm" fw={500}>
                        Library media types
                      </Text>
                      <Text size="xs" c="dimmed" mt={-8}>
                        Automatic detection is used by default. Override it when
                        a server library contains a different kind of media.
                      </Text>
                      {libraries
                        .filter(
                          (library) =>
                            !(form.include_libraries || []).length ||
                            (form.include_libraries || [])
                              .map(String)
                              .includes(String(library.id))
                        )
                        .map((library) => (
                          <Card key={library.id} withBorder padding="sm">
                            <Group
                              justify="space-between"
                              align="end"
                              wrap="wrap"
                            >
                              <Box style={{ flex: 1, minWidth: 180 }}>
                                <Text fw={500}>{library.name}</Text>
                                <Text size="xs" c="dimmed">
                                  Detected as{' '}
                                  {mediaTypeLabel(library.content_type)}
                                </Text>
                              </Box>
                              <Select
                                label="Import as"
                                data={mediaTypeOptions}
                                value={
                                  form.library_content_types?.[
                                    String(library.id)
                                  ] || library.content_type
                                }
                                onChange={(value) =>
                                  updateLibraryContentType(library.id, value)
                                }
                                allowDeselect={false}
                                w={220}
                              />
                            </Group>
                          </Card>
                        ))}
                    </Stack>
                  )}
                </>
              )}
            </>
          )}
          <Divider />
          <Button variant="light" loading={testing} onClick={testConfiguration}>
            {form.provider_type === 'local'
              ? 'Test local paths'
              : 'Test connection and discover libraries'}
          </Button>
          <Switch
            label="Enabled"
            checked={form.enabled}
            onChange={(event) => update('enabled', event.currentTarget.checked)}
          />
          <Switch
            label="Add imported content to VOD"
            checked={form.add_to_vod}
            onChange={(event) =>
              update('add_to_vod', event.currentTarget.checked)
            }
          />
          <Group grow align="end">
            <NumberInput
              label="Automatic import interval"
              description="Set 0 to disable"
              min={0}
              value={form.sync_interval_value}
              onChange={(value) =>
                update('sync_interval_value', Number(value) || 0)
              }
            />
            <Select
              label="Unit"
              value={form.sync_interval_unit}
              onChange={(value) => update('sync_interval_unit', value)}
              data={[
                { value: 'hours', label: 'Hours' },
                { value: 'days', label: 'Days' },
                { value: 'weeks', label: 'Weeks' },
              ]}
            />
          </Group>
          <Group justify="end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button loading={saving} onClick={save}>
              Save source
            </Button>
          </Group>
        </Stack>
      </Modal>

      <SafeDirectoryBrowser
        opened={browserOpen}
        onClose={() => setBrowserOpen(false)}
        scope="media-library-import"
        initialPath={
          browseIndex === null ? '' : form.locations[browseIndex]?.path || ''
        }
        title="Select local media directory"
        onSelect={(path) => {
          if (browseIndex !== null) {
            updateLocation(browseIndex, 'path', path);
          }
          setBrowserOpen(false);
        }}
      />
    </>
  );
}

export function SourceCard({
  source,
  latestRun,
  busy,
  onToggle,
  onTest,
  onSync,
  onViewScan,
  onEdit,
  onDelete,
}) {
  const scanActive = ['pending', 'queued', 'running'].includes(
    latestRun?.status
  );
  const scanMetrics = latestRun
    ? [
        ['Processed', latestRun.processed_items],
        ['Created', latestRun.created_items],
        ['Updated', latestRun.updated_items],
        ['Stale relations', latestRun.removed_items],
        ['Skipped', latestRun.skipped_items],
        ['Ambiguous', latestRun.ambiguous_items],
      ]
    : [];

  return (
    <Card
      data-testid="media-library-source-card"
      withBorder
      radius="md"
      p="md"
      style={{
        backgroundColor: '#27272A',
        borderColor: '#3f3f46',
        height: '100%',
      }}
    >
      <Stack gap="md" style={{ height: '100%' }}>
        <Box
          style={{
            alignItems: 'start',
            display: 'grid',
            gap: '1rem',
            gridTemplateColumns: 'minmax(0, 1fr) auto',
          }}
        >
          <Group gap="sm" align="flex-start" wrap="nowrap" miw={0}>
            <ImportProviderLogo provider={source.provider_type} />
            <Stack gap={2} miw={0}>
              <Text fw={700}>{source.name}</Text>
              <Text size="xs" c="dimmed" style={{ overflowWrap: 'anywhere' }}>
                {source.provider_type === 'local'
                  ? 'Local filesystem import'
                  : source.base_url}
              </Text>
            </Stack>
          </Group>
          <Switch
            label="Enabled"
            checked={!!source.enabled}
            onChange={(event) => onToggle(event.currentTarget.checked)}
            disabled={busy}
          />
        </Box>

        <Box
          p="sm"
          style={{
            backgroundColor: '#202023',
            border: '1px solid #3f3f46',
            borderRadius: 8,
          }}
        >
          <Group gap={8} mb="sm">
            <FolderKanban size={16} />
            <Text size="sm" fw={500}>
              {Array.isArray(source.include_libraries) &&
              source.include_libraries.length > 0
                ? `${source.include_libraries.length} selected librar${
                    source.include_libraries.length > 1 ? 'ies' : 'y'
                  }`
                : 'All media libraries'}
            </Text>
          </Group>
          <Box
            style={{
              display: 'grid',
              gap: '0.75rem',
              gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
            }}
          >
            <Box>
              <Text size="xs" c="dimmed">
                Last synchronized
              </Text>
              <Text size="sm">
                {source.last_synced_at
                  ? new Date(source.last_synced_at).toLocaleString()
                  : 'Never'}
              </Text>
            </Box>
            <Box>
              <Text size="xs" c="dimmed">
                Automatic sync
              </Text>
              <Text size="sm">{formatInterval(source.sync_interval)}</Text>
            </Box>
          </Box>
        </Box>

        <Box>
          <Group justify="space-between" mb="xs">
            <Text size="xs" fw={700} tt="uppercase" c="dimmed">
              {scanActive ? 'Current scan' : 'Latest scan'}
            </Text>
            {latestRun?.status && (
              <Text size="xs" c={statusColor(latestRun.status)}>
                {latestRun.status}
              </Text>
            )}
          </Group>
          {latestRun ? (
            <Box
              data-testid="source-scan-summary"
              p="sm"
              style={{
                backgroundColor: '#202023',
                border: '1px solid #3f3f46',
                borderRadius: 8,
              }}
            >
              <Box
                style={{
                  display: 'grid',
                  gap: '0.9rem 1rem',
                  gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                }}
              >
                {scanMetrics.map(([label, value]) => (
                  <Box key={label}>
                    <Text
                      fw={700}
                      size="lg"
                      style={{ fontVariantNumeric: 'tabular-nums' }}
                    >
                      {(Number(value) || 0).toLocaleString()}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {label === 'Ambiguous' ? (
                        <Tooltip
                          multiline
                          w={320}
                          withArrow
                          label="Dispatcharr found multiple plausible records or conflicting identifiers, so it skipped the item instead of merging it automatically. Ambiguous items are included in the skipped count."
                        >
                          <Text
                            component="span"
                            size="xs"
                            c="dimmed"
                            style={{
                              cursor: 'help',
                              textDecoration: 'underline dotted',
                              textUnderlineOffset: 3,
                            }}
                          >
                            {label}
                          </Text>
                        </Tooltip>
                      ) : (
                        label
                      )}
                    </Text>
                  </Box>
                ))}
              </Box>
              {['failed', 'cancelled'].includes(latestRun.status) &&
                latestRun.message && (
                  <Text size="xs" c="red" mt="sm" lineClamp={2}>
                    {latestRun.message}
                  </Text>
                )}
            </Box>
          ) : (
            <Box
              p="sm"
              style={{
                backgroundColor: '#202023',
                border: '1px solid #3f3f46',
                borderRadius: 8,
              }}
            >
              <Text size="sm" c="dimmed">
                No scans have run yet.
              </Text>
            </Box>
          )}
        </Box>

        <Box
          data-testid="source-action-bar"
          mt="auto"
          pt="md"
          style={{ borderTop: '1px solid #3f3f46' }}
        >
          <Box
            data-testid="source-actions-row"
            style={{
              display: 'grid',
              gap: '0.375rem',
              gridTemplateColumns: '0.9fr 0.95fr 1.3fr 0.75fr 0.9fr',
              width: '100%',
            }}
          >
            <Button
              size="xs"
              variant="light"
              fullWidth
              px={6}
              leftSection={<CircleCheckBig size={14} />}
              onClick={onTest}
              loading={busy}
            >
              Test
            </Button>
            <Button
              size="xs"
              variant="light"
              fullWidth
              px={6}
              leftSection={<RefreshCw size={14} />}
              onClick={onSync}
              loading={busy}
            >
              Sync
            </Button>
            <Button
              size="xs"
              variant="default"
              fullWidth
              px={6}
              leftSection={<ScanSearch size={14} />}
              onClick={onViewScan}
            >
              View Scan
            </Button>
            <Button
              size="xs"
              variant="default"
              fullWidth
              px={6}
              onClick={onEdit}
              disabled={busy}
            >
              Edit
            </Button>
            <Button
              size="xs"
              color="red"
              variant="outline"
              fullWidth
              px={6}
              onClick={onDelete}
              disabled={busy}
            >
              Delete
            </Button>
          </Box>
        </Box>
      </Stack>
    </Card>
  );
}

function ExportCard({ target, busy, onSync, onEdit, onDelete }) {
  const summary = target.last_export_summary || null;
  return (
    <Card
      withBorder
      radius="md"
      p="md"
      style={{ backgroundColor: '#27272A', borderColor: '#3f3f46' }}
    >
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Group gap={8}>
              <HardDrive size={16} />
              <Text fw={700}>{target.name || 'Dispatcharr Output'}</Text>
            </Group>
            <Text size="xs" c="dimmed">
              Jellyfin/Emby output via STRM + NFO files.
            </Text>
          </Stack>
          <Badge variant="light" color="indigo">
            Export
          </Badge>
        </Group>

        <Group gap="xs">
          <ProviderBadge provider={target.target_type} />
          <Badge variant="outline" color={target.enabled ? 'green' : 'gray'}>
            {target.enabled ? 'Enabled' : 'Disabled'}
          </Badge>
          <Badge variant="outline" color="blue">
            STRM/NFO
          </Badge>
        </Group>

        <Text size="xs" c="dimmed">
          Output path: {target.output_root}
        </Text>
        {summary ? (
          <Text size="xs" c="dimmed">
            Items: {summary.strm_files_written || 0} (Movies:{' '}
            {summary.movies_written || 0}, Series: {summary.series_written || 0}
            , Episodes: {summary.episodes_written || 0})
          </Text>
        ) : null}
        {target.last_export_message ? (
          <Text size="xs" c="dimmed" lineClamp={2}>
            {target.last_export_message}
          </Text>
        ) : null}

        <Flex justify="flex-end" gap="xs" mt="sm" wrap="wrap">
          <Button
            size="xs"
            variant="light"
            leftSection={<RefreshCw size={14} />}
            loading={busy}
            onClick={onSync}
          >
            Sync
          </Button>
          <Button
            size="xs"
            variant="light"
            leftSection={<Pencil size={14} />}
            onClick={onEdit}
          >
            Edit
          </Button>
          <Button
            size="xs"
            color="red"
            variant="outline"
            leftSection={<Trash2 size={14} />}
            onClick={onDelete}
          >
            Delete
          </Button>
        </Flex>
      </Stack>
    </Card>
  );
}

function ExportEditor({ opened, target, onClose, onSaved }) {
  const [form, setForm] = useState(emptyTarget);
  const [saving, setSaving] = useState(false);
  const [browserOpen, setBrowserOpen] = useState(false);
  useEffect(() => {
    if (opened)
      setForm(target ? { ...emptyTarget, ...target } : { ...emptyTarget });
  }, [opened, target]);
  const update = (key, value) =>
    setForm((current) => ({ ...current, [key]: value }));
  const save = async (buildAfter = false) => {
    setSaving(true);
    try {
      const saved = await API.saveMediaLibraryExportTarget(form);
      if (buildAfter) {
        await API.buildMediaLibraryExport(saved.id);
        notifications.show({
          title: 'Export target saved',
          message: 'The initial STRM/NFO build was queued.',
          color: 'green',
        });
      }
      onSaved();
    } catch (error) {
      notifyError('Unable to save export target', error);
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={target ? 'Edit export target' : 'Add export target'}
        size="lg"
      >
        <Stack>
          <TextInput
            label="Name"
            value={form.name}
            onChange={(event) => update('name', event.currentTarget.value)}
            required
          />
          <Select
            label="Media server"
            value={form.target_type}
            onChange={(value) => update('target_type', value)}
            data={[
              { value: 'jellyfin', label: 'Jellyfin' },
              { value: 'emby', label: 'Emby' },
            ]}
          />
          <Group align="end" wrap="nowrap">
            <TextInput
              style={{ flex: 1 }}
              label="Export directory inside Dispatcharr/Celery"
              value={form.output_root}
              onChange={(event) =>
                update('output_root', event.currentTarget.value)
              }
              required
            />
            <Button
              variant="light"
              leftSection={<Folder size={16} />}
              onClick={() => setBrowserOpen(true)}
            >
              Browse
            </Button>
          </Group>
          <TextInput
            label="Public Dispatcharr base URL"
            description="The URL Jellyfin/Emby can reach. No credentials are written to STRM files."
            value={form.playback_base_url}
            onChange={(event) =>
              update('playback_base_url', event.currentTarget.value)
            }
            required
          />
          <TextInput
            label="Allowed playback CIDRs"
            description="Required. Comma-separated networks containing the Jellyfin/Emby server."
            value={form.playback_cidrs}
            onChange={(event) =>
              update('playback_cidrs', event.currentTarget.value)
            }
            required
          />
          <NumberInput
            label="Target stream limit (0 is unlimited)"
            min={0}
            value={form.playback_stream_limit}
            onChange={(value) =>
              update('playback_stream_limit', Number(value) || 0)
            }
          />
          <Switch
            label="Enabled"
            checked={form.enabled}
            onChange={(event) => update('enabled', event.currentTarget.checked)}
          />
          <Switch
            label="Write NFO metadata"
            checked={form.include_nfo}
            onChange={(event) =>
              update('include_nfo', event.currentTarget.checked)
            }
          />
          <Switch
            label="Rebuild after VOD changes"
            checked={form.auto_export_on_vod_change}
            onChange={(event) =>
              update('auto_export_on_vod_change', event.currentTarget.checked)
            }
          />
          <Text size="xs" c="dimmed">
            Example media-server mounts:
          </Text>
          <Text
            component="pre"
            p="sm"
            style={{
              border: '1px solid var(--mantine-color-dark-4)',
              borderRadius: 6,
              fontFamily: 'monospace',
              fontSize: '0.78rem',
              whiteSpace: 'pre-wrap',
            }}
          >
            {`- "${form.output_root}/Movies:${form.output_root}/Movies:ro"\n- "${form.output_root}/TV Shows:${form.output_root}/TV Shows:ro"`}
          </Text>
          {target?.id && (
            <>
              <Divider label="Advanced" />
              <Group>
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<RotateCcwKey size={14} />}
                  onClick={async () => {
                    if (
                      !window.confirm(
                        'Rotate this target playback ID? Existing STRM URLs will stop working until rebuilt.'
                      )
                    )
                      return;
                    try {
                      await API.rotateMediaLibraryPlaybackId(target.id);
                      notifications.show({
                        title: 'Playback identifier rotated',
                        message: 'A rebuild has been queued.',
                        color: 'green',
                      });
                      onSaved();
                    } catch (error) {
                      notifyError('Unable to rotate playback ID', error);
                    }
                  }}
                >
                  Rotate playback ID
                </Button>
                <Button
                  size="xs"
                  color="orange"
                  variant="light"
                  leftSection={<FolderKanban size={14} />}
                  onClick={async () => {
                    if (
                      !window.confirm(
                        `Remove only the generated files managed for ${target.name}?`
                      )
                    )
                      return;
                    try {
                      const result = await API.cleanupMediaLibraryExportFiles(
                        target.id
                      );
                      notifications.show({
                        title: 'Generated files removed',
                        message: `${result.managed_files_deleted || 0} managed files removed.`,
                        color: 'green',
                      });
                      onSaved();
                    } catch (error) {
                      notifyError('Unable to clean generated files', error);
                    }
                  }}
                >
                  Remove generated files
                </Button>
              </Group>
            </>
          )}
          <Group justify="end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="light"
              loading={saving}
              onClick={() => save(false)}
            >
              Save
            </Button>
            <Button loading={saving} onClick={() => save(true)}>
              Save and build
            </Button>
          </Group>
        </Stack>
      </Modal>
      <SafeDirectoryBrowser
        opened={browserOpen}
        onClose={() => setBrowserOpen(false)}
        scope="media-library-export"
        initialPath={form.output_root}
        title="Select export directory"
        onSelect={(path) => {
          update('output_root', path);
          setBrowserOpen(false);
        }}
      />
    </>
  );
}

export default function MediaLibrary() {
  const user = useAuthStore((state) => state.user);
  const [sources, setSources] = useState([]);
  const [targets, setTargets] = useState([]);
  const [importRuns, setImportRuns] = useState([]);
  const [exportRuns, setExportRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sourceEditor, setSourceEditor] = useState(undefined);
  const [targetEditor, setTargetEditor] = useState(undefined);
  const [integrationTypeOpen, setIntegrationTypeOpen] = useState(false);
  const [tmdbSettings, setTmdbSettings] = useState(null);
  const [runSource, setRunSource] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [sourceData, targetData, imports, exports, mediaSettings] =
        await Promise.all([
          API.getMediaLibrarySources(),
          API.getMediaLibraryExportTargets(),
          API.getMediaLibraryImportRuns(),
          API.getMediaLibraryExportRuns(),
          API.getMediaLibrarySettings(),
        ]);
      setSources(sourceData);
      setTargets(targetData);
      setImportRuns(imports);
      setExportRuns(exports);
      setTmdbSettings(mediaSettings);
    } catch (error) {
      notifyError('Unable to load Media Library', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const handleImportUpdate = (event) => {
      const incoming = event.detail;
      if (!incoming?.id) return;
      const incomingSource = incoming.source ?? incoming.integration;
      setImportRuns((current) => {
        const next = [...current];
        const index = next.findIndex((run) => run.id === incoming.id);
        if (index === -1) next.unshift(incoming);
        else next[index] = incoming;
        return next;
      });
      setSources((current) =>
        current.map((source) =>
          Number(source.id) === Number(incomingSource)
            ? {
                ...source,
                last_sync_status:
                  incoming.status === 'completed'
                    ? 'success'
                    : incoming.status === 'failed' ||
                        incoming.status === 'cancelled'
                      ? 'error'
                      : 'running',
                last_sync_message: incoming.message,
              }
            : source
        )
      );
    };
    window.addEventListener('media_library_import_updated', handleImportUpdate);
    return () =>
      window.removeEventListener(
        'media_library_import_updated',
        handleImportUpdate
      );
  }, []);

  const startImport = async (source) => {
    try {
      await API.syncMediaLibrarySource(source.id);
      await refresh();
    } catch (error) {
      notifyError('Unable to start import', error);
      throw error;
    }
  };

  const activeCount = useMemo(
    () =>
      [...importRuns, ...exportRuns].filter((run) =>
        ['pending', 'queued', 'running'].includes(run.status)
      ).length,
    [importRuns, exportRuns]
  );

  if (user?.user_level < USER_LEVELS.ADMIN) {
    return (
      <Alert color="red">
        Media Library management is restricted to administrators.
      </Alert>
    );
  }
  if (loading) return <Loader m="xl" />;

  const afterEdit = () => {
    setSourceEditor(undefined);
    setTargetEditor(undefined);
    refresh();
  };

  return (
    <Box p="md">
      <Group justify="space-between" mb="md">
        <Title order={3}>Media Library</Title>
        <Button
          leftSection={<SquarePlus size={14} />}
          variant="light"
          size="xs"
          onClick={() => setIntegrationTypeOpen(true)}
          p={5}
          color="green"
          style={{
            borderWidth: '1px',
            borderColor: 'green',
            color: 'white',
          }}
        >
          Add Media Server
        </Button>
      </Group>

      <Tabs defaultValue="integrations">
        <Tabs.List>
          <Tabs.Tab value="integrations">Integrations</Tabs.Tab>
          <Tabs.Tab value="activity">
            Activity
            {activeCount > 0 ? ` (${activeCount})` : ''}
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="integrations" pt="md">
          <Box
            style={{
              display: 'grid',
              gap: '1rem',
              gridTemplateColumns:
                'repeat(auto-fill, minmax(min(380px, 100%), 1fr))',
            }}
          >
            {targets.map((target) => {
              const busy = exportRuns.some(
                (run) =>
                  Number(run.target) === Number(target.id) &&
                  ['pending', 'queued', 'running'].includes(run.status)
              );
              return (
                <ExportCard
                  key={`dispatcharr-export-${target.id}`}
                  target={target}
                  busy={busy}
                  onSync={async () => {
                    try {
                      await API.buildMediaLibraryExport(target.id);
                      refresh();
                    } catch (error) {
                      notifyError('Unable to start export', error);
                    }
                  }}
                  onEdit={() => setTargetEditor(target)}
                  onDelete={async () => {
                    if (
                      !window.confirm(
                        `Delete export target ${target.name}? Generated files are retained.`
                      )
                    )
                      return;
                    try {
                      await API.deleteMediaLibraryExportTarget(target.id);
                      refresh();
                    } catch (error) {
                      notifyError('Unable to delete target', error);
                    }
                  }}
                />
              );
            })}
            {sources.map((source) => {
              const busy = importRuns.some(
                (run) =>
                  Number(run.source ?? run.integration) === Number(source.id) &&
                  ['pending', 'queued', 'running'].includes(run.status)
              );
              return (
                <SourceCard
                  key={source.id}
                  source={source}
                  latestRun={importRuns.find(
                    (run) =>
                      Number(run.source ?? run.integration) ===
                      Number(source.id)
                  )}
                  busy={busy}
                  onToggle={async (enabled) => {
                    try {
                      await API.saveMediaLibrarySource({
                        id: source.id,
                        enabled,
                      });
                      refresh();
                    } catch (error) {
                      notifyError('Unable to update source', error);
                    }
                  }}
                  onTest={async () => {
                    try {
                      const result = await API.testMediaLibrarySource(
                        source.id
                      );
                      notifications.show({
                        title: 'Connection successful',
                        message: `${result.libraries?.length || 0} libraries found.`,
                        color: 'green',
                      });
                    } catch (error) {
                      notifyError('Connection test failed', error);
                    }
                  }}
                  onSync={() => startImport(source)}
                  onViewScan={() => setRunSource(source)}
                  onEdit={() => setSourceEditor(source)}
                  onDelete={async () => {
                    if (
                      !window.confirm(
                        `Delete ${source.name} and its source relations?`
                      )
                    )
                      return;
                    try {
                      await API.deleteMediaLibrarySource(source.id);
                      refresh();
                    } catch (error) {
                      notifyError('Unable to delete source', error);
                    }
                  }}
                />
              );
            })}
            {!sources.length && !targets.length ? (
              <Card
                withBorder
                radius="md"
                p="xl"
                style={{
                  backgroundColor: '#27272A',
                  borderColor: '#3f3f46',
                }}
              >
                <Stack align="center" gap="sm">
                  <Server size={24} />
                  <Text fw={600}>No integrations configured</Text>
                  <Text size="sm" c="dimmed" ta="center">
                    Add an import integration to ingest content, or add an
                    output integration to publish VODs.
                  </Text>
                </Stack>
              </Card>
            ) : null}
          </Box>
        </Tabs.Panel>

        <Tabs.Panel value="activity" pt="md">
          <Group justify="space-between" mb="sm">
            <Title order={4}>Import runs</Title>
            <Button
              size="xs"
              variant="light"
              onClick={() => API.purgeMediaLibraryImportRuns().then(refresh)}
            >
              Clear finished imports
            </Button>
          </Group>
          <Table striped withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Source</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Progress</Table.Th>
                <Table.Th>Message</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {importRuns.slice(0, 50).map((run) => (
                <Table.Tr key={run.id}>
                  <Table.Td>{run.integration_name}</Table.Td>
                  <Table.Td>
                    <Badge color={statusColor(run.status)}>{run.status}</Badge>
                  </Table.Td>
                  <Table.Td>
                    {run.processed_items} processed / {run.created_items}{' '}
                    created / {run.updated_items} updated / {run.removed_items}{' '}
                    removed / {run.ambiguous_items} ambiguous
                  </Table.Td>
                  <Table.Td>{run.message}</Table.Td>
                  <Table.Td>
                    {['pending', 'queued', 'running'].includes(run.status) && (
                      <Button
                        size="xs"
                        color="orange"
                        onClick={() =>
                          API.cancelMediaLibraryImportRun(run.id).then(refresh)
                        }
                      >
                        Cancel
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Group justify="space-between" mt="xl" mb="sm">
            <Title order={4}>Export runs</Title>
            <Button
              size="xs"
              variant="light"
              onClick={() => API.purgeMediaLibraryExportRuns().then(refresh)}
            >
              Clear finished exports
            </Button>
          </Group>
          <Table striped withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Target</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Reason</Table.Th>
                <Table.Th>Message</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {exportRuns.slice(0, 50).map((run) => (
                <Table.Tr key={run.id}>
                  <Table.Td>{run.target_name}</Table.Td>
                  <Table.Td>
                    <Badge color={statusColor(run.status)}>{run.status}</Badge>
                  </Table.Td>
                  <Table.Td>{run.reason}</Table.Td>
                  <Table.Td>{run.message}</Table.Td>
                  <Table.Td>
                    {['pending', 'queued', 'running'].includes(run.status) && (
                      <Button
                        size="xs"
                        color="orange"
                        onClick={() =>
                          API.cancelMediaLibraryExportRun(run.id).then(refresh)
                        }
                      >
                        Cancel
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>
      </Tabs>

      <Modal
        opened={integrationTypeOpen}
        onClose={() => setIntegrationTypeOpen(false)}
        size="md"
        title="New Integration"
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            Choose whether Dispatcharr should ingest media from a source, or
            publish Dispatcharr VODs to an external media server.
          </Text>

          <Card
            withBorder
            radius="md"
            p="md"
            style={{ borderColor: '#3f3f46' }}
          >
            <Stack gap="xs">
              <Group gap="xs">
                <ArrowDownToLine size={16} />
                <Text fw={600}>Import Media into Dispatcharr</Text>
              </Group>
              <Text size="sm" c="dimmed">
                Bring your existing media (Plex, Emby, Jellyfin, or folders)
                into Dispatcharr to create VOD content.
              </Text>
              <Flex justify="flex-end">
                <Button
                  size="xs"
                  variant="light"
                  onClick={() => {
                    setIntegrationTypeOpen(false);
                    setSourceEditor(null);
                  }}
                >
                  Import
                </Button>
              </Flex>
            </Stack>
          </Card>

          <Card
            withBorder
            radius="md"
            p="md"
            style={{ borderColor: '#3f3f46' }}
          >
            <Stack gap="xs">
              <Group gap="xs">
                <ArrowUpFromLine size={16} />
                <Text fw={600}>Export VOD to Media Server</Text>
              </Group>
              <Text size="sm" c="dimmed">
                Export VOD files as STRM/NFO output for Jellyfin or Emby. (Not
                currently available for Plex.)
              </Text>
              <Flex justify="flex-end">
                <Button
                  size="xs"
                  variant="light"
                  onClick={() => {
                    setIntegrationTypeOpen(false);
                    setTargetEditor(null);
                  }}
                >
                  Export
                </Button>
              </Flex>
            </Stack>
          </Card>
        </Stack>
      </Modal>

      <SourceEditor
        opened={sourceEditor !== undefined}
        source={sourceEditor}
        tmdbSettings={tmdbSettings}
        onClose={() => setSourceEditor(undefined)}
        onSaved={afterEdit}
      />
      <ExportEditor
        opened={targetEditor !== undefined}
        target={targetEditor}
        onClose={() => setTargetEditor(undefined)}
        onSaved={afterEdit}
      />
      <MediaLibraryRunDrawer
        opened={!!runSource}
        source={runSource}
        onClose={() => setRunSource(null)}
        onRun={startImport}
        onChanged={refresh}
      />
    </Box>
  );
}
