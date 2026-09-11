from accounts.models import Child, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from .models import GeoFence, Route, Van


class RouteCleanTest(TestCase):
    """Route.clean() is a real data-integrity rule (a route must go from a
    school to the gym) enforced on every save() via full_clean() - it had
    zero test coverage despite that.
    """

    def setUp(self):
        self.van = Van.objects.create(name="VAN-1", tracker_imei="IMEI0001")
        self.school = GeoFence.objects.create(
            name="School", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.7, longitude=-80.4, radius=50, traccar_id=201,
        )
        self.gym = GeoFence.objects.create(
            name="Gym", location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.8, longitude=-80.5, radius=50, traccar_id=202,
        )
        self.other_school = GeoFence.objects.create(
            name="Other School", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.9, longitude=-80.6, radius=50, traccar_id=203,
        )

    def test_valid_route_saves(self):
        route = Route(van=self.van, origin=self.school, destination=self.gym)
        route.save()
        self.assertIsNotNone(route.pk)

    def test_non_school_origin_rejected(self):
        with self.assertRaises(ValidationError):
            Route.objects.create(van=self.van, origin=self.gym, destination=self.gym)

    def test_non_gym_destination_rejected(self):
        with self.assertRaises(ValidationError):
            Route.objects.create(van=self.van, origin=self.school, destination=self.other_school)


class FleetPermissionScopingTest(TestCase):
    """Mirrors the same read/write scoping pattern accounts.tests verifies
    for children/schedules, for the fleet app's three ModelViewSets.
    """

    def setUp(self):
        self.parent_a = User.objects.create_user(username="fleet-parent-a", password="pw12345!", role=User.Roles.PARENT)
        self.parent_b = User.objects.create_user(username="fleet-parent-b", password="pw12345!", role=User.Roles.PARENT)
        self.operator = User.objects.create_user(username="fleet-operator", password="pw12345!", role=User.Roles.OPERATOR)

        self.van_a = Van.objects.create(name="VAN-A", tracker_imei="IMEI-A")
        self.van_b = Van.objects.create(name="VAN-B", tracker_imei="IMEI-B")
        school_a = GeoFence.objects.create(name="School A", location_type=GeoFence.LocationTypes.SCHOOL, latitude=25.1, longitude=-80.1, radius=50, traccar_id=301)
        gym_a = GeoFence.objects.create(name="Gym A", location_type=GeoFence.LocationTypes.GINAS_GYM, latitude=25.2, longitude=-80.2, radius=50, traccar_id=302)
        school_b = GeoFence.objects.create(name="School B", location_type=GeoFence.LocationTypes.SCHOOL, latitude=25.3, longitude=-80.3, radius=50, traccar_id=303)
        gym_b = GeoFence.objects.create(name="Gym B", location_type=GeoFence.LocationTypes.GINAS_GYM, latitude=25.4, longitude=-80.4, radius=50, traccar_id=304)

        self.route_a = Route.objects.create(van=self.van_a, origin=school_a, destination=gym_a)
        self.route_b = Route.objects.create(van=self.van_b, origin=school_b, destination=gym_b)

        Child.objects.create(name="Child A", parent=self.parent_a, route=self.route_a)
        Child.objects.create(name="Child B", parent=self.parent_b, route=self.route_b)

        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.parent_a)
        self.client_operator = APIClient()
        self.client_operator.force_authenticate(user=self.operator)

    def test_parent_sees_only_own_route(self):
        response = self.client_a.get("/api/routes/")
        ids = [r["id"] for r in response.json()]
        self.assertIn(self.route_a.id, ids)
        self.assertNotIn(self.route_b.id, ids)

    def test_parent_sees_only_own_van(self):
        response = self.client_a.get("/api/vans/")
        ids = [v["id"] for v in response.json()]
        self.assertIn(self.van_a.id, ids)
        self.assertNotIn(self.van_b.id, ids)

    def test_operator_sees_all_routes_and_vans(self):
        routes = self.client_operator.get("/api/routes/").json()
        vans = self.client_operator.get("/api/vans/").json()
        self.assertEqual({r["id"] for r in routes}, {self.route_a.id, self.route_b.id})
        self.assertEqual({v["id"] for v in vans}, {self.van_a.id, self.van_b.id})

    def test_parent_write_forbidden_even_on_own_route(self):
        response = self.client_a.patch(
            f"/api/routes/{self.route_a.id}/",
            {"van": self.van_b.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_write_allowed(self):
        van_c = Van.objects.create(name="VAN-C", tracker_imei="IMEI-C")
        response = self.client_operator.patch(
            f"/api/routes/{self.route_a.id}/",
            {"van": van_c.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
