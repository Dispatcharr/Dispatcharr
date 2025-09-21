from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import MovieViewSet, EpisodeViewSet, SeriesViewSet, VODCategoryViewSet, UnifiedContentViewSet

app_name = 'vod'

router = DefaultRouter()
router.register(r'movies', MovieViewSet)
router.register(r'episodes', EpisodeViewSet)
router.register(r'series', SeriesViewSet)
router.register(r'categories', VODCategoryViewSet)
router.register(r'all', UnifiedContentViewSet, basename='unified-content')

urlpatterns = [
    path('api/', include(router.urls)),
]
