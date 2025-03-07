from django.urls import path, include

app_name = 'proxy'

urlpatterns = [
    path('ts/', include('apps.proxy.ts_proxy.urls')),
    path('hls/', include('apps.proxy.hls_proxy.urls')),
]