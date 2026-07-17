from django.urls import path

from . import views

urlpatterns = [
    path("routes/", views.RouteList.as_view())
]
