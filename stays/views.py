from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.db.models import Min, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from .models import Amenity, Apartment, Booking, ContactInquiry, Payment
from .utils import parse_date, parse_decimal, parse_int


def _public_apartments():
    return Apartment.objects.exclude(status=Apartment.INACTIVE).prefetch_related("photos", "amenities")


def _qr_svg(url):
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=1)
    return img.to_string(encoding="unicode")


class HomeView(View):
    def get(self, request):
        from .services import occupied_apartment_ids

        today = timezone.localdate()
        apartments = list(_public_apartments())
        busy = occupied_apartment_ids(today)
        doors = [{"apt": a, "free": a.is_bookable and a.id not in busy} for a in apartments]
        featured = [a for a in apartments if a.is_featured][:3] or apartments[:3]
        return render(request, "stays/home.html", {
            "doors": doors,
            "free_tonight": sum(1 for d in doors if d["free"]),
            "featured": featured,
            "amenities": Amenity.objects.all()[:12],
            "from_rate": Apartment.objects.exclude(status=Apartment.INACTIVE).aggregate(m=Min("daily_rate"))["m"],
            "today": today,
            "tomorrow": today + timedelta(days=1),
        })


class ApartmentListView(View):
    def get(self, request):
        from .services import BookingError, is_available, quote

        ci = parse_date(request.GET.get("check_in"))
        co = parse_date(request.GET.get("check_out"))
        guests = parse_int(request.GET.get("guests"), 0, 0, 30)
        max_rate = parse_decimal(request.GET.get("max_rate"))
        bedrooms = parse_int(request.GET.get("bedrooms"), 0, 0, 10)
        amenity_ids = request.GET.getlist("amenity")
        sort = request.GET.get("sort", "number")

        qs = _public_apartments()
        if guests:
            qs = qs.filter(capacity__gte=guests)
        if max_rate:
            qs = qs.filter(daily_rate__lte=max_rate)
        if bedrooms:
            qs = qs.filter(bedrooms__gte=bedrooms)
        for aid in amenity_ids:
            qs = qs.filter(amenities__id=aid)
        qs = qs.distinct()
        qs = qs.order_by({"price": "daily_rate", "-price": "-daily_rate", "capacity": "-capacity"}.get(sort, "number"))

        dated = bool(ci and co and co > ci)
        results = []
        for a in qs:
            item = {"apt": a, "available": None, "quote": None}
            if dated:
                item["available"] = is_available(a, ci, co)
                try:
                    item["quote"] = quote(a, ci, co)
                except BookingError:
                    pass
            results.append(item)
        if dated:
            results.sort(key=lambda r: not r["available"])

        return render(request, "stays/apartment_list.html", {
            "results": results,
            "dated": dated,
            "check_in": ci,
            "check_out": co,
            "guests": guests,
            "max_rate": max_rate,
            "bedrooms": bedrooms,
            "amenities": Amenity.objects.all(),
            "selected_amenities": amenity_ids,
            "sort": sort,
            "available_count": sum(1 for r in results if r["available"]),
        })


class ApartmentDetailView(View):
    def get(self, request, slug):
        apt = get_object_or_404(_public_apartments(), slug=slug)
        others = _public_apartments().exclude(pk=apt.pk).order_by("?")[:3]
        return render(request, "stays/apartment_detail.html", {
            "apt": apt,
            "photos": list(apt.photos.all()),
            "others": others,
            "check_in": request.GET.get("check_in", ""),
            "check_out": request.GET.get("check_out", ""),
            "guests": parse_int(request.GET.get("guests"), 1, 1, apt.capacity),
            "payment_methods": [m for m in Payment.METHOD_CHOICES if m[0] != "card"],
        })


class AvailabilityApiView(View):
    def get(self, request, slug):
        from .services import BookingError, is_available, quote, quote_json, unavailable_ranges

        apt = get_object_or_404(Apartment.objects.exclude(status=Apartment.INACTIVE), slug=slug)
        today = timezone.localdate()
        data = {
            "bookable": apt.is_bookable,
            "ranges": unavailable_ranges(apt, today, today + timedelta(days=550)),
            "capacity": apt.capacity,
        }
        ci = parse_date(request.GET.get("check_in"))
        co = parse_date(request.GET.get("check_out"))
        if ci and co:
            try:
                data["quote"] = quote_json(quote(apt, ci, co))
                data["available"] = ci >= today and is_available(apt, ci, co)
            except BookingError as exc:
                data["error"] = str(exc)
        return JsonResponse(data)


