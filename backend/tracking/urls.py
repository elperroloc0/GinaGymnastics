from django.urls import path

from . import views

urlpatterns = [
    path("arrival/", views.arrival_webhook),
    path("position/", views.traccar_position),

]
