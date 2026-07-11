from django.urls import path

from . import stats_views, views

app_name = "catchup"

urlpatterns = [
    path("stats/", stats_views.timeshift_stats, name="catchup_stats"),
    path("programs/", stats_views.catchup_programmes, name="catchup_programmes"),
    path("stop_client/", stats_views.stop_timeshift_session, name="catchup_stop_client"),
    path("<uuid:channel_id>", views.catchup_proxy, name="catchup"),
]
