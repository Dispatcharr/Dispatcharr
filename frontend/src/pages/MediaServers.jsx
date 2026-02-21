import React, { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Card,
  Flex,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  CircleCheckBig,
  CircleDashed,
  CirclePlay,
  CircleX,
  FolderKanban,
  RefreshCw,
  Server,
  SquarePlus,
} from 'lucide-react';

import API from '../api';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';
import MediaServerIntegrationForm from '../components/forms/MediaServerIntegrationForm';

function statusColor(status) {
  switch (status) {
    case 'success':
      return 'green';
    case 'running':
      return 'blue';
    case 'error':
      return 'red';
    default:
      return 'gray';
  }
}

function statusIcon(status) {
  switch (status) {
    case 'success':
      return <CircleCheckBig size={14} />;
    case 'running':
      return <CirclePlay size={14} />;
    case 'error':
      return <CircleX size={14} />;
    default:
      return <CircleDashed size={14} />;
  }
}

function ProviderBadge({ provider }) {
  const normalized = String(provider || '').toLowerCase();
  const label =
    normalized === 'plex'
      ? 'Plex'
      : normalized === 'emby'
        ? 'Emby'
        : normalized === 'jellyfin'
          ? 'Jellyfin'
          : provider || 'Unknown';
  return (
    <Badge variant="light" color="indigo">
      {label}
    </Badge>
  );
}

function formatSyncInterval(syncIntervalHours) {
  const hours = Number(syncIntervalHours) || 0;
  if (hours <= 0) return 'Disabled';
  if (hours % 168 === 0) {
    const weeks = hours / 168;
    return `${weeks} week${weeks === 1 ? '' : 's'}`;
  }
  if (hours % 24 === 0) {
    const days = hours / 24;
    return `${days} day${days === 1 ? '' : 's'}`;
  }
  return `${hours} hour${hours === 1 ? '' : 's'}`;
}

