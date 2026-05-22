from django.urls import path, include

app_name = 'proxy'

urlpatterns = [
    path('ts/', include('apps.proxy.live_proxy.urls')),
    path('hls/', include('apps.proxy.hls_proxy.urls')),
    path('vod/', include('apps.proxy.vod_proxy.urls')),
]
