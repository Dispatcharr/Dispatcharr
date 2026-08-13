from __future__ import annotations

from pathlib import Path

from django.core.exceptions import ValidationError

from core.models import CoreSettings

from .models import MediaLibrarySource


DVR_MEDIA_LIBRARY_NAME = "DVR"
DVR_MEDIA_LIBRARY_LOCATION_ID = "dvr-recordings"


def dvr_library_root() -> Path:
    """Return the canonical recording-library root configured by DVR settings."""
    return Path(CoreSettings.get_dvr_library_dir()).expanduser().resolve(strict=False)


def resolve_dvr_library_path(
    value: str,
    *,
    must_exist: bool = False,
    require_directory: bool = False,
) -> Path:
    """Resolve a DVR path while keeping it inside the configured recording root."""
    raw = str(value or "").strip()
    if not raw:
        raise ValidationError("A DVR media path is required.")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValidationError("The DVR media path must be absolute.")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise ValidationError(f"Unable to resolve DVR media path: {exc}") from exc

    root = dvr_library_root()
    if resolved != root and not resolved.is_relative_to(root):
        raise ValidationError(
            "The resolved path is outside the configured DVR recording library."
        )
    if require_directory and resolved.exists() and not resolved.is_dir():
        raise ValidationError("The DVR media path must be a directory.")
    return resolved


def ensure_dvr_media_library_source() -> MediaLibrarySource:
    """Create and normalize the permanent, system-managed DVR source."""
    source = MediaLibrarySource.objects.filter(
        provider_type=MediaLibrarySource.ProviderTypes.DVR,
    ).order_by("id").first()
    if source is None:
        source = MediaLibrarySource.objects.create(
            name=DVR_MEDIA_LIBRARY_NAME,
            provider_type=MediaLibrarySource.ProviderTypes.DVR,
            enabled=True,
            add_to_vod=True,
            vod_priority=10000,
            sync_interval=0,
        )

    updates = {}
    fixed_values = {
        "name": DVR_MEDIA_LIBRARY_NAME,
        "base_url": "",
        "api_token": "",
        "username": "",
        "password": "",
        "verify_ssl": True,
        "add_to_vod": True,
        "sync_interval": 0,
        "include_libraries": [],
        "library_content_types": {},
        "provider_config": {},
    }
    for field, expected in fixed_values.items():
        if getattr(source, field) != expected:
            updates[field] = expected
    if updates:
        for field, value in updates.items():
            setattr(source, field, value)
        source.save(update_fields=[*updates, "updated_at"])

    # The stream-selection UI displays the managed VOD account name. Keep an
    # existing account in sync immediately so upgrades do not continue showing
    # the former "Media Library" source name until the next import.
    if source.vod_account_id:
        account = source.vod_account
        expected_name = f"Media Library {source.id}: {DVR_MEDIA_LIBRARY_NAME}"
        account_updates = []
        if account.name != expected_name:
            account.name = expected_name
            account_updates.append("name")
        properties = dict(account.custom_properties or {})
        if properties.get("integration_name") != DVR_MEDIA_LIBRARY_NAME:
            properties["integration_name"] = DVR_MEDIA_LIBRARY_NAME
            account.custom_properties = properties
            account_updates.append("custom_properties")
        if account_updates:
            account.save(update_fields=account_updates)
    return source
