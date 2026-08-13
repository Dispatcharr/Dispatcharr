# apps/mac_panel/credentials.py
"""Builds the savePlaylist payload from a Dispatcharr XC user + device."""


def build_xc_payload(user, device, public_base_url):
    """Return the ``savePlaylist`` body for pushing ``user``'s XC credentials
    to ``device``.

    ``current_playlist_url_id`` is ``-1`` (create) unless the device already
    has a ``last_playlist_id`` from a prior push, in which case that id is
    reused so re-pushing updates the existing playlist instead of creating
    a duplicate.
    """
    xc_password = (user.custom_properties or {}).get("xc_password", "")

    xml_url = ""
    if device.include_epg:
        xml_url = f"{public_base_url}/xmltv.php?username={user.username}&password={xc_password}"

    return {
        "current_playlist_url_id": device.last_playlist_id or -1,
        "playlist_type": "xc",
        "playlist_url": public_base_url,
        "username": user.username,
        "password": xc_password,
        "xml_url": xml_url,
        "playlist_name": device.playlist_name,
        "protect": 1 if device.protect_pin else 0,
        "pin": device.protect_pin or "",
        "provider_email": "",
        "provider_number": "",
    }
