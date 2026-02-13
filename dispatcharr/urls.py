from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView, RedirectView
from django.views.static import serve
from .routing import websocket_urlpatterns
from apps.output.views import xc_player_api, xc_panel_api, xc_get, xc_xmltv
from apps.proxy.ts_proxy.views import stream_xc
from apps.output.views import xc_movie_stream, xc_series_stream

urlpatterns = [
    # API Routes
    path("api/", include(("apps.api.urls", "api"), namespace="api")),
    path("api", RedirectView.as_view(url="/api/", permanent=True)),
    # Swagger redirects (Swagger UI is served at /api/swagger/)
    path("swagger/", RedirectView.as_view(url="/api/swagger/", permanent=True)),
    path("swagger", RedirectView.as_view(url="/api/swagger/", permanent=True)),
    path("redoc/", RedirectView.as_view(url="/api/redoc/", permanent=True)),
    path("redoc", RedirectView.as_view(url="/api/redoc/", permanent=True)),
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
    # Admin
    path("admin", RedirectView.as_view(url="/admin/", permanent=True)),
    path("admin/", admin.site.urls),

    # VOD proxy is now handled by the main proxy URLs above
    # Frontend static assets from Vite build output
    re_path(
        r"^assets/(?P<path>.*)$",
        serve,
        {"document_root": settings.BASE_DIR / "frontend" / "dist" / "assets"},
    ),
    re_path(
        r"^(?P<path>logo\.png)$",
        serve,
        {"document_root": settings.BASE_DIR / "frontend" / "dist"},
    ),

    # Catch-all routes should always be last
    path("", TemplateView.as_view(template_name="index.html")),  # React entry point
    path("<path:unused_path>", TemplateView.as_view(template_name="index.html")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += websocket_urlpatterns

# Serve static files for development (React's JS, CSS, etc.)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
