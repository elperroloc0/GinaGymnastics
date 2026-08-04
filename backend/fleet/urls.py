from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("routes", views.RouteViewSet)
router.register("geofences", views.GeoFenceViewSet)
router.register("vans", views.VanViewSet)

urlpatterns = router.urls
