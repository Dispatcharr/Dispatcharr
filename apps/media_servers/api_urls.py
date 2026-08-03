from rest_framework.routers import DefaultRouter
from django.urls import path

from .api_views import (
    MediaLibraryExportRunViewSet,
    MediaLibraryExportTargetViewSet,
    MediaLibraryImportRunViewSet,
    MediaLibrarySourceViewSet,
    MediaLibrarySettingsView,
)

app_name = "media_servers"

router = DefaultRouter()
router.register("sources", MediaLibrarySourceViewSet, basename="source")
router.register("import-runs", MediaLibraryImportRunViewSet, basename="import-run")
router.register(
    "export-targets",
    MediaLibraryExportTargetViewSet,
    basename="export-target",
)
router.register("export-runs", MediaLibraryExportRunViewSet, basename="export-run")

urlpatterns = [
    path("settings/", MediaLibrarySettingsView.as_view(), name="settings"),
    *router.urls,
]
