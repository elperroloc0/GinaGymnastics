from rest_framework import serializers

from .models import GeoFence, Route, Van


class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = [ "id", "van", "origin", "destination"]


class GeoFenceSerializer(serializers.ModelSerializer):
    # Server-assigned via traccar_client.create_geofence() - operators never
    # submit this themselves, see GeoFenceViewSet.perform_create.
    traccar_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = GeoFence
        fields = [ "id", "name", "location_type", "latitude", "longitude", "radius", "traccar_id", "is_active"]

class VanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Van
        fields = ["id", "name", "tracker_imei"]
