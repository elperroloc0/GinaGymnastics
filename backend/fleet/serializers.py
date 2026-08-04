from rest_framework import serializers

from .models import GeoFence, Route


class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = [ "id", "van", "origin", "destination"]


class GeoFenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFence
        fields = [ "id", "name", "location_type", "latitude", "longitude", "radius", "traccar_id", "is_active"]
