from django.urls import path, re_path, include
from .views import m3u_endpoint, epg_endpoint, xc_get, direct_logo_view
from core.views import stream_view

app_name = "output"

urlpatterns = [
    # Allow `/m3u`, `/m3u/`, `/m3u/profile_name`, and `/m3u/profile_name/`
    re_path(r"^m3u(?:/(?P<profile_name>[^/]+))?/?$", m3u_endpoint, name="m3u_endpoint"),
    # Allow `/epg`, `/epg/`, `/epg/profile_name`, and `/epg/profile_name/`
    re_path(r"^epg(?:/(?P<profile_name>[^/]+))?/?$", epg_endpoint, name="epg_endpoint"),
    # Allow both `/stream/<int:stream_id>` and `/stream/<int:stream_id>/`
    re_path(r"^stream/(?P<channel_uuid>[0-9a-fA-F\-]+)/?$", stream_view, name="stream"),
    # Direct logo serving for Plex compatibility
    path("logo/<int:logo_id>/<str:filename>", direct_logo_view, name="direct_logo"),
]