export default function MediaServersPage() {
  const authUser = useAuthStore((s) => s.user);
  const isAdmin = authUser?.user_level === USER_LEVELS.ADMIN;

  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [activeIntegration, setActiveIntegration] = useState(null);
  const [busyById, setBusyById] = useState({});

  const setBusy = (id, value) => {
    setBusyById((prev) => ({ ...prev, [id]: value }));
  };

  const fetchIntegrations = useCallback(async () => {
    setLoading(true);
    try {
      const response = await API.getMediaServerIntegrations();
      setIntegrations(Array.isArray(response) ? response : response?.results || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIntegrations();
  }, [fetchIntegrations]);

  const openCreate = () => {
    setActiveIntegration(null);
    setFormOpen(true);
  };

  const openEdit = (integration) => {
    setActiveIntegration(integration);
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setActiveIntegration(null);
  };

  const onSaved = async () => {
    await fetchIntegrations();
  };

  const toggleEnabled = async (integration) => {
    setBusy(integration.id, true);
    try {
      await API.updateMediaServerIntegration(integration.id, {
        enabled: !integration.enabled,
      });
      await fetchIntegrations();
    } finally {
      setBusy(integration.id, false);
    }
  };

  const runSync = async (integration) => {
    setBusy(integration.id, true);
    try {
      const response = await API.syncMediaServerIntegration(integration.id);
      notifications.show({
        title: 'Sync started',
        message: response?.message || `Sync started for ${integration.name}`,
        color: 'blue',
      });
      await fetchIntegrations();
    } finally {
      setBusy(integration.id, false);
    }
  };

  const testConnection = async (integration) => {
    setBusy(integration.id, true);
    try {
      const response = await API.testMediaServerIntegration(integration.id);
      notifications.show({
        title: 'Connection successful',
        message: `${integration.name}: discovered ${response?.library_count || 0} libraries`,
        color: 'green',
      });
      await fetchIntegrations();
    } finally {
      setBusy(integration.id, false);
    }
  };

  const deleteIntegration = async (integration) => {
    const confirmed = window.confirm(
      `Delete integration "${integration.name}"?`
    );
    if (!confirmed) return;
    setBusy(integration.id, true);
    try {
      await API.deleteMediaServerIntegration(integration.id);
      await fetchIntegrations();
    } finally {
      setBusy(integration.id, false);
    }
  };

  let content = null;
  if (loading) {
    content = (
      <Flex justify="center" py="xl">
        <Loader />
      </Flex>
    );
  } else if (!integrations.length) {
    content = (
      <Card
        withBorder
        radius="md"
        p="xl"
        style={{ backgroundColor: '#27272A', borderColor: '#3f3f46' }}
      >
        <Stack align="center" gap="sm">
          <Server size={24} />
          <Text fw={600}>No media server integrations configured</Text>
          <Text size="sm" c="dimmed" ta="center">
            Add Plex, Emby, or Jellyfin and sync movie and series libraries into VOD.
          </Text>
        </Stack>
      </Card>
    );
  } else {
    content = (
      <Box
        style={{
          display: 'grid',
          gap: '1rem',
          gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))',
        }}
      >
        {integrations.map((integration) => {
          const busy = !!busyById[integration.id];
          return (
            <Card
              key={integration.id}
              withBorder
              radius="md"
              p="md"
              style={{ backgroundColor: '#27272A', borderColor: '#3f3f46' }}
            >
              <Stack gap="sm">
                <Group justify="space-between" align="flex-start">
                  <Stack gap={2}>
                    <Group gap={8}>
                      <Server size={16} />
                      <Text fw={700}>{integration.name}</Text>
                    </Group>
                    <Text size="xs" c="dimmed">
                      {integration.base_url}
                    </Text>
                  </Stack>
                  <Switch
                    label="Enabled"
                    checked={!!integration.enabled}
                    onChange={() => toggleEnabled(integration)}
                    disabled={busy}
                  />
                </Group>

                <Group gap="xs">
                  <ProviderBadge provider={integration.provider_type} />
                  <Badge
                    variant="light"
                    color={statusColor(integration.last_sync_status)}
                    leftSection={statusIcon(integration.last_sync_status)}
                  >
                    {integration.last_sync_status || 'idle'}
                  </Badge>
                  <Badge
                    variant="outline"
                    color={integration.add_to_vod ? 'green' : 'gray'}
                  >
                    {integration.add_to_vod ? 'VOD Enabled' : 'VOD Disabled'}
                  </Badge>
                </Group>

                <Group gap={8}>
                  <FolderKanban size={14} />
                  <Text size="sm">
                    {Array.isArray(integration.include_libraries) &&
                    integration.include_libraries.length > 0
                      ? `${integration.include_libraries.length} selected librar${integration.include_libraries.length > 1 ? 'ies' : 'y'}`
                      : 'All media libraries'}
                  </Text>
                </Group>

                <Text size="xs" c="dimmed">
                  Last synced:{' '}
                  {integration.last_synced_at
                    ? new Date(integration.last_synced_at).toLocaleString()
                    : 'Never'}
                </Text>
                <Text size="xs" c="dimmed">
                  Auto sync: {formatSyncInterval(integration.sync_interval)}
                </Text>
                {integration.last_sync_message ? (
                  <Text size="xs" c="dimmed" lineClamp={2}>
                    {integration.last_sync_message}
                  </Text>
                ) : null}

                <Flex justify="flex-end" gap="xs" mt="sm" wrap="wrap">
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<CircleCheckBig size={14} />}
                    onClick={() => testConnection(integration)}
                    loading={busy}
                  >
                    Test
                  </Button>
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<RefreshCw size={14} />}
                    onClick={() => runSync(integration)}
                    loading={busy}
                  >
                    Sync
                  </Button>
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => openEdit(integration)}
                    disabled={busy}
                  >
                    Edit
                  </Button>
                  <Button
                    size="xs"
                    color="red"
                    variant="outline"
                    onClick={() => deleteIntegration(integration)}
                    disabled={busy}
                  >
                    Delete
                  </Button>
                </Flex>
              </Stack>
            </Card>
          );
        })}
      </Box>
    );
  }

  if (!isAdmin) {
    return (
      <Box p="md">
        <Title order={3}>Media Servers</Title>
        <Text c="dimmed" mt="sm">
          Admin access is required.
        </Text>
      </Box>
    );
  }

  return (
    <Box p="md">
      <Group justify="space-between" mb="md">
        <Title order={3}>Media Servers</Title>
        <Button
          leftSection={<SquarePlus size={16} />}
          variant="light"
          onClick={openCreate}
        >
          New Integration
        </Button>
      </Group>

      {content}

      <MediaServerIntegrationForm
        integration={activeIntegration}
        isOpen={formOpen}
        onClose={closeForm}
        onSaved={onSaved}
      />
    </Box>
  );
}