class BookView(View):
    def post(self, request, slug):
        from . import messages_text, whatsapp
        from .services import BookingError, create_booking, get_or_create_guest

        apt = get_object_or_404(Apartment.objects.exclude(status=Apartment.INACTIVE), slug=slug)
        p = request.POST
        back = apt.get_absolute_url() + "?" + urlencode({
            "check_in": p.get("check_in", ""), "check_out": p.get("check_out", ""), "guests": p.get("adults", "1"),
        }) + "#book"

        if p.get("website"):  # honeypot
            return redirect(back)

        ci, co = parse_date(p.get("check_in")), parse_date(p.get("check_out"))
        full_name = p.get("full_name", "").strip()
        phone = p.get("phone", "").strip()
        email = p.get("email", "").strip()
        errors = []
        if not (ci and co):
            errors.append("Choose your check-in and check-out dates on the calendar.")
        if len(full_name) < 3:
            errors.append("Enter your full name.")
        if len([c for c in phone if c.isdigit()]) < 7:
            errors.append("Enter a phone number we can reach on WhatsApp.")
        if not p.get("agree"):
            errors.append("Please accept the house rules to continue.")
        if errors:
            for e in errors:
                messages.error(request, e)
            return redirect(back)

        guest = get_or_create_guest(
            full_name, phone, email=email,
            whatsapp="" if p.get("same_whatsapp") else p.get("whatsapp", "").strip(),
            country=p.get("country", "").strip(),
        )
        try:
            booking = create_booking(
                apartment=apt, guest=guest, check_in=ci, check_out=co,
                adults=parse_int(p.get("adults"), 1, 1, 30), children=parse_int(p.get("children"), 0, 0, 30),
                payment_option=Booking.OPTION_FULL if p.get("payment_option") == "full" else Booking.OPTION_DEPOSIT,
                source="website", special_requests=p.get("special_requests", "").strip()[:2000],
            )
        except BookingError as exc:
            messages.error(request, str(exc))
            return redirect(back)

        whatsapp.send(guest.wa_number, messages_text.booking_received(booking), booking=booking, kind="received")
        request.session.setdefault("my_bookings", [])
        request.session["my_bookings"] = list({*request.session["my_bookings"], str(booking.pk)})
        messages.success(request, f"Your dates are held. Booking {booking.reference} — details are below and on WhatsApp.")
        return redirect(booking.get_absolute_url())


class BookingDetailView(View):
    def _get(self, pk):
        return get_object_or_404(
            Booking.objects.select_related("apartment", "guest").prefetch_related("payments", "apartment__photos"), pk=pk
        )

    def get(self, request, pk):
        b = self._get(pk)
        url = request.build_absolute_uri(b.get_absolute_url())
        k = settings.KUNDA
        methods = [
            {"key": "wave", "label": "Wave", "detail": k["wave_number"], "icon": "phone"},
            {"key": "afrimoney", "label": "Afrimoney", "detail": k["afrimoney_number"], "icon": "phone"},
            {"key": "qmoney", "label": "QMoney", "detail": k["qmoney_number"], "icon": "phone"},
            {"key": "bank", "label": "Bank transfer", "detail": k["bank_details"], "icon": "bank"},
        ]
        steps = [
            ("Requested", True),
            ("Deposit paid", b.amount_paid >= b.deposit_required and b.amount_paid > 0),
            ("Checked in", b.status in (Booking.CHECKED_IN, Booking.CHECKED_OUT)),
            ("Checked out", b.status == Booking.CHECKED_OUT),
        ]
        suggested = b.deposit_outstanding if b.deposit_outstanding > 0 else b.balance
        from . import whatsapp
        from .models import ExtraItem
        from .services import tab_summary

        menu = []
        if b.status == Booking.CHECKED_IN:
            items = [i for i in ExtraItem.objects.filter(is_active=True, guest_can_order=True) if not i.sold_out]
            for key, label in ExtraItem.CATEGORY_CHOICES:
                group = [i for i in items if i.category == key]
                if group and key != "damages":
                    menu.append({"label": label, "icon": ExtraItem.ICONS[key], "items": group})
        return render(request, "stays/booking_detail.html", {
            "tab": tab_summary(b), "menu": menu, "order_wa": whatsapp.normalize(k["whatsapp"]),
            "b": b,
            "qr": _qr_svg(url),
            "methods": [m for m in methods if m["detail"]],
            "steps": steps,
            "suggested_amount": suggested,
            "payments": sorted(b.payments.all(), key=lambda p: p.created_at, reverse=True),
            "wa_text": f"Hello, about my booking {b.reference} (Apt {b.apartment.number}, {b.check_in:%d %b}–{b.check_out:%d %b}).",
        })

    def post(self, request, pk):
        b = self._get(pk)
        action = request.POST.get("action")
        if action == "submit_payment":
            amount = parse_decimal(request.POST.get("amount"))
            method = request.POST.get("method", "")
            ref = request.POST.get("reference", "").strip()[:80]
            valid_methods = {m for m, _ in Payment.METHOD_CHOICES}
            if not (b.is_active or b.can_pay_online):
                messages.error(request, "This booking is no longer active.")
            elif not amount or amount <= 0:
                messages.error(request, "Enter the amount you sent.")
            elif method not in valid_methods:
                messages.error(request, "Choose how you paid.")
            elif method != "cash" and len(ref) < 4:
                messages.error(request, "Enter the transaction ID from your payment SMS.")
            else:
                kind = Payment.FULL if amount >= b.balance else (Payment.DEPOSIT if b.amount_paid == 0 else Payment.INSTALLMENT)
                Payment.objects.create(
                    booking=b, amount=amount, method=method, reference=ref, kind=kind,
                    status=Payment.PENDING, submitted_by_guest=True,
                )
                if b.status == Booking.PENDING and b.hold_expires_at:
                    b.hold_expires_at = max(b.hold_expires_at, timezone.now() + timedelta(hours=12))
                    b.save(update_fields=["hold_expires_at", "updated_at"])
                messages.success(request, "Payment submitted. We'll verify it and send your receipt on WhatsApp.")
        elif action == "cancel":
            if b.can_guest_cancel:
                b.status = Booking.CANCELLED
                b.cancelled_at = timezone.now()
                b.save(update_fields=["status", "cancelled_at", "updated_at"])
                messages.info(request, "Your booking has been cancelled and the dates released.")
            else:
                messages.error(request, "This booking can't be cancelled online. Message us on WhatsApp.")
        return redirect(b.get_absolute_url() + "#pay")


