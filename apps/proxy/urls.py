from django.urls import path, include

from apps.proxy.live_proxy.views import hls_playlist, hls_segment

app_name = 'proxy'

urlpatterns = [
    path('ts/', include('apps.proxy.live_proxy.urls')),
    path('hls/', include('apps.proxy.hls_proxy.urls')),
    # Native HLS output for live channels (served by live_proxy). Listed
    # after the hls_proxy include so its literal prefixes keep priority.
    path('hls/<str:channel_id>/<str:client_id>/index.m3u8', hls_playlist, name='hls_playlist'),
    path('hls/<str:channel_id>/<str:client_id>/<int:seq>.ts', hls_segment, name='hls_segment'),
    path('vod/', include('apps.proxy.vod_proxy.urls')),
]
