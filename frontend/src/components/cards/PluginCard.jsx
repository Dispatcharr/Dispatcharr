import React, { useState } from 'react';
import { showNotification } from '../../utils/notificationUtils.js';
import { Field } from '../Field.jsx';
import {
  Anchor,
  Avatar,
  Badge,
  Box,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Stack,
  Switch,
  Tabs,
  Text,
  Tooltip,
} from '@mantine/core';
import { Ban, Check, Download, FlaskConical, Info, RefreshCw, Settings, Trash2, Zap } from 'lucide-react';
import { getConfirmationDetails } from '../../utils/cards/PluginCardUtils.js';
import { SUBSCRIPTION_EVENTS } from '../../constants.js';
import useSettingsStore from '../../store/settings.jsx';
import { usePluginStore } from '../../store/plugins.jsx';
import API from '../../api';
import PluginDetailPanel from '../PluginDetailPanel.jsx';
import { compareVersions } from '../pluginUtils.js';
import {
  PluginDowngradeWarning,
  PluginSecurityWarning,
  PluginSupportDisclaimer,
} from '../PluginWarnings.jsx';

const PluginFieldList = ({ plugin, settings, updateField }) => {
  return plugin.fields.map((f) => (
    <Field
      key={f.id}
      field={f}
      value={settings?.[f.id]}
      onChange={updateField}
    />
  ));
};

const PluginActionList = ({
  plugin,
  enabled,
  runningActionId,
  handlePluginRun,
}) => {
  return plugin.actions.map((action) => {
    const events = Array.isArray(action?.events) ? action.events : [];
    return (
      <Group key={action.id} justify="space-between">
        <div>
          <Text size="sm">{action.label}</Text>
          {action.description && (
            <Text size="xs" c="dimmed">
              {action.description}
            </Text>
          )}
          {events.length > 0 && (
            <>
              <Text size="xs" style={{ paddingTop: 6 }}>
                Event Triggers
              </Text>
              {events.map((event) => (
                <Badge key={`${action.id}:${event}`} size="xs" variant="light" color="green">
                  {SUBSCRIPTION_EVENTS[event] || event}
                </Badge>
              ))}
            </>
          )}
        </div>
        <Button
          loading={runningActionId === action.id}
          disabled={!enabled || runningActionId === action.id}
          onClick={() => handlePluginRun(action)}
          size="xs"
          variant={action.button_variant || 'filled'}
          color={action.button_color}
        >
          {runningActionId === action.id
            ? 'Running…'
            : action.button_label || 'Run'}
        </Button>
      </Group>
    );
  });
};

const PluginActionStatus = ({ running, lastResult }) => {
  return (
    <>
      {running && (
        <Text size="xs" c="dimmed">
          Running action… please wait
        </Text>
      )}
      {!running && lastResult?.file && (
        <Text size="xs" c="dimmed">
          Output: {lastResult.file}
        </Text>
      )}
      {!running && lastResult?.error && (
        <Text size="xs" c="red">
          Error: {String(lastResult.error)}
        </Text>
      )}
    </>
  );
};

