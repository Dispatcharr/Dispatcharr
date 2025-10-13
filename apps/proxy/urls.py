from django.urls import include, path

from . import views

app_name = 'proxy'

urlpatterns = [
    path('ts/', include('apps.proxy.ts_proxy.urls')),
    path('hls/', include('apps.proxy.hls_proxy.urls')),
    path('vod/', include('apps.proxy.vod_proxy.urls')),
    path('library/<str:token>/', views.library_stream, name='library-stream'),
]
