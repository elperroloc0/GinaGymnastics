import os

from celery import shared_task
from twilio.rest import Client


@shared_task
def debug_notification_task():
    print("Task done")

@shared_task
def debug_sms(phone, text):
    client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])

    client.messages.create(
        to=phone,
        from_=os.environ["TWILIO_PHONE_NUMBER"],
        body=text,
    )
