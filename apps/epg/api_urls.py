from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    EPGSourceViewSet,
    ProgramViewSet,
    EPGGridAPIView,
    EPGImportAPIView,
    EPGDataViewSet,
    poster_portrait_proxy
)

app_name = 'epg'

router = DefaultRouter()
router.register(r'sources', EPGSourceViewSet, basename='epg-source')
router.register(r'programs', ProgramViewSet, basename='program')
router.register(r'epgdata', EPGDataViewSet, basename='epgdata')

urlpatterns = [
    path('grid/', EPGGridAPIView.as_view(), name='epg_grid'),
    path('import/', EPGImportAPIView.as_view(), name='epg_import'),
    path('poster-portrait/', poster_portrait_proxy, name='poster_portrait'),
]

urlpatterns += router.urls
