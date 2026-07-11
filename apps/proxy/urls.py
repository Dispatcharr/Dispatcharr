from django.urls import path, include

from apps.proxy import stats_views

app_name = 'proxy'

urlpatterns = [
    path('stats/', stats_views.combined_stats, name='combined_stats'),
    path('ts/', include('apps.proxy.live_proxy.urls')),
    path('catchup/', include('apps.timeshift.urls')),
    path('hls/', include('apps.proxy.hls_proxy.urls')),
    path('vod/', include('apps.proxy.vod_proxy.urls')),
]
