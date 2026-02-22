from rest_framework import serializers

from core.models import CoreSettings
from apps.media_servers.models import MediaServerIntegration, MediaServerSyncRun


class MediaServerIntegrationSerializer(serializers.ModelSerializer):
    api_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_api_token = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = MediaServerIntegration
        fields = [
            'id',
            'name',
            'provider_type',
            'base_url',
            'api_token',
            'username',
            'password',
            'verify_ssl',
            'enabled',
            'add_to_vod',
            'sync_interval',
            'include_libraries',
            'provider_config',
            'sync_task',
            'vod_account',
            'has_api_token',
            'last_synced_at',
            'last_sync_status',
            'last_sync_message',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'vod_account',
            'sync_task',
            'last_synced_at',
            'last_sync_status',
            'last_sync_message',
            'created_at',
            'updated_at',
        ]

    def get_has_api_token(self, obj: MediaServerIntegration) -> bool:
        return bool((obj.api_token or '').strip())

    def validate_include_libraries(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('include_libraries must be a list of library IDs.')
        normalized = []
        for entry in value:
            normalized_value = str(entry).strip()
            if normalized_value:
                normalized.append(normalized_value)
        return normalized

    def validate_sync_interval(self, value):
        if value is None:
            return 0
        if int(value) < 0:
            raise serializers.ValidationError('sync_interval must be 0 or greater.')
        return int(value)

    def validate_provider_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('provider_config must be an object.')

        locations = value.get('locations', [])
        if locations in (None, ''):
            locations = []
        if not isinstance(locations, list):
            raise serializers.ValidationError(
                {'locations': 'provider_config.locations must be a list.'}
            )

        normalized_locations = []
        for index, entry in enumerate(locations):
            if not isinstance(entry, dict):
                raise serializers.ValidationError(
                    {'locations': f'Entry #{index + 1} must be an object.'}
                )
            path = str(entry.get('path') or '').strip()
            content_type = str(entry.get('content_type') or '').strip().lower()
            include_subdirectories = bool(entry.get('include_subdirectories', True))
            name = str(entry.get('name') or '').strip()
            location_id = str(entry.get('id') or '').strip()

            if not path:
                raise serializers.ValidationError(
                    {'locations': f'Entry #{index + 1} is missing a path.'}
                )
            if content_type not in {'movie', 'series', 'mixed'}:
                raise serializers.ValidationError(
                    {
                        'locations': (
                            f'Entry #{index + 1} must use content_type '
                            '"movie", "series", or "mixed".'
                        )
                    }
                )

            normalized = {
                'path': path,
                'content_type': content_type,
                'include_subdirectories': include_subdirectories,
            }
            if name:
                normalized['name'] = name
            if location_id:
                normalized['id'] = location_id
            normalized_locations.append(normalized)

        normalized = dict(value)
        normalized['locations'] = normalized_locations
        return normalized

    def validate(self, attrs):
        provider = attrs.get(
            'provider_type',
            getattr(self.instance, 'provider_type', None),
        )
        if not provider:
            return attrs

        provider_changed = (
            self.instance is not None
            and 'provider_type' in attrs
            and attrs.get('provider_type') != self.instance.provider_type
        )

        def get_value(field_name: str) -> str:
            if field_name in attrs:
                return str(attrs.get(field_name) or '').strip()
            if self.instance is None or provider_changed:
                return ''
            return str(getattr(self.instance, field_name, '') or '').strip()

        api_token = get_value('api_token')
        username = get_value('username')
        password = get_value('password')
        base_url = get_value('base_url')
        provider_config = attrs.get(
            'provider_config',
            getattr(self.instance, 'provider_config', {}) or {},
        )

        if provider == MediaServerIntegration.ProviderTypes.LOCAL:
            if base_url:
                attrs['base_url'] = ''
            attrs['api_token'] = ''
            attrs['username'] = ''
            attrs['password'] = ''

            locations = provider_config.get('locations', []) if isinstance(provider_config, dict) else []
            if not locations:
                raise serializers.ValidationError(
                    {'provider_config': 'Local provider requires at least one location.'}
                )
            if not CoreSettings.get_tmdb_api_key():
                raise serializers.ValidationError(
                    {
                        'provider_config': (
                            'Local provider requires a TMDB API key. '
                            'Configure it in Settings > Stream Settings.'
                        )
                    }
                )
        elif provider == MediaServerIntegration.ProviderTypes.PLEX:
            if not base_url:
                raise serializers.ValidationError({'base_url': 'Server URL is required.'})
            if not api_token:
                raise serializers.ValidationError(
                    {'api_token': 'Plex requires a token from the Plex sign-in flow.'}
                )
        elif provider in {
            MediaServerIntegration.ProviderTypes.EMBY,
            MediaServerIntegration.ProviderTypes.JELLYFIN,
        }:
            if not base_url:
                raise serializers.ValidationError({'base_url': 'Server URL is required.'})
            if not api_token and not username:
                raise serializers.ValidationError(
                    {'api_token': 'Provide either an API token or username/password.'}
                )
            if not api_token and username and not password:
                raise serializers.ValidationError(
                    {'password': 'Password is required when using username authentication.'}
                )

        return attrs


class MediaServerSyncRunSerializer(serializers.ModelSerializer):
    integration_name = serializers.CharField(source='integration.name', read_only=True)
    provider_type = serializers.CharField(source='integration.provider_type', read_only=True)

    class Meta:
        model = MediaServerSyncRun
        fields = [
            'id',
            'integration',
            'integration_name',
            'provider_type',
            'status',
            'summary',
            'stages',
            'processed_items',
            'total_items',
            'created_items',
            'updated_items',
            'removed_items',
            'skipped_items',
            'error_count',
            'message',
            'extra',
            'task_id',
            'created_at',
            'updated_at',
            'started_at',
            'finished_at',
        ]
        read_only_fields = fields
