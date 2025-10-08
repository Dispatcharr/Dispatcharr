from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    StreamViewSet,
    ChannelViewSet,
    ChannelGroupViewSet,
    BulkDeleteStreamsAPIView,
    BulkDeleteChannelsAPIView,
    BulkDeleteLogosAPIView,
    CleanupUnusedLogosAPIView,
    LogoViewSet,
    ChannelProfileViewSet,
    UpdateChannelMembershipAPIView,
    BulkUpdateChannelMembershipAPIView,
    RecordingViewSet,
    RecurringRecordingRuleViewSet,
    GetChannelStreamsAPIView,
    SeriesRulesAPIView,
    DeleteSeriesRuleAPIView,
    EvaluateSeriesRulesAPIView,
    BulkRemoveSeriesRecordingsAPIView,
    BulkDeleteUpcomingRecordingsAPIView,
    ComskipConfigAPIView,
)

app_name = 'channels'  # for DRF routing

router = DefaultRouter()
router.register(r'streams', StreamViewSet, basename='stream')
router.register(r'groups', ChannelGroupViewSet, basename='channel-group')
router.register(r'channels', ChannelViewSet, basename='channel')
router.register(r'logos', LogoViewSet, basename='logo')
router.register(r'profiles', ChannelProfileViewSet, basename='profile')
router.register(r'recordings', RecordingViewSet, basename='recording')
router.register(r'recurring-rules', RecurringRecordingRuleViewSet, basename='recurring-rule')

urlpatterns = [
    # Bulk delete is a single APIView, not a ViewSet
    path('streams/bulk-delete/', BulkDeleteStreamsAPIView.as_view(), name='bulk_delete_streams'),
    path('channels/bulk-delete/', BulkDeleteChannelsAPIView.as_view(), name='bulk_delete_channels'),
    path('logos/bulk-delete/', BulkDeleteLogosAPIView.as_view(), name='bulk_delete_logos'),
    path('logos/cleanup/', CleanupUnusedLogosAPIView.as_view(), name='cleanup_unused_logos'),
    path('channels/<int:channel_id>/streams/', GetChannelStreamsAPIView.as_view(), name='get_channel_streams'),
    path('profiles/<int:profile_id>/channels/<int:channel_id>/', UpdateChannelMembershipAPIView.as_view(), name='update_channel_membership'),
    path('profiles/<int:profile_id>/channels/bulk-update/', BulkUpdateChannelMembershipAPIView.as_view(), name='bulk_update_channel_membership'),
    # DVR series rules (order matters: specific routes before catch-all slug)
    path('series-rules/', SeriesRulesAPIView.as_view(), name='series_rules'),
    path('series-rules/evaluate/', EvaluateSeriesRulesAPIView.as_view(), name='evaluate_series_rules'),
    path('series-rules/bulk-remove/', BulkRemoveSeriesRecordingsAPIView.as_view(), name='bulk_remove_series_recordings'),
    path('series-rules/<str:tvg_id>/', DeleteSeriesRuleAPIView.as_view(), name='delete_series_rule'),
    path('recordings/bulk-delete-upcoming/', BulkDeleteUpcomingRecordingsAPIView.as_view(), name='bulk_delete_upcoming_recordings'),
    path('dvr/comskip-config/', ComskipConfigAPIView.as_view(), name='comskip_config'),
]

urlpatterns += router.urls
