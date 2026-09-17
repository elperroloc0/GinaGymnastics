from accounts.models import Child, User

from .tasks import debug_sms, send_arrival_email


def notify_parent(child: Child, message: str) -> None:
    parent = child.parent
    if parent.notify_channel == User.NotifyChannel.EMAIL and parent.email:
        send_arrival_email.delay_on_commit(parent.email, message)  # type: ignore
        return

    # Falls through here for SMS (the default), and also for a parent who
    # chose EMAIL but has none on file - notify_channel is a preference,
    # not a guarantee, and silently notifying no one is worse than texting.
    if not parent.phone_number:
        return
    debug_sms.delay_on_commit(str(parent.phone_number), message)  # type: ignore

