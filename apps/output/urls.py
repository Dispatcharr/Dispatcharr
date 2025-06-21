from django.urls import path, re_path, include
from .views import m3u_endpoint, epg_endpoint, xc_get, hls_manifest_view, hls_segment_view # Added HLS views
from core.views import stream_view

app_name = "output"

urlpatterns = [
    # Allow `/m3u`, `/m3u/`, `/m3u/profile_name`, and `/m3u/profile_name/`
    re_path(r"^m3u(?:/(?P<profile_name>[^/]+))?/?$", m3u_endpoint, name="m3u_endpoint"),
    # Allow `/epg`, `/epg/`, `/epg/profile_name`, and `/epg/profile_name/`
    re_path(r"^epg(?:/(?P<profile_name>[^/]+))?/?$", epg_endpoint, name="epg_endpoint"),
    # Allow both `/stream/<uuid:channel_uuid>` and `/stream/<uuid:channel_uuid>/` (changed to uuid)
    re_path(r"^stream/(?P<channel_uuid>[0-9a-fA-F\-]+)/?$", stream_view, name="stream"),

    # HLS Output Endpoints - Revised for ABR
    # Master/variant playlist (playlist_name can be "master.m3u8" or "720p/playlist.m3u8")
    path('hls/<uuid:channel_uuid>/<path:playlist_name>', hls_manifest_view, name='hls_playlist'),
    # Segments (segment_path_in_channel_dir can be "segment1.ts" or "720p/segment1.ts")
    # This pattern MUST come AFTER the playlist pattern if playlist_name could also match segment patterns (e.g. if segments could be .m3u8)
    # However, since segments are .ts and playlists are .m3u8, the order is less critical here but good practice.
    # For clarity, specific playlist patterns could be defined first if master.m3u8 is always at root.
    # The current hls_manifest_view defaults playlist_name to "master.m3u8", so a direct /hls/<uuid>/master.m3u8 will work.
    path('hls/<uuid:channel_uuid>/<path:segment_path_in_channel_dir>', hls_segment_view, name='hls_segment'),
]
