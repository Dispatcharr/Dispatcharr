import logging
import os
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
