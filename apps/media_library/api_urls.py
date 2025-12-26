from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.media_library.api_views import (
    LibraryScanViewSet,
    LibraryViewSet,
    MediaItemViewSet,
    browse_library_path,
)
from apps.media_library.artwork import artwork_backdrop, artwork_poster

app_name = "media_library"

router = DefaultRouter()
router.register(r"libraries", LibraryViewSet, basename="library")
router.register(r"scans", LibraryScanViewSet, basename="library-scan")
router.register(r"items", MediaItemViewSet, basename="media-item")

urlpatterns = [
    path(
        "items/<int:pk>/artwork/poster/",
        artwork_poster,
        name="media-item-artwork-poster",
    ),
    path(
        "items/<int:pk>/artwork/backdrop/",
        artwork_backdrop,
        name="media-item-artwork-backdrop",
    ),
    path("browse/", browse_library_path, name="browse"),
]

urlpatterns += router.urls
