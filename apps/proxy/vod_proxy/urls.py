from django.urls import path
from . import views
from .views import stream_vod

app_name = 'vod_proxy'

urlpatterns = [
    # Revocable, network-scoped URLs generated for Jellyfin/Emby STRM libraries.
    path(
        'media-library/<uuid:target_public_id>/<str:content_type>/<uuid:content_id>',
        stream_vod,
        name='media_library_vod_stream',
    ),
    path(
        'media-library/<uuid:target_public_id>/<str:content_type>/<uuid:content_id>/<str:session_id>',
        stream_vod,
        name='media_library_vod_stream_with_session',
    ),

    # Generic VOD streaming with session ID in path (for compatibility)
    path('<str:content_type>/<uuid:content_id>/<str:session_id>', stream_vod, name='vod_stream_with_session'),
    path('<str:content_type>/<uuid:content_id>/<str:session_id>/<int:profile_id>/', stream_vod, name='vod_stream_with_session_and_profile'),

    # Generic VOD streaming (supports movies, episodes, series) - legacy patterns
    path('<str:content_type>/<uuid:content_id>', stream_vod, name='vod_stream'),
    path('<str:content_type>/<uuid:content_id>/<int:profile_id>/', stream_vod, name='vod_stream_with_profile'),

    # VOD Stats
    path('stats/', views.vod_stats, name='vod_stats'),

    # Stop VOD client connection
    path('stop_client/', views.stop_vod_client, name='stop_vod_client'),
]
