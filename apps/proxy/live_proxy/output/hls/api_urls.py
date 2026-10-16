from django.urls import path

from . import api_views

app_name = "hls"

urlpatterns = [
    path(
        "sessions/<str:token>/",
        api_views.HlsSessionDestroyAPIView.as_view(),
        name="hls-session-destroy",
    ),
]
