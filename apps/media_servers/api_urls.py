from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.media_servers.api_views import (
    MediaServerIntegrationViewSet,
    MediaServerSyncRunViewSet,
)

app_name = 'media_servers'

router = DefaultRouter()
router.register(
    r'integrations',
    MediaServerIntegrationViewSet,
    basename='media-server-integration',
)
router.register(
    r'sync-runs',
    MediaServerSyncRunViewSet,
    basename='media-server-sync-run',
)

urlpatterns = [
    path(
        'integrations/plex-auth/start/',
        MediaServerIntegrationViewSet.as_view({'post': 'plex_auth_start'}),
        name='media-server-integration-plex-auth-start',
    ),
    path(
        'integrations/plex-auth/check/',
        MediaServerIntegrationViewSet.as_view({'get': 'plex_auth_check'}),
        name='media-server-integration-plex-auth-check',
    ),
    path(
        'integrations/plex-auth/servers/',
        MediaServerIntegrationViewSet.as_view({'get': 'plex_auth_servers'}),
        name='media-server-integration-plex-auth-servers',
    ),
]
urlpatterns += router.urls
