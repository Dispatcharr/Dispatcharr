import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import {
  ActionIcon,
  AppShellMain,
  Badge,
  Box,
  Button,
  Collapse,
  Grid,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Tooltip,
  Transition,
  UnstyledButton,
} from '@mantine/core';
import { ArrowLeft, ChevronDown, Pin, PinOff, RefreshCw, RotateCw, Trash2 } from 'lucide-react';
import { showNotification } from '../utils/notificationUtils.js';
import { usePluginStore, needsCapabilityAck } from '../store/plugins.jsx';
import useSettingsStore from '../store/settings.jsx';
import useAuthStore from '../store/auth.jsx';
import {
  computeResetSettings,
  deletePluginByKey,
  reloadPlugin,
  refreshSinglePlugin,
  runPluginAction,
  setPluginEnabled,
  updatePluginSettings,
} from '../utils/pages/PluginsUtils.js';
import { getConfirmationDetails } from '../utils/cards/PluginCardUtils.js';
import { compareVersions } from '../utils/components/pluginUtils.js';
import ConfirmationDialog from '../components/ConfirmationDialog.jsx';
import PluginEnableConfirmModal from '../components/PluginEnableConfirmModal.jsx';
import PluginHeader from '../components/PluginHeader.jsx';
import PluginDetailPanel from '../components/PluginDetailPanel.jsx';
import PluginFieldList from '../components/PluginFieldList.jsx';
import EvenlyWrappedPills from '../components/EvenlyWrappedPills.jsx';
import { PluginActionList, PluginActionStatus, PluginTaskList } from '../components/PluginActionList.jsx';
import API from '../api';
import './plugin-detail.css';

// Stable fallback reference, see PluginCard.jsx.
const EMPTY_PINNED_PLUGINS = [];

/** Section heading with a collapse chevron, only interactive/collapsible
    in single-column mode, where a long section pushes everything below it
    further down; always expanded (and non-clickable) in the two-column
    layout, where each section already has its own column. */
const CollapsibleHeading = ({ label, isSingleCol, opened, onToggle }) => (
  <UnstyledButton
    onClick={isSingleCol ? onToggle : undefined}
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      cursor: isSingleCol ? 'pointer' : 'default',
    }}
  >
    <Text fw={600} size="sm">{label}</Text>
    {isSingleCol && (
      <ChevronDown
        size={14}
        style={{
          transform: opened ? 'rotate(180deg)' : 'none',
          transition: 'transform 0.15s ease',
        }}
      />
    )}
  </UnstyledButton>
);

// Routing to a different plugin re-renders this same component instance
// with a new `key` route param rather than mounting a fresh one, which left
// stale local state (enabled/version/settings/modals from the previous
// plugin) visible until each individual effect caught up. Keying the actual
// implementation by the route param forces a full remount on every plugin
// switch instead, which resets everything at once and is far less fragile
// than auditing every useState for a manual reset.
export default function PluginDetail() {
  const { key } = useParams();
  return <PluginDetailForKey key={key} routeKey={key} />;
}

