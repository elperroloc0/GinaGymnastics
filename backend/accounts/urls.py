from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("children", views.ChildViewSet, basename="child")

urlpatterns = router.urls

