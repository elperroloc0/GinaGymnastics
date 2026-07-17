from rest_framework import serializers

from .models import ArrivalEvent


class ArrivalEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArrivalEvent
        fields = ["id", "van", "geo_fence", "arrival_type", "time"]

