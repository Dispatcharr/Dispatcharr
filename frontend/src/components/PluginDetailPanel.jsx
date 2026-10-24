import React from 'react';
import { useElementSize } from '@mantine/hooks';
import {
  Alert,
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
  Trash2,
} from 'lucide-react';
import {
  buildCompatibilityTooltip,
  buildVersionSelectItems,
  compareVersions,
} from '../utils/components/pluginUtils.js';
import { formatKB } from '../utils/networkUtils.js';
import { isSafeHttpUrl } from '../utils/url.js';
import { PluginMetadata } from './PluginHeader.jsx';

const changelogLink = (changelog) => {
  if (typeof changelog === 'number' && Number.isInteger(changelog) && changelog > 0) {
    return {
      href: `https://github.com/Dispatcharr/Plugins/pull/${changelog}`,
      label: `PR #${changelog}`,
    };
  }

  if (typeof changelog !== 'string') return null;
  const value = changelog.trim();
  if (/^[1-9]\d*$/.test(value)) {
    return {
      href: `https://github.com/Dispatcharr/Plugins/pull/${value}`,
      label: `PR #${value}`,
    };
  }
  if (isSafeHttpUrl(value)) return { href: value, label: value };
  return null;
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
 *  - hideMeta        boolean  skip the description text and metadata row;
 *                     set when the caller renders metadata in its header
 *  - hideMetadata    boolean  skip only the author/license metadata while
 *                     retaining the description
 *  - metadataActions optional elements placed beside the version action
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
  hideMetadata = false,
  metadataActions,
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
  const { ref: versionControlsRef, width: versionControlsWidth } = useElementSize();
  const compactControls = versionControlsWidth > 0 && versionControlsWidth < 360;

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
  const selectedChangelog = changelogLink(selectedVersionData?.changelog);
  const registryUrl = isSafeHttpUrl(manifest.registry_url) ? manifest.registry_url : null;
  const downloadUrl = isSafeHttpUrl(selectedVersionData?.url) ? selectedVersionData.url : null;

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
    if (!downloadUrl || !onInstall) return;
    const params = {
      repo_id: repoId,
      slug,
      version: selectedVersion,
      download_url: downloadUrl,
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
            ? 'Installed manually. Installing will take over management'
            : `Managed by ${installedSourceRepoName || 'another repo'}. Installing will transfer management to this repo`,
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

      {!hideMeta && !hideMetadata && (
        <Group gap="xs" wrap="wrap">
          <PluginMetadata
            plugin={{ author: manifest.author }}
            license={manifest.license}
          />
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
                {Number.isFinite(selectedVersionData.download_count) &&
                  selectedVersionData.download_count >= 0 && (
                    <TableTr>
                      <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                        Downloads
                      </TableTd>
                      <TableTd>
                        {selectedVersionData.download_count.toLocaleString()}
                      </TableTd>
                    </TableTr>
                  )}
                {selectedChangelog && (
                  <TableTr>
                    <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                      Changelog
                    </TableTd>
                    <TableTd>
                      <Text
                        size="xs"
                        component="a"
                        href={selectedChangelog.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        c="blue"
                      >
                        {selectedChangelog.label}
                      </Text>
                    </TableTd>
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
                      {registryUrl ? (
                        <Text
                          size="xs"
                          component="a"
                          href={`${registryUrl}/commit/${selectedVersionData.commit_sha}`}
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
                {downloadUrl && (
                  <TableTr>
                    <TableTd fw={500} style={{ whiteSpace: 'nowrap' }}>
                      Download
                    </TableTd>
                    <TableTd>
                      <Text
                        size="xs"
                        component="a"
                        href={downloadUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        c="blue"
                      >
                        {downloadUrl.split('/').pop()}
                      </Text>
                    </TableTd>
                  </TableTr>
                )}
              </TableTbody>
            </Table>
          );

          return (
            <>
              <Group
                ref={versionControlsRef}
                gap="xs"
                align="flex-end"
                wrap="nowrap"
                grow={compactVersionDetails}
                style={metadataActions ? { width: '100%' } : undefined}
              >
                <Group
                  gap="xs"
                  align="flex-end"
                  style={{ flex: '1 1 0', minWidth: 0 }}
                >
                  <Select
                    label={hideVersionLabel ? undefined : 'Version'}
                    size="xs"
                    allowDeselect={false}
                    value={selectedVersion}
                    onChange={onVersionChange}
                    data={versionItems}
                    style={{ flex: '1 1 0', minWidth: 0, maxWidth: compactVersionDetails ? undefined : 240 }}
                  />
                  {compactVersionDetails && selectedVersionData && (
                    <Popover width={260} position="bottom-start" withArrow shadow="md">
                      <Popover.Target>
                        <Button size="xs" variant="default" leftSection={!compactControls && <Info size={14} />} aria-label="Details">
                          {compactControls ? <Info size={14} /> : 'Details'}
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
                        leftSection={!compactControls && btnProps.icon}
                        disabled={btnDisabled}
                        onClick={handleInstallClick}
                      >
                        {compactControls ? btnProps.icon : btnProps.label}
                      </Button>
                    </Tooltip>
                  ) : (
                    <Button
                      size="xs"
                      variant={btnProps.variant}
                      color={btnProps.color}
                      leftSection={!compactControls && btnProps.icon}
                      disabled={btnDisabled}
                      onClick={handleInstallClick}
                    >
                      {compactControls ? btnProps.icon : btnProps.label}
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
                {metadataActions && (
                  <Group
                    gap="xs"
                    align="center"
                    justify="center"
                    wrap="nowrap"
                    style={{ flex: 1, alignSelf: 'flex-end' }}
                  >
                    {metadataActions}
                  </Group>
                )}
              </Group>
              {!compactVersionDetails && versionTable}
            </>
          );
        })()}
    </Stack>
  );
};

export default PluginDetailPanel;
