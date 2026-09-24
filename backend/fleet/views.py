import logging

from accounts.models import User
from accounts.permission import IsOperatorOrReadOnly
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from rest_framework import permissions, viewsets
from rest_framework.exceptions import ValidationError

from . import traccar_client
from .models import GeoFence, Route, Van
from .serializers import GeoFenceSerializer, RouteSerializer, VanSerializer

logger = logging.getLogger(__name__)

# Create your views here.


def _sync_van_geofences(van):
    """Make the van's Traccar device linked to exactly the zones its routes use.

    Diffing against Traccar's current links (rather than link/unlink per
    route) keeps this idempotent and correct when several routes share a
    zone: deleting one route must not unlink a zone another route still needs.
    Only zones we manage (GeoFence rows) are ever unlinked.
    """
    device_id = traccar_client.get_device_id(van.tracker_imei)

    wanted = set()
    for route in Route.objects.filter(van=van).select_related("origin", "destination"):
        wanted.add(route.origin.traccar_id)
        wanted.add(route.destination.traccar_id)

    linked = set(traccar_client.list_device_geofence_ids(device_id))
    managed = set(GeoFence.objects.values_list("traccar_id", flat=True))

    for geofence_id in wanted - linked:
        traccar_client.link_geofence(device_id, geofence_id)
    for geofence_id in (linked & managed) - wanted:
        traccar_client.unlink_geofence(device_id, geofence_id)


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

    def perform_create(self, serializer):
        # Atomic so a Traccar failure rolls the route back - a route whose
        # zones aren't linked to the van's tracker would silently never fire
        # arrival events.
        try:
            with transaction.atomic():
                route = serializer.save()
                _sync_van_geofences(route.van)
        except traccar_client.TraccarAPIError as e:
            raise ValidationError({"detail": f"Could not link geofences in Traccar: {e}"})

    def perform_update(self, serializer):
        old_van = serializer.instance.van
        try:
            with transaction.atomic():
                route = serializer.save()
                _sync_van_geofences(route.van)
                if old_van.pk != route.van.pk:
                    _sync_van_geofences(old_van)
        except traccar_client.TraccarAPIError as e:
            raise ValidationError({"detail": f"Could not link geofences in Traccar: {e}"})

    def perform_destroy(self, instance):
        van = instance.van
        instance.delete()

        # Best-effort like GeoFenceViewSet.perform_destroy: the route is
        # already gone, a stale link in Traccar is harmless (no route uses
        # it) and the next sync for this van cleans it up.
        try:
            _sync_van_geofences(van)
        except traccar_client.TraccarAPIError:
            logger.warning("Failed to unlink Traccar geofences for van %s after deleting route", van.pk, exc_info=True)


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

