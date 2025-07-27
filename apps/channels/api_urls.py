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
    BulkDownloadLogosFromEPGAPIView,
    LogoViewSet,
    ChannelProfileViewSet,
    UpdateChannelMembershipAPIView,
    BulkUpdateChannelMembershipAPIView,
    RecordingViewSet,
    GetChannelStreamsAPIView,
)

app_name = 'channels'  # for DRF routing

router = DefaultRouter()
router.register(r'streams', StreamViewSet, basename='stream')
router.register(r'groups', ChannelGroupViewSet, basename='channel-group')
router.register(r'channels', ChannelViewSet, basename='channel')
router.register(r'logos', LogoViewSet, basename='logo')
router.register(r'profiles', ChannelProfileViewSet, basename='profile')
router.register(r'recordings', RecordingViewSet, basename='recording')

urlpatterns = [
    # Bulk delete is a single APIView, not a ViewSet
    path('streams/bulk-delete/', BulkDeleteStreamsAPIView.as_view(), name='bulk_delete_streams'),
    path('channels/bulk-delete/', BulkDeleteChannelsAPIView.as_view(), name='bulk_delete_channels'),
    path('logos/bulk-delete/', BulkDeleteLogosAPIView.as_view(), name='bulk_delete_logos'),
    path('logos/cleanup/', CleanupUnusedLogosAPIView.as_view(), name='cleanup_unused_logos'),
    path('logos/download-from-epg/', BulkDownloadLogosFromEPGAPIView.as_view(), name='bulk_download_logos_from_epg'),
    path('channels/<int:channel_id>/streams/', GetChannelStreamsAPIView.as_view(), name='get_channel_streams'),
    path('profiles/<int:profile_id>/channels/<int:channel_id>/', UpdateChannelMembershipAPIView.as_view(), name='update_channel_membership'),
    path('profiles/<int:profile_id>/channels/bulk-update/', BulkUpdateChannelMembershipAPIView.as_view(), name='bulk_update_channel_membership'),
]

urlpatterns += router.urls
