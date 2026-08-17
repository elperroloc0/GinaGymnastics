from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("routes", views.RouteViewSet, basename="routes")
router.register("geofences", views.GeoFenceViewSet, basename="geofences")
router.register("vans", views.VanViewSet, basename="vans")

urlpatterns = router.urls
