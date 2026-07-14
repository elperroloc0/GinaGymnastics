from django.contrib import admin

from .models import GeoFence, Route, Van

# Register your models here.
admin.site.register(Van)
admin.site.register(GeoFence)
admin.site.register(Route)
