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
    get_system_events,
    browse_safe_directories,
    create_safe_directory,
)
from .log_files import (
    get_log_file,
    list_log_files,
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
    path('directories/browse/', browse_safe_directories, name='browse_safe_directories'),
    path('directories/create/', create_safe_directory, name='create_safe_directory'),
    path('logs/', list_log_files, name='log_files'),
    path('logs/<str:name>/download/', download_log_file, name='log_file_download'),
    path('logs/<str:name>/', get_log_file, name='log_file'),
    path('', include(router.urls)),
]
