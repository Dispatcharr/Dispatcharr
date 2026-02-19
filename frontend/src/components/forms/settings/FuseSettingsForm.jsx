import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useForm } from '@mantine/form';
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Flex,
  Group,
  Loader,
  NumberInput,
  Paper,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import API from '../../../api.js';
import useSettingsStore from '../../../store/settings.jsx';
import {
  createSetting,
  updateSetting,
} from '../../../utils/pages/SettingsUtils.js';

const getFuseSettingsFormInitialValues = () => ({
  enable_fuse: false,
  movies_mount_path: '/mnt/vod_movies',
  tv_mount_path: '/mnt/vod_tv',
  fuse_max_read: 8388608,
  readahead_bytes: 1048576,
  probe_read_bytes: 524288,
  mkv_prefetch_bytes: 16777216,
  mkv_max_fetch_bytes: 33554432,
  mkv_buffer_cache_bytes: 100663296,
  prefetch_trigger_bytes: 2097152,
  transcoder_prefetch_bytes: 4194304,
  transcoder_max_fetch_bytes: 8388608,
  buffer_cache_bytes: 33554432,
  smooth_buffering_enabled: true,
  initial_prebuffer_bytes: 33554432,
  initial_prebuffer_timeout_seconds: 20,
  target_buffer_ahead_bytes: 134217728,
  low_watermark_bytes: 16777216,
  max_total_buffer_bytes: 1073741824,
  prefetch_loop_sleep_seconds: 0.12,
  seek_reset_threshold_bytes: 4194304,
  buffer_release_on_close: true,
  fuse_stats_grace_seconds: 30,
});

const parseBoolean = (value, fallback = false) => {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
    if (['0', 'false', 'no', 'off', ''].includes(normalized)) return false;
  }
  return fallback;
};

const toNumberOrNull = (value) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return parsed;
};

const formatDateTime = (unixSeconds) => {
  const value = toNumberOrNull(unixSeconds);
  if (value === null || value <= 0) {
    return 'Unknown';
  }

  try {
    return new Date(value * 1000).toLocaleString();
  } catch {
    return 'Unknown';
  }
};

const formatDuration = (secondsValue) => {
  const seconds = toNumberOrNull(secondsValue);
  if (seconds === null || seconds < 0) {
    return 'Unknown';
  }

  const totalSeconds = Math.floor(seconds);
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }

  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) {
    return `${totalMinutes}m ${totalSeconds % 60}s`;
  }

  const totalHours = Math.floor(totalMinutes / 60);
  if (totalHours < 24) {
    return `${totalHours}h ${totalMinutes % 60}m`;
  }

  const totalDays = Math.floor(totalHours / 24);
  return `${totalDays}d ${totalHours % 24}h`;
};

const splitCsvValues = (rawValue) =>
  String(rawValue || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

const normalizeFuseMode = (value) => {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'movie') return 'movies';
  if (normalized === 'series') return 'tv';
  return normalized;
};

const formatFuseMode = (mode) => {
  if (mode === 'movies') return 'Movies';
  if (mode === 'tv') return 'TV';
  return mode ? mode.toUpperCase() : '';
};

const getClientModeDisplay = (client) => {
  const discoveredModes = new Set();
  splitCsvValues(client?.modes).forEach((mode) => {
    const normalized = normalizeFuseMode(mode);
    if (normalized) discoveredModes.add(normalized);
  });

  const lastMode = normalizeFuseMode(client?.last_mode);
  if (lastMode) discoveredModes.add(lastMode);
  if (client?.movies_mountpoint) discoveredModes.add('movies');
  if (client?.tv_mountpoint) discoveredModes.add('tv');

  if (discoveredModes.size === 0) {
    discoveredModes.add('movies');
    discoveredModes.add('tv');
  }

  const orderedModes = [];
  ['movies', 'tv'].forEach((mode) => {
    if (discoveredModes.has(mode)) {
      orderedModes.push(mode);
    }
  });
  Array.from(discoveredModes)
    .filter((mode) => !orderedModes.includes(mode))
    .sort()
    .forEach((mode) => orderedModes.push(mode));

  return orderedModes.map((mode) => formatFuseMode(mode)).join(', ');
};

