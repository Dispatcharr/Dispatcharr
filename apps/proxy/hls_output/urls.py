"""
HLS Output URL Configuration
"""
from django.urls import path
from . import views

app_name = 'hls_output'

urlpatterns = [
    # Master playlist (all qualities)
    path('master.m3u8', views.serve_master_playlist, name='master_playlist'),
    
    # Channel-specific playlists
    path('channel/<str:channel_uuid>/<str:quality>.m3u8', views.serve_playlist, name='playlist'),
    
    # Segments
    path('channel/<str:channel_uuid>/<str:segment_name>', views.serve_segment, name='segment'),
]

