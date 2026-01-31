from django.urls import path
from .api_views import (
    PluginsListAPIView,
    PluginReloadAPIView,
    PluginSettingsAPIView,
    PluginRunAPIView,
    PluginEnabledAPIView,
    PluginImportAPIView,
    PluginDeleteAPIView,
    PluginNavigationAPIView,
    PluginPageAPIView,
    PluginDataListAPIView,
    PluginDataDetailAPIView,
    PluginDataBulkAPIView,
)

app_name = "plugins"

urlpatterns = [
    # Plugin management
    path("plugins/", PluginsListAPIView.as_view(), name="list"),
    path("plugins/reload/", PluginReloadAPIView.as_view(), name="reload"),
    path("plugins/import/", PluginImportAPIView.as_view(), name="import"),

    # Navigation items for sidebar
    path("plugins/navigation/", PluginNavigationAPIView.as_view(), name="navigation"),

    # Individual plugin operations
    path("plugins/<str:key>/delete/", PluginDeleteAPIView.as_view(), name="delete"),
    path("plugins/<str:key>/settings/", PluginSettingsAPIView.as_view(), name="settings"),
    path("plugins/<str:key>/run/", PluginRunAPIView.as_view(), name="run"),
    path("plugins/<str:key>/enabled/", PluginEnabledAPIView.as_view(), name="enabled"),

    # Plugin page schema
    path("plugins/<str:key>/page/", PluginPageAPIView.as_view(), name="page-main"),
    path("plugins/<str:key>/page/<str:page_id>/", PluginPageAPIView.as_view(), name="page"),

    # Plugin data CRUD
    # GET: list collection, POST: add to collection, DELETE: clear collection
    path(
        "plugins/<str:key>/data/<str:collection>/",
        PluginDataListAPIView.as_view(),
        name="data-list",
    ),
    # PUT: replace entire collection
    path(
        "plugins/<str:key>/data/<str:collection>/bulk/",
        PluginDataBulkAPIView.as_view(),
        name="data-bulk",
    ),
    # GET: get item, PUT: replace item, PATCH: update item, DELETE: remove item
    path(
        "plugins/<str:key>/data/<str:collection>/<int:record_id>/",
        PluginDataDetailAPIView.as_view(),
        name="data-detail",
    ),
]
