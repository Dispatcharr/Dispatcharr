import logging
import os
import re
import shutil
from urllib.parse import urlencode
import uuid

import requests
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import Authenticated, IsAdmin, permission_classes_by_action
from apps.media_servers.models import MediaServerIntegration, MediaServerSyncRun
from apps.media_servers.providers import get_provider_client
from apps.media_servers.serializers import (
    MediaServerIntegrationSerializer,
    MediaServerSyncRunSerializer,
)
from apps.media_servers.tasks import (
    cleanup_integration_vod,
    ensure_integration_vod_account,
    sync_media_server_integration,
)
from core.utils import send_websocket_update

logger = logging.getLogger(__name__)

PLEX_PRODUCT = 'Dispatcharr'
PLEX_DEVICE = 'Dispatcharr Web'
PLEX_PLATFORM = 'Web'
PLEX_VERSION = '1.0.0'


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return False


def _default_sync_stages() -> dict:
    return {
        'discovery': {'status': 'pending', 'processed': 0, 'total': 0},
        'import': {'status': 'pending', 'processed': 0, 'total': 0},
        'cleanup': {'status': 'pending', 'processed': 0, 'total': 0},
    }


def _broadcast_sync_run_update(run: MediaServerSyncRun) -> None:
    send_websocket_update(
        'updates',
        'update',
        {
            'type': 'media_server_sync_updated',
            'sync_run': MediaServerSyncRunSerializer(run).data,
        },
    )


def _plex_headers(client_identifier: str, auth_token: str | None = None) -> dict:
    headers = {
        'Accept': 'application/json',
        'X-Plex-Product': PLEX_PRODUCT,
        'X-Plex-Client-Identifier': client_identifier,
        'X-Plex-Device-Name': PLEX_DEVICE,
        'X-Plex-Platform': PLEX_PLATFORM,
        'X-Plex-Version': PLEX_VERSION,
    }
    if auth_token:
        headers['X-Plex-Token'] = auth_token
    return headers


def _plex_auth_url(client_identifier: str, code: str, forward_url: str = '') -> str:
    params = {
        'clientID': client_identifier,
        'code': code,
        'context[device][product]': PLEX_PRODUCT,
        'context[device][device]': PLEX_DEVICE,
        'context[device][platform]': PLEX_PLATFORM,
    }
    if forward_url:
        params['forwardUrl'] = forward_url
    return f"https://app.plex.tv/auth#?{urlencode(params)}"


