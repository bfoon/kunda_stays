from datetime import timedelta

from celery import shared_task
from django.utils import timezone


@shared_task
def release_expired_holds():
    """Cancel website bookings whose deposit hold ran out, so the dates reopen."""
    from . import messages_text, whatsapp
    from .models import Booking

    released = 0
    qs = Booking.objects.filter(status=Booking.PENDING, hold_expires_at__lt=timezone.now()).prefetch_related("payments")
    for b in qs:
        if b.amount_paid > 0 or b.pending_payments:
            continue  # money is on the way — staff decide
        b.status = Booking.CANCELLED
        b.cancelled_at = timezone.now()
        b.internal_notes = (b.internal_notes + "\nHold expired automatically.").strip()
        b.save(update_fields=["status", "cancelled_at", "internal_notes", "updated_at"])
        whatsapp.send(b.guest.wa_number, messages_text.hold_released(b), booking=b, kind="released")
        released += 1
    return released


@shared_task
def send_payment_reminders(days_ahead=3):
    """Remind guests with a balance whose arrival is within `days_ahead` days."""
    from . import messages_text, whatsapp
    from .models import Booking

    today = timezone.localdate()
    sent = 0
    qs = Booking.objects.filter(
        status__in=[Booking.CONFIRMED, Booking.CHECKED_IN], check_in__lte=today + timedelta(days=days_ahead)
    ).select_related("guest", "apartment").prefetch_related("payments", "messages")
    for b in qs:
        if b.balance <= 0:
            continue
        if any(m.kind == "reminder" and m.created_at.date() == today for m in b.messages.all()):
            continue
        whatsapp.send(b.guest.wa_number, messages_text.payment_reminder(b), booking=b, kind="reminder")
        sent += 1
    return sent


@shared_task
def send_checkin_reminders():
    from . import messages_text, whatsapp
    from .models import Booking

    tomorrow = timezone.localdate() + timedelta(days=1)
    sent = 0
    for b in Booking.objects.filter(status=Booking.CONFIRMED, check_in=tomorrow).select_related("guest", "apartment"):
        whatsapp.send(b.guest.wa_number, messages_text.checkin_reminder(b), booking=b, kind="checkin")
        sent += 1
    return sent
