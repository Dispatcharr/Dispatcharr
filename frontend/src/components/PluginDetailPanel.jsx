import React from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Popover,
  Select,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTr,
  Text,
  Tooltip,
} from '@mantine/core';
import {
  AlertTriangle,
  Ban,
  Download,
  Info,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import {
  buildCompatibilityTooltip,
  buildVersionSelectItems,
  compareVersions,
} from '../utils/components/pluginUtils.js';
import { formatKB } from '../utils/networkUtils.js';
import { isSafeHttpUrl } from '../utils/url.js';
import { DiscordIcon, GitHubIcon } from './icons.jsx';

/**
 * Author/license/signature/repo-link/discord-link badges, exported so a
 * caller embedding PluginDetailPanel inline (e.g. PluginDetail.jsx's
 * "Plugin Management" pane) can merge these into its own pill row instead
 * of getting a second, separate one from this component (see `hideMeta`).
 */
export const PluginMetaBadges = ({ manifest, signatureVerified, size = 'sm' }) => {
  const safeRepoUrl = isSafeHttpUrl(manifest.repo_url) ? manifest.repo_url : null;
  // Only rewrite to the discord:// deep-link scheme when the source matched
  // the strict https://discord.com/channels/ pattern; any other value still
  // has to pass the plain http(s) allowlist before it's rendered at all.
  const isDiscordChannel = /^https:\/\/discord\.com\/channels\//.test(manifest.discord_thread || '');
  const safeDiscordHref = isDiscordChannel
    ? manifest.discord_thread.replace('https://', 'discord://')
    : isSafeHttpUrl(manifest.discord_thread)
      ? manifest.discord_thread
      : null;

  return (
    <>
      {manifest.author && (
        <Badge size={size} variant="default">
          <span style={{ opacity: 0.5, marginRight: 4 }}>AUTHOR</span>
          {manifest.author}
        </Badge>
      )}
      {manifest.license && (
        <Badge
          size={size}
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
      {signatureVerified != null &&
        (signatureVerified ? (
          <Badge size={size} variant="default" leftSection={<ShieldCheck size={10} />}>
            Verified Signature
          </Badge>
        ) : (
          <Tooltip label="Invalid Signature">
            <Badge
              size={size}
              variant="filled"
              color="red"
              leftSection={<ShieldAlert size={10} />}
            >
              Unverified
            </Badge>
          </Tooltip>
        ))}
      {safeRepoUrl && (
        <Tooltip label="Source Repository">
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            component="a"
            href={safeRepoUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <GitHubIcon size={16} />
          </ActionIcon>
        </Tooltip>
      )}
      {safeDiscordHref && (
        <Tooltip label="Discord Discussion">
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            component="a"
            href={safeDiscordHref}
            {...(!isDiscordChannel && {
              target: '_blank',
              rel: 'noopener noreferrer',
            })}
          >
            <DiscordIcon size={16} />
          </ActionIcon>
        </Tooltip>
      )}
    </>
  );
};

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
 *  - hideMeta        boolean  skip the description text and PluginMetaBadges
 *                     row; set when the caller renders those itself, merged
 *                     into its own pill row (see PluginDetail.jsx)
 *  - compactVersionDetails  boolean  hide the release-details table behind a
 *                     "Details" popover button instead of showing it inline
 *                     (default: inline table, used by AvailablePluginCard's
 *                     "More Info" modal where there's no space pressure)
 *  - hideVersionLabel  boolean  omit the "Version" label above the version
 *                     Select (set when the caller's own section heading
 *                     already makes that context obvious)
 */
const PluginDetailPanel = ({
  hideMeta = false,
  compactVersionDetails = false,
  hideVersionLabel = false,
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
      {!hideMeta && manifest.description && (
        <Text size="sm">{manifest.description}</Text>
      )}

      {!hideMeta && (
        <Group gap="xs" wrap="wrap">
          <PluginMetaBadges manifest={manifest} signatureVerified={detail.signature_verified} />
        </Group>
      )}

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
          const versionItems = buildVersionSelectItems(
            manifest.versions,
            manifest.latest?.version,
            installedVersion,
            installedVersionIsPrerelease
          );

          const versionTable = selectedVersionData && (
            <Table
              fontSize="xs"
              striped
              highlightOnHover
              style={{ tableLayout: 'auto' }}
            >
              <TableTbody>
                {selectedVersionData.build_timestamp && (
                  <TableTr>
                    <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                      Built
                    </TableTd>
                    <TableTd>
                      {new Date(
                        selectedVersionData.build_timestamp
                      ).toLocaleString()}
                    </TableTd>
                  </TableTr>
                )}
                {Number.isFinite(selectedVersionData.size) &&
                  selectedVersionData.size > 0 && (
                    <TableTr>
                      <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                        File Size
                      </TableTd>
                      <TableTd>{formatKB(selectedVersionData.size)}</TableTd>
                    </TableTr>
                  )}
                {selectedVersionData.min_dispatcharr_version && (
                  <TableTr>
                    <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                      Min Version
                    </TableTd>
                    <TableTd>{selectedVersionData.min_dispatcharr_version}</TableTd>
                  </TableTr>
                )}
                {selectedVersionData.max_dispatcharr_version && (
                  <TableTr>
                    <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                      Max Version
                    </TableTd>
                    <TableTd>{selectedVersionData.max_dispatcharr_version}</TableTd>
                  </TableTr>
                )}
                {selectedVersionData.commit_sha_short && (
                  <TableTr>
                    <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                      Commit
                    </TableTd>
                    <TableTd>
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
                    </TableTd>
                  </TableTr>
                )}
                {selectedVersionData.url && (
                  <TableTr>
                    <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                      Download
                    </TableTd>
                    <TableTd>
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
                    </TableTd>
                  </TableTr>
                )}
              </TableTbody>
            </Table>
          );

          return (
            <>
              <Group gap="xs" align="flex-end" grow={compactVersionDetails}>
                <Select
                  label={hideVersionLabel ? undefined : 'Version'}
                  size="xs"
                  allowDeselect={false}
                  value={selectedVersion}
                  onChange={onVersionChange}
                  data={versionItems}
                  style={{ maxWidth: 240 }}
                />
                {compactVersionDetails && selectedVersionData && (
                  <Popover width={260} position="bottom-start" withArrow shadow="md">
                    <Popover.Target>
                      <Button size="xs" variant="default" leftSection={<Info size={14} />}>
                        Details
                      </Button>
                    </Popover.Target>
                    <Popover.Dropdown>{versionTable}</Popover.Dropdown>
                  </Popover>
                )}
                <Group gap="xs" align="center" grow={compactVersionDetails}>
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
                      const tooltip = buildCompatibilityTooltip(
                        selMeetsMin,
                        selectedVersionData,
                        selMeetsMax
                      );
                      const label = !selMeetsMin
                        ? `Min ${selectedVersionData.min_dispatcharr_version}`
                        : `Max ${selectedVersionData.max_dispatcharr_version}`;
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
                </Group>
              </Group>
              {!compactVersionDetails && versionTable}
            </>
          );
        })()}
    </Stack>
  );
};

export default PluginDetailPanel;
