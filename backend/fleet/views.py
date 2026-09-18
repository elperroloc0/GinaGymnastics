import logging

from accounts.models import User
from accounts.permission import IsOperatorOrReadOnly
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from rest_framework import permissions, viewsets
from rest_framework.exceptions import ValidationError

from . import traccar_client
from .models import GeoFence, Route, Van
from .serializers import GeoFenceSerializer, RouteSerializer, VanSerializer

logger = logging.getLogger(__name__)

# Create your views here.


class RouteViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:
            return Route.objects.all()

        # .distinct() matters here: two children of the same parent sharing
        # a route (the common case - siblings usually ride the same route)
        # duplicates the Route row once per matching child via this join,
        # which turns a retrieve (.get(pk=...)) into MultipleObjectsReturned.
        return Route.objects.filter(children__parent=user).distinct()

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

    def perform_create(self, serializer):
        data = serializer.validated_data
        try:
            traccar_id = traccar_client.create_geofence(
                data["name"], float(data["latitude"]), float(data["longitude"]), float(data["radius"])
            )
        except traccar_client.TraccarAPIError as e:
            raise ValidationError({"detail": f"Could not create geofence in Traccar: {e}"})
        serializer.save(traccar_id=traccar_id)

    def perform_update(self, serializer):
        instance = serializer.instance
        data = serializer.validated_data
        if {"name", "latitude", "longitude", "radius"} & data.keys():
            name = data.get("name", instance.name)
            latitude = float(data.get("latitude", instance.latitude))
            longitude = float(data.get("longitude", instance.longitude))
            radius = float(data.get("radius", instance.radius))
            try:
                traccar_client.update_geofence(instance.traccar_id, name, latitude, longitude, radius)
            except traccar_client.TraccarAPIError as e:
                raise ValidationError({"detail": f"Could not update geofence in Traccar: {e}"})
        serializer.save()

    def perform_destroy(self, instance):
        traccar_id = instance.traccar_id
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError({"detail": "This geofence is used by a route and can't be deleted."})

        try:
            traccar_client.delete_geofence(traccar_id)
        except traccar_client.TraccarAPIError:
            logger.warning("Failed to delete Traccar geofence %s after deleting GeoFence row", traccar_id, exc_info=True)

class VanViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:
            return Van.objects.all()
        # Same duplicate-row reasoning as RouteViewSet.get_queryset() above -
        # two children on the same route (or two routes on the same van)
        # both join back to this one Van row.
        return Van.objects.filter(routes__children__parent=user).distinct()
    serializer_class = VanSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrReadOnly]

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError({"detail": "This van is used by a route and can't be deleted."})

