from django.urls import path
from . import views

app_name = 'ts_proxy'

urlpatterns = [
    path('stream/<str:channel_id>', views.stream_ts, name='stream'),
    path('initialize/<str:channel_id>', views.initialize_stream, name='initialize'),
    path('change_stream/<str:channel_id>', views.change_stream, name='change_stream'),
]