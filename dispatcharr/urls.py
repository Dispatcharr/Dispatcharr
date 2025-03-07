from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView, RedirectView
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from .routing import websocket_urlpatterns
from apps.hdhr.api_views import HDHRDeviceViewSet, DiscoverAPIView, LineupAPIView, LineupStatusAPIView, HDHRDeviceXMLAPIView, hdhr_dashboard_view


# Define schema_view for Swagger
schema_view = get_schema_view(
    openapi.Info(
        title="Dispatcharr API",
        default_version='v1',
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
    path('api/', include(('apps.api.urls', 'api'), namespace='api')),
    path('api', RedirectView.as_view(url='/api/', permanent=True)),

    # Admin
    path('admin', RedirectView.as_view(url='/admin/', permanent=True)),
    path('admin/', admin.site.urls),

    # Outputs
    path('output', RedirectView.as_view(url='/output/', permanent=True)),
    path('output/', include(('apps.output.urls', 'output'), namespace='output')),

    # HDHR
    path('hdhr', RedirectView.as_view(url='/hdhr/', permanent=True)),
    path('hdhr/', include(('apps.hdhr.urls', 'hdhr'), namespace='hdhr')),

    # Add proxy apps - Move these before the catch-all
    path('proxy/', include(('apps.proxy.urls', 'proxy'), namespace='proxy')),
    path('proxy', RedirectView.as_view(url='/proxy/', permanent=True)),

    # HDHR API
    path('discover.json', DiscoverAPIView.as_view(), name='discover'),
    path('lineup.json', LineupAPIView.as_view(), name='lineup'),
    path('lineup_status.json', LineupStatusAPIView.as_view(), name='lineup_status'),
    path('device.xml', HDHRDeviceXMLAPIView.as_view(), name='device_xml'),


    # Swagger UI
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),

    # ReDoc UI
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    # Optionally, serve the raw Swagger JSON
    path('swagger.json', schema_view.without_ui(cache_timeout=0), name='schema-json'),

    # Catch-all routes should always be last
    path('', TemplateView.as_view(template_name='index.html')),  # React entry point
    path('<path:unused_path>', TemplateView.as_view(template_name='index.html')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += websocket_urlpatterns

# Serve static files for development (React's JS, CSS, etc.)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
