from django.urls import path, include, re_path
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework.permissions import AllowAny

app_name = 'api'

schema_view = get_schema_view(
    openapi.Info(
        title="Dispatcharr API",
        default_version='v1',
        description="API documentation for Dispatcharr",
        terms_of_service="https://www.google.com/policies/terms/",
        contact=openapi.Contact(email="support@dispatcharr.local"),
        license=openapi.License(name="Unlicense"),
    ),
    public=True,
    permission_classes=(AllowAny,),
)

urlpatterns = [
    path('accounts/', include(('apps.accounts.api_urls', 'accounts'), namespace='accounts')),
    path('channels/', include(('apps.channels.api_urls', 'channels'), namespace='channels')),
    path('epg/', include(('apps.epg.api_urls', 'epg'), namespace='epg')),
    path('hdhr/', include(('apps.hdhr.api_urls', 'hdhr'), namespace='hdhr')),
    path('m3u/', include(('apps.m3u.api_urls', 'm3u'), namespace='m3u')),
    path('core/', include(('core.api_urls', 'core'), namespace='core')),
    path('plugins/', include(('apps.plugins.api_urls', 'plugins'), namespace='plugins')),
    path('vod/', include(('apps.vod.api_urls', 'vod'), namespace='vod')),
    path('backups/', include(('apps.backups.api_urls', 'backups'), namespace='backups')),
    # path('output/', include(('apps.output.api_urls', 'output'), namespace='output')),
    #path('player/', include(('apps.player.api_urls', 'player'), namespace='player')),
    #path('settings/', include(('apps.settings.api_urls', 'settings'), namespace='settings')),
    #path('streams/', include(('apps.streams.api_urls', 'streams'), namespace='streams')),



    # Swagger Documentation api_urls
    re_path(r'^swagger/?$', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path('swagger.json', schema_view.without_ui(cache_timeout=0), name='schema-json'),
]
