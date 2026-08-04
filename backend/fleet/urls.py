from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("routes", views.RouteViewSet)
router.register("geofences", views.GeoFenceViewSet)

urlpatterns = router.urls
