import csv
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from stays.models import (ZERO, Amenity, Apartment, ApartmentPhoto, Booking, ContactInquiry, Guest,
                          MaintenanceTicket, MessageLog, Payment)
from stays.utils import parse_date, parse_decimal, parse_int


class StaffMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Signed-in staff whose role includes `section` (a name or a tuple of names)."""
    section = "front"

    def test_func(self):
        from .roles import can

        user = self.request.user
        wanted = self.section if isinstance(self.section, (tuple, list)) else (self.section,)
        return user.is_staff and any(can(user, s) for s in wanted)

    def handle_no_permission(self):
        from .roles import home_url_name, user_role

        user = self.request.user
        if not user.is_authenticated:
            return super().handle_no_permission()
        if not user.is_staff:
            return render(self.request, "dashboard/denied.html", {"not_staff": True}, status=403)
        if self.section == "today":  # the portal's front door: send people to their own start page
            return redirect(home_url_name(user))
        return render(self.request, "dashboard/denied.html", {"role": user_role(user), "home": home_url_name(user)}, status=403)


def _month_add(d, n):
    m = d.month - 1 + n
    return d.replace(year=d.year + m // 12, month=m % 12 + 1, day=1)


def _overlap(ci, co, start, end):
    return max(0, (min(co, end) - max(ci, start)).days)


class HomeView(StaffMixin, View):
    section = "today"

    def get(self, request):
        from stays.services import revenue_between

        today = timezone.localdate()
        units = Apartment.objects.exclude(status=Apartment.INACTIVE).count()
        occupied = Booking.objects.filter(
            status__in=[Booking.CONFIRMED, Booking.CHECKED_IN], check_in__lte=today, check_out__gt=today
        ).count()
        month_start = today.replace(day=1)
        active = Booking.objects.filter(status__in=Booking.ACTIVE).prefetch_related("payments")
        outstanding = sum((b.balance for b in active), ZERO)

        chart_labels, chart_values = [], []
        for i in range(5, -1, -1):
            m0 = _month_add(month_start, -i)
            chart_labels.append(m0.strftime("%b"))
            chart_values.append(float(revenue_between(m0, _month_add(m0, 1))))

        week = [today + timedelta(days=i) for i in range(7)]
        week_load = []
        for d in week:
            n = Booking.objects.filter(status__in=Booking.ACTIVE, check_in__lte=d, check_out__gt=d).count()
            week_load.append({"day": d, "count": n, "pct": int(n / units * 100) if units else 0})

        related = ("guest", "apartment")
        return render(request, "dashboard/home.html", {
            "today": today,
            "units": units,
            "occupied": occupied,
            "occupancy": int(occupied / units * 100) if units else 0,
            "revenue_month": revenue_between(month_start, _month_add(month_start, 1)),
            "outstanding": outstanding,
            "arrivals": Booking.objects.filter(check_in=today, status__in=[Booking.PENDING, Booking.CONFIRMED]).select_related(*related).prefetch_related("payments"),
            "departures": Booking.objects.filter(check_out=today, status=Booking.CHECKED_IN).select_related(*related).prefetch_related("payments"),
            "in_house": Booking.objects.filter(status=Booking.CHECKED_IN).count(),
            "pending_payments": Payment.objects.filter(status=Payment.PENDING).select_related("booking__guest", "booking__apartment")[:8],
            "awaiting_deposit": Booking.objects.filter(status=Booking.PENDING).select_related(*related).prefetch_related("payments").order_by("hold_expires_at")[:6],
            "tickets": MaintenanceTicket.objects.exclude(status=MaintenanceTicket.RESOLVED).select_related("apartment")[:5],
            "to_send": MessageLog.objects.filter(status__in=["manual", "failed"]).count(),
            "inquiries": ContactInquiry.objects.filter(handled=False).count(),
            "chart_labels": chart_labels,
            "chart_values": chart_values,
            "week_load": week_load,
        })


class TapeChartView(StaffMixin, View):
    section = "front"

    def get(self, request):
        today = timezone.localdate()
        days = 30 if request.GET.get("days") == "30" else 14
        start = parse_date(request.GET.get("start")) or today - timedelta(days=2)
        end = start + timedelta(days=days)
        dates = [start + timedelta(days=i) for i in range(days)]
        apartments = list(Apartment.objects.exclude(status=Apartment.INACTIVE))
        bookings = Booking.objects.filter(
            status__in=[Booking.PENDING, Booking.CONFIRMED, Booking.CHECKED_IN, Booking.CHECKED_OUT],
            check_in__lt=end, check_out__gt=start,
        ).select_related("guest").prefetch_related("payments")
        blocks = MaintenanceTicket.objects.exclude(status=MaintenanceTicket.RESOLVED).filter(
            block_from__isnull=False, block_until__isnull=False, block_from__lt=end, block_until__gte=start
        )
        rows = {a.id: {"apt": a, "bars": []} for a in apartments}
        for b in bookings:
            if b.apartment_id not in rows:
                continue
            s = max(b.check_in, start)
            e = min(b.check_out, end)
            rows[b.apartment_id]["bars"].append({
                "col": (s - start).days + 2, "span": max(1, (e - s).days), "b": b,
                "cut_left": b.check_in < start, "cut_right": b.check_out > end,
            })
        for t in blocks:
            if t.apartment_id not in rows:
                continue
            s = max(t.block_from, start)
            e = min(t.block_until + timedelta(days=1), end)
            rows[t.apartment_id]["bars"].append({"col": (s - start).days + 2, "span": max(1, (e - s).days), "ticket": t})
        return render(request, "dashboard/tape.html", {
            "dates": dates, "rows": rows.values(), "days": days, "start": start, "today": today,
            "prev": start - timedelta(days=days // 2), "next": start + timedelta(days=days // 2),
        })


class ApartmentListView(StaffMixin, View):
    section = "property"

    def get(self, request):
        today = timezone.localdate()
        window = today - timedelta(days=30)
        apartments = Apartment.objects.prefetch_related("photos").annotate(
            open_tickets=Count("tickets", filter=~Q(tickets__status=MaintenanceTicket.RESOLVED), distinct=True)
        )
        data = []
        for a in apartments:
            nights = sum(
                _overlap(ci, co, window, today)
                for ci, co in a.bookings.filter(
                    status__in=[Booking.CONFIRMED, Booking.CHECKED_IN, Booking.CHECKED_OUT], check_out__gt=window, check_in__lt=today
                ).values_list("check_in", "check_out")
            )
            current = a.bookings.filter(status=Booking.CHECKED_IN).select_related("guest").first()
            data.append({"apt": a, "occ30": int(nights / 30 * 100), "current": current})
        return render(request, "dashboard/apartments.html", {"items": data})


class ApartmentEditView(StaffMixin, View):
    section = "property"

    FIELDS_INT = ("floor", "bedrooms", "bathrooms", "capacity", "deposit_percent")

    def get(self, request, pk=None):
        apt = get_object_or_404(Apartment, pk=pk) if pk else Apartment(daily_rate=Decimal("2500"), capacity=2)
        photos = list(apt.photos.order_by("order", "created_at")) if pk else []
        return render(request, "dashboard/apartment_form.html", {
            "apt": apt, "amenities": Amenity.objects.all(),
            "selected": set(apt.amenities.values_list("id", flat=True)) if pk else set(),
            "photos": photos, "statuses": Apartment.STATUS_CHOICES,
            "score": listing_score(apt, photos) if pk else None,
            "rules": apt.rate_rules.filter(is_active=True) if pk else [],
        })

    def post(self, request, pk=None):
        apt = get_object_or_404(Apartment, pk=pk) if pk else Apartment()
        p = request.POST
        if p.get("action") == "delete" and pk:
            if apt.bookings.exists():
                apt.status = Apartment.INACTIVE
                apt.save()
                messages.info(request, f"Apt {apt.number} has bookings, so it was hidden instead of deleted.")
            else:
                apt.delete()
                messages.success(request, "Apartment deleted.")
            return redirect("dashboard:apartments")

        errors = []
        number = p.get("number", "").strip()
        name = p.get("name", "").strip()
        daily = parse_decimal(p.get("daily_rate"))
        if not number:
            errors.append("Apartment number is required.")
        elif Apartment.objects.filter(number__iexact=number).exclude(pk=apt.pk).exists():
            errors.append(f"Apartment number {number} is already used.")
        if not name:
            errors.append("Give the apartment a name.")
        if daily is None or daily <= 0:
            errors.append("Enter a nightly rate.")
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect(request.path)

        apt.number, apt.name = number, name
        apt.tagline = p.get("tagline", "").strip()[:160]
        apt.description = p.get("description", "").strip()
        for f in self.FIELDS_INT:
            setattr(apt, f, parse_int(p.get(f), getattr(apt, f) or 0, 0, 500))
        apt.size_sqm = parse_int(p.get("size_sqm"), 0, 0) or None
        apt.daily_rate = daily
        apt.monthly_rate = parse_decimal(p.get("monthly_rate")) or None
        apt.cleaning_fee = parse_decimal(p.get("cleaning_fee"), ZERO) or ZERO
        apt.status = p.get("status") if p.get("status") in dict(Apartment.STATUS_CHOICES) else Apartment.AVAILABLE
        apt.is_featured = bool(p.get("is_featured"))
        apt.accent = (p.get("accent") or "#0B4F5C")[:7]
        if not pk:
            apt.slug = ""
        apt.save()

        ids = [i for i in p.getlist("amenities") if i]
        if p.get("new_amenity", "").strip():
            am, _ = Amenity.objects.get_or_create(
                name=p["new_amenity"].strip()[:80], defaults={"icon": (p.get("new_amenity_icon") or "check2-circle").strip()}
            )
            ids.append(str(am.id))
        apt.amenities.set(Amenity.objects.filter(id__in=ids))

        for photo_id in p.getlist("delete_photo"):
            ph = ApartmentPhoto.objects.filter(pk=photo_id, apartment=apt).first()
            if ph:
                ph.image.delete(save=False)
                ph.delete()
        for ph in apt.photos.all():
            key = f"caption_{ph.pk}"
            if key in p and p[key].strip()[:120] != ph.caption:
                ph.caption = p[key].strip()[:120]
                ph.save(update_fields=["caption", "updated_at"])
        order = [i for i in p.get("photo_order", "").split(",") if i]
        for position, photo_id in enumerate(order):
            ApartmentPhoto.objects.filter(pk=photo_id, apartment=apt).update(order=position)
        start_order = apt.photos.count()
        for i, f in enumerate(request.FILES.getlist("photos")):
            if (f.content_type or "").startswith("image/"):
                caption = f.name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")[:120]
                ApartmentPhoto.objects.create(apartment=apt, image=f, order=start_order + i, caption=caption)
        if p.get("cover"):
            apt.photos.update(is_cover=False)
            apt.photos.filter(pk=p["cover"]).update(is_cover=True)

        messages.success(request, f"Apt {apt.number} saved.")
        return redirect("dashboard:apartment_edit", pk=apt.pk)


def listing_score(apt, photos):
    """How complete a listing is, with the next fixes to make. Guests book what they can see."""
    checks = [
        (len(photos) >= 5, 25, f"Add {max(0, 5 - len(photos))} more photo{'s' if 5 - len(photos) != 1 else ''} (5+ sells best)"),
        (len(apt.description or "") >= 300, 20, "Write a longer description (300+ characters)"),
        (apt.amenities.count() >= 6, 15, "Tick at least 6 amenities"),
        (bool(apt.tagline), 10, "Add a one-line summary"),
        (all(p.caption for p in photos) and bool(photos), 10, "Caption every photo (Bedroom, Kitchen…)"),
        (bool(apt.monthly_rate), 10, "Set a monthly rate for long stays"),
        (bool(apt.size_sqm), 5, "Add the size in m²"),
        (any(p.is_cover for p in photos), 5, "Choose a cover photo"),
    ]
    score = sum(points for ok, points, _ in checks if ok)
    return {"score": score, "todo": [tip for ok, _, tip in checks if not ok][:3]}


class BookingListView(StaffMixin, View):
    section = "front"

    def get(self, request):
        qs = Booking.objects.select_related("guest", "apartment").prefetch_related("payments")
        q = request.GET.get("q", "").strip()
        status = request.GET.get("status", "")
        apt = request.GET.get("apartment", "")
        frm, to = parse_date(request.GET.get("from")), parse_date(request.GET.get("to"))
        view = request.GET.get("view", "")
        today = timezone.localdate()
        if q:
            qs = qs.filter(Q(reference__icontains=q) | Q(guest__full_name__icontains=q) | Q(guest__phone__icontains=q))
        if status:
            qs = qs.filter(status=status)
        if apt:
            qs = qs.filter(apartment__number=apt)
        if frm:
            qs = qs.filter(check_out__gt=frm)
        if to:
            qs = qs.filter(check_in__lte=to)
        if view == "upcoming":
            qs = qs.filter(check_in__gte=today, status__in=Booking.ACTIVE).order_by("check_in")
        elif view == "unpaid":
            qs = [b for b in qs.filter(status__in=Booking.ACTIVE) if b.balance > 0]
        page = Paginator(qs, 25).get_page(request.GET.get("page"))
        return render(request, "dashboard/bookings.html", {
            "page": page, "statuses": Booking.STATUS_CHOICES, "apartments": Apartment.objects.all(), "f": request.GET,
        })


class BookingCreateView(StaffMixin, View):
    section = "front"

    def get(self, request):
        return render(request, "dashboard/booking_form.html", {
            "apartments": Apartment.objects.exclude(status=Apartment.INACTIVE),
            "sources": Booking.SOURCE_CHOICES, "methods": Payment.METHOD_CHOICES,
            "pre_apt": request.GET.get("apartment", ""), "pre_ci": request.GET.get("check_in", ""),
            "pre_co": request.GET.get("check_out", ""),
        })

    def post(self, request):
        from stays.services import BookingError, confirm_payment, create_booking, get_or_create_guest

        p = request.POST
        apt = Apartment.objects.filter(pk=p.get("apartment")).first() if p.get("apartment") else None
        ci, co = parse_date(p.get("check_in")), parse_date(p.get("check_out"))
        if not apt or not ci or not co or not p.get("full_name") or not p.get("phone"):
            messages.error(request, "Apartment, dates, guest name and phone are required.")
            return redirect(request.get_full_path())
        guest = get_or_create_guest(p["full_name"].strip(), p["phone"].strip(), email=p.get("email", "").strip(), country=p.get("country", "").strip())
        if p.get("id_number"):
            guest.id_type, guest.id_number = p.get("id_type", "")[:40], p["id_number"][:60]
            guest.save()
        try:
            b = create_booking(
                apartment=apt, guest=guest, check_in=ci, check_out=co,
                adults=parse_int(p.get("adults"), 1, 1, 30), children=parse_int(p.get("children"), 0, 0, 30),
                payment_option=p.get("payment_option", "deposit"), source=p.get("source", "walk_in"),
                special_requests=p.get("special_requests", ""), created_by=request.user, allow_past=True,
                discount=parse_decimal(p.get("discount"), ZERO) or ZERO,
            )
        except BookingError as exc:
            messages.error(request, str(exc))
            return redirect(request.get_full_path())
        amount = parse_decimal(p.get("pay_amount"))
        if amount and amount > 0:
            pay = Payment.objects.create(
                booking=b, amount=amount, method=p.get("pay_method", "cash"), reference=p.get("pay_reference", "")[:80],
                kind=Payment.FULL if amount >= b.total_amount else Payment.DEPOSIT,
            )
            confirm_payment(pay, request.user, notify=bool(p.get("notify")))
        elif p.get("notify"):
            from stays import messages_text, whatsapp
            whatsapp.send(guest.wa_number, messages_text.booking_received(b), booking=b, kind="received")
        if p.get("check_in_now") and ci <= timezone.localdate():
            b.refresh_from_db()
            b.status, b.checked_in_at = Booking.CHECKED_IN, timezone.now()
            b.save()
        messages.success(request, f"Booking {b.reference} created.")
        return redirect("dashboard:booking", pk=b.pk)


class BookingDetailView(StaffMixin, View):
    section = ("front", "payments")

    def _get(self, pk):
        return get_object_or_404(
            Booking.objects.select_related("guest", "apartment", "created_by").prefetch_related("payments__received_by", "messages"), pk=pk
        )

    def get(self, request, pk):
        b = self._get(pk)
        return render(request, "dashboard/booking_detail.html", {
            "b": b, "methods": Payment.METHOD_CHOICES, "kinds": Payment.KIND_CHOICES,
            "history": b.guest.bookings.exclude(pk=b.pk).select_related("apartment")[:5],
        })

    def post(self, request, pk):
        from stays import messages_text, whatsapp
        from stays.services import BookingError, confirm_payment, reprice_booking

        b = self._get(pk)
        p = request.POST
        a = p.get("action")
        now = timezone.now()

        if a == "check_in" and b.status in (Booking.PENDING, Booking.CONFIRMED):
            b.status, b.checked_in_at = Booking.CHECKED_IN, now
            b.save()
            messages.success(request, f"{b.guest.first_name} checked in to Apt {b.apartment.number}.")
        elif a == "check_out" and b.status == Booking.CHECKED_IN:
            b.status, b.checked_out_at = Booking.CHECKED_OUT, now
            b.save()
            if b.balance > 0:
                messages.warning(request, f"Checked out with {b.balance:,.2f} still outstanding.")
            else:
                messages.success(request, "Checked out. Unit is ready for housekeeping.")
        elif a == "confirm" and b.status == Booking.PENDING:
            b.status, b.hold_expires_at = Booking.CONFIRMED, None
            b.save()
            whatsapp.send(b.guest.wa_number, messages_text.confirmation(b), booking=b, kind="confirmation")
            messages.success(request, "Booking confirmed and guest notified.")
        elif a in ("cancel", "no_show") and b.is_active:
            b.status = Booking.CANCELLED if a == "cancel" else Booking.NO_SHOW
            b.cancelled_at = now
            b.save()
            messages.info(request, "Booking closed and dates released.")
        elif a == "record_payment":
            amount = parse_decimal(p.get("amount"))
            if not amount or amount <= 0:
                messages.error(request, "Enter an amount.")
            else:
                pay = Payment.objects.create(
                    booking=b, amount=amount, method=p.get("method", "cash"), kind=p.get("kind", Payment.INSTALLMENT),
                    reference=p.get("reference", "")[:80], note=p.get("note", "")[:255],
                )
                confirm_payment(pay, request.user, notify=bool(p.get("notify")))
                messages.success(request, "Payment recorded and receipt issued.")
        elif a == "verify_payment":
            pay = get_object_or_404(Payment, pk=p.get("payment"), booking=b)
            confirm_payment(pay, request.user)
            messages.success(request, "Payment verified. Receipt sent to the guest.")
        elif a == "reject_payment":
            pay = get_object_or_404(Payment, pk=p.get("payment"), booking=b)
            pay.status, pay.note = Payment.REJECTED, p.get("note", "")[:255] or "Not found in statement"
            pay.save()
            messages.info(request, "Payment marked as rejected.")
        elif a == "change_dates":
            ci, co = parse_date(p.get("check_in")), parse_date(p.get("check_out"))
            try:
                reprice_booking(b, ci, co, parse_decimal(p.get("discount"), b.discount))
                messages.success(request, "Stay updated and re-priced.")
            except (BookingError, TypeError) as exc:
                messages.error(request, str(exc) or "Invalid dates.")
        elif a == "send":
            kind = p.get("kind")
            texts = {
                "confirmation": messages_text.confirmation, "reminder": messages_text.payment_reminder,
                "checkin": messages_text.checkin_reminder, "received": messages_text.booking_received,
            }
            body = p.get("body", "").strip() if kind == "custom" else texts.get(kind, messages_text.confirmation)(b)
            if body:
                log = whatsapp.send(b.guest.wa_number, body, booking=b, kind=kind if kind in texts or kind == "custom" else "custom")
                if log.status == "manual":
                    messages.info(request, "Message ready — tap “Open WhatsApp” in the message list to send it.")
                else:
                    messages.success(request, f"WhatsApp {log.get_status_display().lower()}.")
        elif a == "mark_sent":
            MessageLog.objects.filter(pk=p.get("message"), booking=b).update(status="sent")
        elif a == "notes":
            b.internal_notes = p.get("internal_notes", "")
            b.save(update_fields=["internal_notes", "updated_at"])
            messages.success(request, "Notes saved.")
        return redirect("dashboard:booking", pk=b.pk)


class PaymentListView(StaffMixin, View):
    section = "payments"

    def get(self, request):
        qs = Payment.objects.select_related("booking__guest", "booking__apartment", "received_by")
        status, method = request.GET.get("status", ""), request.GET.get("method", "")
        frm, to = parse_date(request.GET.get("from")), parse_date(request.GET.get("to"))
        if status:
            qs = qs.filter(status=status)
        if method:
            qs = qs.filter(method=method)
        if frm:
            qs = qs.filter(created_at__date__gte=frm)
        if to:
            qs = qs.filter(created_at__date__lte=to)
        totals = qs.filter(status=Payment.CONFIRMED).exclude(kind=Payment.REFUND).aggregate(s=Sum("amount"))["s"] or ZERO
        return render(request, "dashboard/payments.html", {
            "page": Paginator(qs, 30).get_page(request.GET.get("page")), "totals": totals,
            "statuses": Payment.STATUS_CHOICES, "methods": Payment.METHOD_CHOICES, "f": request.GET,
            "pending_count": Payment.objects.filter(status=Payment.PENDING).count(),
        })

    def post(self, request):
        from stays.services import confirm_payment

        pay = get_object_or_404(Payment, pk=request.POST.get("payment"))
        if request.POST.get("action") == "verify":
            confirm_payment(pay, request.user)
            messages.success(request, f"Verified {pay.booking.reference}. Receipt sent.")
        elif request.POST.get("action") == "reject":
            pay.status = Payment.REJECTED
            pay.save()
            messages.info(request, "Payment rejected.")
        return redirect(request.META.get("HTTP_REFERER") or reverse("dashboard:payments"))


class GuestListView(StaffMixin, View):
    section = "front"

    def get(self, request):
        q = request.GET.get("q", "").strip()
        qs = Guest.objects.annotate(stays=Count("bookings")).order_by("full_name")
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
        return render(request, "dashboard/guests.html", {"page": Paginator(qs, 30).get_page(request.GET.get("page")), "q": q})


class GuestDetailView(StaffMixin, View):
    section = "front"

    def get(self, request, pk):
        g = get_object_or_404(Guest, pk=pk)
        bookings = g.bookings.select_related("apartment").prefetch_related("payments")
        spent = sum((b.amount_paid for b in bookings), ZERO)
        return render(request, "dashboard/guest_detail.html", {"g": g, "bookings": bookings, "spent": spent})

    def post(self, request, pk):
        g = get_object_or_404(Guest, pk=pk)
        p = request.POST
        for f in ("full_name", "phone", "whatsapp", "email", "country", "id_type", "id_number", "notes"):
            setattr(g, f, p.get(f, "").strip())
        if not g.full_name or not g.phone:
            messages.error(request, "Name and phone are required.")
        else:
            g.save()
            messages.success(request, "Guest updated.")
        return redirect("dashboard:guest", pk=g.pk)


class MaintenanceView(StaffMixin, View):
    section = "maintenance"

    def get(self, request):
        status = request.GET.get("status", "active")
        qs = MaintenanceTicket.objects.select_related("apartment")
        if status == "active":
            qs = qs.exclude(status=MaintenanceTicket.RESOLVED)
        elif status:
            qs = qs.filter(status=status)
        return render(request, "dashboard/maintenance.html", {
            "tickets": qs, "apartments": Apartment.objects.all(), "status": status,
            "priorities": MaintenanceTicket.PRIORITY_CHOICES, "statuses": MaintenanceTicket.STATUS_CHOICES,
            "cost_month": MaintenanceTicket.objects.filter(created_at__date__gte=timezone.localdate().replace(day=1)).aggregate(s=Sum("cost"))["s"] or ZERO,
        })

    def post(self, request):
        p = request.POST
        if p.get("action") == "create":
            apt = Apartment.objects.filter(pk=p.get("apartment")).first() if p.get("apartment") else None
            if not apt or not p.get("title", "").strip():
                messages.error(request, "Choose an apartment and describe the issue.")
                return redirect("dashboard:maintenance")
            bf, bu = parse_date(p.get("block_from")), parse_date(p.get("block_until"))
            if bf and bu and bu < bf:
                bf, bu = bu, bf
            t = MaintenanceTicket.objects.create(
                apartment=apt, title=p["title"].strip()[:150], description=p.get("description", ""),
                priority=p.get("priority", "normal"), block_from=bf, block_until=bu if bf else None,
                reported_by=p.get("reported_by", "")[:100] or request.user.get_username(),
                assigned_to=p.get("assigned_to", "")[:100],
            )
            if bf and bu:
                from stays.services import booking_conflicts
                clash = booking_conflicts(apt, bf, bu + timedelta(days=1)).count()
                if clash:
                    messages.warning(request, f"Heads up: {clash} booking(s) already overlap this maintenance window.")
            messages.success(request, f"Ticket logged for Apt {apt.number}.")
        else:
            t = get_object_or_404(MaintenanceTicket, pk=p.get("ticket"))
            new = p.get("status")
            if new in dict(MaintenanceTicket.STATUS_CHOICES):
                t.status = new
                t.resolved_at = timezone.now() if new == MaintenanceTicket.RESOLVED else None
            if p.get("cost"):
                t.cost = parse_decimal(p.get("cost"), t.cost)
            t.save()
            messages.success(request, "Ticket updated.")
        return redirect(request.META.get("HTTP_REFERER") or reverse("dashboard:maintenance"))


class ReportsView(StaffMixin, View):
    section = "reports"

    def get(self, request):
        from stays.services import signed_amount

        today = timezone.localdate()
        start = parse_date(request.GET.get("from")) or today.replace(day=1)
        end_incl = parse_date(request.GET.get("to")) or (_month_add(start, 1) - timedelta(days=1))
        end = end_incl + timedelta(days=1)
        days = max(1, (end - start).days)

        apartments = list(Apartment.objects.exclude(status=Apartment.INACTIVE))
        bookings = Booking.objects.filter(
            status__in=[Booking.CONFIRMED, Booking.CHECKED_IN, Booking.CHECKED_OUT], check_in__lt=end, check_out__gt=start
        ).select_related("apartment", "guest").prefetch_related("payments")

        if request.GET.get("export") == "csv":
            resp = HttpResponse(content_type="text/csv")
            resp["Content-Disposition"] = f'attachment; filename="bookings-{start}-{end_incl}.csv"'
            w = csv.writer(resp)
            w.writerow(["Reference", "Apartment", "Guest", "Phone", "Check-in", "Check-out", "Nights", "Status", "Source", "Total", "Paid", "Balance"])
            for b in bookings:
                w.writerow([b.reference, b.apartment.number, b.guest.full_name, b.guest.phone, b.check_in, b.check_out, b.nights,
                            b.get_status_display(), b.get_source_display(), b.total_amount, b.amount_paid, b.balance])
            return resp

        per_apt = {a.id: {"apt": a, "nights": 0, "room_rev": ZERO, "collected": ZERO} for a in apartments}
        nights_sold, room_rev = 0, ZERO
        sources = {}
        for b in bookings:
            ov = _overlap(b.check_in, b.check_out, start, end)
            value = (b.subtotal / b.nights * ov) if b.nights else ZERO
            nights_sold += ov
            room_rev += value
            sources[b.get_source_display()] = sources.get(b.get_source_display(), 0) + 1
            if b.apartment_id in per_apt:
                per_apt[b.apartment_id]["nights"] += ov
                per_apt[b.apartment_id]["room_rev"] += value

        pays = Payment.objects.filter(status=Payment.CONFIRMED, paid_at__date__gte=start, paid_at__date__lt=end)
        collected = pays.aggregate(s=Sum(signed_amount()))["s"] or ZERO
        by_method = list(pays.values("method").annotate(total=Sum(signed_amount()), n=Count("id")).order_by("-total"))
        method_names = dict(Payment.METHOD_CHOICES)
        for m in by_method:
            m["label"] = method_names.get(m["method"], m["method"])
        for row in pays.values("booking__apartment_id").annotate(total=Sum(signed_amount())):
            if row["booking__apartment_id"] in per_apt:
                per_apt[row["booking__apartment_id"]]["collected"] = row["total"]
        whole = Decimal("1")
        for r in per_apt.values():
            r["occ"] = int(r["nights"] / days * 100)
            r["room_rev"] = Decimal(r["room_rev"]).quantize(whole)
        room_rev = Decimal(room_rev).quantize(whole)

        capacity_nights = len(apartments) * days
        outstanding = [b for b in Booking.objects.filter(status__in=Booking.ACTIVE + (Booking.CHECKED_OUT,)).select_related("guest", "apartment").prefetch_related("payments") if b.balance > 0]
        maint_cost = MaintenanceTicket.objects.filter(created_at__date__gte=start, created_at__date__lt=end).aggregate(s=Sum("cost"))["s"] or ZERO

        daily_labels, daily_occ = [], []
        for i in range(days):
            d = start + timedelta(days=i)
            n = sum(1 for b in bookings if b.check_in <= d < b.check_out)
            daily_labels.append(d.strftime("%d %b"))
            daily_occ.append(int(n / len(apartments) * 100) if apartments else 0)

        return render(request, "dashboard/reports.html", {
            "start": start, "end": end_incl, "days": days,
            "nights_sold": nights_sold, "occupancy": int(nights_sold / capacity_nights * 100) if capacity_nights else 0,
            "adr": (room_rev / nights_sold).quantize(whole) if nights_sold else ZERO,
            "revpar": (room_rev / capacity_nights).quantize(whole) if capacity_nights else ZERO,
            "room_rev": room_rev, "collected": collected, "by_method": by_method,
            "per_apt": sorted(per_apt.values(), key=lambda r: -r["room_rev"]),
            "sources": sorted(sources.items(), key=lambda x: -x[1]),
            "outstanding": outstanding[:15], "outstanding_total": sum((b.balance for b in outstanding), ZERO),
            "maint_cost": maint_cost, "daily_labels": daily_labels, "daily_occ": daily_occ,
            "this_month": today.replace(day=1), "last_month": _month_add(today.replace(day=1), -1),
            "last_month_end": today.replace(day=1) - timedelta(days=1),
        })


class MessagesView(StaffMixin, View):
    section = "front"

    def get(self, request):
        tab = request.GET.get("tab", "outbox")
        logs = MessageLog.objects.select_related("booking__guest")
        if tab == "outbox":
            logs = logs.filter(status__in=["manual", "failed"])
        return render(request, "dashboard/messages.html", {
            "tab": tab, "logs": Paginator(logs, 30).get_page(request.GET.get("page")),
            "inquiries": ContactInquiry.objects.select_related("apartment")[:50],
            "outbox_count": MessageLog.objects.filter(status__in=["manual", "failed"]).count(),
            "unhandled": ContactInquiry.objects.filter(handled=False).count(),
        })

    def post(self, request):
        p = request.POST
        if p.get("action") == "mark_sent":
            MessageLog.objects.filter(pk=p.get("message")).update(status="sent")
        elif p.get("action") == "mark_all_sent":
            MessageLog.objects.filter(status="manual").update(status="sent")
        elif p.get("action") == "handled":
            ContactInquiry.objects.filter(pk=p.get("inquiry")).update(handled=True)
        elif p.get("action") == "run_reminders":
            from stays.tasks import send_checkin_reminders, send_payment_reminders
            n = send_payment_reminders() + send_checkin_reminders()
            messages.success(request, f"{n} reminder(s) prepared.")
        return redirect(request.META.get("HTTP_REFERER") or reverse("dashboard:messages"))
