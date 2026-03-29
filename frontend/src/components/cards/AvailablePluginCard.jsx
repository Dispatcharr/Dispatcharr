import React, { useState } from 'react';
import {
  ActionIcon,
  Avatar,
  Badge,
  Box,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
import { AlertTriangle, Check, Download, Info, RefreshCw, RotateCcw, ShieldAlert, ShieldCheck, Trash2 } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import API from '../../api';
import { usePluginStore } from '../../store/plugins';

const GitHubIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
  </svg>
);

const DiscordIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.947 2.418-2.157 2.418z" />
  </svg>
);

const AvailablePluginCard = ({ plugin, appVersion, multiRepo = false, autoOpenDetail = false, onDetailClose, onInstalled }) => {
  const meetsMinVersion = !plugin.min_dispatcharr_version || compareVersions(appVersion, plugin.min_dispatcharr_version) >= 0;
  const meetsMaxVersion = !plugin.max_dispatcharr_version || compareVersions(appVersion, plugin.max_dispatcharr_version) <= 0;
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
  const [enableNow, setEnableNow] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [uninstallConfirmOpen, setUninstallConfirmOpen] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);
  const installPlugin = usePluginStore((s) => s.installPlugin);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const onMyPlugins = pathname === '/plugins';

  const isLatestDowngrade = plugin.install_status === 'update_available' &&
    plugin.latest_version && plugin.installed_version &&
    compareVersions(plugin.latest_version, plugin.installed_version) < 0;

  const doInstall = (params) => {
    setPendingInstall(params);
    setConfirmOpen(true);
  };

  const confirmAndInstall = () => {
    setConfirmOpen(false);
    if (pendingInstall) executeInstall(pendingInstall);
  };

  const executeInstall = async (params) => {
    const wasInstalled = plugin.installed;
    const wasDowngrade = plugin.installed_version && params.version &&
      compareVersions(params.version, plugin.installed_version) < 0;
    setInstalling(true);
    const result = await installPlugin(params);
    setInstalling(false);
    setPendingInstall(null);
    if (result?.success) {
      setInstallAction(wasDowngrade ? 'downgraded' : wasInstalled ? 'updated' : 'installed');
      setInstalledKey(result.plugin?.key || params.slug);
      setEnableNow(false);
      setRestartPromptOpen(true);
      onInstalled?.();
    }
  };

  const [uninstallDoneOpen, setUninstallDoneOpen] = useState(false);

  const handleUninstall = async () => {
    const key = plugin.key || installedKey;
    if (!key) return;
    setUninstalling(true);
    try {
      const resp = await API.deletePlugin(key);
      if (resp?.success) {
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
    if (detail) return;
    if (!plugin.manifest_url) {
      // No per-plugin manifest — synthesize from top-level repo entry (latest only)
      setDetail({
        manifest: {
          description: plugin.description,
          author: plugin.author,
          license: plugin.license,
          versions: plugin.latest_version ? [{
            version: plugin.latest_version,
            url: plugin.latest_url,
            checksum_sha256: plugin.latest_sha256,
            min_dispatcharr_version: plugin.min_dispatcharr_version,
            max_dispatcharr_version: plugin.max_dispatcharr_version,
            build_timestamp: plugin.last_updated,
          }] : [],
          latest: plugin.latest_version ? { version: plugin.latest_version } : null,
        },
        signature_verified: plugin.signature_verified ?? null,
      });
      if (plugin.latest_version) setSelectedVersion(plugin.latest_version);
      return;
    }
    setDetailLoading(true);
    const result = await API.getPluginDetailManifest(plugin.repo_id, plugin.manifest_url);
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

  const selectedVersionData = detail?.manifest?.versions?.find(
    (v) => v.version === selectedVersion
  );
  const isSelDowngrade = plugin.installed_version && selectedVersion &&
    compareVersions(selectedVersion, plugin.installed_version) < 0;
  const selMeetsMin = !selectedVersionData?.min_dispatcharr_version ||
    compareVersions(appVersion, selectedVersionData.min_dispatcharr_version) >= 0;
  const selMeetsMax = !selectedVersionData?.max_dispatcharr_version ||
    compareVersions(appVersion, selectedVersionData.max_dispatcharr_version) <= 0;
  const selCompatible = selMeetsMin && selMeetsMax;

  const latestInstallParams = {
    repo_id: plugin.repo_id,
    slug: plugin.slug,
    version: plugin.latest_version,
    download_url: plugin.latest_url,
    sha256: plugin.latest_sha256,
    min_dispatcharr_version: plugin.min_dispatcharr_version,
    max_dispatcharr_version: plugin.max_dispatcharr_version,
  };

  return (
    <Card
      shadow="sm"
      radius="md"
      withBorder
      style={multiRepo && plugin.is_official_repo ? { borderColor: '#0e6459' } : undefined}
    >
      <Group justify="space-between" mb="xs" align="flex-start" wrap="nowrap">
        <Group gap="sm" align="flex-start" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
          <Avatar
            src={plugin.icon_url}
            radius="sm"
            size={48}
            alt={`${plugin.name} logo`}
          >
            {plugin.name?.[0]?.toUpperCase()}
          </Avatar>
          <Box style={{ minWidth: 0, flex: 1 }}>
            <Text fw={600} lineClamp={1}>
              {plugin.name}
            </Text>
            <Group gap={6} align="center" wrap="nowrap">
              {plugin.author && (
                <Text size="xs" c="dimmed">by {plugin.author}</Text>
              )}
              {plugin.install_status === 'installed' && (
                <Badge size="xs" variant="light" color="green" leftSection={<Check size={8} />}>
                  Installed
                </Badge>
              )}
              {plugin.install_status === 'update_available' && (
                <Badge size="xs" variant="light" color={isLatestDowngrade ? 'orange' : 'yellow'} leftSection={isLatestDowngrade ? <AlertTriangle size={8} /> : <RefreshCw size={8} />}>
                  {isLatestDowngrade ? 'Newer Installed' : 'Update Available'}
                </Badge>
              )}
              {plugin.install_status === 'unmanaged' && (
                <Tooltip label="Installed manually - installing from this repo will take over management">
                  <Badge size="xs" variant="light" color="orange" leftSection={<Check size={8} />}>
                    Installed
                  </Badge>
                </Tooltip>
              )}
              {plugin.install_status === 'different_repo' && (
                <Tooltip label={`Managed by ${plugin.installed_source_repo_name || 'another repo'}`}>
                  <Badge size="xs" variant="light" color="orange" leftSection={<Check size={8} />}>
                    Installed
                  </Badge>
                </Tooltip>
              )}
            </Group>
          </Box>
        </Group>
        <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
          {plugin.is_official_repo && (
            plugin.signature_verified != null ? (
              <Tooltip label={plugin.signature_verified ? 'Verified Signature' : 'Invalid Signature'}>
                <Badge
                  size="xs"
                  variant="filled"
                  style={{ backgroundColor: plugin.signature_verified === false ? 'var(--mantine-color-red-9)' : '#14917E' }}
                  leftSection={plugin.signature_verified ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
                >
                  Official Repo
                </Badge>
              </Tooltip>
            ) : (
              <Badge size="xs" variant="filled" style={{ backgroundColor: '#14917E' }}>
                Official Repo
              </Badge>
            )
          )}
          {!plugin.is_official_repo && plugin.repo_name && (
            plugin.signature_verified != null ? (
              <Tooltip label={plugin.signature_verified ? 'Verified Signature' : 'Invalid Signature'}>
                <Badge
                  size="xs"
                  variant="filled"
                  color={plugin.signature_verified === false ? 'red.9' : 'gray'}
                  leftSection={plugin.signature_verified ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
                >
                  {plugin.repo_name}
                </Badge>
              </Tooltip>
            ) : (
              <Badge size="xs" variant="filled" color="gray">
                {plugin.repo_name}
              </Badge>
            )
          )}
        </Group>
      </Group>

      <Text size="sm" c="dimmed" lineClamp={2} mb="xs">
        {plugin.description}
      </Text>

      <Stack gap={4} mt="xs">
        <Group gap="xs" wrap="wrap">
          {plugin.latest_version && (
            <Badge size="xs" variant="default">
              <span style={{ opacity: 0.5, marginRight: 4 }}>LATEST</span>
              v{plugin.latest_version}
            </Badge>
          )}
          {plugin.license && (
            <Badge
              size="xs"
              variant="default"
              component="a"
              href={`https://spdx.org/licenses/${encodeURIComponent(plugin.license)}.html`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ cursor: 'pointer' }}
            >
              <span style={{ opacity: 0.5, marginRight: 4 }}>LICENSE</span>
              {plugin.license}
            </Badge>
          )}
          {plugin.min_dispatcharr_version && (
            <Badge size="xs" variant="default">
              <span style={{ opacity: 0.5, marginRight: 4 }}>MIN</span>
              {plugin.min_dispatcharr_version}
            </Badge>
          )}
          {plugin.max_dispatcharr_version && (
            <Badge size="xs" variant="default">
              <span style={{ opacity: 0.5, marginRight: 4 }}>MAX</span>
              {plugin.max_dispatcharr_version}
            </Badge>
          )}
          {plugin.last_updated && (
            <Badge size="xs" variant="default">
              <span style={{ opacity: 0.5, marginRight: 4 }}>UPDATED</span>
              {new Date(plugin.last_updated).toLocaleDateString()}
            </Badge>
          )}
        </Group>
        {!meetsMinVersion && (
          <Group gap={4} align="center">
            <Tooltip label={`Requires Dispatcharr ${plugin.min_dispatcharr_version} or newer (you have v${appVersion})`}>
              <Group gap={4} align="center">
                <AlertTriangle size={14} color="var(--mantine-color-yellow-6)" />
                <Text size="xs" c="yellow">
                  Requires {plugin.min_dispatcharr_version}+
                </Text>
              </Group>
            </Tooltip>
          </Group>
        )}
        {meetsMinVersion && !meetsMaxVersion && (
          <Group gap={4} align="center">
            <Tooltip label={`Requires Dispatcharr ${plugin.max_dispatcharr_version} or older (you have v${appVersion})`}>
              <Group gap={4} align="center">
                <AlertTriangle size={14} color="var(--mantine-color-yellow-6)" />
                <Text size="xs" c="yellow">
                  Max v{plugin.max_dispatcharr_version}
                </Text>
              </Group>
            </Tooltip>
          </Group>
        )}
      </Stack>

      <Group justify="flex-end" mt="sm">
        <Button
          size="xs"
          variant="default"
          leftSection={<Info size={14} />}
          onClick={handleMoreInfo}
        >
          More Info
        </Button>
        {(plugin.install_status === 'unmanaged') && (
          <Tooltip label="Installed manually - installing from this repo will take over management">
            <Button
              size="xs"
              variant="filled"
              leftSection={installing ? <Loader size={14} /> : <Download size={14} />}
              disabled={!meetsVersion || installing}
              onClick={() => doInstall(latestInstallParams)}
            >
              {installing ? 'Installing...' : 'Install'}
            </Button>
          </Tooltip>
        )}
        {(plugin.install_status === 'different_repo') && (
          <Tooltip label={`Managed by ${plugin.installed_source_repo_name || 'another repo'} - installing will transfer management to this repo`}>
            <Button
              size="xs"
              variant="filled"
              leftSection={installing ? <Loader size={14} /> : <Download size={14} />}
              disabled={!meetsVersion || installing}
              onClick={() => doInstall(latestInstallParams)}
            >
              {installing ? 'Installing...' : 'Install'}
            </Button>
          </Tooltip>
        )}
        {(plugin.install_status === 'installed') && (
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
        {(plugin.install_status === 'update_available') && (
          <Button
            size="xs"
            variant="filled"
            color={isLatestDowngrade ? 'orange' : 'yellow'}
            leftSection={installing ? <Loader size={14} /> : isLatestDowngrade ? <AlertTriangle size={14} /> : <RefreshCw size={14} />}
            disabled={!meetsVersion || installing}
            onClick={() => doInstall(latestInstallParams)}
          >
            {installing
              ? (isLatestDowngrade ? 'Downgrading...' : 'Updating...')
              : (isLatestDowngrade ? 'Downgrade' : 'Update')}
          </Button>
        )}
        {(!plugin.install_status || plugin.install_status === 'not_installed') && (
          <Button
            size="xs"
            variant="filled"
            leftSection={installing ? <Loader size={14} /> : <Download size={14} />}
            disabled={!meetsVersion || installing}
            onClick={() => doInstall(latestInstallParams)}
          >
            {installing ? 'Installing...' : 'Install'}
          </Button>
        )}
      </Group>

      {/* Detail Modal */}
      <Modal
        opened={detailOpen}
        onClose={() => { setDetailOpen(false); onDetailClose?.(); }}
        title={
          <Group gap="xs" align="center">
            <Avatar
              src={plugin.icon_url}
              radius="sm"
              size={28}
              alt={`${plugin.name} logo`}
            >
              {plugin.name?.[0]?.toUpperCase()}
            </Avatar>
            <Text fw={600}>{plugin.name}</Text>
            {plugin.is_official_repo && (
              detail?.signature_verified != null ? (
                <Tooltip label={detail.signature_verified ? 'Verified Signature' : 'Invalid Signature'}>
                  <Badge
                    size="xs"
                    variant="filled"
                    style={{ backgroundColor: detail.signature_verified === false ? 'var(--mantine-color-red-9)' : '#14917E' }}
                    leftSection={detail.signature_verified ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
                  >
                    Official Repo
                  </Badge>
                </Tooltip>
              ) : (
                <Badge size="xs" variant="filled" style={{ backgroundColor: '#14917E' }}>
                  Official Repo
                </Badge>
              )
            )}
            {!plugin.is_official_repo && plugin.repo_name && (
              detail?.signature_verified != null ? (
                <Tooltip label={detail.signature_verified ? 'Verified Signature' : 'Invalid Signature'}>
                  <Badge
                    size="xs"
                    variant="filled"
                    color={detail.signature_verified === false ? 'red.9' : 'gray'}
                    leftSection={detail.signature_verified ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
                  >
                    {plugin.repo_name}
                  </Badge>
                </Tooltip>
              ) : (
                <Badge size="xs" variant="filled" color="gray">
                  {plugin.repo_name}
                </Badge>
              )
            )}
          </Group>
        }
        size="lg"
      >
        {detailLoading && (
          <Stack align="center" py="xl">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">Loading plugin details...</Text>
          </Stack>
        )}
        {!detailLoading && detail?.manifest && (
          <Stack gap="md">
            {detail.manifest.description && (
              <Text size="sm">{detail.manifest.description}</Text>
            )}

            <Group gap="xs" wrap="wrap">
              {detail.manifest.author && (
                <Badge size="sm" variant="default">
                  <span style={{ opacity: 0.5, marginRight: 4 }}>AUTHOR</span>
                  {detail.manifest.author}
                </Badge>
              )}
              {detail.manifest.license && (
                <Badge
                  size="sm"
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
              )}
              {detail.manifest.repo_url && (
                <Tooltip label="Source Repository">
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="sm"
                    component="a"
                    href={detail.manifest.repo_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <GitHubIcon size={16} />
                  </ActionIcon>
                </Tooltip>
              )}
              {detail.manifest.discord_thread && (() => {
                const isDiscordChannel = /^https:\/\/discord\.com\/channels\//.test(detail.manifest.discord_thread);
                return (
                <Tooltip label="Discord Discussion">
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="sm"
                    component="a"
                    href={isDiscordChannel
                      ? detail.manifest.discord_thread.replace('https://', 'discord://')
                      : detail.manifest.discord_thread}
                    {...(!isDiscordChannel && { target: '_blank', rel: 'noopener noreferrer' })}
                  >
                    <DiscordIcon size={16} />
                  </ActionIcon>
                </Tooltip>
                );
              })()}
            </Group>

            {detail.manifest.versions?.length > 0 && (
              <>
                <Group gap="xs" align="flex-end">
                  <Select
                    label="Version"
                    size="xs"
                    allowDeselect={false}
                    value={selectedVersion}
                    onChange={setSelectedVersion}
                    data={detail.manifest.versions.map((v) => ({
                      value: v.version,
                      label: `v${v.version}${v.version === detail.manifest.latest?.version ? ' (latest)' : ''}`,
                    }))}
                    style={{ maxWidth: 200 }}
                  />
                  {(plugin.install_status === 'unmanaged' || plugin.install_status === 'different_repo') ? (
                    <Tooltip label={
                      plugin.install_status === 'unmanaged'
                        ? 'Installed manually - installing will take over management'
                        : `Managed by ${plugin.installed_source_repo_name || 'another repo'} - installing will transfer management to this repo`
                    }>
                      <Button
                        size="xs"
                        variant="filled"
                        leftSection={installing ? <Loader size={14} /> : <Download size={14} />}
                        disabled={!selCompatible || installing}
                        onClick={() => {
                          if (!selectedVersionData?.url) return;
                          doInstall({
                            repo_id: plugin.repo_id,
                            slug: plugin.slug,
                            version: selectedVersion,
                            download_url: selectedVersionData.url,
                            sha256: selectedVersionData.checksum_sha256,
                            min_dispatcharr_version: selectedVersionData.min_dispatcharr_version,
                            max_dispatcharr_version: selectedVersionData.max_dispatcharr_version,
                          });
                        }}
                      >
                        {installing ? 'Installing...' : 'Install'}
                      </Button>
                    </Tooltip>
                  ) : (() => {
                    return (
                      <>
                        <Button
                          size="xs"
                          variant={
                            plugin.installed_version === selectedVersion
                              ? 'light'
                              : 'filled'
                          }
                          color={
                            plugin.installed_version === selectedVersion ? 'red'
                            : !selCompatible ? 'gray'
                            : plugin.installed && plugin.installed_version !== selectedVersion
                              ? (isSelDowngrade ? 'orange' : 'yellow')
                              : undefined
                          }
                          leftSection={
                            installing ? <Loader size={14} />
                              : uninstalling ? <Loader size={14} />
                              : plugin.installed_version === selectedVersion ? <Trash2 size={14} />
                              : !selCompatible ? <AlertTriangle size={14} />
                              : isSelDowngrade ? <AlertTriangle size={14} />
                              : plugin.installed && plugin.installed_version !== selectedVersion ? <RefreshCw size={14} />
                              : <Download size={14} />
                          }
                          disabled={
                            !selCompatible ||
                            installing ||
                            uninstalling
                          }
                          onClick={() => {
                            if (plugin.installed_version === selectedVersion) {
                              setUninstallConfirmOpen(true);
                              return;
                            }
                            if (!selectedVersionData?.url) return;
                            doInstall({
                              repo_id: plugin.repo_id,
                              slug: plugin.slug,
                              version: selectedVersion,
                              download_url: selectedVersionData.url,
                              sha256: selectedVersionData.checksum_sha256,
                              min_dispatcharr_version: selectedVersionData.min_dispatcharr_version,
                              max_dispatcharr_version: selectedVersionData.max_dispatcharr_version,
                            });
                          }}
                        >
                          {installing
                            ? (isSelDowngrade ? 'Downgrading...' : 'Installing...')
                            : !selCompatible
                              ? 'Incompatible'
                              : plugin.installed_version === selectedVersion
                                ? 'Uninstall'
                                : isSelDowngrade
                                  ? 'Downgrade'
                                  : plugin.installed && plugin.installed_version !== selectedVersion
                                    ? 'Update'
                                    : 'Install'}
                        </Button>
                        {!selCompatible && (
                          <Tooltip label={
                            !selMeetsMin
                              ? `Requires Dispatcharr ${selectedVersionData.min_dispatcharr_version}+ (you have v${appVersion})`
                              : `Requires Dispatcharr ≤${selectedVersionData.max_dispatcharr_version} (you have v${appVersion})`
                          }>
                            <Group gap={4} align="center">
                              <AlertTriangle size={14} color="var(--mantine-color-yellow-6)" />
                            </Group>
                          </Tooltip>
                        )}
                      </>
                    );
                  })()}
                </Group>
                {selectedVersionData && (
                  <Table fontSize="xs" striped highlightOnHover style={{ tableLayout: 'auto' }}>
                    <Table.Tbody>
                      {selectedVersionData.build_timestamp && (
                        <Table.Tr>
                          <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>Built</Table.Td>
                          <Table.Td>{new Date(selectedVersionData.build_timestamp).toLocaleString()}</Table.Td>
                        </Table.Tr>
                      )}
                      {selectedVersionData.min_dispatcharr_version && (
                        <Table.Tr>
                          <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>Minimum Dispatcharr Version</Table.Td>
                          <Table.Td>{selectedVersionData.min_dispatcharr_version}</Table.Td>
                        </Table.Tr>
                      )}
                      {selectedVersionData.max_dispatcharr_version && (
                        <Table.Tr>
                          <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>Maximum Dispatcharr Version</Table.Td>
                          <Table.Td>{selectedVersionData.max_dispatcharr_version}</Table.Td>
                        </Table.Tr>
                      )}
                      {selectedVersionData.commit_sha_short && (
                        <Table.Tr>
                          <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>Commit</Table.Td>
                          <Table.Td>
                            {detail.manifest.registry_url ? (
                              <Text
                                size="xs"
                                component="a"
                                href={`${detail.manifest.registry_url}/commit/${selectedVersionData.commit_sha}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                c="blue"
                              >
                                {selectedVersionData.commit_sha_short}
                              </Text>
                            ) : (
                              selectedVersionData.commit_sha_short
                            )}
                          </Table.Td>
                        </Table.Tr>
                      )}
                      {selectedVersionData.url && (
                        <Table.Tr>
                          <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>Download</Table.Td>
                          <Table.Td>
                            <Text
                              size="xs"
                              component="a"
                              href={selectedVersionData.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              c="blue"
                            >
                              {selectedVersionData.url.split('/').pop()}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      )}
                    </Table.Tbody>
                  </Table>
                )}
              </>
            )}
          </Stack>
        )}
        {!detailLoading && !detail && (
          <Text size="sm" c="dimmed">Failed to load plugin details.</Text>
        )}
      </Modal>

      {/* Unified install confirmation modal */}
      {(() => {
        const isDowngrade = pendingInstall && plugin.installed_version &&
          compareVersions(pendingInstall.version, plugin.installed_version) < 0;
        const isUpdate = pendingInstall && plugin.installed_version &&
          !isDowngrade &&
          compareVersions(pendingInstall.version, plugin.installed_version) > 0;
        const isBadSig = plugin.signature_verified === false;
        const actionLabel = isDowngrade ? 'Downgrade' : isUpdate ? 'Update' : 'Install';
        const btnColor = (isDowngrade && isBadSig) ? 'red' : isDowngrade ? 'orange' : isBadSig ? 'red' : undefined;
        return (
          <Modal
            opened={confirmOpen}
            onClose={() => { setConfirmOpen(false); setPendingInstall(null); }}
            title={
              <Group gap="xs" align="center">
                {isBadSig
                  ? <ShieldAlert size={18} color="var(--mantine-color-red-6)" />
                  : isDowngrade
                    ? <AlertTriangle size={18} color="var(--mantine-color-orange-6)" />
                    : <Download size={18} />}
                <Text fw={600}>Confirm {actionLabel}</Text>
              </Group>
            }
            size="sm"
          >
            <Stack gap="md">
              <Text size="sm">
                You are about to {actionLabel.toLowerCase()} <b>{plugin.name}</b>{' '}
                {isUpdate || isDowngrade
                  ? <>from <b>v{plugin.installed_version}</b> to <b>v{pendingInstall?.version}</b></>
                  : <><b>v{pendingInstall?.version}</b></>}
                {plugin.repo_name ? <> from <b>{plugin.repo_name}</b></> : ''}.
              </Text>
              <Text size="sm" c="dimmed">
                Plugins run server-side code with full access to your Dispatcharr instance and its
                data. Only install plugins from developers you trust. Malicious plugins could read
                or modify data, call internal APIs, or perform unwanted actions.
              </Text>
              {isDowngrade && (
                <Text size="sm" c="orange">
                  <b>Warning:</b> Downgrading may cause issues with saved settings or data.
                </Text>
              )}
              {isBadSig && (
                <Text size="sm" c="red">
                  <b>Warning:</b> This repository has an invalid or unverified signature.
                  Installing plugins from unverified sources may be risky.
                </Text>
              )}
              {plugin.install_status === 'unmanaged' && (
                <Text size="sm" c="orange">
                  <b>Note:</b> This plugin was installed manually. Installing from this repo
                  will bring it under repo management and enable future update checks.
                </Text>
              )}
              {plugin.install_status === 'different_repo' && (
                <Text size="sm" c="orange">
                  <b>Note:</b> This plugin is currently managed
                  by <b>{plugin.installed_source_repo_name || 'another repo'}</b>.
                  Installing will transfer management to this repo.
                </Text>
              )}
              <Text size="sm" fw={500}>Are you sure you want to proceed?</Text>
              <Group justify="flex-end" gap="xs">
                <Button
                  size="xs"
                  variant="default"
                  onClick={() => { setConfirmOpen(false); setPendingInstall(null); }}
                >
                  Cancel
                </Button>
                <Button
                  size="xs"
                  color={btnColor}
                  onClick={confirmAndInstall}
                >
                  {actionLabel}
                </Button>
              </Group>
            </Stack>
          </Modal>
        );
      })()}

      {/* Uninstall confirmation modal */}
      <Modal
        opened={uninstallConfirmOpen}
        onClose={() => setUninstallConfirmOpen(false)}
        title={
          <Group gap="xs" align="center">
            <Trash2 size={18} color="var(--mantine-color-red-6)" />
            <Text fw={600}>Uninstall Plugin</Text>
          </Group>
        }
        size="sm"
      >
        <Stack gap="md">
          <Text size="sm">
            Are you sure you want to uninstall <b>{plugin.name}</b>? This will
            remove the plugin files and all associated settings.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button
              size="xs"
              variant="default"
              onClick={() => setUninstallConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button
              size="xs"
              color="red"
              loading={uninstalling}
              onClick={handleUninstall}
            >
              Uninstall
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Post-uninstall notice */}
      <Modal
        opened={uninstallDoneOpen}
        onClose={() => setUninstallDoneOpen(false)}
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
            Dispatcharr must be restarted to fully remove the plugin.
          </Text>
          <Group justify="flex-end">
            <Button size="xs" variant="default" onClick={() => setUninstallDoneOpen(false)}>
              Done
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Post-install restart prompt */}
      <Modal
        opened={restartPromptOpen}
        onClose={() => setRestartPromptOpen(false)}
        title={
          <Group gap="xs" align="center">
            <RotateCcw size={18} color="var(--mantine-color-blue-6)" />
            <Text fw={600}>
              Plugin {installAction === 'installed' ? 'Installed' : installAction === 'downgraded' ? 'Downgraded' : 'Updated'}
            </Text>
          </Group>
        }
        size="sm"
      >
        <Stack gap="md">
          <Text size="sm">
            <b>{plugin.name}</b> has been {installAction || 'installed'} successfully.
          </Text>
          <Text size="sm">
            Dispatcharr must be restarted to load the plugin.
          </Text>
          {installAction === 'installed' && (
            <>
              <Text size="xs" c="dimmed">
                Plugins are disabled by default. You can enable it now or at any time from My Plugins.
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
              onClick={async () => {
                if (installAction === 'installed' && enableNow && installedKey) {
                  setEnabling(true);
                  try {
                    await API.setPluginEnabled(installedKey, true);
                  } finally {
                    setEnabling(false);
                  }
                }
                setRestartPromptOpen(false);
              }}
            >
              Done
            </Button>
            {!onMyPlugins && (
              <Button
                size="xs"
                loading={enabling}
                onClick={async () => {
                  if (installAction === 'installed' && enableNow && installedKey) {
                    setEnabling(true);
                    try {
                      await API.setPluginEnabled(installedKey, true);
                    } finally {
                      setEnabling(false);
                    }
                  }
                  setRestartPromptOpen(false);
                  navigate('/plugins');
                }}
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

/**
 * Compare two semver-like version strings.
 * Returns negative if a < b, 0 if equal, positive if a > b.
 */
function compareVersions(a, b) {
  if (!a || !b) return 0;
  const parse = (v) => v.replace(/^v/, '').split('.').map(Number);
  const pa = parse(a);
  const pb = parse(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

export default AvailablePluginCard;
