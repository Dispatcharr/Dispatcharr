from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .library_api import VODLibraryViewSet
from .api_views import (
    MovieViewSet,
    EpisodeViewSet,
    SeriesViewSet,
    VODCategoryViewSet,
    UnifiedContentViewSet,
    VODLogoViewSet,
    MovieSourceViewSet,
    SeriesSourceViewSet,
    EpisodeSourceViewSet,
    SourceMetadataOptionsView,
)

app_name = 'vod'

router = DefaultRouter()
router.register(r'library', VODLibraryViewSet, basename='library')
router.register(r'movies', MovieViewSet, basename='movie')
router.register(r'episodes', EpisodeViewSet, basename='episode')
router.register(r'series', SeriesViewSet, basename='series')
router.register(r'categories', VODCategoryViewSet, basename='vodcategory')
router.register(r'all', UnifiedContentViewSet, basename='unified-content')
router.register(r'vodlogos', VODLogoViewSet, basename='vodlogo')
router.register(r'movie-sources', MovieSourceViewSet, basename='movie-source')
router.register(r'series-sources', SeriesSourceViewSet, basename='series-source')
router.register(r'episode-sources', EpisodeSourceViewSet, basename='episode-source')

urlpatterns = [
    path('source-metadata-options/', SourceMetadataOptionsView.as_view(), name='source-metadata-options'),
    # Some clients strip trailing slashes from artwork URLs. Serve the same
    # views directly (no redirect) so image fetches still return bytes.
    path(
        'vodlogos/<int:pk>/cache',
        VODLogoViewSet.as_view({'get': 'cache'}),
        name='vodlogo-cache-noslash',
    ),
    path(
        'movies/<int:pk>/image',
        MovieViewSet.as_view({'get': 'image'}),
        name='movie-image-noslash',
    ),
    path(
        'series/<int:pk>/image',
        SeriesViewSet.as_view({'get': 'image'}),
        name='series-image-noslash',
    ),
    path(
        'episodes/<int:pk>/image',
        EpisodeViewSet.as_view({'get': 'image'}),
        name='episode-image-noslash',
    ),
]
urlpatterns += router.urls
