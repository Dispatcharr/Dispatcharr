import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Stack,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import { Ban, Check, ExternalLink, FlaskConical, Pin, PinOff, RefreshCw, Trash2 } from 'lucide-react';
import PluginHeader from '../PluginHeader.jsx';
import useAuthStore from '../../store/auth.jsx';
import { needsCapabilityAck } from '../../store/plugins.jsx';

// Stable fallback reference: an inline `[]` here causes an infinite render loop under zustand v5.
const EMPTY_PINNED_PLUGINS = [];

const PluginCard = ({
  plugin,
  onToggleEnabled,
  onRequireTrust,
  onRequestDelete,
}) => {
  const navigate = useNavigate();
  const [enabled, setEnabled] = useState(!!plugin.enabled);
  const pinnedPlugins = useAuthStore(
    (s) => s.user?.custom_properties?.pinnedPlugins || EMPTY_PINNED_PLUGINS
  );
  const togglePinnedPlugin = useAuthStore((s) => s.togglePinnedPlugin);
  const pinned = pinnedPlugins.includes(plugin.key);

  // Keep local enabled state in sync with props
  React.useEffect(() => {
    setEnabled(!!plugin.enabled);
  }, [plugin.enabled]);

  const missing = plugin.missing;

  const openDetail = () => navigate(`/plugins/${plugin.key}`);

  const handleEnableChange = () => {
    return async (e) => {
      const next = e.currentTarget.checked;
      if (next && needsCapabilityAck(plugin) && onRequireTrust) {
        const ok = await onRequireTrust(plugin);
        if (!ok) {
          setEnabled(false);
          return;
        }
      }
      const previous = enabled;
      setEnabled(next);
      try {
        const resp = await onToggleEnabled(plugin.key, next);
        if (!resp?.success) {
          setEnabled(previous);
          return;
        }
      } catch {
        setEnabled(previous);
      }
    };
  };

  return (
    <Card
      shadow="sm"
      radius="md"
      withBorder
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 220,
        backgroundColor: '#27272A',
        opacity: !missing && enabled ? 1 : 0.6,
      }}
    >
      {/* Header: avatar, name/author, badges, toggle */}
      <Group justify="space-between" mb="xs" align="flex-start" wrap="nowrap">
        <PluginHeader plugin={plugin} onClick={openDetail} hideLinks />
        <Group gap={6} wrap="nowrap" align="center" style={{ flexShrink: 0 }}>
          {plugin.is_managed && plugin.installed_version_is_prerelease ? (
            <Tooltip
              label={
                plugin.deprecated
                  ? 'Prerelease installed (deprecated), click for details'
                  : 'Prerelease installed, click for details'
              }
            >
              <Badge
                size="xs"
                variant="light"
                color={plugin.deprecated ? 'red' : 'gray'}
                leftSection={plugin.deprecated ? <Ban size={8} /> : <FlaskConical size={8} />}
                style={{ cursor: 'pointer' }}
                onClick={openDetail}
              >
                {plugin.deprecated ? 'Prerelease · Deprecated' : 'Prerelease'}
              </Badge>
            </Tooltip>
          ) : plugin.update_available ? (
            <Tooltip
              label={
                plugin.deprecated
                  ? `Update available: v${plugin.latest_version} (deprecated)`
                  : `Update available: v${plugin.latest_version}`
              }
            >
              <Badge
                size="xs"
                variant="light"
                color={plugin.deprecated ? 'red' : 'yellow'}
                leftSection={plugin.deprecated ? <Ban size={8} /> : <RefreshCw size={8} />}
                style={{ cursor: 'pointer' }}
                onClick={openDetail}
              >
                {plugin.deprecated ? 'Update · Deprecated' : 'Update'}
              </Badge>
            </Tooltip>
          ) : plugin.is_managed ? (
            plugin.deprecated ? (
              <Tooltip label="Installed (deprecated), click for details">
                <Badge
                  size="xs"
                  variant="light"
                  color="orange"
                  leftSection={<Ban size={8} />}
                  style={{ cursor: 'pointer' }}
                  onClick={openDetail}
                >
                  Deprecated
                </Badge>
              </Tooltip>
            ) : (
              <Badge size="xs" variant="light" color="green" leftSection={<Check size={8} />}>
                Up to Date
              </Badge>
            )
          ) : (
            <Badge size="xs" variant="light" color="gray">
              Unmanaged
            </Badge>
          )}
          <Tooltip label={pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              onClick={() => togglePinnedPlugin(plugin.key)}
              aria-label={pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
            >
              {pinned ? <PinOff size={14} /> : <Pin size={14} />}
            </ActionIcon>
          </Tooltip>
          <Switch
            checked={!missing && enabled}
            onChange={handleEnableChange()}
            size="xs"
            onLabel="On"
            offLabel="Off"
            disabled={missing}
          />
        </Group>
      </Group>

      {/* Description */}
      <div style={{ overflow: 'hidden' }}>
        <Text size="sm" c="dimmed" lineClamp={3} mb={0}>
          {plugin.description}
        </Text>
      </div>

      {/* Status warnings */}
      {(missing || plugin.legacy) && (
        <Text size="xs" c={missing ? 'red' : 'yellow'} mt="xs">
          {missing
            ? 'Missing plugin files. Re-import or delete this entry.'
            : 'Please update or ask the developer to add plugin.json.'}
        </Text>
      )}

      {/* Bottom metadata pills */}
      <Stack gap={2} mt="auto" pt={4} style={{ flexShrink: 0 }}>
        <Group gap="xs" wrap="wrap">
          <Badge size="xs" variant="default">
            <span style={{ opacity: 0.5, marginRight: 4 }}>VERSION</span>v
            {plugin.version || '1.0.0'}
          </Badge>
          {plugin.is_managed && plugin.source_repo_name && (
            <Badge size="xs" variant="default">
              <span style={{ opacity: 0.5, marginRight: 4 }}>REPO</span>
              {plugin.source_repo_name}
            </Badge>
          )}
        </Group>
      </Stack>

      {/* Bottom button row */}
      <Group justify="flex-end" mt="sm" gap="xs">
        <Button
          size="xs"
          variant="default"
          leftSection={<ExternalLink size={14} />}
          onClick={openDetail}
        >
          Open
        </Button>
        {/* No download/version data lives on the My Plugins list entry, so
            this can't install directly: it's a shortcut into the detail
            page (which has the version picker) rather than a full update. */}
        {plugin.update_available && (
          <Button
            size="xs"
            variant="light"
            color="yellow"
            leftSection={<RefreshCw size={14} />}
            onClick={openDetail}
          >
            Update
          </Button>
        )}
        <Button
          size="xs"
          variant="light"
          color="red"
          leftSection={<Trash2 size={14} />}
          onClick={() => onRequestDelete && onRequestDelete(plugin)}
        >
          Uninstall
        </Button>
      </Group>
    </Card>
  );
};

export default PluginCard;
