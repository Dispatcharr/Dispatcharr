from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    M3UAccountViewSet,
    M3UFilterViewSet,
    M3UGroupRuleViewSet,
    ServerGroupViewSet,
    RefreshM3UAPIView,
    RefreshSingleM3UAPIView,
    RefreshAccountInfoAPIView,
    UserAgentViewSet,
    M3UAccountProfileViewSet,
    M3UAccountTemplateViewSet,
)

app_name = "m3u"

router = DefaultRouter()
router.register(r"accounts", M3UAccountViewSet, basename="m3u-account")
router.register(
    r"account-templates",
    M3UAccountTemplateViewSet,
    basename="m3u-account-template",
)
router.register(
    r"accounts/(?P<account_id>\d+)/profiles",
    M3UAccountProfileViewSet,
    basename="m3u-account-profiles",
)
router.register(
    r"accounts/(?P<account_id>\d+)/group-rules",
    M3UGroupRuleViewSet,
    basename="m3u-group-rules",
)
router.register(
    r"accounts/(?P<account_id>\d+)/filters",
    M3UFilterViewSet,
    basename="m3u-filters",
)
router.register(r"server-groups", ServerGroupViewSet, basename="server-group")

urlpatterns = [
    path("refresh/", RefreshM3UAPIView.as_view(), name="m3u_refresh"),
    path(
        "refresh/<int:account_id>/",
        RefreshSingleM3UAPIView.as_view(),
        name="m3u_refresh_single",
    ),
    path(
        "refresh-account-info/<int:profile_id>/",
        RefreshAccountInfoAPIView.as_view(),
        name="m3u_refresh_account_info",
    ),
]

urlpatterns += router.urls
