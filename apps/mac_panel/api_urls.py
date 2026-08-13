# apps/mac_panel/api_urls.py
from rest_framework.routers import DefaultRouter

from .api_views import MacPanelDeviceViewSet

app_name = "mac_panel"

router = DefaultRouter()
router.register(r"devices", MacPanelDeviceViewSet, basename="mac-panel-device")

urlpatterns = router.urls
