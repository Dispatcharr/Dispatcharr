"""Shared version-comparison logic for plugins.

Single source of truth for "is a plugin up to date" so the My Plugins list
(``PluginManager.list_plugins``) and the Find Plugins marketplace
(``AvailablePluginsAPIView``) agree on status.
"""


def compare_versions(a, b):
    """Compare two semver-like version strings.
    Returns negative if a < b, 0 if equal, positive if a > b.

    If either version is a prerelease (any dot-segment contains non-digit
    characters), numeric ordering is meaningless. Falls back to exact string
    equality: 0 if identical, 1 otherwise.
    """
    if not a or not b:
        return 0
    na = a.lstrip("v")
    nb = b.lstrip("v")
    if any(not p.isdigit() for p in na.split(".")) or any(not p.isdigit() for p in nb.split(".")):
        return 0 if na == nb else 1
    pa = [int(x) for x in na.split(".")]
    pb = [int(x) for x in nb.split(".")]
    for i in range(max(len(pa), len(pb))):
        diff = (pa[i] if i < len(pa) else 0) - (pb[i] if i < len(pb) else 0)
        if diff != 0:
            return diff
    return 0


def _is_purely_numeric(version):
    stripped = version.lstrip("v")
    return bool(stripped) and all(p.isdigit() for p in stripped.split("."))


def get_plugin_status(
    installed_version,
    latest_version,
    *,
    is_prerelease=False,
    is_managed=False,
    has_repo_match=True,
):
    """Return a single, direction-aware install status enum.

    One of: "not_installed", "unmanaged", "prerelease", "different_repo",
    "up_to_date", "update_available", "downgrade_available".

    ``has_repo_match`` should be False when the plugin is managed but by a
    *different* repo than the one currently being evaluated (Find Plugins'
    per-repo iteration needs this; My Plugins, which only ever looks at a
    plugin's own repo, should leave it True).
    """
    if installed_version is None:
        return "not_installed"
    if not is_managed:
        return "unmanaged"
    if not has_repo_match:
        return "different_repo"
    if is_prerelease:
        return "prerelease"
    if not latest_version:
        return "up_to_date"
    if installed_version == latest_version:
        return "up_to_date"
    # compare_versions can only give a meaningful direction when both sides
    # are plain numeric dot-versions; for anything else (e.g. a "-beta1"
    # suffix) it just signals "different", so any difference is treated as
    # an update rather than guessed at as a downgrade.
    if not (_is_purely_numeric(installed_version) and _is_purely_numeric(latest_version)):
        return "update_available"
    cmp = compare_versions(installed_version, latest_version)
    if cmp < 0:
        return "update_available"
    if cmp > 0:
        return "downgrade_available"
    return "up_to_date"
