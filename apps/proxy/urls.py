from django.urls import path, include

from apps.proxy import stats_views
from apps.proxy.live_proxy.output.hls.views import hls_playlist, hls_segment

app_name = 'proxy'

urlpatterns = [
    path('stats/', stats_views.combined_stats, name='combined_stats'),
    path('ts/', include('apps.proxy.live_proxy.urls')),
    path('catchup/', include('apps.timeshift.urls')),
    # Opaque HLS capability URLs (token maps to channel + client in Redis).
    path('hls/<str:token>/index.m3u8', hls_playlist, name='hls_playlist'),
    path('hls/<str:token>/<int:seq>.ts', hls_segment, name='hls_segment'),
    path('vod/', include('apps.proxy.vod_proxy.urls')),
]
