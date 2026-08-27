from accounts.models import Child

from .tasks import debug_sms


def notify_parent(child: Child, message:str) -> None:
            parent = child.parent
            if not parent.phone_number:
                return
            debug_sms.delay_on_commit(str(parent.phone_number), message) # type: ignore

