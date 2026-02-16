from django.urls import path
from rest_framework.routers import DefaultRouter
from .api_views import (
    IntegrationViewSet,
    EventSubscriptionViewSet,
    DeliveryLogViewSet,
)

app_name = 'connect'

router = DefaultRouter()
router.register(r'integrations', IntegrationViewSet, basename='integration')
router.register(r'subscriptions', EventSubscriptionViewSet, basename='subscription')
router.register(r'logs', DeliveryLogViewSet, basename='delivery-log')

urlpatterns = []
urlpatterns += router.urls
