from django.urls import path
from .api_views import HLSChannelStartStopView, HLSChannelStatusView

app_name = "hls_output_api"

urlpatterns = [
    path('channel/<uuid:channel_uuid>/<str:action>', HLSChannelStartStopView.as_view(), name='hls_channel_action'),
    path('channel/<uuid:channel_uuid>/status', HLSChannelStatusView.as_view(), name='hls_channel_status'),
]
