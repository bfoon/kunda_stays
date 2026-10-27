"""Plain-text templates for guest messages (WhatsApp-friendly, *bold* supported)."""
from django.conf import settings


def _money(v):
    v = float(v or 0)
    s = f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"
    return f"{settings.KUNDA['currency_symbol']} {s}"


def _url(booking):
    return settings.KUNDA["site_url"] + booking.get_absolute_url()


def _stay(b):
    return f"Apt {b.apartment.number} ({b.apartment.name})\n{b.check_in:%a %d %b} → {b.check_out:%a %d %b %Y} · {b.nights} night{'s' if b.nights != 1 else ''}"


def booking_received(b):
    k = settings.KUNDA
    return (
        f"Hello {b.guest.first_name}, thank you for choosing {k['name']}! 🌴\n\n"
        f"*Booking {b.reference}*\n{_stay(b)}\n\n"
        f"Total: {_money(b.total_amount)}\n"
        f"To confirm, pay {_money(b.deposit_required)} within {k['hold_hours']} hours.\n"
        f"Payment options and your booking page:\n{_url(b)}"
    )


def confirmation(b):
    k = settings.KUNDA
    return (
        f"✅ *Booking confirmed — {b.reference}*\n\n{_stay(b)}\n\n"
        f"Paid: {_money(b.amount_paid)} · Balance: {_money(b.balance)}\n"
        f"Check-in from {k['checkin_time']}, check-out by {k['checkout_time']}.\n"
        f"📍 {k['address']}\nhttps://maps.google.com/?q={k['lat']},{k['lng']}\n\n"
        f"Your booking: {_url(b)}"
    )


def payment_received(p):
    b = p.booking
    return (
        f"🧾 Payment received — thank you, {b.guest.first_name}.\n\n"
        f"Receipt {p.receipt_number}: {_money(p.amount)} via {p.get_method_display()}\n"
        f"Booking {b.reference} · Balance now {_money(b.balance)}\n\n"
        f"Download your receipt: {_url(b)}"
    )


def payment_reminder(b):
    return (
        f"Hello {b.guest.first_name}, a friendly reminder about booking *{b.reference}*.\n\n"
        f"{_stay(b)}\n\nOutstanding balance: *{_money(b.balance)}*\n"
        f"Pay by Wave, Afrimoney, QMoney, bank transfer or at reception:\n{_url(b)}"
    )


def checkin_reminder(b):
    k = settings.KUNDA
    return (
        f"See you tomorrow, {b.guest.first_name}! 🗝️\n\n{_stay(b)}\n"
        f"Check-in from {k['checkin_time']}.\n"
        f"📍 {k['address']}\nhttps://maps.google.com/?q={k['lat']},{k['lng']}\n"
        f"Need an airport pickup? Just reply to this message."
    )


def hold_released(b):
    return (
        f"Hello {b.guest.first_name}, we didn't receive a deposit for booking {b.reference}, "
        f"so the dates have been released. Reply here if you'd still like to stay — we'll help you rebook."
    )
