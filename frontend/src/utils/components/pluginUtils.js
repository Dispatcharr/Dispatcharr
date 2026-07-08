/**
 * Compare two semver-like version strings.
 * Returns negative if a < b, 0 if equal, positive if a > b.
 *
 * If either version is a prerelease (any dot-segment contains non-digit
 * characters), numeric ordering is meaningless. Fall back to exact string
 * equality: 0 if identical, non-zero otherwise.
 */
export function compareVersions(a, b) {
  if (!a || !b) return 0;
  const normalize = (v) => v.replace(/^v/, '');
  const na = normalize(a);
  const nb = normalize(b);
  const isPrerelease = (v) => v.split('.').some((p) => !/^\d+$/.test(p));
  if (isPrerelease(na) || isPrerelease(nb)) {
    return na === nb ? 0 : 1;
  }
  const pa = na.split('.').map(Number);
  const pb = nb.split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

export const buildCompatibilityTooltip = (
  selMeetsMin,
  selectedVersionData,
  selMeetsMax
) => {
  const parts = [];
  if (!selMeetsMin)
    parts.push(`${selectedVersionData.min_dispatcharr_version} or newer`);
  if (!selMeetsMax)
    parts.push(`${selectedVersionData.max_dispatcharr_version} or older`);
  return parts.join(' and ');
};

export function buildVersionSelectItems(
  versions,
  latestVersion,
  installedVersion,
  installedVersionIsPrerelease
) {
  const buildLabel = (v) =>
    `v${v.version}` +
    (v.prerelease ? ' (prerelease)' : '') +
    (v.version === latestVersion ? ' (latest)' : '') +
    (installedVersion && compareVersions(v.version, installedVersion) === 0
      ? ' (installed)'
      : '');

  let sorted = [...versions];
  if (installedVersionIsPrerelease) {
    sorted = [
      ...sorted.filter((v) => v.prerelease),
      ...sorted.filter((v) => !v.prerelease),
    ];
  }

  const items = sorted.map((v) => ({
    value: v.version,
    label: buildLabel(v),
    disabled: false,
  }));

  const installedMissing =
    installedVersion &&
    !versions.some((v) => compareVersions(v.version, installedVersion) === 0);

  if (installedMissing) {
    const ghost = {
      value: installedVersion,
      label: `v${installedVersion} (installed)`,
      disabled: true,
    };
    const idx = items.findIndex(
      (item) => compareVersions(installedVersion, item.value) > 0
    );
    idx === -1 ? items.push(ghost) : items.splice(idx, 0, ghost);
  }

  return items;
}

export const getInstallInfo = (pendingInstall, plugin) => {
  const isDowngrade =
    pendingInstall &&
    plugin.installed_version &&
    compareVersions(pendingInstall.version, plugin.installed_version) < 0;
  const isUpdate =
    pendingInstall &&
    plugin.installed_version &&
    !isDowngrade &&
    compareVersions(pendingInstall.version, plugin.installed_version) > 0;
  const isBadSig = plugin.signature_verified === false;
  return { isDowngrade, isUpdate, isBadSig };
};
