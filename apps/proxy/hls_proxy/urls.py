from django.urls import path
from . import views

app_name = 'hls_proxy'

urlpatterns = [
    path('stream/<str:channel_id>', views.stream_endpoint, name='stream'),
    path('initialize/<str:channel_id>', views.initialize_stream, name='initialize'),
    path('segments/<path:segment_name>', views.get_segment, name='segment'),
    path('change_stream/<str:channel_id>', views.change_stream, name='change_stream'),
]