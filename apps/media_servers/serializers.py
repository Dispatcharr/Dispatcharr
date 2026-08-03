from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from core.utils import RedisClient

from .models import (
    MediaLibraryExportRun,
    MediaLibraryExportTarget,
    MediaLibraryImportRun,
    MediaLibraryLocation,
    MediaLibrarySource,
)
from .path_security import (
    resolve_export_path,
    resolve_import_path,
    validate_no_import_export_overlap,
)


class MediaLibraryLocationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", required=False)

    class Meta:
        model = MediaLibraryLocation
        fields = ["id", "name", "path", "content_type", "include_subdirectories", "enabled"]

    def validate_path(self, value):
        try:
            resolved = resolve_import_path(
                value,
                must_exist=False,
                require_directory=True,
            )
            export_paths = MediaLibraryExportTarget.objects.values_list(
                "output_root",
                flat=True,
            )
            validate_no_import_export_overlap(resolved, (), export_paths)
            return str(resolved)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc


class MediaLibrarySourceSerializer(serializers.ModelSerializer):
    api_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    clear_api_token = serializers.BooleanField(write_only=True, required=False, default=False)
    clear_password = serializers.BooleanField(write_only=True, required=False, default=False)
    plex_credential_handle = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )
    has_api_token = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()
    locations = MediaLibraryLocationSerializer(many=True, required=False)

    class Meta:
        model = MediaLibrarySource
        fields = [
            "id", "name", "provider_type", "base_url", "api_token", "username",
            "password", "clear_api_token", "clear_password", "has_api_token",
            "has_password", "plex_credential_handle", "verify_ssl", "enabled",
            "add_to_vod", "sync_interval",
            "include_libraries", "library_content_types", "provider_config",
            "locations", "sync_task",
            "vod_account", "last_synced_at", "last_sync_status",
            "last_sync_message", "created_at", "updated_at",
        ]
        read_only_fields = [
            "sync_task", "vod_account", "last_synced_at", "last_sync_status",
            "last_sync_message", "created_at", "updated_at",
        ]

    def get_has_api_token(self, obj):
        return bool(obj.api_token)

    def get_has_password(self, obj):
        return bool(obj.password)

    def validate_include_libraries(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Expected a list of provider library IDs.")
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    def validate_library_content_types(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "Expected an object keyed by provider library ID."
            )
        valid_types = set(MediaLibraryLocation.ContentTypes.values)
        normalized = {}
        for library_id, content_type in value.items():
            normalized_id = str(library_id).strip()
            normalized_type = str(content_type or "").strip().lower()
            if not normalized_id:
                raise serializers.ValidationError("Library IDs may not be empty.")
            if normalized_type not in valid_types:
                raise serializers.ValidationError(
                    f"Invalid media type for library {normalized_id}."
                )
            normalized[normalized_id] = normalized_type
        return normalized

    def validate_base_url(self, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            raise serializers.ValidationError(
                "Credentials may not be embedded in provider URLs."
            )
        if parsed.query or parsed.fragment:
            raise serializers.ValidationError(
                "Provider base URLs may not contain query parameters or fragments."
            )
        return value.rstrip("/")

    def _normalize_locations(self, attrs):
        locations = attrs.get("locations")
        provider_config = attrs.get("provider_config")
        if locations is None and isinstance(provider_config, dict) and "locations" in provider_config:
            field = MediaLibraryLocationSerializer(many=True)
            locations = field.run_validation(provider_config.get("locations") or [])
            attrs["locations"] = locations
        return locations

    def validate(self, attrs):
        credential_handle = str(attrs.pop("plex_credential_handle", "") or "").strip()
        self._credential_handle = credential_handle
        if credential_handle:
            raw = RedisClient.get_client().get(
                f"media_library_plex_auth:{credential_handle}"
            )
            if not raw:
                raise serializers.ValidationError(
                    {"plex_credential_handle": "Credential handle is invalid or expired."}
                )
            try:
                credential = json.loads(raw)
                attrs["api_token"] = str(credential["token"])
            except (ValueError, KeyError, TypeError) as exc:
                raise serializers.ValidationError(
                    {"plex_credential_handle": "Credential handle is invalid."}
                ) from exc
        locations = self._normalize_locations(attrs)
        provider = attrs.get("provider_type", getattr(self.instance, "provider_type", None))
        provider_changed = self.instance and provider != self.instance.provider_type
        enabled = attrs.get("enabled", getattr(self.instance, "enabled", True))

        clear_token = attrs.pop("clear_api_token", False)
        clear_password = attrs.pop("clear_password", False)
        if clear_token:
            attrs["api_token"] = ""
        elif self.instance and "api_token" not in attrs and not provider_changed:
            attrs["api_token"] = self.instance.api_token
        if clear_password:
            attrs["password"] = ""
        elif self.instance and "password" not in attrs and not provider_changed:
            attrs["password"] = self.instance.password

        def resolved(field):
            if field in attrs:
                return str(attrs.get(field) or "").strip()
            if self.instance and not provider_changed:
                return str(getattr(self.instance, field, "") or "").strip()
            return ""

        if provider == MediaLibrarySource.ProviderTypes.LOCAL:
            attrs.update(
                base_url="",
                api_token="",
                username="",
                password="",
                include_libraries=[],
                library_content_types={},
            )
            current_count = self.instance.locations.count() if self.instance and locations is None else 0
            if not locations and not current_count:
                raise serializers.ValidationError({"locations": "At least one local location is required."})
        elif provider == MediaLibrarySource.ProviderTypes.PLEX:
            if not resolved("base_url"):
                raise serializers.ValidationError({"base_url": "Server URL is required."})
            if enabled and not resolved("api_token"):
                raise serializers.ValidationError({"api_token": "A Plex token is required."})
        elif provider in (
            MediaLibrarySource.ProviderTypes.EMBY,
            MediaLibrarySource.ProviderTypes.JELLYFIN,
        ):
            if not resolved("base_url"):
                raise serializers.ValidationError({"base_url": "Server URL is required."})
            if enabled and not resolved("api_token"):
                if not resolved("username") or not resolved("password"):
                    raise serializers.ValidationError(
                        {"api_token": "Provide a token or username and password."}
                    )
        return attrs

    def _save_locations(self, source, locations):
        if locations is None:
            return
        retained = []
        config_locations = []
        for entry in locations:
            public_id = entry.pop("public_id", None)
            location = None
            if public_id:
                location = source.locations.filter(public_id=public_id).first()
            if location is None:
                location = MediaLibraryLocation(source=source)
            for key, value in entry.items():
                setattr(location, key, value)
            location.save()
            retained.append(location.pk)
            config_locations.append(
                {
                    "id": str(location.public_id),
                    "name": location.name,
                    "path": location.path,
                    "content_type": location.content_type,
                    "include_subdirectories": location.include_subdirectories,
                    "enabled": location.enabled,
                }
            )
        source.locations.exclude(pk__in=retained).delete()
        source.provider_config = {"locations": config_locations}
        source.save(update_fields=["provider_config", "updated_at"])

    @transaction.atomic
    def create(self, validated_data):
        locations = validated_data.pop("locations", None)
        source = super().create(validated_data)
        self._save_locations(source, locations)
        if getattr(self, "_credential_handle", ""):
            RedisClient.get_client().delete(
                f"media_library_plex_auth:{self._credential_handle}"
            )
        return source

    @transaction.atomic
    def update(self, instance, validated_data):
        locations = validated_data.pop("locations", None)
        source = super().update(instance, validated_data)
        self._save_locations(source, locations)
        if getattr(self, "_credential_handle", ""):
            RedisClient.get_client().delete(
                f"media_library_plex_auth:{self._credential_handle}"
            )
        return source


class MediaLibraryImportRunSerializer(serializers.ModelSerializer):
    source = serializers.IntegerField(source="integration_id", read_only=True)
    integration_name = serializers.CharField(source="integration.name", read_only=True)
    provider_type = serializers.CharField(source="integration.provider_type", read_only=True)

    class Meta:
        model = MediaLibraryImportRun
        fields = [
            "id", "source", "integration", "integration_name", "provider_type",
            "status", "summary", "stages", "scope_results", "processed_items",
            "total_items", "created_items", "updated_items", "removed_items",
            "skipped_items", "ambiguous_items", "error_count", "message", "extra",
            "task_id", "cancellation_requested_at", "created_at", "updated_at",
            "started_at", "finished_at",
        ]
        read_only_fields = fields


class MediaLibraryExportTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaLibraryExportTarget
        fields = [
            "id", "public_id", "name", "target_type", "enabled", "output_root",
            "playback_base_url", "playback_cidrs", "playback_stream_limit",
            "include_nfo", "auto_export_on_vod_change", "last_exported_at",
            "last_export_status", "last_export_message", "last_export_summary",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "public_id", "last_exported_at", "last_export_status",
            "last_export_message", "last_export_summary", "created_at", "updated_at",
        ]

    def validate_playback_cidrs(self, value):
        networks = [entry.strip() for entry in value.split(",") if entry.strip()]
        if not networks:
            raise serializers.ValidationError(
                "At least one explicit playback CIDR is required."
            )
        try:
            return ", ".join(
                str(ipaddress.ip_network(entry, strict=False))
                for entry in networks
            )
        except ValueError as exc:
            raise serializers.ValidationError("One or more CIDRs are invalid.") from exc

    def validate(self, attrs):
        output_root = attrs.get("output_root", getattr(self.instance, "output_root", ""))
        try:
            resolved = resolve_export_path(output_root, must_exist=False, require_directory=True)
            local_paths = MediaLibraryLocation.objects.filter(enabled=True).values_list("path", flat=True)
            other_outputs = MediaLibraryExportTarget.objects.exclude(
                pk=getattr(self.instance, "pk", None)
            ).values_list("output_root", flat=True)
            validate_no_import_export_overlap(resolved, local_paths, other_outputs)
            attrs["output_root"] = str(resolved)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"output_root": exc.messages}) from exc
        playback_base_url = attrs.get(
            "playback_base_url",
            getattr(self.instance, "playback_base_url", ""),
        )
        parsed = urlsplit(playback_base_url)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise serializers.ValidationError(
                {
                    "playback_base_url": (
                        "Credentials, query parameters, and fragments are not "
                        "allowed in the playback base URL."
                    )
                }
            )
        attrs["playback_base_url"] = playback_base_url.rstrip("/")
        return attrs


class MediaLibraryExportRunSerializer(serializers.ModelSerializer):
    target_name = serializers.CharField(source="target.name", read_only=True)

    class Meta:
        model = MediaLibraryExportRun
        fields = [
            "id", "target", "target_name", "status", "reason", "task_id",
            "summary", "message", "cancellation_requested_at", "created_at",
            "updated_at", "started_at", "finished_at",
        ]
        read_only_fields = fields


# Compatibility names for the adapted reference views.
MediaServerIntegrationSerializer = MediaLibrarySourceSerializer
MediaServerSyncRunSerializer = MediaLibraryImportRunSerializer
