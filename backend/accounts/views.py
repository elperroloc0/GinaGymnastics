from django.shortcuts import render
from rest_framework import viewsets

from .models import Child
from .serializers import ChildSerializer

# Create your views here.

class ChildViewSet(viewsets.ModelViewSet):
    queryset = Child.objects.all()
    serializer_class = ChildSerializer
