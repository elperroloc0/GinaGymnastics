from unittest.mock import ANY, patch

from accounts.models import Child, User
from django.core import mail
from django.test import TestCase
from fleet.models import GeoFence, Route, Van
from notifications.services import notify_parent
from notifications.tasks import debug_sms, send_arrival_email

# Create your tests here.

class TwilioClientTest(TestCase):

    @patch("notifications.tasks.Client")
    def test_twilio_client(self, mock_client):
        debug_sms("+12345678901", "test text")
        mock_client.return_value.messages.create.assert_called_once_with(
            to="+12345678901",
            from_=ANY,
            body="test text",
        )


class SendArrivalEmailTest(TestCase):
    """The email counterpart to debug_sms - Django's test runner swaps
    EMAIL_BACKEND for locmem automatically, so a real send lands in
    mail.outbox instead of hitting SMTP."""

    def test_sends_html_and_plaintext_alternatives(self):
        send_arrival_email("parent@example.com", "Van has arrived to the school.")

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["parent@example.com"])
        self.assertIn("Van has arrived to the school.", sent.body)

        self.assertEqual(len(sent.alternatives), 1)
        html_body, mimetype = sent.alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("Van has arrived to the school.", html_body)


@patch("notifications.services.send_arrival_email")
@patch("notifications.services.debug_sms")
class NotifyParentTest(TestCase):
    """notify_parent()'s channel branching - SMS by default, EMAIL when
    chosen and an address is on file, SMS as the fallback when EMAIL is
    chosen but there's no address to send it to."""

    def setUp(self):
        self.van = Van.objects.create(name="NP-VAN", tracker_imei="NP-IMEI")
        school = GeoFence.objects.create(
            name="NP School", location_type=GeoFence.LocationTypes.SCHOOL,
            latitude=25.5, longitude=-80.5, radius=50, traccar_id=901,
        )
        gym = GeoFence.objects.create(
            name="NP Gym", location_type=GeoFence.LocationTypes.GINAS_GYM,
            latitude=25.6, longitude=-80.6, radius=50, traccar_id=902,
        )
        self.route = Route.objects.create(van=self.van, origin=school, destination=gym)

    def test_sms_is_the_default_channel(self, debug_sms, send_arrival_email):
        parent = User.objects.create_user(username="np-parent-1", role=User.Roles.PARENT, phone_number="+13055557777")
        child = Child.objects.create(name="Kid One", parent=parent, route=self.route)

        notify_parent(child, "test message")

        debug_sms.delay_on_commit.assert_called_once_with("+13055557777", "test message")
        send_arrival_email.delay_on_commit.assert_not_called()

    def test_email_channel_with_an_address_sends_email_not_sms(self, debug_sms, send_arrival_email):
        parent = User.objects.create_user(
            username="np-parent-2", role=User.Roles.PARENT, phone_number="+13055558888",
            email="parent2@example.com", notify_channel=User.NotifyChannel.EMAIL,
        )
        child = Child.objects.create(name="Kid Two", parent=parent, route=self.route)

        notify_parent(child, "test message")

        send_arrival_email.delay_on_commit.assert_called_once_with("parent2@example.com", "test message")
        debug_sms.delay_on_commit.assert_not_called()

    def test_email_channel_without_an_address_falls_back_to_sms(self, debug_sms, send_arrival_email):
        parent = User.objects.create_user(
            username="np-parent-3", role=User.Roles.PARENT, phone_number="+13055559999",
            notify_channel=User.NotifyChannel.EMAIL,  # chosen, but no email on file
        )
        child = Child.objects.create(name="Kid Three", parent=parent, route=self.route)

        notify_parent(child, "test message")

        debug_sms.delay_on_commit.assert_called_once_with("+13055559999", "test message")
        send_arrival_email.delay_on_commit.assert_not_called()

    def test_sms_channel_with_no_phone_notifies_no_one(self, debug_sms, send_arrival_email):
        parent = User.objects.create_user(username="np-parent-4", role=User.Roles.PARENT)
        child = Child.objects.create(name="Kid Four", parent=parent, route=self.route)

        notify_parent(child, "test message")

        debug_sms.delay_on_commit.assert_not_called()
        send_arrival_email.delay_on_commit.assert_not_called()
