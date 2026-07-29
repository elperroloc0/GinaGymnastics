from django.urls import path

from .consumers import VanPositionConsumer

websocket_urlpatterns = [
    path("ws/van/", VanPositionConsumer.as_asgi())
]
