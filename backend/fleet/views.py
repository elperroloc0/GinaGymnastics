from accounts.models import User
from accounts.permission import IsOperatorOrReadOnly
from django.db.models import Q
from rest_framework import permissions, viewsets

from .models import GeoFence, Route, Van
from .serializers import GeoFenceSerializer, RouteSerializer, VanSerializer

# Create your views here.


class RouteViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:
            return Route.objects.all()

        return Route.objects.filter(children__parent=user)

    serializer_class = RouteSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrReadOnly]


class GeoFenceViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:
            return GeoFence.objects.all()
        return GeoFence.objects.filter(Q(routes_from__children__parent=user) | Q(routes_to__children__parent=user)).distinct()

    serializer_class = GeoFenceSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrReadOnly]

class VanViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:
            return Van.objects.all()
        return Van.objects.filter(routes__children__parent=user)
    serializer_class = VanSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrReadOnly]

