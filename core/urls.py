from django.urls import path
from .views import settings_view, rehash_streams_view

urlpatterns = [
    path('', settings_view, name='settings'),
    path('rehash-streams/', rehash_streams_view, name='rehash_streams'),
]
