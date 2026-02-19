from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .api_views import (
    FuseBrowseView,
    FuseConnectedClientsView,
    FusePairingTokenView,
    FuseRegisterHostView,
    FuseSettingsViewSet,
    FusePublicSettingsView,
    FuseStreamURLView,
    FuseClientDownloadView,
)

app_name = "fuse"

router = DefaultRouter()
router.register(r"settings", FuseSettingsViewSet, basename="fuse-settings")

urlpatterns = [
    path("browse/<str:mode>/", FuseBrowseView.as_view(), name="browse"),
    path("clients/", FuseConnectedClientsView.as_view(), name="clients"),
    path("pairing-token/", FusePairingTokenView.as_view(), name="pairing-token"),
    path("register-host/", FuseRegisterHostView.as_view(), name="register-host"),
    path("settings/public/", FusePublicSettingsView.as_view(), name="settings-public"),
    path("stream/<str:content_type>/<uuid:content_id>/", FuseStreamURLView.as_view(), name="stream-url"),
    path("client-script/", FuseClientDownloadView.as_view(), name="client-script"),
    path(
        "client-script/<str:target>/",
        FuseClientDownloadView.as_view(),
        name="client-script-target",
    ),
    path("", include(router.urls)),
]
