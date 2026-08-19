from django.urls import path

from .consumers import VanPositionConsumer
from .views import WebSocketTicketView

websocket_urlpatterns = [
    path("ws/van/", VanPositionConsumer.as_asgi()), # type: ignore
]
