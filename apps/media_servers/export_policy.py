from __future__ import annotations

from typing import Any, Iterable


def _properties(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _managed_source_and_provider(relation: Any) -> tuple[str, str]:
    relation_properties = _properties(
        getattr(relation, "custom_properties", None)
    )
    account = getattr(relation, "m3u_account", None)
    account_properties = _properties(
        getattr(account, "custom_properties", None)
    )
    managed_source = (
        relation_properties.get("managed_source")
        or account_properties.get("managed_source")
    )
    provider = str(
        relation_properties.get("provider")
        or account_properties.get("provider")
        or ""
    ).strip().lower()
    return str(managed_source or "").strip().lower(), provider


def is_remote_media_server_relation(relation: Any) -> bool:
    """Return whether a relation came from a remote media-server import."""
    managed_source, provider = _managed_source_and_provider(relation)
    if managed_source != "media_server":
        return False
    if not provider:
        # A managed media-server relation without provenance is not safe to
        # use in a STRM playback chain. Local imports always record provenance.
        return True
    return provider not in {"local", "dvr"}


def is_safe_export_relation(relation: Any) -> bool:
    """Only XC providers and trusted local filesystem sources may back STRM URLs."""
    account = getattr(relation, "m3u_account", None)
    if not account or not bool(getattr(account, "is_active", False)):
        return False
    managed_source, provider = _managed_source_and_provider(relation)
    if managed_source == "media_server":
        return provider in {"local", "dvr"}
    return str(getattr(account, "account_type", "")).strip().upper() == "XC"


def export_relation_groups(
    relations: Iterable[Any],
) -> tuple[list[Any], list[Any]]:
    """Split relations into active safe origins and known remote imports."""
    safe = []
    remote_imports = []
    for relation in relations or []:
        account = getattr(relation, "m3u_account", None)
        if not account:
            continue
        if is_remote_media_server_relation(relation):
            remote_imports.append(relation)
        elif is_safe_export_relation(relation):
            safe.append(relation)
    return safe, remote_imports


def safe_export_relations(relations: Iterable[Any]) -> list[Any]:
    safe, _remote_imports = export_relation_groups(relations)
    return safe
