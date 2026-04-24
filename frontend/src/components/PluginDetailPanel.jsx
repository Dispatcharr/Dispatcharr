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

export const GitHubIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
  </svg>
);

export const DiscordIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.947 2.418-2.157 2.418z" />
  </svg>
);

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
