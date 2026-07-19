from django.urls import path, include, re_path
from drf_spectacular.views import SpectacularSwaggerView, SpectacularRedocView

from apps.api.schema_views import LockedSpectacularAPIView

app_name = 'api'

urlpatterns = [
    path('accounts/', include(('apps.accounts.api_urls', 'accounts'), namespace='accounts')),
    path('channels/', include(('apps.channels.api_urls', 'channels'), namespace='channels')),
    path('epg/', include(('apps.epg.api_urls', 'epg'), namespace='epg')),
    path('hdhr/', include(('apps.hdhr.api_urls', 'hdhr'), namespace='hdhr')),
    path('m3u/', include(('apps.m3u.api_urls', 'm3u'), namespace='m3u')),
    path('core/', include(('core.api_urls', 'core'), namespace='core')),
    path('plugins/', include(('apps.plugins.api_urls', 'plugins'), namespace='plugins')),
    path('vod/', include(('apps.vod.api_urls', 'vod'), namespace='vod')),
    path('catchup/', include(('apps.timeshift.api_urls', 'catchup'), namespace='catchup')),
    path('backups/', include(('apps.backups.api_urls', 'backups'), namespace='backups')),
    path('connect/', include(('apps.connect.api_urls', 'connect'), namespace='connect')),
    # path('output/', include(('apps.output.api_urls', 'output'), namespace='output')),
    #path('player/', include(('apps.player.api_urls', 'player'), namespace='player')),
    #path('settings/', include(('apps.settings.api_urls', 'settings'), namespace='settings')),
    #path('streams/', include(('apps.streams.api_urls', 'streams'), namespace='streams')),



    # OpenAPI schema (single-flight + Django cache; see apps.api.schema_views)
    path('schema/', LockedSpectacularAPIView.as_view(), name='schema'),
    re_path(r'^swagger/?$', SpectacularSwaggerView.as_view(url_name='api:schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api:schema'), name='redoc'),
    path('swagger.json', LockedSpectacularAPIView.as_view(), name='schema-json'),
]