function PluginDetailForKey({ routeKey: key }) {
  const navigate = useNavigate();
  const appVersion = useSettingsStore((s) => s.version?.version || '');
  const plugins = usePluginStore((s) => s.plugins);
  const pluginsLoading = usePluginStore((s) => s.loading);
  const installPlugin = usePluginStore((s) => s.installPlugin);
  const pinnedPlugins = useAuthStore(
    (s) => s.user?.custom_properties?.pinnedPlugins || EMPTY_PINNED_PLUGINS
  );
  const togglePinnedPlugin = useAuthStore((s) => s.togglePinnedPlugin);

  const plugin = plugins.find((p) => p.key === key);
  const pinned = plugin ? pinnedPlugins.includes(plugin.key) : false;

  useEffect(() => {
    if (!plugin && !pluginsLoading) {
      usePluginStore.getState().fetchPlugins();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const [settings, setSettings] = useState(plugin?.settings || {});
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(!!plugin?.enabled);
  const [runningActionId, setRunningActionId] = useState(null);
  const [lastResult, setLastResult] = useState(null);

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [installing, setInstalling] = useState(false);
  const [installConfirmOpen, setInstallConfirmOpen] = useState(false);
  const [pendingInstallParams, setPendingInstallParams] = useState(null);
  const [uninstallConfirmOpen, setUninstallConfirmOpen] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [reloadConfirmOpen, setReloadConfirmOpen] = useState(false);
  const [reloadingCode, setReloadingCode] = useState(false);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  // Matches the Grid.Col `lg` breakpoint (see plugin-detail.css); below it
  // the layout is a single stacked column, where a long Actions list makes
  // more sense collapsed than pushing Settings further down.
  const isSingleCol = useMediaQuery('(max-width: 74.99em)');
  const [actionsOpened, { toggle: toggleActions }] = useDisclosure(true);
  const [settingsOpened, { toggle: toggleSettings }] = useDisclosure(true);
  // Independent of isSingleCol: unlike Actions/Settings, this section
  // should stay user-toggleable regardless of layout breakpoint.
  const [tasksOpened, { toggle: toggleTasks }] = useDisclosure(true);
  const allPluginTasks = usePluginStore((s) => s.pluginTasks) || {};
  const pluginTasks = Object.fromEntries(
    Object.entries(allPluginTasks).filter(([, t]) => t.pluginKey === plugin?.key)
  );
  const hasPluginTasks = Object.keys(pluginTasks).length > 0;

  useEffect(() => {
    setSettings(plugin?.settings || {});
    setEnabled(!!plugin?.enabled);
  }, [plugin?.key, plugin?.settings, plugin?.enabled]);

  // Rehydrate the Tasks panel from the backend's bounded task history so
  // past runs (including from a prior page load or another tab) show up
  // alongside anything already tracked live in this session.
  useEffect(() => {
    if (!plugin?.key) return;
    let cancelled = false;
    API.getPluginTaskHistory(plugin.key).then((tasks) => {
      if (cancelled) return;
      usePluginStore.getState().hydratePluginTasks(plugin.key, plugin.name, tasks);
    });
    return () => {
      cancelled = true;
    };
  }, [plugin?.key, plugin?.name]);

  const isManaged = !!(plugin?.slug && plugin?.source_repo);

  const fetchDetail = async () => {
    if (!plugin || detailLoading || !isManaged) return;
    let avail = usePluginStore
      .getState()
      .availablePlugins.find(
        (ap) => ap.slug === plugin.slug && ap.repo_id === plugin.source_repo
      );
    if (!avail) {
      setDetailLoading(true);
      try {
        await usePluginStore.getState().fetchAvailablePlugins();
        avail = usePluginStore
          .getState()
          .availablePlugins.find(
            (ap) => ap.slug === plugin.slug && ap.repo_id === plugin.source_repo
          );
      } catch {
        /* ignore */
      }
    }
    if (!avail) {
      setDetailLoading(false);
      return;
    }
    if (!avail.manifest_url) {
      setDetail({
        manifest: {
          description: avail.description,
          author: avail.author,
          license: avail.license,
          repo_url: avail.repo_url,
          discord_thread: avail.discord_thread,
          registry_url: avail.registry_url,
          versions: avail.latest_version
            ? [
                {
                  version: avail.latest_version,
                  url: avail.latest_url,
                  checksum_sha256: avail.latest_sha256,
                  min_dispatcharr_version: avail.min_dispatcharr_version,
                  max_dispatcharr_version: avail.max_dispatcharr_version,
                  build_timestamp: avail.last_updated,
                  size: avail.latest_size,
                },
              ]
            : [],
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

  useEffect(() => {
    if (isManaged) fetchDetail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plugin?.key, isManaged]);

  if (!plugin) {
    return (
      <AppShellMain p={16}>
        {pluginsLoading ? (
          <Loader />
        ) : (
          <Stack gap="sm">
            <Text c="dimmed">Plugin not found.</Text>
            <Button
              variant="default"
              size="xs"
              leftSection={<ArrowLeft size={14} />}
              onClick={() => navigate('/plugins')}
              style={{ alignSelf: 'flex-start' }}
            >
              Back to Plugins
            </Button>
          </Stack>
        )}
      </AppShellMain>
    );
  }

  const missing = plugin.missing;
  const hasFields = !missing && enabled && plugin.fields?.length > 0;
  const hasActions = !missing && enabled && plugin.actions?.length > 0;
  const isSettingsDirty =
    hasFields && JSON.stringify(settings) !== JSON.stringify(plugin.settings || {});

  // Managed plugins: once the per-version manifest loads, its description
  // is more current than the summary one on `plugin` (e.g. after picking a
  // different version in the selector below).
  const displayDescription =
    (isManaged && detail?.manifest?.description) || plugin.description;

  // PluginDetailPanel's own version-action button already says "Uninstall"
  // when the selected version equals the installed one; showing the
  // standalone Uninstall button too in that state would duplicate it.
  const versionActionIsUninstall =
    isManaged &&
    !!plugin.version &&
    !!selectedVersion &&
    compareVersions(selectedVersion, plugin.version) === 0;

  const pillItems = [
    {
      key: 'version',
      node: (
        <Badge size="xs" variant="default">
          <span style={{ opacity: 0.5, marginRight: 4 }}>VERSION</span>v{plugin.version || '1.0.0'}
        </Badge>
      ),
    },
  ];
  if (plugin.is_managed && plugin.source_repo_name) {
    pillItems.push({
      key: 'repo',
      node: (
        <Badge size="xs" variant="default">
          <span style={{ opacity: 0.5, marginRight: 4 }}>REPO</span>
          {plugin.source_repo_name}
        </Badge>
      ),
    });
  }
  // Author isn't a pill here: it's already shown right under the plugin
  // name in the header (PluginHeader's AuthorRow).
  if (isManaged && detail?.manifest?.license) {
    pillItems.push({
      key: 'license',
      node: (
        <Badge
          size="xs"
          variant="default"
          component="a"
          href={`https://spdx.org/licenses/${encodeURIComponent(detail.manifest.license)}.html`}
          target="_blank"
          rel="noopener noreferrer"
          style={{ cursor: 'pointer' }}
        >
          <span style={{ opacity: 0.5, marginRight: 4 }}>LICENSE</span>
          {detail.manifest.license}
        </Badge>
      ),
    });
  }

  const updateField = (id, val) => {
    setSettings((prev) => ({ ...prev, [id]: val }));
  };

  const handleResetToDefaults = async () => {
    const defaults = computeResetSettings(plugin.fields);
    setSettings(defaults);
    await saveSettings(defaults);
    setResetConfirmOpen(false);
  };

  const handleEnableChange = async (next) => {
    if (next && needsCapabilityAck(plugin)) {
      const ok = await usePluginStore.getState().requestEnableConfirmation(plugin);
      if (!ok) return;
    }
    const previous = enabled;
    setEnabled(next);
    try {
      const resp = await setPluginEnabled(plugin.key, next);
      if (resp?.success) {
        const updates = resp?.plugin || { enabled: next, ever_enabled: resp?.ever_enabled };
        usePluginStore.getState().updatePlugin(plugin.key, updates);
      } else {
        setEnabled(previous);
      }
    } catch {
      setEnabled(previous);
    }
  };

  const saveSettings = async (settingsToSave = settings) => {
    setSaving(true);
    try {
      const result = await updatePluginSettings(plugin.key, settingsToSave);
      if (result) {
        usePluginStore.getState().updatePlugin(plugin.key, { settings: settingsToSave });
        showNotification({ title: 'Saved', message: `${plugin.name} settings updated`, color: 'green' });
      } else {
        showNotification({ title: `${plugin.name} error`, message: 'Failed to update settings', color: 'red' });
      }
    } catch (e) {
      showNotification({ title: `${plugin.name} error`, message: e?.message || 'Failed to update settings', color: 'red' });
    } finally {
      setSaving(false);
    }
  };

  const handlePluginRun = async (action) => {
    try {
      const { requireConfirm, confirmTitle, confirmMessage } = getConfirmationDetails(action, plugin, settings);
      if (requireConfirm && !window.confirm(`${confirmTitle}\n\n${confirmMessage}`)) return;

      setRunningActionId(action.id);
      setLastResult(null);
      if (isSettingsDirty) {
        try {
          await updatePluginSettings(plugin.key, settings);
        } catch {
          /* ignore, run anyway */
        }
      }
      const resp = await runPluginAction(plugin.key, action.id);
      if (resp?.status === 'started' && resp?.task_id) {
        usePluginStore.getState().startPluginTask(resp.task_id, {
          pluginKey: plugin.key,
          plugin: plugin.name,
          actionId: action.id,
          actionLabel: action.label,
        });
        showNotification({
          id: `plugin-task-${resp.task_id}`,
          title: plugin.name,
          message: `${action.label} started`,
          color: 'blue',
          loading: true,
          autoClose: false,
        });
      } else if (resp?.success) {
        setLastResult(resp.result || {});
        showNotification({ title: plugin.name, message: resp.result?.message || 'Plugin action completed', color: 'green' });
      } else {
        const err = resp?.error || 'Unknown error';
        setLastResult({ error: err });
        showNotification({ title: `${plugin.name} error`, message: String(err), color: 'red' });
      }
    } finally {
      setRunningActionId(null);
    }
  };

  const handleDetailInstall = (params) => {
    setPendingInstallParams(params);
    setInstallConfirmOpen(true);
  };

  const selVer = pendingInstallParams?.version;
  const isDown = plugin.version && selVer && compareVersions(selVer, plugin.version) < 0;

  const confirmAndInstall = async () => {
    if (!pendingInstallParams) return;
    const params = pendingInstallParams;
    setInstallConfirmOpen(false);
    setPendingInstallParams(null);
    setInstalling(true);
    try {
      const result = await installPlugin(params);
      if (result?.success) {
        showNotification({
          title: plugin.name,
          message: `Successfully ${isDown ? 'downgraded' : 'updated'} to v${params.version}`,
          color: 'green',
        });
        usePluginStore.getState().invalidatePlugins();
      }
    } finally {
      setInstalling(false);
    }
  };

  const handleCheckForUpdate = async () => {
    if (!plugin.source_repo || !plugin.slug) return;
    setCheckingUpdate(true);
    try {
      await refreshSinglePlugin(plugin.source_repo, plugin.slug);
      await usePluginStore.getState().fetchPlugins();
      await usePluginStore.getState().fetchAvailablePlugins();
      await fetchDetail();
    } finally {
      setCheckingUpdate(false);
    }
  };

  const handleReloadCode = async () => {
    setReloadingCode(true);
    try {
      const resp = await reloadPlugin(plugin.key);
      if (resp?.success) {
        await usePluginStore.getState().fetchPlugins();
        showNotification({ title: plugin.name, message: 'Plugin code reloaded', color: 'green' });
      } else {
        showNotification({
          title: `${plugin.name} error`,
          message: resp?.error || 'Failed to reload plugin code',
          color: 'red',
        });
      }
    } finally {
      setReloadingCode(false);
      setReloadConfirmOpen(false);
    }
  };

  const handleUninstall = async () => {
    setUninstalling(true);
    try {
      const resp = await deletePluginByKey(plugin.key);
      if (resp?.success) {
        usePluginStore.getState().removePlugin(plugin.key);
        showNotification({ title: plugin.name, message: 'Plugin deleted', color: 'green' });
        navigate('/plugins');
      }
    } finally {
      setUninstalling(false);
      setUninstallConfirmOpen(false);
    }
  };

  return (
    <AppShellMain p={0}>
      <div className="plugin-detail-bg-host">
        <Grid gutter={0} className="plugin-detail-grid">
        <Grid.Col
          span={{ base: 12, lg: 4 }}
          className="plugin-detail-col-padding"
        >
          <Stack gap="md">
            <Stack gap="md" align="center">
              <PluginHeader
                plugin={plugin}
                avatarSize={56}
                centered
                repoUrl={isManaged ? detail?.manifest?.repo_url : undefined}
                discordThread={isManaged ? detail?.manifest?.discord_thread : undefined}
                signatureVerified={isManaged ? detail?.signature_verified : undefined}
              />

              <Text size="sm" c="dimmed" ta="center">
                {displayDescription}
              </Text>

              {(missing || plugin.legacy) && (
                <Text size="xs" c={missing ? 'red' : 'yellow'} ta="center">
                  {missing
                    ? 'Missing plugin files. Re-import or delete this entry.'
                    : 'Please update or ask the developer to add plugin.json.'}
                </Text>
              )}

              <EvenlyWrappedPills items={pillItems} gap="xs" justify="center" />
            </Stack>

            {/* Dispatcharr-provided controls (not part of the plugin's own
                Actions list below) all live together in one pane. */}
            <Paper withBorder radius="sm" p="sm" className="plugin-management-pane">
              <Stack gap="sm">
                <Group justify="space-between" align="center">
                  <Text size="xs" fw={600} c="dimmed" tt="uppercase">
                    Plugin Control
                  </Text>
                  <Group gap="xs" align="center">
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
                    <SegmentedControl
                      size="xs"
                      value={enabled ? 'on' : 'off'}
                      onChange={(value) => handleEnableChange(value === 'on')}
                      disabled={missing}
                      data={[
                        { label: 'Disabled', value: 'off' },
                        { label: 'Enabled', value: 'on' },
                      ]}
                    />
                  </Group>
                </Group>
                <Group gap="xs" wrap="wrap" align="center" grow>
                  {isManaged && (
                    <Button
                      size="xs"
                      variant="default"
                      loading={checkingUpdate}
                      disabled={checkingUpdate}
                      leftSection={<RefreshCw size={14} />}
                      onClick={handleCheckForUpdate}
                    >
                      Check for Updates
                    </Button>
                  )}
                  <Button
                    size="xs"
                    variant="default"
                    loading={reloadingCode}
                    disabled={reloadingCode || missing}
                    leftSection={<RotateCw size={14} />}
                    onClick={() => setReloadConfirmOpen(true)}
                  >
                    Reload Plugin
                  </Button>
                  {/* PluginDetailPanel's own version-action button already IS
                      the uninstall action when the selected version equals
                      the installed one, so don't show a second one in that
                      state. */}
                  {!versionActionIsUninstall && (
                    <Button
                      size="xs"
                      variant="light"
                      color="red"
                      leftSection={<Trash2 size={14} />}
                      onClick={() => setUninstallConfirmOpen(true)}
                    >
                      Uninstall
                    </Button>
                  )}
                </Group>

                {isManaged && (
                  <PluginDetailPanel
                    hideMeta
                    compactVersionDetails
                    hideVersionLabel
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
                    onUninstall={() => setUninstallConfirmOpen(true)}
                    installStatus={plugin.install_status || 'installed'}
                    repoId={plugin.source_repo}
                    slug={plugin.slug}
                  />
                )}
              </Stack>
            </Paper>

            {hasPluginTasks && (
              <Stack gap="sm">
                <CollapsibleHeading
                  label="Background Tasks"
                  isSingleCol
                  opened={tasksOpened}
                  onToggle={toggleTasks}
                />
                <Collapse in={tasksOpened}>
                  <PluginTaskList tasks={pluginTasks} />
                </Collapse>
              </Stack>
            )}

            {hasActions && (
              <Stack gap="sm">
                <CollapsibleHeading
                  label="Actions"
                  isSingleCol={isSingleCol}
                  opened={actionsOpened}
                  onToggle={toggleActions}
                />
                <Collapse in={!isSingleCol || actionsOpened}>
                  <Stack gap="sm">
                    <PluginActionList
                      plugin={plugin}
                      enabled={enabled}
                      runningActionId={runningActionId}
                      handlePluginRun={handlePluginRun}
                    />
                    <PluginActionStatus running={!!runningActionId} lastResult={lastResult} />
                  </Stack>
                </Collapse>
              </Stack>
            )}
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 8 }} className="plugin-detail-col-padding">
          {hasFields ? (
            <Stack gap="md">
              <Group justify="space-between">
                <CollapsibleHeading
                  label="Settings"
                  isSingleCol={isSingleCol}
                  opened={settingsOpened}
                  onToggle={toggleSettings}
                />
                <Button
                  variant="subtle"
                  color="gray"
                  size="xs"
                  onClick={() => setResetConfirmOpen(true)}
                >
                  Reset to Defaults
                </Button>
              </Group>
              <Collapse in={!isSingleCol || settingsOpened}>
                <Stack gap="md">
                  <PluginFieldList plugin={plugin} settings={settings} updateField={updateField} />
                  {/* Reserves space for the fixed save bar below so it never
                      sits on top of the last field, regardless of scroll
                      position; see the bar itself past the Grid. */}
                  {isSettingsDirty && <Box style={{ height: 64 }} />}
                </Stack>
              </Collapse>
            </Stack>
          ) : !enabled ? (
            <Text c="dimmed" size="sm">
              Enable this plugin to configure it.
            </Text>
          ) : (
            <Text c="dimmed" size="sm">
              This plugin has no configurable settings.
            </Text>
          )}
        </Grid.Col>
        </Grid>
      </div>

      {/* Persistent save bar: pops in the moment settings differ from the
          last-saved values, and stays fixed to the viewport bottom so it's
          reachable from any scroll position; the Box spacer above (in the
          Settings column) reserves room for it so it never covers a field. */}
      <Transition mounted={isSettingsDirty} transition="slide-up" duration={150}>
        {(styles) => (
          <Paper
            withBorder
            radius={0}
            p="sm"
            style={{
              ...styles,
              position: 'fixed',
              bottom: 0,
              left: 'var(--app-shell-navbar-width, 0px)',
              right: 0,
              zIndex: 200,
              borderLeft: 0,
              borderRight: 0,
              borderBottom: 0,
              backgroundColor: '#1A1A1E',
            }}
          >
            <Group justify="flex-end" gap="xs">
              <Text size="xs" c="dimmed" style={{ flex: 1 }}>
                Unsaved settings changes
              </Text>
              <Button
                variant="default"
                disabled={saving}
                onClick={() => setSettings(plugin?.settings || {})}
                size="xs"
              >
                Discard
              </Button>
              <Button loading={saving} onClick={() => saveSettings()} size="xs">
                Save
              </Button>
            </Group>
          </Paper>
        )}
      </Transition>

      {/* Install/update confirmation modal */}
      <ConfirmationDialog
        opened={installConfirmOpen}
        onClose={() => {
          setInstallConfirmOpen(false);
          setPendingInstallParams(null);
        }}
        onConfirm={confirmAndInstall}
        zIndex={300}
        size="sm"
        title={`Confirm ${isDown ? 'Downgrade' : 'Update'}`}
        message={
          <>
            You are about to {isDown ? 'downgrade' : 'update'} <b>{plugin.name}</b> from{' '}
            <b>v{plugin.version}</b> to <b>v{selVer}</b>.
          </>
        }
        confirmLabel={isDown ? 'Downgrade' : 'Update'}
        confirmColor={isDown ? 'orange' : undefined}
      />

      {/* Reset to Defaults confirmation modal */}
      <ConfirmationDialog
        opened={resetConfirmOpen}
        onClose={() => setResetConfirmOpen(false)}
        onConfirm={handleResetToDefaults}
        zIndex={300}
        title="Reset settings to defaults?"
        message="This will reset every setting to its default value and save immediately. This cannot be undone."
        confirmLabel="Reset"
        confirmColor={undefined}
        loading={saving}
      />

      {/* Reload Plugin confirmation modal */}
      <ConfirmationDialog
        opened={reloadConfirmOpen}
        onClose={() => setReloadConfirmOpen(false)}
        onConfirm={handleReloadCode}
        zIndex={300}
        title="Reload plugin code?"
        message="This reimports the plugin's Python code from disk. Continue?"
        confirmLabel="Reload"
        confirmColor={undefined}
        loading={reloadingCode}
      />

      {/* Uninstall confirmation modal */}
      <ConfirmationDialog
        opened={uninstallConfirmOpen}
        onClose={() => setUninstallConfirmOpen(false)}
        onConfirm={handleUninstall}
        zIndex={300}
        title={`Delete ${plugin.name}?`}
        message="This will remove the plugin files and its configuration. This action cannot be undone."
        confirmLabel="Delete"
        loading={uninstalling}
      />

      <PluginEnableConfirmModal />
    </AppShellMain>
  );
}
