from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.media_library import api_views, views

router = DefaultRouter()
router.register(r"libraries", api_views.LibraryViewSet, basename="library")
router.register(r"scans", api_views.LibraryScanViewSet, basename="libraryscan")
router.register(r"items", api_views.MediaItemViewSet, basename="mediaitem")
router.register(r"files", api_views.MediaFileViewSet, basename="mediafile")
router.register(r"progress", api_views.WatchProgressViewSet, basename="watchprogress")

urlpatterns = [
    path("", include(router.urls)),
    path("stream/<str:token>/", views.stream_media_file, name="stream-file"),
]
