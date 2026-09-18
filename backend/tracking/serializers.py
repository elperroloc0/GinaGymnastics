from rest_framework import serializers

from .models import ArrivalEvent, Position


class ArrivalEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArrivalEvent
        fields = ["id", "van", "geo_fence", "arrival_type", "time"]



class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ["van", "latitude", "longitude", "device_time", "speed", "attributes"]
