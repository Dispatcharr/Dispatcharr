# core/api_urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    UserAgentViewSet,
    StreamProfileViewSet,
    CoreSettingsViewSet,
    environment,
    version,
    check_update,
)

router = DefaultRouter()
router.register(r'useragents', UserAgentViewSet, basename='useragent')
router.register(r'streamprofiles', StreamProfileViewSet, basename='streamprofile')
router.register(r'settings', CoreSettingsViewSet, basename='coresettings')
router.register(r'settings', CoreSettingsViewSet, basename='settings')
urlpatterns = [
    path('settings/env/', environment, name='token_refresh'),
    path('version/', version, name='version'),
    path('check_update/', check_update, name='check_update'),
    path('', include(router.urls)),
]