@method_decorator(csrf_exempt, name='dispatch')
class MediaServerIntegrationViewSet(viewsets.ModelViewSet):
    queryset = MediaServerIntegration.objects.select_related('vod_account')
    serializer_class = MediaServerIntegrationSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            action = getattr(self, self.action, None)
            if action and hasattr(action, 'permission_classes'):
                return [perm() for perm in action.permission_classes]
            return [Authenticated()]

    def perform_create(self, serializer):
        integration = serializer.save()
        ensure_integration_vod_account(integration)

    def perform_update(self, serializer):
        integration = serializer.save()
        ensure_integration_vod_account(integration)

    def perform_destroy(self, instance):
        cleanup_integration_vod(instance)
        super().perform_destroy(instance)

    def _run_connection_test(self, integration: MediaServerIntegration) -> dict:
        with get_provider_client(integration) as client:
            client.ping()
            libraries = client.list_libraries()
        payload = [
            {
                'id': library.id,
                'name': library.name,
                'content_type': library.content_type,
            }
            for library in libraries
        ]
        return {
            'ok': True,
            'library_count': len(payload),
            'libraries': payload,
        }

    def _build_test_integration_from_payload(self, request) -> MediaServerIntegration:
        integration_id = request.data.get('integration_id')
        existing = None
        if integration_id not in (None, '', 0, '0'):
            try:
                integration_id = int(integration_id)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {'integration_id': 'Integration ID must be numeric.'}
                )
            existing = self.get_queryset().filter(id=integration_id).first()
            if not existing:
                raise serializers.ValidationError(
                    {'integration_id': 'Integration not found.'}
                )

        payload = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        payload.pop('integration_id', None)

        serializer = self.get_serializer(
            instance=existing,
            data=payload,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        integration = MediaServerIntegration()
        source = existing or MediaServerIntegration()
        for field_name in (
            'name',
            'provider_type',
            'base_url',
            'api_token',
            'username',
            'password',
            'verify_ssl',
            'enabled',
            'add_to_vod',
            'include_libraries',
            'provider_config',
        ):
            setattr(integration, field_name, getattr(source, field_name, None))

        for field_name, value in serializer.validated_data.items():
            setattr(integration, field_name, value)

        if not str(integration.provider_type or '').strip():
            raise serializers.ValidationError(
                {'provider_type': 'Provider type is required.'}
            )
        provider_type = str(integration.provider_type or '').strip().lower()
        if (
            provider_type != MediaServerIntegration.ProviderTypes.LOCAL
            and not str(integration.base_url or '').strip()
        ):
            raise serializers.ValidationError({'base_url': 'Server URL is required.'})

        return integration

    @action(detail=True, methods=['post'], url_path='sync', permission_classes=[IsAdmin])
    def sync(self, request, pk=None):
        integration = self.get_object()
        sync_run = MediaServerSyncRun.objects.create(
            integration=integration,
            status=MediaServerSyncRun.Status.QUEUED,
            summary='Manual sync',
            message='Sync queued.',
            stages=_default_sync_stages(),
        )
        task = sync_media_server_integration.delay(integration.id, sync_run.id)
        sync_run.task_id = task.id
        sync_run.save(update_fields=['task_id', 'updated_at'])
        _broadcast_sync_run_update(sync_run)
        return Response(
            {
                'message': f'Sync started for {integration.name}',
                'task_id': task.id,
                'sync_run': MediaServerSyncRunSerializer(sync_run).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=False,
        methods=['post'],
        url_path='test-connection',
        permission_classes=[IsAdmin],
    )
    def test_connection(self, request):
        try:
            integration = self._build_test_integration_from_payload(request)
            return Response(self._run_connection_test(integration))
        except serializers.ValidationError:
            raise
        except (ValueError, OSError) as exc:
            return Response(
                {'ok': False, 'error': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except requests.RequestException as exc:
            logger.warning('Media server payload connection test failed: %s', exc)
            return Response(
                {'ok': False, 'error': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            logger.exception('Unexpected media server payload connection test failure')
            return Response(
                {'ok': False, 'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=True,
        methods=['post'],
        url_path='test-connection',
        permission_classes=[IsAdmin],
    )
    def test_connection_saved(self, request, pk=None):
        integration = self.get_object()
        try:
            return Response(self._run_connection_test(integration))
        except (ValueError, OSError) as exc:
            return Response(
                {'ok': False, 'error': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except requests.RequestException as exc:
            logger.warning(
                'Media server connection test failed for %s: %s',
                integration.id,
                exc,
            )
            return Response(
                {'ok': False, 'error': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            logger.exception(
                'Unexpected media server connection test failure for %s',
                integration.id,
            )
            return Response(
                {'ok': False, 'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=True,
        methods=['get'],
        url_path='libraries',
        permission_classes=[IsAdmin],
    )
    def libraries(self, request, pk=None):
        integration = self.get_object()
        try:
            with get_provider_client(integration) as client:
                libraries = client.list_libraries()
            return Response(
                [
                    {
                        'id': library.id,
                        'name': library.name,
                        'content_type': library.content_type,
                    }
                    for library in libraries
                ]
            )
        except (ValueError, OSError) as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except requests.RequestException as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @action(
        detail=False,
        methods=['post'],
        url_path='plex-auth/start',
        permission_classes=[IsAdmin],
    )
    def plex_auth_start(self, request):
        client_identifier = (
            str(request.data.get('client_identifier') or '').strip()
            or f"dispatcharr-{uuid.uuid4()}"
        )
        forward_url = str(request.data.get('forward_url') or '').strip()
        try:
            response = requests.post(
                'https://plex.tv/api/v2/pins',
                params={'strong': 'true'},
                headers=_plex_headers(client_identifier),
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            pin_id = payload.get('id')
            code = payload.get('code')
            if not pin_id or not code:
                return Response(
                    {'error': 'Unexpected response from Plex pin endpoint.'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            return Response(
                {
                    'pin_id': pin_id,
                    'code': code,
                    'client_identifier': client_identifier,
                    'auth_url': _plex_auth_url(client_identifier, code, forward_url),
                    'expires_in': payload.get('expiresIn'),
                }
            )
        except requests.RequestException as exc:
            logger.warning('Plex auth start failed: %s', exc)
            return Response(
                {'error': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @action(
        detail=False,
        methods=['get'],
        url_path='plex-auth/check',
        permission_classes=[IsAdmin],
    )
    def plex_auth_check(self, request):
        pin_id = str(request.query_params.get('pin_id') or '').strip()
        client_identifier = str(
            request.query_params.get('client_identifier') or ''
        ).strip()
        if not pin_id or not client_identifier:
            return Response(
                {'error': 'pin_id and client_identifier are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            response = requests.get(
                f'https://plex.tv/api/v2/pins/{pin_id}',
                headers=_plex_headers(client_identifier),
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            auth_token = (
                str(payload.get('authToken') or payload.get('auth_token') or '').strip()
            )
            return Response(
                {
                    'claimed': bool(auth_token),
                    'auth_token': auth_token,
                    'expires_in': payload.get('expiresIn'),
                }
            )
        except requests.RequestException as exc:
            logger.warning('Plex auth check failed: %s', exc)
            return Response(
                {'error': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @action(
        detail=False,
        methods=['get'],
        url_path='plex-auth/servers',
        permission_classes=[IsAdmin],
    )
    def plex_auth_servers(self, request):
        auth_token = str(request.query_params.get('auth_token') or '').strip()
        client_identifier = str(
            request.query_params.get('client_identifier') or ''
        ).strip()
        if not auth_token or not client_identifier:
            return Response(
                {'error': 'auth_token and client_identifier are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            response = requests.get(
                'https://plex.tv/api/v2/resources',
                params={'includeHttps': '1', 'includeRelay': '0'},
                headers=_plex_headers(client_identifier, auth_token),
                timeout=25,
            )
            response.raise_for_status()
            payload = response.json()
            entries = []
            if isinstance(payload, list):
                entries = payload
            elif isinstance(payload, dict):
                container = payload.get('MediaContainer') or {}
                entries = container.get('Metadata') or container.get('Device') or []

            servers = []
            for entry in entries:
                provides = str(entry.get('provides') or '').lower()
                if 'server' not in provides:
                    continue

                raw_connections = entry.get('connections') or entry.get('Connection') or []
                connections = []
                for connection in raw_connections:
                    uri = str(connection.get('uri') or '').strip()
                    if not uri:
                        continue
                    connections.append(
                        {
                            'uri': uri,
                            'local': _as_bool(connection.get('local')),
                            'relay': _as_bool(connection.get('relay')),
                            'protocol': str(connection.get('protocol') or '').strip(),
                        }
                    )

                if not connections:
                    continue

                preferred = next(
                    (
                        c['uri']
                        for c in connections
                        if c.get('local') and c.get('protocol') == 'https'
                    ),
                    None,
                )
                if not preferred:
                    preferred = next(
                        (
                            c['uri']
                            for c in connections
                            if c.get('local')
                        ),
                        None,
                    )
                if not preferred:
                    preferred = next(
                        (
                            c['uri']
                            for c in connections
                            if c.get('protocol') == 'https'
                        ),
                        None,
                    )
                if not preferred:
                    preferred = connections[0]['uri']

                servers.append(
                    {
                        'id': str(
                            entry.get('clientIdentifier')
                            or entry.get('machineIdentifier')
                            or entry.get('name')
                        ),
                        'name': str(entry.get('name') or entry.get('product') or 'Plex Server'),
                        'base_url': preferred,
                        'access_token': str(entry.get('accessToken') or auth_token),
                        'connections': connections,
                    }
                )

            return Response({'count': len(servers), 'servers': servers})
        except requests.RequestException as exc:
            logger.warning('Plex server lookup failed: %s', exc)
            return Response(
                {'error': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @action(
        detail=False,
        methods=['get'],
        url_path='browse-local-path',
        permission_classes=[IsAdmin],
    )
    def browse_local_path(self, request):
        raw_path = str(request.query_params.get('path') or '').strip()
        if not raw_path:
            path = os.path.abspath(os.sep)
        else:
            path = os.path.abspath(os.path.expanduser(raw_path))

        if not os.path.exists(path) or not os.path.isdir(path):
            return Response(
                {'detail': 'Path not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        parent = os.path.dirname(path.rstrip(os.sep))
        if parent == path:
            parent = None

        entries = []
        try:
            with os.scandir(path) as iterator:
                for entry in iterator:
                    if entry.is_dir():
                        entries.append({'name': entry.name, 'path': entry.path})
        except PermissionError:
            return Response(
                {'detail': 'Permission denied.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        entries.sort(key=lambda item: item['name'].lower())
        return Response({'path': path, 'parent': parent, 'entries': entries})


@method_decorator(csrf_exempt, name='dispatch')
class MediaServerSyncRunViewSet(viewsets.ModelViewSet):
    queryset = MediaServerSyncRun.objects.select_related('integration')
    serializer_class = MediaServerSyncRunSerializer
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_permissions(self):
        return [IsAdmin()]

    def get_queryset(self):
        queryset = super().get_queryset()
        integration_id = self.request.query_params.get('integration')
        if integration_id:
            try:
                integration_value = int(integration_id)
            except (TypeError, ValueError):
                return queryset.none()
            queryset = queryset.filter(integration_id=integration_value)
        return queryset

    def destroy(self, request, *args, **kwargs):
        sync_run = self.get_object()
        if sync_run.status not in {
            MediaServerSyncRun.Status.PENDING,
            MediaServerSyncRun.Status.QUEUED,
        }:
            return Response(
                {'detail': 'Only pending or queued sync runs can be deleted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], url_path='cancel', permission_classes=[IsAdmin])
    def cancel(self, request, pk=None):
        sync_run = self.get_object()
        if sync_run.status not in {
            MediaServerSyncRun.Status.PENDING,
            MediaServerSyncRun.Status.QUEUED,
            MediaServerSyncRun.Status.RUNNING,
        }:
            return Response(
                {'detail': 'Sync run is not cancelable.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sync_run.status = MediaServerSyncRun.Status.CANCELLED
        sync_run.message = 'Sync cancelled by user.'
        if not sync_run.finished_at:
            sync_run.finished_at = timezone.now()
        sync_run.save(update_fields=['status', 'message', 'finished_at', 'updated_at'])
        _broadcast_sync_run_update(sync_run)
        return Response(self.get_serializer(sync_run).data)

    @action(detail=False, methods=['delete'], url_path='purge', permission_classes=[IsAdmin])
    def purge(self, request):
        queryset = self.get_queryset().filter(
            status__in=[
                MediaServerSyncRun.Status.COMPLETED,
                MediaServerSyncRun.Status.FAILED,
                MediaServerSyncRun.Status.CANCELLED,
            ]
        )
        deleted, _ = queryset.delete()
        return Response({'deleted': deleted})


# ---- Output Integration Views ----

from rest_framework.views import APIView

from core.models import CoreSettings, LEGACY_OUTPUT_SETTINGS_KEY, OUTPUT_SETTINGS_KEY
from .output_paths import (
    DEFAULT_STRM_OUTPUT_PATH,
    normalize_local_path,
    normalize_strm_output_path,
    paths_overlap,
    sanitize_output_settings_paths,
)
from .strm_export import build_strm_nfo_snapshot

LEGACY_OUTPUT_PROFILE_ID = '__legacy-output__'


def _as_bool_output(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off', ''}:
            return False
    return default


def _normalize_settings_value(raw_value):
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _get_output_settings_value() -> tuple[CoreSettings | None, dict]:
    obj = CoreSettings.objects.filter(key=OUTPUT_SETTINGS_KEY).first()
    if obj is None:
        obj = CoreSettings.objects.filter(key=LEGACY_OUTPUT_SETTINGS_KEY).first()
    if obj is None:
        return None, {}

    settings_value = _normalize_settings_value(obj.value)
    sanitized_value, changed = sanitize_output_settings_paths(settings_value)
    if changed:
        obj.value = sanitized_value
        obj.save(update_fields=['value'])
    if obj.key == LEGACY_OUTPUT_SETTINGS_KEY:
        obj = _save_output_settings_value(sanitized_value, obj=obj)
    return obj, sanitized_value


def _save_output_settings_value(raw_value: dict, obj: CoreSettings | None = None) -> CoreSettings:
    safe_value = raw_value if isinstance(raw_value, dict) else {}
    output_settings, _ = CoreSettings.objects.update_or_create(
        key=OUTPUT_SETTINGS_KEY,
        defaults={'name': 'Output Settings', 'value': safe_value},
    )
    CoreSettings.objects.filter(key=LEGACY_OUTPUT_SETTINGS_KEY).exclude(
        pk=output_settings.pk
    ).delete()
    return output_settings


def _resolve_backend_base_url(request, settings_value: dict) -> str:
    configured = str((settings_value or {}).get('backend_base_url') or '').strip()
    if configured.startswith(('http://', 'https://')):
        return configured.rstrip('/')
    return request.build_absolute_uri('/').rstrip('/')


def _resolve_strm_output_path(request, settings_value: dict, payload_path: str = '') -> str:
    raw_path = str(payload_path or '').strip()
    if not raw_path:
        raw_path = str((settings_value or {}).get('strm_output_path') or '').strip()
    return normalize_strm_output_path(raw_path, fallback=DEFAULT_STRM_OUTPUT_PATH)


def _normalize_output_target_provider(raw_value) -> str:
    provider = str(raw_value or '').strip().lower()
    if provider in {'emby', 'jellyfin', 'jellyfin_emby'}:
        return 'jellyfin_emby'
    return 'jellyfin_emby'


def _normalize_output_profile(raw_profile: dict) -> dict:
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    profile_id = str(profile.get('id') or profile.get('integration_id') or '').strip()
    if not profile_id:
        profile_id = f'output-{uuid.uuid4()}'

    return {
        'id': profile_id,
        'integration_name': str(profile.get('integration_name') or '').strip()
        or 'Dispatcharr Output',
        'target_provider': _normalize_output_target_provider(profile.get('target_provider')),
        'export_mode': 'strm_nfo',
        'export_enabled': _as_bool_output(profile.get('export_enabled'), default=True),
        'target_base_url': '',
        'target_api_token': '',
        'target_verify_ssl': True,
        'strm_output_path': normalize_strm_output_path(
            profile.get('strm_output_path'),
            fallback=DEFAULT_STRM_OUTPUT_PATH,
        ),
        'strm_include_nfo': _as_bool_output(profile.get('strm_include_nfo'), default=True),
        'strm_last_built_at': str(profile.get('strm_last_built_at') or '').strip(),
        'strm_last_build_summary': profile.get('strm_last_build_summary')
        if isinstance(profile.get('strm_last_build_summary'), dict)
        else None,
        'updated_at': str(profile.get('updated_at') or '').strip(),
    }


def _legacy_output_configured(settings_value: dict) -> bool:
    raw = settings_value if isinstance(settings_value, dict) else {}
    return bool(
        _as_bool_output(raw.get('export_enabled'), default=False)
        or str(raw.get('updated_at') or '').strip()
        or str(raw.get('strm_last_built_at') or '').strip()
        or str(raw.get('strm_output_path') or '').strip()
        or str(raw.get('integration_name') or '').strip()
    )


def _build_legacy_output_profile(settings_value: dict) -> dict:
    raw = settings_value if isinstance(settings_value, dict) else {}
    return _normalize_output_profile(
        {
            'id': LEGACY_OUTPUT_PROFILE_ID,
            'integration_name': str(raw.get('integration_name') or '').strip()
            or 'Dispatcharr Output',
            'target_provider': raw.get('target_provider'),
            'export_mode': raw.get('export_mode'),
            'export_enabled': _as_bool_output(raw.get('export_enabled'), default=True),
            'strm_output_path': normalize_strm_output_path(
                raw.get('strm_output_path'),
                fallback=DEFAULT_STRM_OUTPUT_PATH,
            ),
            'strm_include_nfo': _as_bool_output(raw.get('strm_include_nfo'), default=True),
            'strm_last_built_at': str(raw.get('strm_last_built_at') or '').strip(),
            'strm_last_build_summary': raw.get('strm_last_build_summary'),
            'updated_at': str(raw.get('updated_at') or '').strip(),
        }
    )


def _extract_output_profiles(settings_value: dict) -> list[dict]:
    raw = settings_value if isinstance(settings_value, dict) else {}
    raw_profiles = raw.get('output_integrations')
    if isinstance(raw_profiles, list):
        profiles = []
        used_ids = set()
        for raw_profile in raw_profiles:
            if not isinstance(raw_profile, dict):
                continue
            normalized = _normalize_output_profile(raw_profile)
            profile_id = str(normalized.get('id') or '').strip()
            if not profile_id or profile_id in used_ids:
                continue
            used_ids.add(profile_id)
            profiles.append(normalized)
        if profiles:
            return profiles

    if _legacy_output_configured(raw):
        return [_build_legacy_output_profile(raw)]
    return []


def _legacy_fields_from_output_profile(profile: dict | None) -> dict:
    if not profile:
        return _clear_output_integration_settings({})

    return {
        'integration_name': str(profile.get('integration_name') or '').strip()
        or 'Dispatcharr Output',
        'target_provider': _normalize_output_target_provider(profile.get('target_provider')),
        'export_mode': 'strm_nfo',
        'export_enabled': _as_bool_output(profile.get('export_enabled'), default=True),
        'target_base_url': '',
        'target_api_token': '',
        'target_verify_ssl': True,
        'strm_output_path': normalize_strm_output_path(
            profile.get('strm_output_path'),
            fallback=DEFAULT_STRM_OUTPUT_PATH,
        ),
        'strm_include_nfo': _as_bool_output(profile.get('strm_include_nfo'), default=True),
        'strm_last_built_at': str(profile.get('strm_last_built_at') or '').strip(),
        'strm_last_build_summary': (
            profile.get('strm_last_build_summary')
            if isinstance(profile.get('strm_last_build_summary'), dict)
            else None
        ),
        'updated_at': str(profile.get('updated_at') or '').strip(),
    }


def _persist_output_profiles(settings_value: dict, profiles: list[dict]) -> dict:
    base = dict(settings_value or {})
    if profiles:
        normalized_profiles = [
            _normalize_output_profile(profile)
            for profile in profiles
            if isinstance(profile, dict)
        ]
        if not normalized_profiles:
            cleared = _clear_output_integration_settings(base)
            cleared['output_integrations'] = []
            return cleared

        primary = normalized_profiles[0]
        legacy_fields = _legacy_fields_from_output_profile(primary)
        base.update(legacy_fields)
        base['output_integrations'] = normalized_profiles
        base.pop('scan_target_server_url', None)
        base.pop('scan_target_server_token', None)
        base.pop('scan_target_server_verify_ssl', None)
        base.pop('scan_control_enabled', None)
        base.pop('scan_control_integration_id', None)
        base.pop('scan_control_schedule_time', None)
        base.pop('scan_control_library_ids', None)
        base.pop('scan_control_timeout_seconds', None)
        base.pop('scan_control_wait_for_idle_seconds', None)
        base.pop('scan_last_run_at', None)
        base.pop('scan_last_status', None)
        base.pop('scan_last_message', None)
        base.pop('scan_last_summary', None)
        base.pop('strm_client_output_path', None)
        return base

    cleared = _clear_output_integration_settings(base)
    cleared['output_integrations'] = []
    return cleared


def _find_output_profile(profiles: list[dict], integration_id: str) -> tuple[int, dict | None]:
    target_id = str(integration_id or '').strip()
    if not target_id:
        return -1, None
    for idx, profile in enumerate(profiles):
        if str(profile.get('id') or '').strip() == target_id:
            return idx, profile
    return -1, None


def _find_integrations_referencing_strm_output(output_root: str) -> list[dict]:
    target = normalize_local_path(output_root)
    if not target:
        return []

    matches = []
    queryset = MediaServerIntegration.objects.filter(
        enabled=True,
        provider_type=MediaServerIntegration.ProviderTypes.LOCAL,
    ).only('id', 'name', 'provider_config')

    for integration in queryset:
        provider_config = (
            integration.provider_config
            if isinstance(integration.provider_config, dict)
            else {}
        )
        locations = provider_config.get('locations', [])
        if not isinstance(locations, list):
            continue

        for entry in locations:
            if not isinstance(entry, dict):
                continue
            location_path = str(entry.get('path') or '').strip()
            if not location_path:
                continue
            if not paths_overlap(location_path, target):
                continue
            matches.append(
                {
                    'integration_id': integration.id,
                    'integration_name': integration.name,
                    'path': location_path,
                }
            )
    return matches


def _find_output_profiles_referencing_strm_output(
    settings_value: dict,
    output_root: str,
    *,
    exclude_profile_id: str = '',
) -> list[dict]:
    target = normalize_local_path(output_root)
    if not target:
        return []

    excluded = str(exclude_profile_id or '').strip()
    matches = []
    profiles = _extract_output_profiles(settings_value)

    for profile in profiles:
        profile_id = str(profile.get('id') or '').strip()
        if excluded and profile_id == excluded:
            continue

        profile_output_path = str(profile.get('strm_output_path') or '').strip()
        if not profile_output_path:
            profile_output_path = DEFAULT_STRM_OUTPUT_PATH
        if not paths_overlap(profile_output_path, target):
            continue

        matches.append(
            {
                'integration_id': profile_id,
                'integration_name': str(
                    profile.get('integration_name') or 'Dispatcharr Output'
                ).strip()
                or 'Dispatcharr Output',
                'path': profile_output_path,
            }
        )

    return matches


def _delete_strm_output_files(output_root: str) -> dict:
    root = normalize_local_path(output_root)
    if not root:
        return {'deleted_paths': [], 'removed_root': False}

    deleted_paths: list[str] = []
    for child in ('Movies', 'TV Shows'):
        target = os.path.join(root, child)
        if os.path.isdir(target):
            shutil.rmtree(target)
            deleted_paths.append(target)

    removed_root = False
    if os.path.isdir(root):
        try:
            if not os.listdir(root):
                os.rmdir(root)
                removed_root = True
        except OSError:
            removed_root = False

    return {
        'deleted_paths': deleted_paths,
        'removed_root': removed_root,
    }


def _clear_output_integration_settings(raw_settings: dict) -> dict:
    cleaned = dict(raw_settings or {})
    cleaned.update(
        {
            'integration_name': '',
            'target_provider': '',
            'export_mode': '',
            'export_enabled': False,
            'target_base_url': '',
            'target_api_token': '',
            'target_verify_ssl': True,
            'strm_output_path': DEFAULT_STRM_OUTPUT_PATH,
            'strm_include_nfo': True,
            'strm_last_built_at': '',
            'strm_last_build_summary': None,
            'updated_at': '',
        }
    )
    cleaned.pop('scan_control_enabled', None)
    cleaned.pop('scan_control_integration_id', None)
    cleaned.pop('scan_control_schedule_time', None)
    cleaned.pop('scan_control_library_ids', None)
    cleaned.pop('scan_control_timeout_seconds', None)
    cleaned.pop('scan_control_wait_for_idle_seconds', None)
    cleaned.pop('scan_last_run_at', None)
    cleaned.pop('scan_last_status', None)
    cleaned.pop('scan_last_message', None)
    cleaned.pop('scan_last_summary', None)
    cleaned.pop('scan_target_server_url', None)
    cleaned.pop('scan_target_server_token', None)
    cleaned.pop('scan_target_server_verify_ssl', None)
    cleaned.pop('strm_client_output_path', None)
    cleaned['output_integrations'] = []
    return cleaned


class OutputSTRMExportBuildView(APIView):
    """
    Build STRM/NFO files to a server-side folder for Docker bind-mount usage.
    """

    permission_classes = [IsAdmin]

    def post(self, request):
        settings_obj, raw_settings = _get_output_settings_value()
        settings_value = dict(raw_settings or {})
        integration_id = str(request.data.get('integration_id') or '').strip()
        profiles = _extract_output_profiles(settings_value)
        has_output_path_override = bool(str(request.data.get('output_path') or '').strip())
        has_include_nfo_override = 'include_nfo' in request.data
        has_explicit_overrides = has_output_path_override or has_include_nfo_override

        selected_profile = None
        selected_profile_index = -1
        if profiles:
            if integration_id:
                selected_profile_index, selected_profile = _find_output_profile(
                    profiles,
                    integration_id,
                )
                if selected_profile is None:
                    return Response(
                        {'detail': 'Output integration not found.'},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            elif not has_explicit_overrides:
                selected_profile_index = 0
                selected_profile = profiles[0]
        elif integration_id:
            return Response(
                {'detail': 'Output integration not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        profile_value = selected_profile if isinstance(selected_profile, dict) else {}
        include_nfo = _as_bool_output(
            request.data.get('include_nfo'),
            default=_as_bool_output(
                profile_value.get('strm_include_nfo'),
                default=_as_bool_output(settings_value.get('strm_include_nfo'), default=True),
            ),
        )
        profile_output_path = normalize_strm_output_path(
            profile_value.get('strm_output_path'),
            fallback=DEFAULT_STRM_OUTPUT_PATH,
        )
        output_path = _resolve_strm_output_path(
            request,
            settings_value,
            payload_path=(
                str(request.data.get('output_path', '')).strip() or profile_output_path
            ),
        )
        base_url = _resolve_backend_base_url(request, settings_value)

        try:
            os.makedirs(output_path, exist_ok=True)
        except PermissionError:
            return Response(
                {
                    'detail': (
                        f'Output path is not writable: {output_path}. '
                        'Use a writable path inside the container (recommended: /data/media/strm), '
                        'or mount and grant write permission to your custom path.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OSError as exc:
            return Response(
                {'detail': f'Unable to prepare output path {output_path}: {exc}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            summary = build_strm_nfo_snapshot(
                output_path,
                base_url=base_url,
                include_nfo=include_nfo,
            )
        except PermissionError:
            return Response(
                {
                    'detail': (
                        f'Output path is not writable: {output_path}. '
                        'Use a writable path inside the container (recommended: /data/media/strm), '
                        'or mount and grant write permission to your custom path.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            logger.exception('STRM/NFO export build failed')
            return Response(
                {'detail': f'Failed to build STRM/NFO export: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        now_iso = timezone.now().isoformat()
        if selected_profile:
            updated_profile = dict(selected_profile)
            updated_profile.update(
                {
                    'strm_output_path': output_path,
                    'strm_include_nfo': include_nfo,
                    'strm_last_built_at': now_iso,
                    'strm_last_build_summary': summary,
                    'updated_at': now_iso,
                }
            )
            profiles[selected_profile_index] = updated_profile
            merged_settings = _persist_output_profiles(settings_value, profiles)
        elif not profiles:
            merged_settings = dict(settings_value)
            merged_settings.update(
                {
                    'strm_output_path': output_path,
                    'strm_include_nfo': include_nfo,
                    'strm_last_built_at': now_iso,
                    'strm_last_build_summary': summary,
                }
            )
        else:
            merged_settings = dict(settings_value)

        if merged_settings != settings_value or settings_obj is None:
            _save_output_settings_value(merged_settings, obj=settings_obj)

        response_payload = {
            'success': True,
            'message': 'STRM/NFO export snapshot generated.',
            **summary,
        }
        if selected_profile:
            response_payload['integration_id'] = str(selected_profile.get('id') or '')
        return Response(response_payload)


class OutputIntegrationView(APIView):
    """
    Delete the saved output integration profile and clean STRM export files.
    """

    permission_classes = [IsAdmin]

    def get(self, request):
        settings_obj, settings_value = _get_output_settings_value()
        profiles = _extract_output_profiles(settings_value)
        setting_payload = None
        if settings_obj is not None:
            setting_payload = {
                'id': settings_obj.id,
                'key': settings_obj.key,
                'name': settings_obj.name,
            }
        return Response(
            {
                'setting': setting_payload,
                'value': settings_value,
                'profiles': profiles,
            }
        )

    def delete(self, request):
        settings_obj, raw_settings = _get_output_settings_value()
        settings_value = dict(raw_settings or {})
        payload = request.data if hasattr(request, 'data') else {}
        delete_strm_files = _as_bool_output(
            payload.get('delete_strm_files'),
            default=True,
        )
        integration_id = str(payload.get('integration_id') or '').strip()

        profiles = _extract_output_profiles(settings_value)
        selected_profile = None
        selected_profile_index = -1
        if profiles:
            if integration_id:
                selected_profile_index, selected_profile = _find_output_profile(
                    profiles,
                    integration_id,
                )
                if selected_profile is None:
                    return Response(
                        {'detail': 'Output integration not found.'},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                selected_profile_index = 0
                selected_profile = profiles[0]
        elif integration_id:
            return Response(
                {'detail': 'Output integration not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        selected_profile_id = (
            str(selected_profile.get('id') or '').strip()
            if selected_profile
            else ''
        )

        cleanup = {
            'attempted': False,
            'deleted': False,
            'deleted_paths': [],
            'removed_root': False,
            'skipped': False,
            'skip_reason': '',
            'in_use_by': [],
            'output_path': '',
        }

        if delete_strm_files and selected_profile:
            output_path = _resolve_strm_output_path(
                request,
                settings_value,
                payload_path=(
                    str(selected_profile.get('strm_output_path') or '').strip()
                    if selected_profile
                    else ''
                ),
            )
            cleanup['attempted'] = True
            cleanup['output_path'] = output_path

            in_use_by_local = _find_integrations_referencing_strm_output(output_path)
            in_use_by_outputs = _find_output_profiles_referencing_strm_output(
                settings_value,
                output_path,
                exclude_profile_id=selected_profile_id,
            )

            if in_use_by_local or in_use_by_outputs:
                cleanup['skipped'] = True
                if in_use_by_outputs:
                    cleanup['skip_reason'] = (
                        'STRM cleanup skipped because another output integration '
                        'references this path.'
                    )
                else:
                    cleanup['skip_reason'] = (
                        'STRM cleanup skipped because another enabled local integration '
                        'references this path.'
                    )
                cleanup['in_use_by'] = [*in_use_by_local, *in_use_by_outputs]
            else:
                try:
                    deleted_result = _delete_strm_output_files(output_path)
                except Exception as exc:
                    logger.exception('Failed to delete STRM output files', exc_info=exc)
                    return Response(
                        {'detail': f'Failed to delete STRM output files: {exc}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                cleanup['deleted_paths'] = deleted_result.get('deleted_paths', [])
                cleanup['removed_root'] = bool(deleted_result.get('removed_root'))
                cleanup['deleted'] = bool(cleanup['deleted_paths'])

        if profiles and selected_profile:
            remaining_profiles = [
                profile
                for idx, profile in enumerate(profiles)
                if idx != selected_profile_index
            ]
            next_settings = _persist_output_profiles(settings_value, remaining_profiles)
        else:
            next_settings = _clear_output_integration_settings(settings_value)

        _save_output_settings_value(next_settings, obj=settings_obj)

        response_payload = {
            'success': True,
            'message': 'Output integration deleted.',
            'strm_cleanup': cleanup,
        }
        if selected_profile_id:
            response_payload['deleted_integration_id'] = selected_profile_id
        return Response(response_payload)
