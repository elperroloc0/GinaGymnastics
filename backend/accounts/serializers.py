from rest_framework import serializers

from .models import Child, ChildSchedule


class ChildScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChildSchedule
        fields = ["id", "child", "weekday", "pickup_hour"]


class ChildSerializer(serializers.ModelSerializer):
    schedule = ChildScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = Child
        fields = ["id", "name", "parent", "route", "schedule"]
