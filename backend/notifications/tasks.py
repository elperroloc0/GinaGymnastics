import os

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from twilio.rest import Client


@shared_task
def debug_notification_task():
    print("Task done")

@shared_task(autoretry_for=(Exception,), retry_backoff=True,retry_kwargs={"max_retries":5})
def debug_sms(phone:str, text:str) -> None:
    client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])

    client.messages.create(
        to=phone,
        from_=os.environ["TWILIO_PHONE_NUMBER"],
        body=text,
    )


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def send_arrival_email(to_email: str, message: str) -> None:
    """Email counterpart to debug_sms - same retry pattern, used when a
    parent's notify_channel is EMAIL (notifications.services.notify_parent).
    HTML with a plain-text fallback, same EmailMultiAlternatives pattern as
    Concierge_app's post_call_summary alerts - no third-party ESP library,
    just Django's own SMTP backend (see EMAIL_* in backend/settings.py)."""
    subject = "Gina's Gymnastics: Ride Update"
    html_body = render_to_string("emails/arrival.html", {"message": message})
    email = EmailMultiAlternatives(subject, message, settings.DEFAULT_FROM_EMAIL, [to_email])
    email.attach_alternative(html_body, "text/html")
    email.send()
