from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    MovieViewSet,
    EpisodeViewSet,
    SeriesViewSet,
    VODCategoryViewSet,
    UnifiedContentViewSet,
    VODLogoViewSet,
)

app_name = 'vod'

router = DefaultRouter()
router.register(r'movies', MovieViewSet, basename='movie')
router.register(r'episodes', EpisodeViewSet, basename='episode')
router.register(r'series', SeriesViewSet, basename='series')
router.register(r'categories', VODCategoryViewSet, basename='vodcategory')
router.register(r'all', UnifiedContentViewSet, basename='unified-content')
router.register(r'vodlogos', VODLogoViewSet, basename='vodlogo')

urlpatterns = router.urls
