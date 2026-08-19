from django.urls import path

from . import views

urlpatterns = [
    path("events/", views.ArrivalEventList.as_view()),
    path("ws-ticket/", views.WebSocketTicketView.as_view()), # type: ignore
]
