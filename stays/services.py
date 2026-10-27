"""Booking rules: pricing, availability, holds, payments, reporting helpers."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Case, DecimalField, F, Sum, When
from django.utils import timezone

from .models import ZERO, Apartment, Booking, Guest, MaintenanceTicket, Payment


class BookingError(Exception):
    pass


def _q(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------- pricing ----------

def rules_for(apartment, start, end):
    """Active price rules touching [start, end) for this apartment, in the order they stack."""
    from django.db.models import Q

    from .models import RateRule

    return list(
        RateRule.objects.filter(is_active=True, start__lt=end, end__gte=start)
        .filter(Q(apartments=None) | Q(apartments=apartment)).distinct().order_by("priority", "start", "created_at")
    )


def nightly_prices(apartment, check_in, check_out, stay_nights=None, rules=None):
    """[(date, price, [(rule, delta), ...]), ...] — one entry per night."""
    stay_nights = stay_nights or (check_out - check_in).days
    if rules is None:
        rules = rules_for(apartment, check_in, check_out)
    nights = []
    day = check_in
    while day < check_out:
        price = apartment.daily_rate
        applied = []
        for rule in rules:
            if rule.covers(day, stay_nights):
                new_price = max(rule.apply(price), ZERO)
                applied.append((rule, new_price - price))
                price = new_price
        nights.append((day, _q(price), applied))
        day += timedelta(days=1)
    return nights


def quote(apartment, check_in, check_out, discount=ZERO):
    nights = (check_out - check_in).days
    if nights <= 0:
        raise BookingError("Check-out must be after check-in.")
    daily = apartment.daily_rate
    monthly = apartment.monthly_rate
    per_night = nightly_prices(apartment, check_in, check_out, nights)
    nightly_total = sum((p for _, p, _ in per_night), ZERO)
    base_subtotal = daily * nights

    adjustments = {}
    for _, _, applied in per_night:
        for rule, delta in applied:
            adjustments[rule.name] = adjustments.get(rule.name, ZERO) + delta

    plan = "daily"
    if monthly and nights >= 30:
        months, rest = divmod(nights, 30)
        rest_total = sum((p for _, p, _ in per_night[nights - rest:]), ZERO) if rest else ZERO
        subtotal = monthly * months + min(rest_total, monthly)
        plan = "monthly"
        adjustments = {}  # monthly contracts ignore nightly rules
    else:
        subtotal = nightly_total
    cleaning = apartment.cleaning_fee or ZERO
    total = max(_q(subtotal + cleaning - (discount or ZERO)), ZERO)
    deposit = _q(total * Decimal(apartment.deposit_percent) / Decimal(100))
    return {
        "nights": nights,
        "rate_plan": plan,
        "nightly_rate": daily,
        "average_nightly": _q(nightly_total / nights),
        "base_subtotal": _q(base_subtotal),
        "adjustments": [{"name": n, "amount": _q(a)} for n, a in adjustments.items() if _q(a) != ZERO],
        "subtotal": _q(subtotal),
        "cleaning_fee": _q(cleaning),
        "discount": _q(discount or ZERO),
        "total": total,
        "deposit": deposit,
        "deposit_percent": apartment.deposit_percent,
        "savings": _q(max(nightly_total - subtotal, ZERO)),
    }


def quote_json(q):
    def conv(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, list):
            return [{k: conv(x) for k, x in item.items()} for item in v]
        return v

    return {k: conv(v) for k, v in q.items()}


# ---------- availability ----------

def booking_conflicts(apartment, check_in, check_out, exclude_id=None):
    qs = Booking.objects.filter(
        apartment=apartment, status__in=Booking.ACTIVE, check_in__lt=check_out, check_out__gt=check_in
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs


def maintenance_blocks(apartment, check_in, check_out):
    return MaintenanceTicket.objects.filter(
        apartment=apartment,
        status__in=[MaintenanceTicket.OPEN, MaintenanceTicket.IN_PROGRESS],
        block_from__isnull=False,
        block_until__isnull=False,
        block_from__lt=check_out,
        block_until__gte=check_in,
    )


def is_available(apartment, check_in, check_out, exclude_id=None):
    if not apartment.is_bookable:
        return False
    return not booking_conflicts(apartment, check_in, check_out, exclude_id).exists() and not maintenance_blocks(
        apartment, check_in, check_out
    ).exists()


def unavailable_ranges(apartment, start, end):
    """Occupied *nights* as inclusive {from, to} ranges — for the calendar."""
    ranges = []
    for ci, co in Booking.objects.filter(
        apartment=apartment, status__in=Booking.ACTIVE, check_out__gt=start, check_in__lt=end
    ).values_list("check_in", "check_out"):
        ranges.append({"from": ci.isoformat(), "to": (co - timedelta(days=1)).isoformat()})
    for bf, bu in MaintenanceTicket.objects.filter(
        apartment=apartment,
        status__in=[MaintenanceTicket.OPEN, MaintenanceTicket.IN_PROGRESS],
        block_from__isnull=False,
        block_until__isnull=False,
        block_until__gte=start,
        block_from__lt=end,
    ).values_list("block_from", "block_until"):
        ranges.append({"from": bf.isoformat(), "to": bu.isoformat()})
    return sorted(ranges, key=lambda r: r["from"])


def occupied_apartment_ids(day):
    busy = set(
        Booking.objects.filter(status__in=Booking.ACTIVE, check_in__lte=day, check_out__gt=day).values_list(
            "apartment_id", flat=True
        )
    )
    busy |= set(
        MaintenanceTicket.objects.filter(
            status__in=[MaintenanceTicket.OPEN, MaintenanceTicket.IN_PROGRESS],
            block_from__lte=day,
            block_until__gte=day,
        ).values_list("apartment_id", flat=True)
    )
    return busy


# ---------- guests & bookings ----------

def get_or_create_guest(full_name, phone, email="", whatsapp="", country=""):
    from .whatsapp import normalize

    norm = normalize(phone)
    guest = None
    for g in Guest.objects.filter(phone__icontains=norm[-7:] if norm else phone):
        if normalize(g.phone) == norm:
            guest = g
            break
    if guest is None:
        guest = Guest(phone=phone)
    guest.full_name = full_name or guest.full_name
    if email:
        guest.email = email
    if whatsapp:
        guest.whatsapp = whatsapp
    if country:
        guest.country = country
    guest.save()
    return guest


def create_booking(
    *, apartment, guest, check_in, check_out, adults=1, children=0, payment_option=Booking.OPTION_DEPOSIT,
    source="website", special_requests="", created_by=None, allow_past=False, status=Booking.PENDING, discount=ZERO,
):
    today = timezone.localdate()
    if check_out <= check_in:
        raise BookingError("Check-out must be after check-in.")
    if not allow_past and check_in < today:
        raise BookingError("Check-in can't be in the past.")
    if adults + children > apartment.capacity:
        raise BookingError(f"Apt {apartment.number} sleeps up to {apartment.capacity} guests.")
    if adults < 1:
        raise BookingError("At least one adult is required.")

    with transaction.atomic():
        apt = Apartment.objects.select_for_update().get(pk=apartment.pk)
        if not is_available(apt, check_in, check_out):
            raise BookingError("Those dates were just taken or the unit is closed. Please choose other dates.")
        q = quote(apt, check_in, check_out, discount)
        booking = Booking(
            apartment=apt, guest=guest, check_in=check_in, check_out=check_out, adults=adults, children=children,
            payment_option=payment_option, source=source, special_requests=special_requests, created_by=created_by,
            rate_plan=q["rate_plan"], subtotal=q["subtotal"], cleaning_fee=q["cleaning_fee"], discount=q["discount"],
            total_amount=q["total"], deposit_amount=q["deposit"], status=status,
        )
        if status == Booking.PENDING:
            booking.hold_expires_at = timezone.now() + timedelta(hours=settings.KUNDA["hold_hours"])
        try:
            with transaction.atomic():
                booking.save()
        except IntegrityError:
            # Exclusion constraint fired: a concurrent request won the same dates.
            raise BookingError("Those dates were just taken. Please choose other dates.")
    return booking


def reprice_booking(booking, check_in, check_out, discount=None):
    if check_out <= check_in:
        raise BookingError("Check-out must be after check-in.")
    discount = booking.discount if discount is None else discount
    with transaction.atomic():
        Apartment.objects.select_for_update().get(pk=booking.apartment_id)
        if booking.is_active and not is_available(booking.apartment, check_in, check_out, exclude_id=booking.pk):
            raise BookingError("The new dates overlap another booking or a maintenance block.")
        q = quote(booking.apartment, check_in, check_out, discount)
        booking.check_in, booking.check_out = check_in, check_out
        booking.rate_plan, booking.subtotal = q["rate_plan"], q["subtotal"]
        booking.cleaning_fee, booking.discount = q["cleaning_fee"], q["discount"]
        booking.total_amount, booking.deposit_amount = q["total"], q["deposit"]
        try:
            with transaction.atomic():
                booking.save()
        except IntegrityError:
            raise BookingError("The new dates overlap another booking.")
    return booking


# ---------- payments ----------

def confirm_payment(payment, user=None, notify=True):
    from . import messages_text, whatsapp

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == Payment.CONFIRMED:
            return payment
        payment.status = Payment.CONFIRMED
        payment.paid_at = payment.paid_at or timezone.now()
        payment.receipt_number = Payment.next_receipt_number()
        payment.received_by = user
        payment.save()
        booking = Booking.objects.prefetch_related("payments").get(pk=payment.booking_id)
        newly_confirmed = False
        if booking.status == Booking.PENDING and booking.amount_paid >= booking.deposit_required:
            booking.status = Booking.CONFIRMED
            booking.hold_expires_at = None
            booking.save(update_fields=["status", "hold_expires_at", "updated_at"])
            newly_confirmed = True
    if notify:
        whatsapp.send(booking.guest.wa_number, messages_text.payment_received(payment), booking=booking, kind="payment")
        if newly_confirmed:
            whatsapp.send(booking.guest.wa_number, messages_text.confirmation(booking), booking=booking, kind="confirmation")
    return payment


def signed_amount():
    return Case(
        When(kind=Payment.REFUND, then=-F("amount")),
        default=F("amount"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def revenue_between(start, end):
    """Confirmed money in [start, end) by paid date (refunds subtracted)."""
    return (
        Payment.objects.filter(status=Payment.CONFIRMED, paid_at__date__gte=start, paid_at__date__lt=end).aggregate(
            s=Sum(signed_amount())
        )["s"]
        or ZERO
    )


# ---------- room charges (the guest's tab) ----------

VOID_WINDOW_MINUTES = 30


def post_charges(booking, lines, user=None, source="desk", note=""):
    """Add lines to a guest's tab in one transaction.

    lines: [{"item": ExtraItem | None, "quantity": int, "description": str, "unit_price": Decimal, "category": str}]
    Stock is taken under a row lock so two staff can't sell the last bottle twice.
    """
    from django.db.models import F

    from .models import ExtraItem, RoomCharge

    if not booking.accepts_charges:
        raise BookingError("This booking can't take room charges (it isn't in house or recently checked out).")
    lines = [ln for ln in lines if ln.get("quantity", 0) > 0]
    if not lines:
        raise BookingError("Add at least one item.")
    today = timezone.localdate()
    created = []
    with transaction.atomic():
        for ln in lines:
            item = ln.get("item")
            qty = int(ln["quantity"])
            if item is not None:
                item = ExtraItem.objects.select_for_update().get(pk=item.pk)
                if item.stock is not None:
                    if item.stock < qty:
                        raise BookingError(f"Only {item.stock} {item.name} left in stock.")
                    ExtraItem.objects.filter(pk=item.pk).update(stock=F("stock") - qty)
                price = ln.get("unit_price") if ln.get("unit_price") is not None else item.price
                desc, cat = item.name, item.category
            else:
                price = ln["unit_price"]
                desc, cat = ln["description"].strip()[:120], ln.get("category") or "other"
                if not desc:
                    raise BookingError("A custom charge needs a description.")
            if price is None or price < 0:
                raise BookingError("Prices can't be negative. Use a discount on the booking instead.")
            created.append(RoomCharge.objects.create(
                booking=booking, item=item, description=desc, category=cat, quantity=qty, unit_price=_q(price),
                amount=_q(price * qty), charged_on=today, source=source, note=(ln.get("note") or note or "")[:200], posted_by=user,
            ))
        booking.recompute_extras()
    return created


def can_void(charge, user):
    from dashboard.roles import can

    if charge.is_void:
        return False
    if can(user, "finance") or user.is_superuser or can(user, "staff"):
        return True
    recent = timezone.now() - charge.created_at <= timedelta(minutes=VOID_WINDOW_MINUTES)
    return charge.posted_by_id == user.id and recent


def void_charge(charge, user, reason):
    """Cancel a tab line (wrong room, wrong item, comped). Restores stock. Kept on record."""
    from django.db.models import F

    from .models import ExtraItem

    reason = (reason or "").strip()
    if not reason:
        raise BookingError("Say why you're voiding this charge.")
    if not can_void(charge, user):
        raise BookingError(f"Only the person who posted it (within {VOID_WINDOW_MINUTES} minutes), finance or a manager can void a charge.")
    with transaction.atomic():
        charge.voided_at, charge.voided_by, charge.void_reason = timezone.now(), user, reason[:200]
        charge.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
        if charge.item_id:
            ExtraItem.objects.filter(pk=charge.item_id, stock__isnull=False).update(stock=F("stock") + charge.quantity)
        charge.booking.recompute_extras()
    return charge


def tab_summary(booking):
    """Live tab lines grouped by day, plus category totals — for the bill, the guest page and WhatsApp."""
    charges = list(booking.charges.filter(voided_at__isnull=True).select_related("posted_by"))
    days, by_cat = [], {}
    for c in charges:
        if not days or days[-1]["day"] != c.charged_on:
            days.append({"day": c.charged_on, "lines": [], "total": ZERO})
        days[-1]["lines"].append(c)
        days[-1]["total"] += c.amount
        # Guest-facing view: the same item at the same price on the same day reads as one line ("6 × Coffee")
        key = (c.description, c.unit_price)
        grouped = days[-1].setdefault("_g", {})
        if key in grouped:
            grouped[key]["quantity"] += c.quantity
            grouped[key]["amount"] += c.amount
        else:
            grouped[key] = {"description": c.description, "quantity": c.quantity, "unit_price": c.unit_price, "amount": c.amount, "icon": c.icon}
        by_cat[c.get_category_display()] = by_cat.get(c.get_category_display(), ZERO) + c.amount
    for d in days:
        d["grouped"] = list(d.pop("_g", {}).values())
    return {"charges": charges, "days": days, "by_category": sorted(by_cat.items(), key=lambda kv: -kv[1]), "total": sum((c.amount for c in charges), ZERO)}