const getClientMountpointEntries = (client) => {
  const orderedPaths = [];
  const labelsByPath = new Map();

  const registerMountpoint = (rawPath, label = '') => {
    const path = String(rawPath || '').trim();
    if (!path) {
      return;
    }

    if (!labelsByPath.has(path)) {
      labelsByPath.set(path, new Set());
      orderedPaths.push(path);
    }

    if (label) {
      labelsByPath.get(path).add(label);
    }
  };

  splitCsvValues(client?.mountpoints).forEach((mountpoint) => {
    registerMountpoint(mountpoint);
  });

  registerMountpoint(client?.movies_mountpoint, 'Movies');
  registerMountpoint(client?.tv_mountpoint, 'TV');

  const lastMode = normalizeFuseMode(client?.last_mode);
  if (lastMode === 'movies') {
    registerMountpoint(client?.last_mountpoint, 'Movies');
  } else if (lastMode === 'tv') {
    registerMountpoint(client?.last_mountpoint, 'TV');
  } else {
    registerMountpoint(client?.last_mountpoint, 'Last Seen');
  }

  return orderedPaths.map((path) => ({
    path,
    labels: Array.from(labelsByPath.get(path) || []),
  }));
};

const CommandBlock = React.memo(({ command, label = 'Command' }) => {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    if (!command) return;
    try {
      if (
        typeof navigator !== 'undefined' &&
        navigator.clipboard &&
        navigator.clipboard.writeText
      ) {
        await navigator.clipboard.writeText(command);
      } else if (typeof document !== 'undefined') {
        const textArea = document.createElement('textarea');
        textArea.value = command;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (error) {
      console.error('Failed to copy command:', error);
    }
  };

  return (
    <Stack gap={4}>
      <Flex justify="space-between" align="center">
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Button size="xs" variant="subtle" onClick={onCopy}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </Flex>
      <Text
        component="pre"
        p="sm"
        style={{
          fontFamily:
            'ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
          fontSize: '0.82rem',
          whiteSpace: 'pre-wrap',
          border: '1px solid var(--mantine-color-gray-4)',
          borderRadius: 8,
          backgroundColor: 'rgba(0, 0, 0, 0.2)',
          overflowX: 'auto',
        }}
      >
        {command}
      </Text>
    </Stack>
  );
});

const FuseSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const [saved, setSaved] = useState(false);
  const [fuseClients, setFuseClients] = useState([]);
  const [fuseClientsLoading, setFuseClientsLoading] = useState(false);
  const [fuseClientsRefreshing, setFuseClientsRefreshing] = useState(false);
  const [fuseClientsError, setFuseClientsError] = useState('');
  const [fuseClientsLastUpdated, setFuseClientsLastUpdated] = useState(null);
  const [forcingClientId, setForcingClientId] = useState('');
  const [pairingToken, setPairingToken] = useState('');
  const [pairingTokenExpiresAt, setPairingTokenExpiresAt] = useState(null);
  const [pairingTokenLoading, setPairingTokenLoading] = useState(false);
  const [pairingTokenError, setPairingTokenError] = useState('');

  const form = useForm({
    mode: 'controlled',
    initialValues: getFuseSettingsFormInitialValues(),
  });

  useEffect(() => {
    if (!active) {
      setSaved(false);
    }
  }, [active]);

  useEffect(() => {
    const fuseSettings = settings?.fuse_settings?.value;
    if (!fuseSettings || typeof fuseSettings !== 'object') {
      return;
    }

    form.setValues({
      enable_fuse: parseBoolean(fuseSettings.enable_fuse, false),
      movies_mount_path: fuseSettings.movies_mount_path || '/mnt/vod_movies',
      tv_mount_path: fuseSettings.tv_mount_path || '/mnt/vod_tv',
      fuse_max_read: Number(fuseSettings.fuse_max_read) || 8388608,
      readahead_bytes: Number(fuseSettings.readahead_bytes) || 1048576,
      probe_read_bytes: Number(fuseSettings.probe_read_bytes) || 524288,
      mkv_prefetch_bytes: Number(fuseSettings.mkv_prefetch_bytes) || 16777216,
      mkv_max_fetch_bytes: Number(fuseSettings.mkv_max_fetch_bytes) || 33554432,
      mkv_buffer_cache_bytes: Number(fuseSettings.mkv_buffer_cache_bytes) || 100663296,
      prefetch_trigger_bytes: Number(fuseSettings.prefetch_trigger_bytes) || 2097152,
      transcoder_prefetch_bytes:
        Number(fuseSettings.transcoder_prefetch_bytes) || 4194304,
      transcoder_max_fetch_bytes:
        Number(fuseSettings.transcoder_max_fetch_bytes) || 8388608,
      buffer_cache_bytes: Number(fuseSettings.buffer_cache_bytes) || 33554432,
      smooth_buffering_enabled:
        fuseSettings.smooth_buffering_enabled === undefined
          ? true
          : parseBoolean(fuseSettings.smooth_buffering_enabled, true),
      initial_prebuffer_bytes:
        Number(fuseSettings.initial_prebuffer_bytes) || 33554432,
      initial_prebuffer_timeout_seconds:
        Number(fuseSettings.initial_prebuffer_timeout_seconds) || 20,
      target_buffer_ahead_bytes:
        Number(fuseSettings.target_buffer_ahead_bytes) || 134217728,
      low_watermark_bytes: Number(fuseSettings.low_watermark_bytes) || 16777216,
      max_total_buffer_bytes:
        Number(fuseSettings.max_total_buffer_bytes) || 1073741824,
      prefetch_loop_sleep_seconds:
        Number(fuseSettings.prefetch_loop_sleep_seconds) || 0.12,
      seek_reset_threshold_bytes:
        Number(fuseSettings.seek_reset_threshold_bytes) || 4194304,
      buffer_release_on_close:
        fuseSettings.buffer_release_on_close === undefined
          ? true
          : parseBoolean(fuseSettings.buffer_release_on_close, true),
      fuse_stats_grace_seconds:
        fuseSettings.fuse_stats_grace_seconds === undefined ||
        fuseSettings.fuse_stats_grace_seconds === null
          ? 30
          : Number(fuseSettings.fuse_stats_grace_seconds),
    });
  }, [settings]);

  const backendBaseUrl = useMemo(() => {
    if (typeof window !== 'undefined' && window.location?.origin) {
      return window.location.origin;
    }
    return 'http://127.0.0.1:9191';
  }, []);

  const moviesMountPath =
    (form.values.movies_mount_path || '').trim() || '/mnt/vod_movies';
  const tvMountPath = (form.values.tv_mount_path || '').trim() || '/mnt/vod_tv';

  const loadFuseClients = useCallback(async ({ showSpinner = false } = {}) => {
    if (showSpinner) {
      setFuseClientsLoading(true);
    } else {
      setFuseClientsRefreshing(true);
    }
    setFuseClientsError('');

    try {
      const response = await API.getFuseClients(true);
      setFuseClients(Array.isArray(response?.clients) ? response.clients : []);
      setFuseClientsLastUpdated(Date.now());
    } catch (error) {
      console.error('Error fetching FUSE client list:', error);
      setFuseClientsError('Failed to load connected FUSE clients.');
    } finally {
      if (showSpinner) {
        setFuseClientsLoading(false);
      } else {
        setFuseClientsRefreshing(false);
      }
    }
  }, []);

  const forceRemoveFuseClient = useCallback(
    async (client) => {
      const confirmed =
        typeof window === 'undefined'
          ? true
          : window.confirm(
              `Force remove ${client.hostname || client.client_id}? This disconnects this host now and blocks reconnects for about 5 minutes.`
            );
      if (!confirmed) {
        return;
      }

      setForcingClientId(client.client_id);
      try {
        await API.forceRemoveFuseClient(client.client_id);
        await loadFuseClients();
      } catch (error) {
        console.error('Error force-removing FUSE client:', error);
      } finally {
        setForcingClientId('');
      }
    },
    [loadFuseClients]
  );

  const createPairingToken = useCallback(async () => {
    setPairingTokenLoading(true);
    setPairingTokenError('');
    try {
      const response = await API.createFusePairingToken(600);
      const token = String(response?.pairing_token || '').trim();
      if (!token) {
        throw new Error('Pairing token response was empty');
      }
      setPairingToken(token);
      setPairingTokenExpiresAt(
        response?.expires_at ? Number(response.expires_at) : null
      );
    } catch (error) {
      console.error('Error creating FUSE pairing token:', error);
      setPairingTokenError('Failed to create pairing token.');
    } finally {
      setPairingTokenLoading(false);
    }
  }, []);

  const linuxInstallCommand = useMemo(() => {
    const pairingPrefix = pairingToken
      ? `FUSE_PAIRING_TOKEN="${pairingToken}" `
      : 'FUSE_PAIRING_TOKEN="<paste-pairing-token>" ';
    return `curl -fsSL "${backendBaseUrl}/api/fuse/client-script/linux/" -o /tmp/dispatcharr_mount_linux.sh && chmod +x /tmp/dispatcharr_mount_linux.sh && sudo ${pairingPrefix}BACKEND_URL="${backendBaseUrl}" /tmp/dispatcharr_mount_linux.sh`;
  }, [backendBaseUrl, pairingToken]);

  useEffect(() => {
    if (!active) {
      return;
    }

    loadFuseClients({ showSpinner: true });
    const intervalId = setInterval(() => {
      loadFuseClients();
    }, 10000);

    return () => {
      clearInterval(intervalId);
    };
  }, [active, loadFuseClients]);

  const onSubmit = async () => {
    setSaved(false);
    const payload = {
      enable_fuse: parseBoolean(form.values.enable_fuse, false),
      movies_mount_path:
        (form.values.movies_mount_path || '').trim() || '/mnt/vod_movies',
      tv_mount_path: (form.values.tv_mount_path || '').trim() || '/mnt/vod_tv',
      fuse_max_read: Number(form.values.fuse_max_read) || 8388608,
      readahead_bytes: Number(form.values.readahead_bytes) || 1048576,
      probe_read_bytes: Number(form.values.probe_read_bytes) || 524288,
      mkv_prefetch_bytes: Number(form.values.mkv_prefetch_bytes) || 16777216,
      mkv_max_fetch_bytes: Number(form.values.mkv_max_fetch_bytes) || 33554432,
      mkv_buffer_cache_bytes: Number(form.values.mkv_buffer_cache_bytes) || 100663296,
      prefetch_trigger_bytes: Number(form.values.prefetch_trigger_bytes) || 2097152,
      transcoder_prefetch_bytes:
        Number(form.values.transcoder_prefetch_bytes) || 4194304,
      transcoder_max_fetch_bytes:
        Number(form.values.transcoder_max_fetch_bytes) || 8388608,
      buffer_cache_bytes: Number(form.values.buffer_cache_bytes) || 33554432,
      smooth_buffering_enabled: parseBoolean(
        form.values.smooth_buffering_enabled,
        true
      ),
      initial_prebuffer_bytes:
        Number(form.values.initial_prebuffer_bytes) || 33554432,
      initial_prebuffer_timeout_seconds:
        Number(form.values.initial_prebuffer_timeout_seconds) || 20,
      target_buffer_ahead_bytes:
        Number(form.values.target_buffer_ahead_bytes) || 134217728,
      low_watermark_bytes: Number(form.values.low_watermark_bytes) || 16777216,
      max_total_buffer_bytes:
        Number(form.values.max_total_buffer_bytes) || 1073741824,
      prefetch_loop_sleep_seconds:
        Number(form.values.prefetch_loop_sleep_seconds) || 0.12,
      seek_reset_threshold_bytes:
        Number(form.values.seek_reset_threshold_bytes) || 4194304,
      buffer_release_on_close: parseBoolean(
        form.values.buffer_release_on_close,
        true
      ),
      fuse_stats_grace_seconds:
        form.values.fuse_stats_grace_seconds === '' ||
        form.values.fuse_stats_grace_seconds === null ||
        form.values.fuse_stats_grace_seconds === undefined
          ? 30
          : Math.max(0, Number(form.values.fuse_stats_grace_seconds)),
    };

    try {
      const existing = settings?.fuse_settings;
      const result = existing?.id
        ? await updateSetting({
            ...existing,
            value: payload,
          })
        : await createSetting({
            key: 'fuse_settings',
            name: 'Fuse Settings',
            value: payload,
          });

      if (result) {
        setSaved(true);
      }
    } catch (error) {
      // API helpers handle user-facing error notifications.
      console.error('Error saving FUSE settings:', error);
    }
  };

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="md">
        {saved && <Alert variant="light" color="green" title="Saved Successfully" />}

        <Switch
          label="Enable FUSE integration"
          description="Expose Movies/TV as read-only host-side virtual drives."
          {...form.getInputProps('enable_fuse', { type: 'checkbox' })}
          id="enable_fuse"
          name="enable_fuse"
        />

        <Accordion multiple variant="separated">
          <Accordion.Item value="linux">
            <Accordion.Control>FUSE Setup</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                <Text size="sm">
                  Run this once on your host. It launches the guided installer,
                  prompts for Movies/TV mount paths (with defaults), and configures
                  auto-start with systemd when available.
                </Text>
                <Flex align="center" gap="sm" wrap="wrap">
                  <Button
                    type="button"
                    size="xs"
                    variant="light"
                    loading={pairingTokenLoading}
                    onClick={createPairingToken}
                  >
                    Generate Pairing Token
                  </Button>
                  <Text size="xs" c="dimmed">
                    One-time token expires after about 10 minutes.
                  </Text>
                </Flex>
                {pairingTokenError && (
                  <Alert variant="light" color="red" title="Pairing Token Error">
                    {pairingTokenError}
                  </Alert>
                )}
                {pairingToken && (
                  <Alert variant="light" color="green" title="Pairing Token">
                    <Text component="code" size="sm">
                      {pairingToken}
                    </Text>
                    {pairingTokenExpiresAt && (
                      <Text size="xs" c="dimmed">
                        Expires: {new Date(pairingTokenExpiresAt * 1000).toLocaleString()}
                      </Text>
                    )}
                  </Alert>
                )}
                <CommandBlock
                  label="Install & Configure FUSE"
                  command={linuxInstallCommand}
                />
                <Text size="xs" c="dimmed">
                  Re-run the same command later to change mount paths, restart
                  services, or uninstall.
                </Text>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          <Accordion.Item value="connected-fuse-clients">
            <Accordion.Control>Connected FUSE Clients</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Flex justify="space-between" align="center" gap="sm">
                  <Text size="sm" c="dimmed">
                    Host computers running Dispatcharr FUSE client.
                  </Text>
                  <Button
                    type="button"
                    size="xs"
                    variant="light"
                    loading={fuseClientsLoading || fuseClientsRefreshing}
                    onClick={() => loadFuseClients({ showSpinner: true })}
                  >
                    Refresh
                  </Button>
                </Flex>

                {fuseClientsLastUpdated && (
                  <Text size="xs" c="dimmed">
                    Last updated: {new Date(fuseClientsLastUpdated).toLocaleString()}
                  </Text>
                )}

                {fuseClientsError && (
                  <Alert variant="light" color="red" title="Client List Error">
                    {fuseClientsError}
                  </Alert>
                )}

                {fuseClientsLoading ? (
                  <Group gap="xs">
                    <Loader size="sm" />
                    <Text size="sm" c="dimmed">
                      Loading connected FUSE clients...
                    </Text>
                  </Group>
                ) : fuseClients.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    No connected FUSE clients found.
                  </Text>
                ) : (
                  <Stack gap="sm">
                    {fuseClients.map((client) => {
                      const modeDisplay = getClientModeDisplay(client);
                      const mountpointEntries = getClientMountpointEntries(client);
                      return (
                        <Paper
                          key={client.client_id}
                          withBorder
                          radius="md"
                          p="md"
                          style={{
                            background: 'rgba(255, 255, 255, 0.02)',
                          }}
                        >
                          <Flex justify="space-between" align="flex-start" gap="sm" wrap="wrap">
                            <Stack gap={2}>
                              <Group gap="xs" wrap="wrap">
                                <Text size="lg" fw={600}>
                                  {client.hostname || 'Unknown'}
                                </Text>
                                <Badge
                                  variant="light"
                                  color={client.is_active ? 'green' : 'gray'}
                                >
                                  {client.is_active ? 'CONNECTED' : 'IDLE'}
                                </Badge>
                              </Group>
                              <Text size="xs" c="dimmed" component="code">
                                {client.client_id}
                              </Text>
                            </Stack>
                            <Button
                              type="button"
                              size="xs"
                              color="red"
                              variant="light"
                              loading={forcingClientId === client.client_id}
                              onClick={() => forceRemoveFuseClient(client)}
                            >
                              Force Remove
                            </Button>
                          </Flex>

                          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm" mt="sm">
                            <Stack gap={2}>
                              <Text size="xs" c="dimmed">
                                IP
                              </Text>
                              <Text size="sm">{client.ip_address || 'Unknown'}</Text>
                            </Stack>

                            <Stack gap={2}>
                              <Text size="xs" c="dimmed">
                                Mode
                              </Text>
                              <Text size="sm">{modeDisplay || 'Movies, TV'}</Text>
                            </Stack>

                            <Stack gap={2}>
                              <Text size="xs" c="dimmed">
                                Mountpoints
                              </Text>
                              {mountpointEntries.length === 0 ? (
                                <Text size="sm">Unknown</Text>
                              ) : (
                                <Stack gap={4}>
                                  {mountpointEntries.map((entry) => (
                                    <Group
                                      key={`${client.client_id}-${entry.path}`}
                                      gap={6}
                                      wrap="wrap"
                                    >
                                      <Text size="sm" component="code">
                                        {entry.path}
                                      </Text>
                                      {entry.labels.map((label) => (
                                        <Badge
                                          key={`${client.client_id}-${entry.path}-${label}`}
                                          size="xs"
                                          variant="light"
                                          color="gray"
                                        >
                                          {label}
                                        </Badge>
                                      ))}
                                    </Group>
                                  ))}
                                </Stack>
                              )}
                            </Stack>

                            <Stack gap={2}>
                              <Text size="xs" c="dimmed">
                                Connected Since
                              </Text>
                              <Text size="sm">{formatDateTime(client.first_seen)}</Text>
                            </Stack>

                            <Stack gap={2}>
                              <Text size="xs" c="dimmed">
                                Last Seen
                              </Text>
                              <Text size="sm">{formatDateTime(client.last_seen)}</Text>
                            </Stack>

                            <Stack gap={2}>
                              <Text size="xs" c="dimmed">
                                Idle
                              </Text>
                              <Text size="sm">{formatDuration(client.idle_seconds)}</Text>
                            </Stack>
                          </SimpleGrid>
                        </Paper>
                      );
                    })}
                  </Stack>
                )}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          <Accordion.Item value="docker-bind">
            <Accordion.Control>
              Bind Mount + Scanner Settings (Plex / Jellyfin / Emby)
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Text size="sm">
                  Add the host FUSE paths as read-only volumes in your media server
                  container:
                </Text>
                <CommandBlock
                  label="Compose Volume Snippet"
                  command={`services:
  media_server:
    volumes:
      - ${moviesMountPath}:/vod/movies:ro
      - ${tvMountPath}:/vod/tv:ro`}
                />
                <Text size="sm">
                  In your media server, create libraries that point to{' '}
                  <code>/vod/movies</code> and <code>/vod/tv</code>.
                </Text>
                <Text size="sm" c="dimmed">
                  Setting labels can vary by version, but the goals are the same:
                  disable deep media analysis, chapter/preview image extraction, and
                  intro/credits marker generation where possible.
                </Text>

                <Stack gap={4}>
                  <Text fw={600} size="sm">
                    Plex
                  </Text>
                  <Text size="sm">
                    Disable: video preview thumbnails, chapter thumbnails,
                    intro detection, credits detection, and extensive media
                    analysis tasks.
                  </Text>
                  <Group gap="xs">
                    <Anchor
                      href="https://support.plex.tv/articles/202197528-video-preview-thumbnails/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Preview thumbnails
                    </Anchor>
                    <Anchor
                      href="https://support.plex.tv/articles/skip-content/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Intro/Credits
                    </Anchor>
                    <Anchor
                      href="https://support.plex.tv/articles/201553286-scheduled-tasks/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Scheduled tasks
                    </Anchor>
                  </Group>
                </Stack>

                <Stack gap={4}>
                  <Text fw={600} size="sm">
                    Jellyfin
                  </Text>
                  <Text size="sm">
                    Disable chapter image extraction during library scans and
                    disable related scheduled extraction tasks.
                  </Text>
                  <Group gap="xs">
                    <Anchor
                      href="https://jellyfin.org/docs/general/server/metadata/chapter-images"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Chapter images
                    </Anchor>
                    <Anchor
                      href="https://jellyfin.org/docs/general/server/tasks"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Scheduled tasks
                    </Anchor>
                  </Group>
                </Stack>

                <Stack gap={4}>
                  <Text fw={600} size="sm">
                    Emby
                  </Text>
                  <Text size="sm">
                    Disable chapter image extraction on library scan and disable
                    intro/credits marker generation tasks.
                  </Text>
                  <Group gap="xs">
                    <Anchor
                      href="https://emby.media/support/articles/Library-Setup.html"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Library setup
                    </Anchor>
                    <Anchor
                      href="https://emby.media/support/articles/Intro-Skip.html"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Intro skip
                    </Anchor>
                    <Anchor
                      href="https://emby.media/support/articles/Scheduled-Tasks.html"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Scheduled tasks
                    </Anchor>
                  </Group>
                </Stack>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          <Accordion.Item value="fuse-tuning">
            <Accordion.Control>Advanced Settings</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                <Text size="sm" c="dimmed">
                  Host mount scripts will auto-load these values
                  from the backend on startup.
                </Text>
                <NumberInput
                  label="FUSE Max Read (bytes)"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('fuse_max_read')}
                />
                <NumberInput
                  label="Readahead Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('readahead_bytes')}
                />
                <NumberInput
                  label="Probe Read Bytes"
                  min={4096}
                  step={4096}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('probe_read_bytes')}
                />
                <NumberInput
                  label="MKV Prefetch Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('mkv_prefetch_bytes')}
                />
                <NumberInput
                  label="MKV Max Fetch Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('mkv_max_fetch_bytes')}
                />
                <NumberInput
                  label="MKV Buffer Cache Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('mkv_buffer_cache_bytes')}
                />
                <NumberInput
                  label="Prefetch Trigger Bytes"
                  min={4096}
                  step={4096}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('prefetch_trigger_bytes')}
                />
                <NumberInput
                  label="Transcoder Prefetch Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('transcoder_prefetch_bytes')}
                />
                <NumberInput
                  label="Transcoder Max Fetch Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('transcoder_max_fetch_bytes')}
                />
                <NumberInput
                  label="General Buffer Cache Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('buffer_cache_bytes')}
                />
                <Switch
                  label="Enable Smooth Buffering Worker"
                  {...form.getInputProps('smooth_buffering_enabled', {
                    type: 'checkbox',
                  })}
                />
                <NumberInput
                  label="Initial Prebuffer Bytes"
                  min={0}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('initial_prebuffer_bytes')}
                />
                <NumberInput
                  label="Initial Prebuffer Timeout (seconds)"
                  min={0}
                  step={1}
                  decimalScale={2}
                  {...form.getInputProps('initial_prebuffer_timeout_seconds')}
                />
                <NumberInput
                  label="Target Buffer Ahead Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('target_buffer_ahead_bytes')}
                />
                <NumberInput
                  label="Low Watermark Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('low_watermark_bytes')}
                />
                <NumberInput
                  label="Max Total Buffer Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('max_total_buffer_bytes')}
                />
                <NumberInput
                  label="Prefetch Loop Sleep Seconds"
                  min={0.01}
                  step={0.01}
                  decimalScale={3}
                  {...form.getInputProps('prefetch_loop_sleep_seconds')}
                />
                <NumberInput
                  label="Seek Reset Threshold Bytes"
                  min={65536}
                  step={65536}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('seek_reset_threshold_bytes')}
                />
                <Switch
                  label="Release Buffers On Close"
                  {...form.getInputProps('buffer_release_on_close', {
                    type: 'checkbox',
                  })}
                />
                <NumberInput
                  label="FUSE Stats Grace Seconds"
                  description="Keep FUSE sessions visible on the Stats page this long after reads stop."
                  min={0}
                  step={1}
                  allowDecimal={false}
                  clampBehavior="strict"
                  {...form.getInputProps('fuse_stats_grace_seconds')}
                />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>

        <Flex justify="flex-end">
          <Button type="submit" disabled={form.submitting} variant="default">
            Save
          </Button>
        </Flex>
      </Stack>
    </form>
  );
});

export default FuseSettingsForm;
