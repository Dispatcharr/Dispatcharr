from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .api_views import (
    FuseBrowseView,
    FuseSettingsViewSet,
    FuseStreamURLView,
    FuseClientDownloadView,
)

app_name = "fuse_api"

router = DefaultRouter()
router.register(r"settings", FuseSettingsViewSet, basename="fuse-settings")

urlpatterns = [
    path("browse/<str:mode>/", FuseBrowseView.as_view(), name="browse"),
    path("stream/<str:content_type>/<uuid:content_id>/", FuseStreamURLView.as_view(), name="stream-url"),
    path("client-script/", FuseClientDownloadView.as_view(), name="client-script"),
    path("", include(router.urls)),
]
