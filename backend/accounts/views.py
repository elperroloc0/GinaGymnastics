from accounts.permission import IsOperatorOrReadOnly
from django.shortcuts import render
from rest_framework import permissions, viewsets
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Child, ChildSchedule, User
from .serializers import (
    ChildScheduleSerializer,
    ChildSerializer,
    RoleTokenObtainPairSerializer,
)

# Create your views here.

class ChildViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:#type:ignore
            return Child.objects.all()

        return Child.objects.filter(parent=user)

    serializer_class = ChildSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrReadOnly]


class ChildScheduleViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser: #type: ignore
            return ChildSchedule.objects.all()

        return ChildSchedule.objects.filter(child__parent=user)

    serializer_class = ChildScheduleSerializer
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrReadOnly]


class RoleTokenObtainPairView(TokenObtainPairView):
    serializer_class = RoleTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
