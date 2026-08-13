# apps/mac_panel/panels.py
"""Registry of known MAC-panel providers.

All entries in this registry are the same IBOSOL-family React SPA
(https://iboxiptvplayer.com, https://www.cr7player.com, and ~15 sibling
domains known to run the identical backend). ``MacPanelDevice.panel_base_url``
lets an admin point at any sibling domain ad hoc without touching this file;
add an entry here only when a panel is common enough to deserve a friendly
label in the dropdown.
"""

PANELS = {
    "iboxx": {
        "label": "IBOXX Player",
        "base_url": "https://iboxiptvplayer.com",
    },
    "cr7": {
        "label": "CR7 Player",
        "base_url": "https://www.cr7player.com",
    },
    "iboplayer": {
        "label": "IBO Player",
        "base_url": "https://iboplayer.com",
    },
    "ibovpn": {
        "label": "IBO VPN Player",
        "base_url": "https://ibovpnplayer.com",
    },
    "messitv": {
        "label": "Messi TV Player",
        "base_url": "https://messitvplayer.com",
    },
    "hqplayer": {
        "label": "HQ Player TV",
        "base_url": "https://hqplayertv.com",
    },
}


def resolve_base_url(panel_key, override=None):
    """Return the base URL to use for a device: explicit override wins,
    otherwise the registry entry for ``panel_key``."""
    if override:
        return override.rstrip("/")
    entry = PANELS.get(panel_key)
    return entry["base_url"].rstrip("/") if entry else None


def panel_choices():
    return [(key, entry["label"]) for key, entry in PANELS.items()]
