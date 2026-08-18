from django.urls import path
from rest_framework.routers import DefaultRouter
from .api_views import (
    HDHRDeviceViewSet,
    DiscoverAPIView,
    LineupAPIView,
    LineupStatusAPIView,
    HDHRDeviceXMLAPIView,
)

app_name = 'hdhr'

router = DefaultRouter()
router.register(r'devices', HDHRDeviceViewSet, basename='hdhr-device')

urlpatterns = [
    path('discover.json', DiscoverAPIView.as_view(), name='discover'),
    path('lineup.json', LineupAPIView.as_view(), name='lineup'),
    path('lineup_status.json', LineupStatusAPIView.as_view(), name='lineup_status'),
    path('device.xml', HDHRDeviceXMLAPIView.as_view(), name='device_xml'),
]

urlpatterns += router.urls
