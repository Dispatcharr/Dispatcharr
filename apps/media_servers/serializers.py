from rest_framework import serializers

from apps.media_servers.models import MediaServerIntegration


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

        if provider == MediaServerIntegration.ProviderTypes.PLEX:
            if not api_token:
                raise serializers.ValidationError(
                    {'api_token': 'Plex requires a token from the Plex sign-in flow.'}
                )
        elif provider in {
            MediaServerIntegration.ProviderTypes.EMBY,
            MediaServerIntegration.ProviderTypes.JELLYFIN,
        }:
            if not api_token and not username:
                raise serializers.ValidationError(
                    {'api_token': 'Provide either an API token or username/password.'}
                )
            if not api_token and username and not password:
                raise serializers.ValidationError(
                    {'password': 'Password is required when using username authentication.'}
                )

        return attrs
