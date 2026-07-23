import os
from unittest.mock import patch

from accounts.models import Child, User
from django.test import TestCase
from fleet.models import GeoFence, Van
from rest_framework.test import APIClient
from tracking.models import ArrivalEvent


# Create your tests here.
class WebhookTest(TestCase):
    def setUp(self):
        self.van = Van.objects.create(name="TEST-VAN", tracker_imei="IMEI12345")
        self.school = GeoFence.objects.create(name="Test School", latitude=25.72, longitude=-80.43, radius=40, traccar_id=3,)

    def test_no_secret_rejected(self):
        response = self.client.post(
            "/webhooks/traccar/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_event_created(self):
        secret = os.environ["TRACCAR_WEBHOOK_SECRET"]
        response = self.client.post(
            "/webhooks/traccar/",
            data={"event": {"id": 1, "deviceId": 1, "type": "geofenceEnter", "eventTime": "2026-07-15T18:30:17.386+00:00", "positionId": 9, "geofenceId": 3}, "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI12345"}, "geofence": {"id": 3, "name": "Test School"}},
            content_type="application/json",
            headers={"X-Webhook-Secret": secret}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ArrivalEvent.objects.count(), 1)


    def test_event_with_no_secret(self):
        response = self.client.post(
            "/webhooks/traccar/",
            data={"event": {"id": 1, "deviceId": 1, "type": "geofenceEnter", "eventTime": "2026-07-15T18:30:17.386+00:00", "positionId": 9, "geofenceId": 3}, "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI123"}, "geofence": {"id": 3, "name": "Test School"}},
            content_type="application/json",
            headers={"X-Webhook-Secret": ''}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ArrivalEvent.objects.count(), 0)


    def test_wrong_secret_rejected(self):
        response = self.client.post(
            "/webhooks/traccar/",
            data={"event": {"id": 1, "deviceId": 1, "type": "geofenceEnter", "eventTime": "2026-07-15T18:30:17.386+00:00", "positionId": 9, "geofenceId": 3}, "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI123"}, "geofence": {"id": 3, "name": "Test School"}},
            content_type="application/json",
            headers={"X-Webhook-Secret": 'wrong-key'}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ArrivalEvent.objects.count(), 0)

    def test_foreign_event_ignored(self):
        secret = os.environ["TRACCAR_WEBHOOK_SECRET"]
        response = self.client.post(
            "/webhooks/traccar/",
            data={"event": {"id": 1, "deviceId": 1, "type": "deviceStopped", "eventTime": "2026-07-15T18:30:17.386+00:00", "positionId": 9, "geofenceId": 3}, "device": {"id": 1, "name": "tracker-1", "uniqueId": "IMEI123"}, "geofence": {"id": 3, "name": "Test School"}},
            content_type="application/json",
            headers={"X-Webhook-Secret": secret}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ArrivalEvent.objects.count(), 0)


class EventListPermissionTest(TestCase):
    def setUp(self):
        self.van = Van.objects.create(name="TEST-VAN", tracker_imei="IMEI12345")
        self.school_1 = GeoFence.objects.create(name="Test School 1", latitude=25.72, longitude=-80.43, radius=40, traccar_id=1,)
        self.school_2 = GeoFence.objects.create(name="Test School 2", latitude=26.72, longitude=-81.43, radius=40, traccar_id=2,)

        self.admin = User.objects.create_superuser(username="admin1", email='', password="unsecure12345")
        self.parent = User.objects.create(username="parent", password="unsecure12345", role=User.Roles.PARENT)
        self.child = Child.objects.create(name="child 1", parent=self.parent, school=self.school_1,)

        ArrivalEvent.objects.create(van=self.van, geo_fence=self.school_1, arrival_type=ArrivalEvent.ArrivalType.ENTER, time="2012-09-04 06:00:00.000000+0800")

        ArrivalEvent.objects.create(van=self.van, geo_fence=self.school_2, arrival_type=ArrivalEvent.ArrivalType.ENTER, time="2012-09-04 07:00:00.000000+0800")

    def test_anonymous_rejected(self):
        response = self.client.get("/api/events/")
        self.assertEqual(response.status_code, 401)

    def test_parent_sees_only_school(self):
        client = APIClient()
        client.force_authenticate(user=self.parent)
        response = client.get("/api/events/")
        data = response.json()
        self.assertEqual(len(data), 1)

    def test_admin_sees_all_events(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get("/api/events/")
        data = response.json()
        self.assertEqual(len(data), 2)


class TaskTest(TestCase):
    def setUp(self):
        self.secret = os.environ["TRACCAR_WEBHOOK_SECRET"]

        self.van = Van.objects.create(name="TEST-VAN", tracker_imei="IMEI12345")
        self.school = GeoFence.objects.create(name="Test School", latitude=25.72, longitude=-80.43, radius=40, traccar_id=1,)

        self.parent = User.objects.create(username="parent", password="unsecure12345", role=User.Roles.PARENT, phone_number= "+17869167736")
        self.child = Child.objects.create(name="child 1", parent=self.parent, school=self.school,)

        ArrivalEvent.objects.create(van=self.van, geo_fence=self.school, arrival_type=ArrivalEvent.ArrivalType.ENTER, time="2012-09-04 06:00:00.000000+0800")

    @patch("tracking.views.debug_sms")
    def test_task_is_created(self, mock_task):
        response = self.client.post(
            "/webhooks/traccar/",
            data={"event": {"id": 1, "deviceId": 1, "type": "geofenceEnter", "eventTime": "2026-07-15T18:30:17.386+00:00", "positionId": 9, "geofenceId": 1}, "device": {"id": 1, "name": "TEST-VAN", "uniqueId": "IMEI12345"}, "geofence": {"id": 1, "name": "Test School"}},
            content_type="application/json",
            headers={"X-Webhook-Secret": self.secret}
        )
        mock_task.delay_on_commit.assert_called_once()

