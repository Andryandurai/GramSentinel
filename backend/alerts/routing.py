from django.urls import path

from .consumers import OfficerAlertConsumer

websocket_urlpatterns = [
    path("ws/officer/alerts/", OfficerAlertConsumer.as_asgi()),
]
