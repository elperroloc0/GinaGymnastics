from django.urls import path

from . import views

urlpatterns = [
    path("traccar/", views.traccar_webhook),
    path("position/", views.traccar_position),

]