const PluginCard = ({
  plugin,
  onSaveSettings,
  onRunAction,
  onToggleEnabled,
  onRequireTrust,
  onRequestDelete,
  onRequestConfirm,
}) => {
  const appVersion = useSettingsStore((s) => s.version?.version || '');
  const [settings, setSettings] = useState(plugin.settings || {});
  const [saving, setSaving] = useState(false);
  const [runningActionId, setRunningActionId] = useState(null);
  const [enabled, setEnabled] = useState(!!plugin.enabled);
  const [lastResult, setLastResult] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalTab, setModalTab] = useState('settings');
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [installing, setInstalling] = useState(false);
  const [uninstalling] = useState(false);
  const [installConfirmOpen, setInstallConfirmOpen] = useState(false);
  const [pendingInstallParams, setPendingInstallParams] = useState(null);

  const installPlugin = usePluginStore((s) => s.installPlugin);

  // Keep local enabled state in sync with props
  React.useEffect(() => {
    setEnabled(!!plugin.enabled);
  }, [plugin.enabled]);

  // Sync settings if plugin changes identity
  React.useEffect(() => {
    setSettings(plugin.settings || {});
  }, [plugin.key, plugin.settings]);

  const hasActions = !plugin.missing && enabled && plugin.actions?.length > 0;
  const isManaged = !!(plugin.slug && plugin.source_repo);

  const fetchDetail = async () => {
    if (detailLoading || !isManaged) return;
    // Find the available plugin entry for manifest_url
    let avail = usePluginStore.getState().availablePlugins.find(
      (ap) => ap.slug === plugin.slug && ap.repo_id === plugin.source_repo
    );
    if (!avail) {
      setDetailLoading(true);
      try {
        await usePluginStore.getState().fetchAvailablePlugins();
        avail = usePluginStore.getState().availablePlugins.find(
          (ap) => ap.slug === plugin.slug && ap.repo_id === plugin.source_repo
        );
      } catch { /* ignore */ }
    }
    if (!avail) { setDetailLoading(false); return; }
    if (!avail.manifest_url) {
      // Synthesize from top-level entry
      setDetail({
        manifest: {
          description: avail.description,
          author: avail.author,
          license: avail.license,
          repo_url: avail.repo_url,
          discord_thread: avail.discord_thread,
          registry_url: avail.registry_url,
          versions: avail.latest_version ? [{
            version: avail.latest_version,
            url: avail.latest_url,
            checksum_sha256: avail.latest_sha256,
            min_dispatcharr_version: avail.min_dispatcharr_version,
            max_dispatcharr_version: avail.max_dispatcharr_version,
            build_timestamp: avail.last_updated,
            size: avail.latest_size,
          }] : [],
          latest: avail.latest_version ? { version: avail.latest_version } : null,
        },
        signature_verified: avail.signature_verified ?? null,
        _avail: avail,
      });
      if (avail.latest_version) setSelectedVersion(avail.latest_version);
      setDetailLoading(false);
      return;
    }
    setDetailLoading(true);
    try {
      const result = await API.getPluginDetailManifest(avail.repo_id, avail.manifest_url);
      if (result) {
        setDetail({ ...result, _avail: avail });
        if (result.manifest?.versions?.length) {
          setSelectedVersion(result.manifest.versions[0].version);
        }
      }
    } finally {
      setDetailLoading(false);
    }
  };

  const updateField = (id, val) => {
    setSettings((prev) => ({ ...prev, [id]: val }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const result = await onSaveSettings(plugin.key, settings);
      if (result) {
        showNotification({
          title: 'Saved',
          message: `${plugin.name} settings updated`,
          color: 'green',
        });
      } else {
        showNotification({
          title: `${plugin.name} error`,
          message: 'Failed to update settings',
          color: 'red',
        });
      }
    } catch (e) {
      showNotification({
        title: `${plugin.name} error`,
        message: e?.message || 'Failed to update settings',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  const missing = plugin.missing;

  const handleEnableChange = () => {
    return async (e) => {
      const next = e.currentTarget.checked;
      if (next && !plugin.ever_enabled && onRequireTrust) {
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

  const handlePluginRun = async (a) => {
    try {
      const { requireConfirm, confirmTitle, confirmMessage } =
        getConfirmationDetails(a, plugin, settings);

      if (requireConfirm) {
        const confirmed = await onRequestConfirm(confirmTitle, confirmMessage);
        if (!confirmed) return;
      }

      setRunningActionId(a.id);
      setLastResult(null);

      // Save settings before running to ensure backend uses latest values
      try {
        await onSaveSettings(plugin.key, settings);
      } catch {
        /* ignore, run anyway */
      }
      const resp = await onRunAction(plugin.key, a.id);
      if (resp?.success) {
        setLastResult(resp.result || {});
        const msg = resp.result?.message || 'Plugin action completed';
        showNotification({
          title: plugin.name,
          message: msg,
          color: 'green',
        });
      } else {
        const err = resp?.error || 'Unknown error';
        setLastResult({ error: err });
        showNotification({
          title: `${plugin.name} error`,
          message: String(err),
          color: 'red',
        });
      }
    } finally {
      setRunningActionId(null);
    }
  };

  const hasFields = !missing && enabled && plugin.fields?.length > 0;

  const openModal = (tab) => {
    setModalTab(tab);
    setModalOpen(true);
    if (tab === 'details') fetchDetail();
  };

  const handleDetailInstall = async (params) => {
    setPendingInstallParams(params);
    setInstallConfirmOpen(true);
  };

  const confirmAndInstall = async () => {
    if (!pendingInstallParams) return;
    const params = pendingInstallParams;
    const selVer = params.version;
    const isDown = plugin.version && compareVersions(selVer, plugin.version) < 0;
    const action = isDown ? 'downgrade' : 'update';
    setInstallConfirmOpen(false);
    setPendingInstallParams(null);
    setInstalling(true);
    try {
      const result = await installPlugin(params);
      if (result?.success) {
        showNotification({
          title: plugin.name,
          message: `Successfully ${action === 'downgrade' ? 'downgraded' : 'updated'} to v${selVer}`,
          color: 'green',
        });
        usePluginStore.getState().invalidatePlugins();
      }
    } finally {
      setInstalling(false);
    }
  };

  const handleDetailUninstall = () => {
    onRequestDelete && onRequestDelete(plugin);
  };

  return (
    <div style={{ position: 'relative' }}>
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
          <Group gap="sm" align="flex-start" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
            <Avatar
              src={plugin.logo_url}
              radius="sm"
              size={48}
              alt={`${plugin.name} logo`}
              onClick={isManaged ? () => openModal('details') : undefined}
              style={isManaged ? { cursor: 'pointer' } : undefined}
              imageProps={{ draggable: false }}
            >
              {plugin.name?.[0]?.toUpperCase()}
            </Avatar>
            <Box style={{ minWidth: 0, flex: 1 }}>
              <Text
                fw={600}
                lineClamp={1}
                onClick={isManaged ? () => openModal('details') : undefined}
                style={isManaged ? { cursor: 'pointer' } : undefined}
              >
                {plugin.name}
              </Text>
              <Group gap={6} align="center" wrap="nowrap">
                {plugin.author && (
                  <Text
                    size="xs"
                    c="dimmed"
                    truncate
                    onClick={isManaged ? () => openModal('details') : undefined}
                    style={{ minWidth: 0, maxWidth: '100%', ...(isManaged ? { cursor: 'pointer' } : {}) }}
                  >
                    {plugin.author}
                  </Text>
                )}
                {plugin.help_url && (
                  <Anchor
                    href={plugin.help_url}
                    target="_blank"
                    rel="noreferrer"
                    size="xs"
                  >
                    Docs
                  </Anchor>
                )}
              </Group>
            </Box>
          </Group>
          <Group gap={6} wrap="nowrap" align="center" style={{ flexShrink: 0 }}>
            {plugin.is_managed && plugin.installed_version_is_prerelease ? (
              <Tooltip label={plugin.deprecated ? 'Prerelease installed (deprecated), click for details' : 'Prerelease installed, click for details'}>
                <Badge
                  size="xs"
                  variant="light"
                  color={plugin.deprecated ? 'red' : 'violet'}
                  leftSection={detailLoading ? <Loader size={8} /> : plugin.deprecated ? <Ban size={8} /> : <FlaskConical size={8} />}
                  style={{ cursor: 'pointer' }}
                  onClick={() => openModal('details')}
                >
                  {plugin.deprecated ? 'Prerelease · Deprecated' : 'Prerelease'}
                </Badge>
              </Tooltip>
            ) : plugin.update_available ? (
              <Tooltip label={plugin.deprecated ? `Update available: v${plugin.latest_version} (deprecated)` : `Update available: v${plugin.latest_version}`}>
                <Badge
                  size="xs"
                  variant="light"
                  color={plugin.deprecated ? 'red' : 'yellow'}
                  leftSection={detailLoading ? <Loader size={8} /> : plugin.deprecated ? <Ban size={8} /> : <RefreshCw size={8} />}
                  style={{ cursor: 'pointer' }}
                  onClick={() => openModal('details')}
                >
                  {plugin.deprecated ? 'Update · Deprecated' : 'Update'}
                </Badge>
              </Tooltip>
            ) : plugin.is_managed ? (
              <Tooltip label={plugin.deprecated ? 'Installed (deprecated), click for details' : 'View plugin details'}>
                <Badge
                  size="xs"
                  variant="light"
                  color={plugin.deprecated ? 'orange' : 'green'}
                  leftSection={detailLoading ? <Loader size={8} /> : plugin.deprecated ? <Ban size={8} /> : <Check size={8} />}
                  style={{ cursor: 'pointer' }}
                  onClick={() => openModal('details')}
                >
                  {plugin.deprecated ? 'Deprecated' : 'Up to Date'}
                </Badge>
              </Tooltip>
            ) : (
              <Badge size="xs" variant="light" color="gray">
                Unmanaged
              </Badge>
            )}
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
              <span style={{ opacity: 0.5, marginRight: 4 }}>VERSION</span>
              v{plugin.version || '1.0.0'}
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
          {hasFields && (
            <Button
              size="xs"
              variant="default"
              leftSection={<Settings size={14} />}
              onClick={() => openModal('settings')}
            >
              Settings
            </Button>
          )}
          {hasActions && (
            <Button
              size="xs"
              variant="light"
              color="blue"
              leftSection={<Zap size={14} />}
              onClick={() => openModal('actions')}
            >
              Actions
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

      {/* Settings & Actions Modal */}
      <Modal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        title={
          <Group gap="xs" align="center">
            <Avatar src={plugin.logo_url} radius="sm" size={28} alt={`${plugin.name} logo`} imageProps={{ draggable: false }}>
              {plugin.name?.[0]?.toUpperCase()}
            </Avatar>
            <Text fw={600}>{plugin.name}</Text>
          </Group>
        }
        size="lg"
      >
        <Tabs value={modalTab} onChange={(tab) => { setModalTab(tab); if (tab === 'details') fetchDetail(); }}>
          <Tabs.List>
            {isManaged && <Tabs.Tab value="details" leftSection={<Info size={14} />}>Details</Tabs.Tab>}
            {hasFields && <Tabs.Tab value="settings" leftSection={<Settings size={14} />}>Settings</Tabs.Tab>}
            {hasActions && <Tabs.Tab value="actions" leftSection={<Zap size={14} />}>Actions</Tabs.Tab>}
          </Tabs.List>

          {isManaged && (
            <Tabs.Panel value="details" pt="md">
              <PluginDetailPanel
                detail={detail}
                detailLoading={detailLoading}
                selectedVersion={selectedVersion}
                onVersionChange={setSelectedVersion}
                installedVersion={plugin.version}
                installedVersionIsPrerelease={!!plugin.installed_version_is_prerelease}
                appVersion={appVersion}
                installing={installing}
                uninstalling={uninstalling}
                onInstall={handleDetailInstall}
                onUninstall={handleDetailUninstall}
                installStatus="installed"
                repoId={plugin.source_repo}
                slug={plugin.slug}
              />
            </Tabs.Panel>
          )}

          {hasFields && (
            <Tabs.Panel value="settings" pt="md">
              <Stack gap="md">
                <PluginFieldList
                  plugin={plugin}
                  settings={settings}
                  updateField={updateField}
                />
                <Group justify="flex-end">
                  <Button
                    variant="default"
                    size="xs"
                    onClick={() => setModalOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    loading={saving}
                    onClick={async () => {
                      await save();
                      setModalOpen(false);
                    }}
                    size="xs"
                  >
                    Save
                  </Button>
                </Group>
              </Stack>
            </Tabs.Panel>
          )}

          {hasActions && (
            <Tabs.Panel value="actions" pt="md">
              <Stack gap="sm">
                <PluginActionList
                  plugin={plugin}
                  enabled={enabled}
                  runningActionId={runningActionId}
                  handlePluginRun={handlePluginRun}
                />
                <PluginActionStatus
                  running={!!runningActionId}
                  lastResult={lastResult}
                />
              </Stack>
            </Tabs.Panel>
          )}
        </Tabs>
      </Modal>

      {/* Install confirmation modal */}
      {(() => {
        const selVer = pendingInstallParams?.version;
        const isDown = plugin.version && selVer && compareVersions(selVer, plugin.version) < 0;
        const actionLabel = isDown ? 'Downgrade' : 'Update';
        return (
          <Modal
            opened={installConfirmOpen}
            onClose={() => {
              setInstallConfirmOpen(false);
              setPendingInstallParams(null);
            }}
            zIndex={300}
            title={
              <Group gap="xs" align="center">
                {isDown
                  ? <Download size={18} color="var(--mantine-color-orange-6)" />
                  : <Download size={18} />}
                <Text fw={600}>Confirm {actionLabel}</Text>
              </Group>
            }
            size="sm"
          >
            <Stack gap="md">
              <Text size="sm">
                You are about to {actionLabel.toLowerCase()} <b>{plugin.name}</b>{' '}
                from <b>v{plugin.version}</b> to <b>v{selVer}</b>.
              </Text>
              <PluginSecurityWarning>
                Plugins run server-side code with full access to your Dispatcharr
                instance and its data. Only install plugins from developers you
                trust. Malicious plugins could read or modify data, call internal
                APIs, or perform unwanted actions.
              </PluginSecurityWarning>
              <PluginSupportDisclaimer />
              {isDown && (
                <PluginDowngradeWarning>
                  Downgrading may cause issues with saved settings or data.
                </PluginDowngradeWarning>
              )}
              <Text size="sm" fw={500}>Are you sure you want to proceed?</Text>
              <Group justify="flex-end" gap="xs">
                <Button
                  size="xs"
                  variant="default"
                  onClick={() => {
                    setInstallConfirmOpen(false);
                    setPendingInstallParams(null);
                  }}
                >
                  Cancel
                </Button>
                <Button
                  size="xs"
                  color={isDown ? 'orange' : undefined}
                  onClick={confirmAndInstall}
                >
                  {actionLabel}
                </Button>
              </Group>
            </Stack>
          </Modal>
        );
      })()}
    </div>
  );
};

export default PluginCard;
