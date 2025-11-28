from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView, RedirectView
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from .routing import websocket_urlpatterns
from apps.output.views import xc_player_api, xc_panel_api, xc_get, xc_xmltv
from apps.proxy.ts_proxy.views import stream_xc
from apps.output.views import xc_movie_stream, xc_series_stream

# Define schema_view for Swagger
schema_view = get_schema_view(
    openapi.Info(
        title="Dispatcharr API",
        default_version="v1",
        description="API documentation for Dispatcharr",
        terms_of_service="https://www.google.com/policies/terms/",
        contact=openapi.Contact(email="contact@dispatcharr.local"),
        license=openapi.License(name="Creative Commons by-nc-sa"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    # API Routes
    path("api/", include(("apps.api.urls", "api"), namespace="api")),
    path("api", RedirectView.as_view(url="/api/", permanent=True)),
    # Admin
    path("admin", RedirectView.as_view(url="/admin/", permanent=True)),
    path("admin/", admin.site.urls),
    # Outputs
    path("output", RedirectView.as_view(url="/output/", permanent=True)),
    path("output/", include(("apps.output.urls", "output"), namespace="output")),
    # HDHR
    path("hdhr", RedirectView.as_view(url="/hdhr/", permanent=True)),
    path("hdhr/", include(("apps.hdhr.urls", "hdhr"), namespace="hdhr")),
    # Add proxy apps - Move these before the catch-all
    path("proxy/", include(("apps.proxy.urls", "proxy"), namespace="proxy")),
    path("proxy", RedirectView.as_view(url="/proxy/", permanent=True)),
    # xc
    re_path("player_api.php", xc_player_api, name="xc_player_api"),
    re_path("panel_api.php", xc_panel_api, name="xc_panel_api"),
    re_path("get.php", xc_get, name="xc_get"),
    re_path("xmltv.php", xc_xmltv, name="xc_xmltv"),
    path(
        "live/<str:username>/<str:password>/<str:channel_id>",
        stream_xc,
        name="xc_live_stream_endpoint",
    ),
    path(
        "<str:username>/<str:password>/<str:channel_id>",
        stream_xc,
        name="xc_stream_endpoint",
    ),
    # XC VOD endpoints
    path(
        "movie/<str:username>/<str:password>/<str:stream_id>.<str:extension>",
        xc_movie_stream,
        name="xc_movie_stream",
    ),
    path(
        "series/<str:username>/<str:password>/<str:stream_id>.<str:extension>",
        xc_series_stream,
        name="xc_series_stream",
    ),

    re_path(r"^swagger/?$", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
    # ReDoc UI
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    # Optionally, serve the raw Swagger JSON
    path("swagger.json", schema_view.without_ui(cache_timeout=0), name="schema-json"),

    # VOD proxy is now handled by the main proxy URLs above
    # Catch-all routes should always be last
    path("", TemplateView.as_view(template_name="index.html")),  # React entry point
    path("<path:unused_path>", TemplateView.as_view(template_name="index.html")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += websocket_urlpatterns

# Serve static files for development (React's JS, CSS, etc.)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
