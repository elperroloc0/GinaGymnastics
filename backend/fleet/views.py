from django.shortcuts import render
from rest_framework import generics

from .models import Route
from .serializers import RouteSerializer

# Create your views here.


class RouteList(generics.ListAPIView):
    queryset = Route.objects.all()
    serializer_class = RouteSerializer



