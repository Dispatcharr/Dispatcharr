from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import EPGSourceViewSet, ProgramViewSet, EPGGridAPIView, EPGImportAPIView, EPGDataViewSet, CurrentProgramsAPIView

app_name = 'epg'

router = DefaultRouter()
router.register(r'sources', EPGSourceViewSet, basename='epg-source')
router.register(r'programs', ProgramViewSet, basename='program')
router.register(r'epgdata', EPGDataViewSet, basename='epgdata')

urlpatterns = [
    path('grid/', EPGGridAPIView.as_view(), name='epg_grid'),
    path('import/', EPGImportAPIView.as_view(), name='epg_import'),
    path('current-programs/', CurrentProgramsAPIView.as_view(), name='current_programs'),
    # Some clients strip trailing slashes from artwork URLs. Serve the same
    # view directly (no redirect) so poster fetches still return an image.
    path(
        'programs/<int:pk>/poster',
        ProgramViewSet.as_view({'get': 'poster'}),
        name='program-poster-noslash',
    ),
]

urlpatterns += router.urls
