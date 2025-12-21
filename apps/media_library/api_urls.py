from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.media_library.api_views import (
    LibraryScanViewSet,
    LibraryViewSet,
    MediaItemViewSet,
    browse_library_path,
)

app_name = "media_library"

router = DefaultRouter()
router.register(r"libraries", LibraryViewSet, basename="library")
router.register(r"scans", LibraryScanViewSet, basename="library-scan")
router.register(r"items", MediaItemViewSet, basename="media-item")

urlpatterns = [
    path("browse/", browse_library_path, name="browse"),
]

urlpatterns += router.urls