class BookingLookupView(View):
    def get(self, request):
        recent = Booking.objects.filter(pk__in=request.session.get("my_bookings", [])).select_related("apartment")
        return render(request, "stays/lookup.html", {"recent": recent})

    def post(self, request):
        from .whatsapp import normalize

        ref = request.POST.get("reference", "").strip().upper()
        contact = request.POST.get("contact", "").strip()
        if ref and not ref.startswith("KS-"):
            ref = "KS-" + ref
        b = Booking.objects.select_related("guest").filter(reference=ref).first()
        if b and contact and (
            contact.lower() == (b.guest.email or "").lower()
            or (normalize(contact) and normalize(contact) in (normalize(b.guest.phone), normalize(b.guest.whatsapp)))
        ):
            return redirect(b.get_absolute_url())
        messages.error(request, "We couldn't match that reference with the phone or email. Check both and try again.")
        return redirect("stays:lookup")


class ReceiptPdfView(View):
    def get(self, request, pk):
        from .receipts import receipt_pdf

        p = get_object_or_404(Payment.objects.select_related("booking__guest", "booking__apartment", "received_by"), pk=pk)
        if p.status != Payment.CONFIRMED:
            raise Http404
        resp = HttpResponse(receipt_pdf(p), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="receipt-{p.receipt_number}.pdf"'
        return resp


class StatementPdfView(View):
    def get(self, request, pk):
        from .receipts import statement_pdf

        b = get_object_or_404(Booking.objects.select_related("guest", "apartment"), pk=pk)
        resp = HttpResponse(statement_pdf(b), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="statement-{b.reference}.pdf"'
        return resp


class BookingIcsView(View):
    def get(self, request, pk):
        b = get_object_or_404(Booking.objects.select_related("apartment"), pk=pk)
        k = settings.KUNDA
        stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
        body = "\r\n".join([
            "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Kunda Stays//Booking//EN", "BEGIN:VEVENT",
            f"UID:{b.pk}@kunda", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{b.check_in:%Y%m%d}", f"DTEND;VALUE=DATE:{b.check_out:%Y%m%d}",
            f"SUMMARY:{k['name']} – Apt {b.apartment.number} ({b.reference})",
            f"LOCATION:{k['address']}",
            f"DESCRIPTION:Check-in from {k['checkin_time']}. Booking page: {k['site_url']}{b.get_absolute_url()}",
            "END:VEVENT", "END:VCALENDAR", "",
        ])
        resp = HttpResponse(body, content_type="text/calendar")
        resp["Content-Disposition"] = f'attachment; filename="{b.reference}.ics"'
        return resp


class ContactView(View):
    def get(self, request):
        return render(request, "stays/contact.html", {"apartments": _public_apartments()})

    def post(self, request):
        p = request.POST
        if p.get("website"):
            return redirect("stays:contact")
        name, msg = p.get("name", "").strip(), p.get("message", "").strip()
        if len(name) < 2 or len(msg) < 5:
            messages.error(request, "Add your name and a short message so we can help.")
            return redirect("stays:contact")
        apt = None
        if p.get("apartment"):
            try:
                apt = Apartment.objects.filter(pk=p.get("apartment")).first()
            except Exception:
                apt = None
        ContactInquiry.objects.create(
            name=name[:120], phone=p.get("phone", "").strip()[:30], email=p.get("email", "").strip()[:254],
            message=msg[:3000], apartment=apt,
        )
        messages.success(request, "Message sent. We usually reply within the hour — faster on WhatsApp.")
        return redirect("stays:contact")
