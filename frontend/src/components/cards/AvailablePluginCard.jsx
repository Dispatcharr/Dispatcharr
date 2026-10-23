import React, { useState } from 'react';
import {
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
  Text,
  Tooltip,
} from '@mantine/core';
import {
  AlertTriangle,
  Ban,
  CalendarClock,
  Check,
  Download,
  FlaskConical,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import {
  PluginDowngradeWarning,
  PluginInfoNote,
  PluginSecurityWarning,
  PluginSupportDisclaimer,
} from '../PluginWarnings.jsx';
import ConfirmationDialog from '../ConfirmationDialog.jsx';
import { useLocation, useNavigate } from 'react-router-dom';
import { usePluginStore, needsCapabilityAck } from '../../store/plugins';
import PluginDetailPanel from '../PluginDetailPanel.jsx';
import {
  PluginLinks,
  PluginMetadata,
  SignatureIndicator,
} from '../PluginHeader.jsx';
import {
  buildCompatibilityTooltip,
  compareVersions,
  getInstallInfo,
} from '../../utils/components/pluginUtils.js';
import SizedInstallButton from '../theme/SizedInstallButton.jsx';
import {
  deletePluginByKey,
  getPluginDetailManifest,
  setPluginEnabled,
} from '../../utils/pages/PluginsUtils.js';
import './AvailablePluginCard.css';

const RepoBadge = ({ isOfficial, repoName, signatureVerified }) => {
  if (isOfficial) {
    const badge = (
      <Badge
        size="xs"
        variant="filled"
        style={{
          backgroundColor:
            signatureVerified === false
              ? 'var(--mantine-color-red-9)'
              : '#14917E',
        }}
        leftSection={
          signatureVerified != null ? (
            signatureVerified ? (
              <ShieldCheck size={10} />
            ) : (
              <ShieldAlert size={10} />
            )
          ) : undefined
        }
      >
        Official Repo
      </Badge>
    );
    return signatureVerified != null ? (
      <Tooltip
        label={signatureVerified ? 'Verified Signature' : 'Invalid Signature'}
      >
        {badge}
      </Tooltip>
    ) : (
      badge
    );
  }
  if (!repoName) return null;
  const badge = (
    <Badge
      size="xs"
      variant="filled"
      color={signatureVerified === false ? 'red.9' : 'gray'}
      leftSection={
        signatureVerified != null ? (
          signatureVerified ? (
            <ShieldCheck size={10} />
          ) : (
            <ShieldAlert size={10} />
          )
        ) : undefined
      }
    >
      {repoName}
    </Badge>
  );
  return signatureVerified != null ? (
    <Tooltip
      label={signatureVerified ? 'Verified Signature' : 'Invalid Signature'}
    >
      {badge}
    </Tooltip>
  ) : (
    badge
  );
};

const StatusBadge = ({
  status,
  deprecated,
  isPrerelease,
  installedSourceRepoName,
}) => {
  const isLatestDowngrade = status === 'downgrade_available';
  if (status === 'installed') {
    const baseLabel = isPrerelease ? 'Prerelease' : 'Installed';
    if (!deprecated) {
      return (
        <Badge
          size="xs"
          variant="light"
          color={isPrerelease ? 'gray' : 'green'}
          leftSection={
            isPrerelease ? <FlaskConical size={8} /> : <Check size={8} />
          }
        >
          {baseLabel}
        </Badge>
      );
    }
    return (
      <Tooltip
        label={`${isPrerelease ? 'Prerelease installed' : 'Installed'}, but this plugin has been deprecated by its maintainer`}
      >
        <Badge
          size="xs"
          variant="light"
          color={isPrerelease ? 'red' : 'orange'}
          leftSection={<Ban size={8} />}
        >
          {baseLabel} · Deprecated
        </Badge>
      </Tooltip>
    );
  }
  if (status === 'update_available' || status === 'downgrade_available') {
    const baseLabel = isLatestDowngrade
      ? 'Newer Installed'
      : 'Update Available';
    if (!deprecated) {
      return (
        <Badge
          size="xs"
          variant="light"
          color={isLatestDowngrade ? 'orange' : 'yellow'}
          leftSection={
            isLatestDowngrade ? (
              <AlertTriangle size={8} />
            ) : (
              <RefreshCw size={8} />
            )
          }
        >
          {baseLabel}
        </Badge>
      );
    }
    return (
      <Tooltip label="Update available, but this plugin has been deprecated by its maintainer">
        <Badge
          size="xs"
          variant="light"
          color="red"
          leftSection={<Ban size={8} />}
        >
          {baseLabel} · Deprecated
        </Badge>
      </Tooltip>
    );
  }
  if (status === 'unmanaged' || status === 'different_repo') {
    const tooltip =
      status === 'unmanaged'
        ? deprecated
          ? 'Installed manually (deprecated) - installing from this repo will take over management'
          : 'Installed manually - installing from this repo will take over management'
        : `Managed by ${installedSourceRepoName || 'another repo'}${deprecated ? ' (deprecated)' : ''}`;
    return (
      <Tooltip label={tooltip}>
        <Badge
          size="xs"
          variant="light"
          color={deprecated ? 'red' : 'orange'}
          leftSection={deprecated ? <Ban size={8} /> : <Check size={8} />}
        >
          {deprecated ? 'Installed · Deprecated' : 'Installed'}
        </Badge>
      </Tooltip>
    );
  }
  if (deprecated) {
    return (
      <Tooltip label="This plugin has been marked as deprecated by its maintainer">
        <Badge
          size="xs"
          variant="light"
          color="red"
          leftSection={<Ban size={8} />}
        >
          Deprecated
        </Badge>
      </Tooltip>
    );
  }
  return null;
};

const AvailablePluginCardHeader = ({
  plugin,
  signatureVerified = plugin.signature_verified,
}) => (
  <Group justify="space-between" mb="xs" align="flex-start" wrap="nowrap">
    <Group
      gap="sm"
      align="center"
      wrap="nowrap"
      style={{ minWidth: 0, flex: 1 }}
    >
      <Avatar
        src={plugin.icon_url}
        radius="sm"
        size={48}
        alt={`${plugin.name} logo`}
        imageProps={{ draggable: false }}
      >
        {plugin.name?.[0]?.toUpperCase()}
      </Avatar>
      <Box style={{ minWidth: 0, flex: 1 }}>
        <Group gap={4} align="baseline" wrap="nowrap">
          <Text fw={600} lineClamp={1} style={{ minWidth: 0 }}>
            {plugin.name}
          </Text>
          {plugin.latest_version && (
            <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
              v{plugin.latest_version}
            </Text>
          )}
        </Group>
        <Group gap={6} align="center" wrap="nowrap">
          <PluginMetadata
            plugin={plugin}
            license={plugin.license}
            authorClassName="available-plugin-card__author"
            licenseClassName="available-plugin-card__license"
            separatorClassName="available-plugin-card__license-separator"
          />
          <StatusBadge
            status={plugin.install_status}
            deprecated={plugin.deprecated}
            isPrerelease={plugin.installed_version_is_prerelease}
            installedSourceRepoName={plugin.installed_source_repo_name}
          />
        </Group>
      </Box>
    </Group>
    <Stack gap={2} align="flex-end" style={{ flexShrink: 0 }}>
      <RepoBadge
        isOfficial={plugin.is_official_repo}
        repoName={plugin.repo_name}
        signatureVerified={signatureVerified}
      />
    </Stack>
  </Group>
);

const AvailablePluginCard = ({
  plugin,
  appVersion,
  autoOpenDetail = false,
  onDetailClose,
  onInstalled,
  onUninstalled,
  onBeforeInstall,
}) => {
  const meetsMinVersion =
    !plugin.min_dispatcharr_version ||
    compareVersions(appVersion, plugin.min_dispatcharr_version) >= 0;
  const meetsMaxVersion =
    !plugin.max_dispatcharr_version ||
    compareVersions(appVersion, plugin.max_dispatcharr_version) <= 0;
  const meetsVersion = meetsMinVersion && meetsMaxVersion;
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [selectedVersion, setSelectedVersion] = useState(null);
  const [installing, setInstalling] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [restartPromptOpen, setRestartPromptOpen] = useState(false);
  const [installAction, setInstallAction] = useState(null); // 'installed' | 'updated' | 'downgraded'
  const [pendingInstall, setPendingInstall] = useState(null);
  const [installedKey, setInstalledKey] = useState(null);
  const [installedPlugin, setInstalledPlugin] = useState(null);
  const [enableNow, setEnableNow] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [pluginIsDisabled, setPluginIsDisabled] = useState(false);
  const [uninstallConfirmOpen, setUninstallConfirmOpen] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);
  const [deprecationWarnOpen, setDeprecationWarnOpen] = useState(false);
  const [pendingDeprecatedInstall, setPendingDeprecatedInstall] =
    useState(null);
  const installPlugin = usePluginStore((s) => s.installPlugin);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const onMyPlugins = pathname === '/plugins';

  const isLatestDowngrade = plugin.install_status === 'downgrade_available';
  const hasDownloadCount =
    Number.isFinite(plugin.download_count) && plugin.download_count >= 0;

  const doInstall = (params) => {
    if (plugin.deprecated) {
      setPendingDeprecatedInstall(params);
      setDeprecationWarnOpen(true);
      return;
    }
    setPendingInstall(params);
    setConfirmOpen(true);
  };

  const confirmDeprecatedInstall = () => {
    setDeprecationWarnOpen(false);
    if (pendingDeprecatedInstall) {
      setPendingInstall(pendingDeprecatedInstall);
      setPendingDeprecatedInstall(null);
      setConfirmOpen(true);
    }
  };

  const confirmAndInstall = () => {
    setConfirmOpen(false);
    if (pendingInstall) executeInstall(pendingInstall);
  };

  const executeInstall = async (params) => {
    const wasInstalled = plugin.installed;
    const wasDowngrade =
      plugin.installed_version &&
      params.version &&
      compareVersions(params.version, plugin.installed_version) < 0;
    onBeforeInstall?.(plugin.slug);
    setInstalling(true);
    const result = await installPlugin(params);
    setInstalling(false);
    setPendingInstall(null);
    if (result?.error_code === 'capability_confirmation_required') {
      const confirmationPlugin = {
        key: plugin.key || params.slug,
        name: plugin.name,
        capabilities: result.capabilities || [],
      };
      const confirmed = await usePluginStore
        .getState()
        .requestEnableConfirmation(confirmationPlugin, 'update');
      if (confirmed) {
        await executeInstall({
          ...params,
          acknowledge_capabilities: (result.capabilities || []).map((capability) => capability.id),
        });
      } else {
        await installPlugin({ ...params, deny_capabilities: true });
        usePluginStore.getState().invalidatePlugins?.();
      }
      return;
    }
    if (result?.success) {
      setInstallAction(
        wasDowngrade ? 'downgraded' : wasInstalled ? 'updated' : 'installed'
      );
      setInstalledKey(result.plugin?.key || params.slug);
      setInstalledPlugin(result.plugin || null);
      setPluginIsDisabled(result.plugin?.enabled === false);
      setEnableNow(false);
      setRestartPromptOpen(true);
      onInstalled?.(plugin.slug);
    }
  };

  const [uninstallDoneOpen, setUninstallDoneOpen] = useState(false);

  const handleDismissRestart = async (andNavigate = false) => {
    if (enableNow && installedKey) {
      const proceed =
        !needsCapabilityAck(installedPlugin) ||
        (await usePluginStore
          .getState()
          .requestEnableConfirmation(installedPlugin || { key: installedKey }));
      if (proceed) {
        setEnabling(true);
        try {
          await setPluginEnabled(
            installedKey,
            true,
            (installedPlugin?.capabilities || []).map((capability) => capability.id)
          );
        } finally {
          setEnabling(false);
        }
      }
    }
    setRestartPromptOpen(false);
    if (andNavigate) navigate('/plugins');
  };

  const handleUninstall = async () => {
    const key = plugin.key || installedKey;
    if (!key) return;
    setUninstalling(true);
    try {
      const resp = await deletePluginByKey(key);
      if (resp?.success) {
        onUninstalled?.(plugin.slug);
        usePluginStore.getState().invalidatePlugins();
        usePluginStore.getState().fetchAvailablePlugins();
        setUninstallConfirmOpen(false);
        setUninstallDoneOpen(true);
      }
    } finally {
      setUninstalling(false);
    }
  };

  const handleMoreInfo = async () => {
    setDetailOpen(true);
    if (detailLoading) return;
    if (!plugin.manifest_url) {
      // No per-plugin manifest: synthesize from the top-level repo entry (latest only)
      setDetail({
        manifest: {
          description: plugin.description,
          author: plugin.author,
          license: plugin.license,
          versions: plugin.latest_version
            ? [
                {
                  version: plugin.latest_version,
                  url: plugin.latest_url,
                  checksum_sha256: plugin.latest_sha256,
                  min_dispatcharr_version: plugin.min_dispatcharr_version,
                  max_dispatcharr_version: plugin.max_dispatcharr_version,
                  build_timestamp: plugin.last_updated,
                  size: plugin.latest_size,
                  changelog: plugin.latest_changelog,
                },
              ]
            : [],
          latest: plugin.latest_version
            ? { version: plugin.latest_version }
            : null,
        },
        signature_verified: plugin.signature_verified ?? null,
      });
      if (plugin.latest_version) setSelectedVersion(plugin.latest_version);
      return;
    }
    setDetailLoading(true);
    const result = await getPluginDetailManifest(
      plugin.repo_id,
      plugin.manifest_url
    );
    if (result) {
      setDetail(result);
      if (result.manifest?.versions?.length) {
        setSelectedVersion(result.manifest.versions[0].version);
      }
    }
    setDetailLoading(false);
  };

  React.useEffect(() => {
    if (autoOpenDetail) handleMoreInfo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const latestInstallParams = {
    repo_id: plugin.repo_id,
    slug: plugin.slug,
    version: plugin.latest_version,
    download_url: plugin.latest_url,
    sha256: plugin.latest_sha256,
    min_dispatcharr_version: plugin.min_dispatcharr_version,
    max_dispatcharr_version: plugin.max_dispatcharr_version,
  };
  const hasModalActionLinks = Boolean(
    detail?.manifest?.repo_url || detail?.manifest?.discord_thread
  );

  return (
    <Card
      className="available-plugin-card"
      shadow="sm"
      radius="md"
      withBorder
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: 200,
        paddingTop: 12,
        backgroundColor: '#27272A',
      }}
    >
      <AvailablePluginCardHeader plugin={plugin} />

      <Box
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ overflow: 'hidden' }}>
          <Text size="sm" c="dimmed" lineClamp={4} mb={0}>
            {plugin.description}
          </Text>
        </div>
      </Box>

      <Group justify="space-between" mt="sm" align="center" wrap="nowrap">
        {!meetsVersion &&
          (() => {
            const tooltip = buildCompatibilityTooltip(
              meetsMinVersion,
              plugin,
              meetsMaxVersion
            );
            const label = !meetsMinVersion
              ? `Min ${plugin.min_dispatcharr_version}`
              : `Max ${plugin.max_dispatcharr_version}`;
            return (
              <Tooltip
                label={`Incompatible: requires Dispatcharr ${tooltip} (you have v${appVersion})`}
              >
                <Group gap={4} align="center" wrap="nowrap">
                  <AlertTriangle
                    size={14}
                    color="var(--mantine-color-yellow-6)"
                  />
                  <Text size="xs" c="yellow">
                    {label}
                  </Text>
                </Group>
              </Tooltip>
            );
          })()}
        {meetsVersion && (plugin.last_updated || hasDownloadCount) && (
          <Group
            gap={4}
            align="center"
            wrap="nowrap"
          >
            {plugin.last_updated && (
              <Group
                className="available-plugin-card__updated"
                gap={4}
                align="center"
                wrap="nowrap"
              >
                <CalendarClock
                  size={12}
                  color="var(--mantine-color-dimmed)"
                />
                <Text size="xs" c="dimmed">
                  {new Date(plugin.last_updated).toLocaleDateString()}
                </Text>
              </Group>
            )}
            {hasDownloadCount && plugin.last_updated && (
              <Text
                className="available-plugin-card__action-separator"
                size="xs"
                c="dimmed"
              >
                •
              </Text>
            )}
            {hasDownloadCount && (
              <Group
                className="available-plugin-card__downloads"
                gap={3}
                align="center"
                wrap="nowrap"
              >
                <Download size={12} color="var(--mantine-color-dimmed)" />
                <Text size="xs" c="dimmed">
                  {plugin.download_count.toLocaleString()}
                </Text>
              </Group>
            )}
          </Group>
        )}
        {meetsVersion && !plugin.last_updated && !hasDownloadCount && <span />}
        <Group gap="xs" wrap="nowrap">
          <Button
            size="xs"
            variant="default"
            onClick={handleMoreInfo}
          >
            More Info
          </Button>
          {plugin.install_status === 'unmanaged' &&
            plugin.latest_version &&
            plugin.latest_url && (
              <Tooltip label="Installed manually - installing from this repo will take over management">
                <SizedInstallButton
                  size="xs"
                  variant="filled"
                  color="orange"
                  latest_size={plugin.latest_size}
                  leftSection={
                    installing ? <Loader size={14} /> : <Download size={14} />
                  }
                  disabled={!meetsVersion || installing}
                  onClick={() => doInstall(latestInstallParams)}
                >
                  {installing ? 'Installing...' : 'Overwrite'}
                </SizedInstallButton>
              </Tooltip>
            )}
          {plugin.install_status === 'different_repo' && plugin.latest_url && (
            <Tooltip
              label={`Managed by ${plugin.installed_source_repo_name || 'another repo'} - installing will transfer management to this repo`}
            >
              <SizedInstallButton
                size="xs"
                variant="filled"
                color="orange"
                latest_size={plugin.latest_size}
                leftSection={
                  installing ? <Loader size={14} /> : <Download size={14} />
                }
                disabled={!meetsVersion || installing}
                onClick={() => doInstall(latestInstallParams)}
              >
                {installing ? 'Installing...' : 'Overwrite'}
              </SizedInstallButton>
            </Tooltip>
          )}
          {plugin.install_status === 'installed' && (
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
          {(plugin.install_status === 'update_available' ||
            plugin.install_status === 'downgrade_available') && (
            <SizedInstallButton
              size="xs"
              variant="filled"
              color={isLatestDowngrade ? 'orange' : 'yellow'}
              latest_size={plugin.latest_size}
              leftSection={
                installing ? (
                  <Loader size={14} />
                ) : isLatestDowngrade ? (
                  <AlertTriangle size={14} />
                ) : (
                  <RefreshCw size={14} />
                )
              }
              disabled={!meetsVersion || installing}
              onClick={() => doInstall(latestInstallParams)}
            >
              {installing
                ? isLatestDowngrade
                  ? 'Downgrading...'
                  : 'Updating...'
                : isLatestDowngrade
                  ? 'Downgrade'
                  : 'Update'}
            </SizedInstallButton>
          )}
          {(!plugin.install_status ||
            plugin.install_status === 'not_installed') &&
            plugin.latest_url && (
              <SizedInstallButton
                size="xs"
                variant="filled"
                latest_size={plugin.latest_size}
                leftSection={
                  installing ? <Loader size={14} /> : <Download size={14} />
                }
                disabled={!meetsVersion || installing}
                onClick={() => doInstall(latestInstallParams)}
              >
                {installing ? 'Installing...' : 'Install'}
              </SizedInstallButton>
            )}
        </Group>
      </Group>

      {/* Detail Modal */}
      <Modal
        opened={detailOpen}
        onClose={() => {
          setDetailOpen(false);
          onDetailClose?.();
        }}
        title={
          <Group gap="sm" align="center" wrap="nowrap" style={{ minWidth: 0 }}>
            <Avatar
              src={plugin.icon_url}
              radius="sm"
              size={48}
              alt={`${plugin.name} logo`}
              imageProps={{ draggable: false }}
            >
              {plugin.name?.[0]?.toUpperCase()}
            </Avatar>
            <Box style={{ minWidth: 0, flex: 1 }}>
              <Group gap={4} align="baseline" wrap="nowrap">
                <Text fw={600} lineClamp={1} style={{ minWidth: 0 }}>
                  {plugin.name}
                </Text>
                {plugin.latest_version && (
                  <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                    v{plugin.latest_version}
                  </Text>
                )}
                <SignatureIndicator
                  signatureVerified={
                    detail?.signature_verified ?? plugin.signature_verified
                  }
                />
              </Group>
              <PluginMetadata
                plugin={{ author: detail?.manifest?.author ?? plugin.author }}
                license={detail?.manifest?.license ?? plugin.license}
                sourceRepoName={plugin.repo_name}
                trailing={<PluginLinks helpUrl={detail?.manifest?.help_url} compact />}
              />
            </Box>
          </Group>
        }
        size="lg"
      >
        <PluginDetailPanel
          detail={detail}
          detailLoading={detailLoading}
          selectedVersion={selectedVersion}
          onVersionChange={setSelectedVersion}
          installedVersion={plugin.installed_version}
          installedVersionIsPrerelease={
            !!plugin.installed_version_is_prerelease
          }
          appVersion={appVersion}
          installing={installing}
          uninstalling={uninstalling}
          onInstall={doInstall}
          onUninstall={() => setUninstallConfirmOpen(true)}
          installStatus={plugin.install_status}
          installedSourceRepoName={plugin.installed_source_repo_name}
          repoId={plugin.repo_id}
          slug={plugin.slug}
          hideMetadata
          metadataActions={hasModalActionLinks ? (
            <PluginLinks
              repoUrl={detail?.manifest?.repo_url}
              discordThread={detail?.manifest?.discord_thread}
              compact
              asButtons
            />
          ) : null}
        />
      </Modal>

      <ConfirmationDialog
        opened={deprecationWarnOpen}
        onClose={() => {
          setDeprecationWarnOpen(false);
          setPendingDeprecatedInstall(null);
        }}
        onConfirm={confirmDeprecatedInstall}
        zIndex={300}
        size="sm"
        title={
          <Group gap="xs" align="center">
            <Ban size={18} color="var(--mantine-color-red-6)" />
            <Text fw={600}>Deprecated Plugin</Text>
          </Group>
        }
        confirmLabel="Install Anyway"
        message={
          <Stack gap="md">
            <Text size="sm">
              <b>{plugin.name}</b> has been marked as <b>deprecated</b> by its
              maintainer.
            </Text>
            <Text size="sm" c="dimmed">
              Deprecated plugins may no longer receive updates or fixes, and
              could stop working with future versions of Dispatcharr. It is
              recommended to look for an alternative.
            </Text>
            <PluginSecurityWarning>
              Plugins run server-side code with full access to your
              Dispatcharr instance and its data. Only install plugins from
              developers you trust. Malicious plugins could read or modify
              data, call internal APIs, or perform unwanted actions.
            </PluginSecurityWarning>
            <PluginSupportDisclaimer />
            <Text size="sm" fw={500}>
              Do you still want to proceed?
            </Text>
          </Stack>
        }
      />

      {/* Unified install confirmation modal */}
      {(() => {
        const { isDowngrade, isUpdate, isBadSig } = getInstallInfo(
          pendingInstall,
          plugin
        );
        const actionLabel = isDowngrade
          ? 'Downgrade'
          : isUpdate
            ? 'Update'
            : 'Install';
        const btnColor =
          isDowngrade && isBadSig
            ? 'red'
            : isDowngrade
              ? 'orange'
              : isBadSig
                ? 'red'
                : 'blue';
        return (
          <ConfirmationDialog
            opened={confirmOpen}
            onClose={() => {
              setConfirmOpen(false);
              setPendingInstall(null);
            }}
            onConfirm={confirmAndInstall}
            zIndex={300}
            size="sm"
            title={
              <Group gap="xs" align="center">
                {isBadSig ? (
                  <ShieldAlert size={18} color="var(--mantine-color-red-6)" />
                ) : isDowngrade ? (
                  <AlertTriangle
                    size={18}
                    color="var(--mantine-color-orange-6)"
                  />
                ) : (
                  <Download size={18} />
                )}
                <Text fw={600}>Confirm {actionLabel}</Text>
              </Group>
            }
            confirmLabel={actionLabel}
            confirmColor={btnColor}
            message={
              <Stack gap="md">
                <Text size="sm">
                  You are about to {actionLabel.toLowerCase()}{' '}
                  <b>{plugin.name}</b>{' '}
                  {isUpdate || isDowngrade ? (
                    <>
                      from <b>v{plugin.installed_version}</b> to{' '}
                      <b>v{pendingInstall?.version}</b>
                    </>
                  ) : (
                    <>
                      <b>v{pendingInstall?.version}</b>
                    </>
                  )}
                  {plugin.repo_name ? (
                    <>
                      {' '}
                      from <b>{plugin.repo_name}</b>
                    </>
                  ) : (
                    ''
                  )}
                  .
                </Text>
                <PluginSecurityWarning>
                  Plugins run server-side code with full access to your
                  Dispatcharr instance and its data. Only install plugins from
                  developers you trust. Malicious plugins could read or modify
                  data, call internal APIs, or perform unwanted actions.
                </PluginSecurityWarning>
                <PluginSupportDisclaimer />
                {isDowngrade && (
                  <PluginDowngradeWarning>
                    Downgrading may cause issues with saved settings or data.
                  </PluginDowngradeWarning>
                )}
                {isBadSig && (
                  <PluginSecurityWarning>
                    This repository has an invalid or unverified signature.
                    Installing plugins from unverified sources may be risky.
                  </PluginSecurityWarning>
                )}
                {plugin.install_status === 'unmanaged' && (
                  <PluginInfoNote>
                    This plugin was installed manually. Installing from this
                    repo will bring it under repo management and enable
                    future update checks.
                  </PluginInfoNote>
                )}
                {plugin.install_status === 'different_repo' && (
                  <PluginInfoNote>
                    This plugin is currently managed by{' '}
                    <b>{plugin.installed_source_repo_name || 'another repo'}</b>.
                    Installing will transfer management to this repo.
                  </PluginInfoNote>
                )}
                <Text size="sm" fw={500}>
                  Are you sure you want to proceed?
                </Text>
              </Stack>
            }
          />
        );
      })()}

      <ConfirmationDialog
        opened={uninstallConfirmOpen}
        onClose={() => setUninstallConfirmOpen(false)}
        onConfirm={handleUninstall}
        zIndex={300}
        size="sm"
        title={
          <Group gap="xs" align="center">
            <Trash2 size={18} color="var(--mantine-color-red-6)" />
            <Text fw={600}>Uninstall Plugin</Text>
          </Group>
        }
        confirmLabel="Uninstall"
        loading={uninstalling}
        message={
          <Text size="sm">
            Are you sure you want to uninstall <b>{plugin.name}</b>? This
            will remove the plugin files and all associated settings.
          </Text>
        }
      />

      {/* Post-uninstall notice */}
      <Modal
        opened={uninstallDoneOpen}
        onClose={() => setUninstallDoneOpen(false)}
        zIndex={300}
        title={
          <Group gap="xs" align="center">
            <Trash2 size={18} color="var(--mantine-color-green-6)" />
            <Text fw={600}>Plugin Uninstalled</Text>
          </Group>
        }
        size="sm"
      >
        <Stack gap="md">
          <Text size="sm">
            <b>{plugin.name}</b> has been uninstalled successfully.
          </Text>
          <Text size="sm">
            A restart of Dispatcharr may be required to fully unload the plugin.
          </Text>
          <Group justify="flex-end">
            <Button
              size="xs"
              variant="default"
              onClick={() => setUninstallDoneOpen(false)}
            >
              Done
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Post-install restart prompt */}
      <Modal
        opened={restartPromptOpen}
        onClose={() => setRestartPromptOpen(false)}
        zIndex={300}
        title={
          <Group gap="xs" align="center">
            <RotateCcw size={18} color="var(--mantine-color-blue-6)" />
            <Text fw={600}>
              Plugin{' '}
              {installAction === 'installed'
                ? 'Installed'
                : installAction === 'downgraded'
                  ? 'Downgraded'
                  : 'Updated'}
            </Text>
          </Group>
        }
        size="sm"
      >
        <Stack gap="md">
          <Text size="sm">
            <b>{plugin.name}</b> has been {installAction || 'installed'}{' '}
            successfully.
          </Text>
          <Text size="sm">
            A restart of Dispatcharr may be required for the plugin to be fully
            loaded.
          </Text>
          {pluginIsDisabled && (
            <>
              <Text size="xs" c="dimmed">
                This plugin is currently disabled. You can enable it now or at
                any time from My Plugins.
              </Text>
              <Group justify="space-between" align="center">
                <Text size="sm">Enable plugin</Text>
                <Switch
                  size="sm"
                  checked={enableNow}
                  onChange={(e) => setEnableNow(e.currentTarget.checked)}
                />
              </Group>
            </>
          )}
          <Group justify="flex-end" gap="xs">
            <Button
              size="xs"
              variant="default"
              loading={enabling}
              onClick={() => handleDismissRestart(false)}
            >
              Done
            </Button>
            {!onMyPlugins && (
              <Button
                size="xs"
                loading={enabling}
                onClick={() => handleDismissRestart(true)}
              >
                Go to My Plugins
              </Button>
            )}
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
};

export default AvailablePluginCard;
