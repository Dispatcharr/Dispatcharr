from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import EPGSourceViewSet, ProgramViewSet, EPGGridAPIView, EPGImportAPIView, EPGDataViewSet, CurrentProgramsAPIView, ProgramSearchAPIView

app_name = 'epg'

router = DefaultRouter()
router.register(r'sources', EPGSourceViewSet, basename='epg-source')
router.register(r'programs', ProgramViewSet, basename='program')
router.register(r'epgdata', EPGDataViewSet, basename='epgdata')

urlpatterns = [
    path('grid/', EPGGridAPIView.as_view(), name='epg_grid'),
    path('import/', EPGImportAPIView.as_view(), name='epg_import'),
    path('current-programs/', CurrentProgramsAPIView.as_view(), name='current_programs'),
    path('programs/search/', ProgramSearchAPIView.as_view(), name='program_search'),
]

urlpatterns += router.urls
