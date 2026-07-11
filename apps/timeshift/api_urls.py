from django.urls import path

from . import api_views

app_name = "catchup"

urlpatterns = [
    path(
        "sessions/",
        api_views.CatchupSessionCreateAPIView.as_view(),
        name="catchup-session-create",
    ),
    path(
        "sessions/<str:session_id>/",
        api_views.CatchupSessionDestroyAPIView.as_view(),
        name="catchup-session-destroy",
    ),
]
