from django.urls import path
from .api_views import (
    PluginsListAPIView,
    PluginReloadAPIView,
    PluginSettingsAPIView,
    PluginRunAPIView,
    PluginEnabledAPIView,
    PluginImportAPIView,
    PluginDeleteAPIView,
)

app_name = "plugins"

urlpatterns = [
    path("plugins/", PluginsListAPIView.as_view(), name="list"),
    path("plugins/reload/", PluginReloadAPIView.as_view(), name="reload"),
    path("plugins/import/", PluginImportAPIView.as_view(), name="import"),
    path("plugins/<str:key>/delete/", PluginDeleteAPIView.as_view(), name="delete"),
    path("plugins/<str:key>/settings/", PluginSettingsAPIView.as_view(), name="settings"),
    path("plugins/<str:key>/run/", PluginRunAPIView.as_view(), name="run"),
    path("plugins/<str:key>/enabled/", PluginEnabledAPIView.as_view(), name="enabled"),
]
