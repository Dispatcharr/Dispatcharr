import React from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
import {
  AlertTriangle,
  Ban,
  Download,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { compareVersions } from './pluginUtils.js';
import { formatKB } from '../utils/networkUtils.js';
import { DiscordIcon, GitHubIcon } from './icons.jsx';

/**
 * Shared plugin detail panel used in both PluginCard and AvailablePluginCard modals.
 *
 * Props:
 *  - detail          manifest detail object { manifest: { ... }, signature_verified }
 *  - detailLoading   boolean
 *  - selectedVersion string | null
 *  - onVersionChange (version) => void
 *  - installedVersion string | null   currently installed version
 *  - appVersion      string           current app version for compat checks
 *  - installing      boolean
 *  - uninstalling    boolean
 *  - onInstall       (params) => void  called with { version, url, sha256, min/max }
 *  - onUninstall     () => void        called when uninstall button clicked
 *  - installStatus   string | null     'unmanaged' | 'different_repo' | 'installed' | 'update_available' | 'not_installed'
 *  - installedSourceRepoName  string   for different_repo tooltip
 *  - installedVersionIsPrerelease  boolean
 *  - repoId          number
 *  - slug            string
 */
const PluginDetailPanel = ({
  detail,
  detailLoading,
  selectedVersion,
  onVersionChange,
  installedVersion,
  installedVersionIsPrerelease = false,
  appVersion,
  installing = false,
  uninstalling = false,
  onInstall,
  onUninstall,
  installStatus,
  installedSourceRepoName,
  repoId,
  slug,
}) => {
  if (detailLoading) {
    return (
      <Stack align="center" py="xl">
        <Loader size="sm" />
        <Text size="sm" c="dimmed">
          Loading plugin details…
        </Text>
      </Stack>
    );
  }

  if (!detail?.manifest) {
    return (
      <Text size="sm" c="dimmed">
        Failed to load plugin details.
      </Text>
    );
  }

  const manifest = detail.manifest;
  const selectedVersionData = manifest.versions?.find(
    (v) => v.version === selectedVersion
  );

  const isSelSame =
    installedVersion &&
    selectedVersion &&
    compareVersions(selectedVersion, installedVersion) === 0;
  const isSelDowngrade =
    installedVersion &&
    selectedVersion &&
    compareVersions(selectedVersion, installedVersion) < 0;
  const isInstalled = !!installedVersion;

  const selMeetsMin =
    !selectedVersionData?.min_dispatcharr_version ||
    compareVersions(appVersion, selectedVersionData.min_dispatcharr_version) >=
      0;
  const selMeetsMax =
    !selectedVersionData?.max_dispatcharr_version ||
    compareVersions(appVersion, selectedVersionData.max_dispatcharr_version) <=
      0;
  const selCompatible = selMeetsMin && selMeetsMax;

  const isOverwrite =
    installStatus === 'unmanaged' || installStatus === 'different_repo';

  const handleInstallClick = () => {
    if (isSelSame && onUninstall) {
      onUninstall();
      return;
    }
    if (!selectedVersionData?.url || !onInstall) return;
    const params = {
      repo_id: repoId,
      slug,
      version: selectedVersion,
      download_url: selectedVersionData.url,
      sha256: selectedVersionData.checksum_sha256,
      min_dispatcharr_version: selectedVersionData.min_dispatcharr_version,
      max_dispatcharr_version: selectedVersionData.max_dispatcharr_version,
      prerelease: selectedVersionData.prerelease === true,
    };
    onInstall(params);
  };

  const getButtonProps = () => {
    if (isOverwrite) {
      return {
        label: installing ? 'Installing…' : 'Overwrite',
        color: 'orange',
        icon: installing ? <Loader size={14} /> : <Download size={14} />,
        variant: 'filled',
        tooltip:
          installStatus === 'unmanaged'
            ? 'Installed manually – installing will take over management'
            : `Managed by ${installedSourceRepoName || 'another repo'} – installing will transfer management to this repo`,
      };
    }
    if (isSelSame) {
      return {
        label: uninstalling ? 'Uninstalling…' : 'Uninstall',
        color: 'red',
        icon: uninstalling ? <Loader size={14} /> : <Trash2 size={14} />,
        variant: 'light',
      };
    }
    if (!selCompatible) {
      return {
        label: 'Incompatible',
        color: 'gray',
        icon: <AlertTriangle size={14} />,
        variant: 'filled',
      };
    }
    if (isSelDowngrade) {
      return {
        label: installing ? 'Downgrading…' : 'Downgrade',
        color: 'orange',
        icon: installing ? <Loader size={14} /> : <AlertTriangle size={14} />,
        variant: 'filled',
      };
    }
    if (isInstalled && !installedVersionIsPrerelease) {
      return {
        label: installing ? 'Updating…' : 'Update',
        color: 'yellow',
        icon: installing ? <Loader size={14} /> : <RefreshCw size={14} />,
        variant: 'filled',
      };
    }
    return {
      label: installing ? 'Installing…' : 'Install',
      color: undefined,
      icon: installing ? <Loader size={14} /> : <Download size={14} />,
      variant: 'filled',
    };
  };

  const btnProps = getButtonProps();
  const btnDisabled = isSelSame
    ? uninstalling
    : !selCompatible || installing || !selectedVersionData?.url;

  return (
    <Stack gap="md">
      {manifest.description && <Text size="sm">{manifest.description}</Text>}

      <Group gap="xs" wrap="wrap">
        {manifest.author && (
          <Badge size="sm" variant="default">
            <span style={{ opacity: 0.5, marginRight: 4 }}>AUTHOR</span>
            {manifest.author}
          </Badge>
        )}
        {manifest.license && (
          <Badge
            size="sm"
            variant="default"
            component="a"
            href={`https://spdx.org/licenses/${encodeURIComponent(manifest.license)}.html`}
            target="_blank"
            rel="noopener noreferrer"
            style={{ cursor: 'pointer' }}
          >
            <span style={{ opacity: 0.5, marginRight: 4 }}>LICENSE</span>
            {manifest.license}
          </Badge>
        )}
        {detail.signature_verified != null &&
          (detail.signature_verified ? (
            <Badge
              size="sm"
              variant="default"
              leftSection={<ShieldCheck size={10} />}
            >
              Verified Signature
            </Badge>
          ) : (
            <Tooltip label="Invalid Signature">
              <Badge
                size="sm"
                variant="filled"
                color="red"
                leftSection={<ShieldAlert size={10} />}
              >
                Unverified
              </Badge>
            </Tooltip>
          ))}
        {manifest.repo_url && (
          <Tooltip label="Source Repository">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              component="a"
              href={manifest.repo_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <GitHubIcon size={16} />
            </ActionIcon>
          </Tooltip>
        )}
        {manifest.discord_thread &&
          (() => {
            const isDiscordChannel = /^https:\/\/discord\.com\/channels\//.test(
              manifest.discord_thread
            );
            return (
              <Tooltip label="Discord Discussion">
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="sm"
                  component="a"
                  href={
                    isDiscordChannel
                      ? manifest.discord_thread.replace(
                          'https://',
                          'discord://'
                        )
                      : manifest.discord_thread
                  }
                  {...(!isDiscordChannel && {
                    target: '_blank',
                    rel: 'noopener noreferrer',
                  })}
                >
                  <DiscordIcon size={16} />
                </ActionIcon>
              </Tooltip>
            );
          })()}
      </Group>

      {manifest.deprecated && (
        <Alert
          icon={<Ban size={16} />}
          color="red"
          variant="light"
          title="Deprecated Plugin"
        >
          This plugin has been marked as deprecated by its maintainer. It may no
          longer receive updates or fixes, and could stop working with future
          versions of Dispatcharr. Consider looking for an alternative.
        </Alert>
      )}

      {manifest.versions?.length > 0 &&
        (() => {
          const installedMissing =
            installedVersion &&
            !manifest.versions.some(
              (v) => compareVersions(v.version, installedVersion) === 0
            );
          const buildLabel = (v) =>
            `v${v.version}${v.prerelease ? ' (prerelease)' : ''}${v.version === manifest.latest?.version ? ' (latest)' : ''}${installedVersion && compareVersions(v.version, installedVersion) === 0 ? ' (installed)' : ''}`;

          let versions = [...manifest.versions];
          if (installedVersionIsPrerelease) {
            const prereleases = versions.filter((v) => v.prerelease);
            const stable = versions.filter((v) => !v.prerelease);
            versions = [...prereleases, ...stable];
          }

          const versionItems = versions.map((v) => ({
            value: v.version,
            label: buildLabel(v),
            disabled: false,
          }));
          if (installedMissing) {
            const ghostItem = {
              value: installedVersion,
              label: `v${installedVersion} (installed)`,
              disabled: true,
            };
            // Insert in sorted position (newest first, matching manifest order convention)
            const idx = versionItems.findIndex(
              (item) => compareVersions(installedVersion, item.value) > 0
            );
            if (idx === -1) {
              versionItems.push(ghostItem);
            } else {
              versionItems.splice(idx, 0, ghostItem);
            }
          }
          return (
            <>
              <Group gap="xs" align="flex-end">
                <Select
                  label="Version"
                  size="xs"
                  allowDeselect={false}
                  value={selectedVersion}
                  onChange={onVersionChange}
                  data={versionItems}
                  style={{ maxWidth: 240 }}
                />
                <Group gap="xs" align="center">
                  {btnProps.tooltip ? (
                    <Tooltip label={btnProps.tooltip}>
                      <Button
                        size="xs"
                        variant={btnProps.variant}
                        color={btnProps.color}
                        leftSection={btnProps.icon}
                        disabled={btnDisabled}
                        onClick={handleInstallClick}
                      >
                        {btnProps.label}
                      </Button>
                    </Tooltip>
                  ) : (
                    <Button
                      size="xs"
                      variant={btnProps.variant}
                      color={btnProps.color}
                      leftSection={btnProps.icon}
                      disabled={btnDisabled}
                      onClick={handleInstallClick}
                    >
                      {btnProps.label}
                    </Button>
                  )}
                  {!selCompatible &&
                    selectedVersionData &&
                    !isSelSame &&
                    (() => {
                      const parts = [];
                      if (!selMeetsMin)
                        parts.push(
                          `${selectedVersionData.min_dispatcharr_version} or newer`
                        );
                      if (!selMeetsMax)
                        parts.push(
                          `${selectedVersionData.max_dispatcharr_version} or older`
                        );
                      const label = !selMeetsMin
                        ? `Min ${selectedVersionData.min_dispatcharr_version}`
                        : `Max ${selectedVersionData.max_dispatcharr_version}`;
                      return (
                        <Tooltip
                          label={`Incompatible: requires Dispatcharr ${parts.join(' and ')} (you have v${appVersion})`}
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
                </Group>
              </Group>
              {selectedVersionData && (
                <Table
                  fontSize="xs"
                  striped
                  highlightOnHover
                  style={{ tableLayout: 'auto' }}
                >
                  <Table.Tbody>
                    {selectedVersionData.build_timestamp && (
                      <Table.Tr>
                        <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>
                          Built
                        </Table.Td>
                        <Table.Td>
                          {new Date(
                            selectedVersionData.build_timestamp
                          ).toLocaleString()}
                        </Table.Td>
                      </Table.Tr>
                    )}
                    {Number.isFinite(selectedVersionData.size) &&
                      selectedVersionData.size > 0 && (
                        <Table.Tr>
                          <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>
                            File Size
                          </Table.Td>
                          <Table.Td>
                            {formatKB(selectedVersionData.size)}
                          </Table.Td>
                        </Table.Tr>
                      )}
                    {selectedVersionData.min_dispatcharr_version && (
                      <Table.Tr>
                        <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>
                          Min Version
                        </Table.Td>
                        <Table.Td>
                          {selectedVersionData.min_dispatcharr_version}
                        </Table.Td>
                      </Table.Tr>
                    )}
                    {selectedVersionData.max_dispatcharr_version && (
                      <Table.Tr>
                        <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>
                          Max Version
                        </Table.Td>
                        <Table.Td>
                          {selectedVersionData.max_dispatcharr_version}
                        </Table.Td>
                      </Table.Tr>
                    )}
                    {selectedVersionData.commit_sha_short && (
                      <Table.Tr>
                        <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>
                          Commit
                        </Table.Td>
                        <Table.Td>
                          {manifest.registry_url ? (
                            <Text
                              size="xs"
                              component="a"
                              href={`${manifest.registry_url}/commit/${selectedVersionData.commit_sha}`}
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
                        <Table.Td fw={500} style={{ whiteSpace: 'nowrap' }}>
                          Download
                        </Table.Td>
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
          );
        })()}
    </Stack>
  );
};

export default PluginDetailPanel;
