from rest_framework import viewsets

from .models import GeoFence, Route, Van
from .serializers import GeoFenceSerializer, RouteSerializer

# Create your views here.


class RouteViewSet(viewsets.ModelViewSet):
    queryset = Route.objects.all()
    serializer_class = RouteSerializer


class GeoFenceViewSet(viewsets.ModelViewSet):
    queryset = GeoFence.objects.all()
    serializer_class = GeoFenceSerializer


