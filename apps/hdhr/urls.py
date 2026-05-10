from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import HDHRDeviceViewSet, DiscoverAPIView, LineupAPIView, LineupStatusAPIView, HDHRDeviceXMLAPIView, hdhr_dashboard_view

app_name = 'hdhr'

router = DefaultRouter()
router.register(r'devices', HDHRDeviceViewSet, basename='hdhr-device')

urlpatterns = [
    path('dashboard/', hdhr_dashboard_view, name='hdhr_dashboard'),
    path('', hdhr_dashboard_view, name='hdhr_dashboard'),

    # channel_profile + output_profile_id  (/hdhr/<channel_profile>/output_profile/<id>/...)
    path('<str:channel_profile>/output_profile/<int:output_profile_id>/discover.json', DiscoverAPIView.as_view(), name='discover_with_profile_and_output'),
    path('<str:channel_profile>/output_profile/<int:output_profile_id>/lineup.json', LineupAPIView.as_view(), name='lineup_with_profile_and_output'),
    path('<str:channel_profile>/output_profile/<int:output_profile_id>/lineup_status.json', LineupStatusAPIView.as_view(), name='lineup_status_with_profile_and_output'),

    # output_profile_id only  (/hdhr/output_profile/<id>/...)
    path('output_profile/<int:output_profile_id>/discover.json', DiscoverAPIView.as_view(), name='discover_with_output'),
    path('output_profile/<int:output_profile_id>/lineup.json', LineupAPIView.as_view(), name='lineup_with_output'),
    path('output_profile/<int:output_profile_id>/lineup_status.json', LineupStatusAPIView.as_view(), name='lineup_status_with_output'),

    # channel_profile only
    path('<str:channel_profile>/discover.json', DiscoverAPIView.as_view(), name='discover_with_profile'),
    path('<str:channel_profile>/lineup.json', LineupAPIView.as_view(), name='lineup_with_profile'),
    path('<str:channel_profile>/lineup_status.json', LineupStatusAPIView.as_view(), name='lineup_status_with_profile'),

    # bare endpoints
    path('discover.json', DiscoverAPIView.as_view(), name='discover_no_profile'),
    path('lineup.json', LineupAPIView.as_view(), name='lineup_no_profile'),
    path('lineup_status.json', LineupStatusAPIView.as_view(), name='lineup_status_no_profile'),

    path('device.xml', HDHRDeviceXMLAPIView.as_view(), name='device_xml'),
]

urlpatterns += router.urls
