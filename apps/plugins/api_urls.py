from django.urls import path
from .api_views import (
    PluginsListAPIView,
    PluginReloadAPIView,
    PluginSingleReloadAPIView,
    PluginSettingsAPIView,
    PluginFieldUploadAPIView,
    PluginRunAPIView,
    PluginEnabledAPIView,
    PluginImportAPIView,
    PluginDeleteAPIView,
    PluginLogoAPIView,
    PluginRepoListCreateAPIView,
    PluginRepoPreviewAPIView,
    PluginRepoDetailAPIView,
    PluginRepoRefreshAPIView,
    PluginRepoRefreshSinglePluginAPIView,
    AvailablePluginsAPIView,
    PluginDetailManifestAPIView,
    PluginInstallFromRepoAPIView,
    PluginRepoSettingsAPIView,
)

app_name = "plugins"

urlpatterns = [
    path("plugins/", PluginsListAPIView.as_view(), name="list"),
    path("plugins/reload/", PluginReloadAPIView.as_view(), name="reload"),
    path("plugins/import/", PluginImportAPIView.as_view(), name="import"),
    path("plugins/<str:key>/delete/", PluginDeleteAPIView.as_view(), name="delete"),
    path("plugins/<str:key>/settings/", PluginSettingsAPIView.as_view(), name="settings"),
    path("plugins/<str:key>/fields/<str:field_id>/upload/", PluginFieldUploadAPIView.as_view(), name="field-upload"),
    path("plugins/<str:key>/run/", PluginRunAPIView.as_view(), name="run"),
    path("plugins/<str:key>/enabled/", PluginEnabledAPIView.as_view(), name="enabled"),
    path("plugins/<str:key>/logo/", PluginLogoAPIView.as_view(), name="logo"),
    path("plugins/<str:key>/reload/", PluginSingleReloadAPIView.as_view(), name="single-reload"),
    # Plugin repos (hub / store) - static paths first, then parametric
    path("repos/", PluginRepoListCreateAPIView.as_view(), name="repo-list"),
    path("repos/available/", AvailablePluginsAPIView.as_view(), name="available-plugins"),
    path("repos/plugin-detail/", PluginDetailManifestAPIView.as_view(), name="plugin-detail-manifest"),
    path("repos/install/", PluginInstallFromRepoAPIView.as_view(), name="repo-install"),
    path("repos/settings/", PluginRepoSettingsAPIView.as_view(), name="repo-settings"),
    path("repos/preview/", PluginRepoPreviewAPIView.as_view(), name="repo-preview"),
    path("repos/<int:pk>/", PluginRepoDetailAPIView.as_view(), name="repo-detail"),
    path("repos/<int:pk>/refresh/", PluginRepoRefreshAPIView.as_view(), name="repo-refresh"),
    path("repos/<int:pk>/plugins/<str:slug>/refresh/", PluginRepoRefreshSinglePluginAPIView.as_view(), name="repo-refresh-single-plugin"),
]
