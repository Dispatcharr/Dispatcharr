# core/api_urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    UserAgentViewSet,
    StreamProfileViewSet,
    OutputProfileViewSet,
    CoreSettingsViewSet,
    SystemNotificationViewSet,
    environment,
    version,
    rehash_streams_endpoint,
    TimezoneListView,
    get_system_events
)
from .log_files import (
    get_log_file,
    list_log_files,
    get_log_download_token,
    download_log_file,
)

router = DefaultRouter()
router.register(r'useragents', UserAgentViewSet, basename='useragent')
router.register(r'streamprofiles', StreamProfileViewSet, basename='streamprofile')
router.register(r'outputprofiles', OutputProfileViewSet, basename='outputprofile')
router.register(r'settings', CoreSettingsViewSet, basename='coresettings')
router.register(r'notifications', SystemNotificationViewSet, basename='systemnotification')
urlpatterns = [
    path('settings/env/', environment, name='token_refresh'),
    path('version/', version, name='version'),
    path('rehash-streams/', rehash_streams_endpoint, name='rehash_streams'),
    path('timezones/', TimezoneListView.as_view(), name='timezones'),
    path('system-events/', get_system_events, name='system_events'),
    path('logs/', list_log_files, name='log_files'),
    path('logs/<str:name>/download-token/', get_log_download_token, name='log_file_download_token'),
    path('logs/<str:name>/download/', download_log_file, name='log_file_download'),
    path('logs/<str:name>/', get_log_file, name='log_file'),
    path('', include(router.urls)),
]
