from unittest.mock import ANY, patch

from django.test import TestCase
from notifications.tasks import debug_sms

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

