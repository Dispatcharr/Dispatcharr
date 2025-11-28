"""
HLS Output URL Configuration
"""

from django.urls import path
from . import views

app_name = 'hls_output'

urlpatterns = [
    # Stream Management
    path('streams/', views.HLSStreamListView.as_view(), name='stream-list'),
    path('streams/<uuid:stream_id>/', views.HLSStreamDetailView.as_view(), name='stream-detail'),
    path('streams/start/', views.start_stream, name='stream-start'),
    path('streams/<uuid:stream_id>/stop/', views.stop_stream, name='stream-stop'),
    path('streams/<uuid:stream_id>/restart/', views.restart_stream, name='stream-restart'),
    
    # Playlist Serving
    path('live/<uuid:stream_id>/master.m3u8', views.master_playlist, name='master-playlist'),
    path('live/<uuid:stream_id>/<str:quality>/playlist.m3u8', views.media_playlist, name='media-playlist'),
    path('live/<uuid:stream_id>/<str:quality>/<str:segment>', views.serve_segment, name='serve-segment'),
    
    # Profile Management
    path('profiles/', views.HLSProfileListView.as_view(), name='profile-list'),
    path('profiles/<int:pk>/', views.HLSProfileDetailView.as_view(), name='profile-detail'),
    
    # Stats and Metrics
    path('streams/<uuid:stream_id>/stats/', views.stream_stats, name='stream-stats'),
    path('stats/', views.global_stats, name='global-stats'),
]

