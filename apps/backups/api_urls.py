from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import BackupJobViewSet, BackupSettingsView

app_name = "backups"

router = DefaultRouter()
router.register(r"jobs", BackupJobViewSet, basename="backup-job")

urlpatterns = [
    path("settings/", BackupSettingsView.as_view(), name="backup-settings"),
    path("", include(router.urls)),
]
