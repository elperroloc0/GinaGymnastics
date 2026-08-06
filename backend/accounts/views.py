from django.shortcuts import render
from rest_framework import viewsets

from .models import Child, User
from .serializers import ChildSerializer

# Create your views here.

class ChildViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Roles.OPERATOR or user.is_superuser:#type:ignore
            return Child.objects.all()

        return Child.objects.filter(parent=user)

    serializer_class = ChildSerializer
