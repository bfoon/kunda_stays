"""Room charges: tap-to-charge screen for the desk, bar and housekeeping, and the extras menu."""
import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from stays.models import ZERO, Booking, ExtraItem, RoomCharge
from stays.utils import parse_decimal, parse_int

from .views import StaffMixin


def _open_tabs():
    """Bookings that can take charges: in house first, then late charges for recent check-outs."""
    today = timezone.localdate()
    qs = Booking.objects.select_related("guest", "apartment").prefetch_related("payments")
    in_house = list(qs.filter(status=Booking.CHECKED_IN).order_by("apartment__number"))
    arriving = list(qs.filter(status=Booking.CONFIRMED, check_in=today).order_by("apartment__number"))
    recent = list(qs.filter(status=Booking.CHECKED_OUT, check_out__gte=today - timedelta(days=2)).order_by("-checked_out_at")[:8])
    return in_house, arriving, recent


def parse_ticket(raw):
    """[{item, qty} | {custom, price, qty, category}] from the JSON the tap screen posts."""
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    items = {str(i.pk): i for i in ExtraItem.objects.filter(pk__in=[d.get("item") for d in data if d.get("item")])}
    lines = []
    for d in data[:60]:
        qty = parse_int(d.get("qty"), 0, 0, 99)
        if not qty:
            continue
        if d.get("item"):
            item = items.get(str(d["item"]))
            if item:
                lines.append({"item": item, "quantity": qty})
        else:
            price = parse_decimal(str(d.get("price", "")))
            cat = d.get("category") if d.get("category") in dict(ExtraItem.CATEGORY_CHOICES) else "other"
            lines.append({"item": None, "quantity": qty, "description": str(d.get("custom", ""))[:120], "unit_price": price, "category": cat})
    return lines


class ChargeToRoomView(StaffMixin, View):
    section = "charges"

    def get(self, request):
        from stays.services import can_void, tab_summary

        in_house, arriving, recent = _open_tabs()
        all_tabs = in_house + arriving + recent
        selected = None
        if request.GET.get("booking"):
            selected = next((b for b in all_tabs if str(b.pk) == request.GET["booking"]), None)
        elif request.GET.get("apt"):
            selected = next((b for b in in_house if str(b.apartment_id) == request.GET["apt"]), None)
        if selected is None and len(in_house) == 1:
            selected = in_house[0]

        items = list(ExtraItem.objects.filter(is_active=True))
        cats = []
        for key, label in ExtraItem.CATEGORY_CHOICES:
            group = [i for i in items if i.category == key]
            if group:
                cats.append({"key": key, "label": label, "icon": ExtraItem.ICONS[key], "items": group})

        today = timezone.localdate()
        todays = RoomCharge.objects.filter(charged_on=today, voided_at__isnull=True)
        stats = todays.aggregate(total=Sum("amount"), n=Sum("quantity"))
        top = todays.values("description").annotate(q=Sum("quantity")).order_by("-q").first()
        feed = RoomCharge.objects.filter(charged_on=today).select_related("booking__apartment", "posted_by", "voided_by").order_by("-created_at")[:12]
        tab = tab_summary(selected) if selected else None
        if tab:
            for c in tab["charges"]:
                c.voidable = can_void(c, request.user)
        for c in feed:
            c.voidable = can_void(c, request.user)
        return render(request, "dashboard/charges.html", {
            "in_house": in_house, "arriving": arriving, "recent": recent, "selected": selected, "tab": tab,
            "cats": cats, "stats": stats, "top": top, "feed": feed, "low": [i for i in items if i.low_stock],
            "sources": RoomCharge.SOURCE_CHOICES, "categories": ExtraItem.CATEGORY_CHOICES,
            "default_source": "housekeeping" if request.user.groups.filter(name="Housekeeping").exists() else "desk",
        })

    def post(self, request):
        from stays.services import BookingError, post_charges, void_charge

        p = request.POST
        if p.get("action") == "void":
            charge = get_object_or_404(RoomCharge.objects.select_related("booking"), pk=p.get("charge"))
            try:
                void_charge(charge, request.user, p.get("reason"))
                messages.info(request, f"Voided {charge.quantity} × {charge.description}. Tab now {settings.KUNDA['currency_symbol']} {charge.booking.extras_total:,.2f}.")
            except BookingError as exc:
                messages.error(request, str(exc))
            return redirect(reverse("dashboard:charges") + f"?booking={charge.booking_id}")

        booking = get_object_or_404(Booking.objects.select_related("apartment", "guest"), pk=p.get("booking"))
        source = p.get("source") if p.get("source") in dict(RoomCharge.SOURCE_CHOICES) else "desk"
        try:
            created = post_charges(booking, parse_ticket(p.get("ticket")), request.user, source=source, note=p.get("note", ""))
        except BookingError as exc:
            messages.error(request, str(exc))
            return redirect(reverse("dashboard:charges") + f"?booking={booking.pk}")
        added = sum((c.amount for c in created), ZERO)
        sym = settings.KUNDA["currency_symbol"]
        messages.success(request, f"Charged {sym} {added:,.2f} to Apt {booking.apartment.number} ({booking.guest.first_name}). Tab now {sym} {booking.extras_total:,.2f}.")
        return redirect(reverse("dashboard:charges") + f"?booking={booking.pk}")


class ExtrasMenuView(StaffMixin, View):
    """Price list for room charges, with stock for things you count."""
    section = "property"

    def get(self, request):
        since = timezone.localdate() - timedelta(days=30)
        items = ExtraItem.objects.annotate(
            sold=Sum("charges__quantity", filter=Q(charges__voided_at__isnull=True, charges__charged_on__gte=since)),
            revenue=Sum("charges__amount", filter=Q(charges__voided_at__isnull=True, charges__charged_on__gte=since)),
        )
        groups = []
        for key, label in ExtraItem.CATEGORY_CHOICES:
            g = [i for i in items if i.category == key]
            if g:
                groups.append({"label": label, "icon": ExtraItem.ICONS[key], "items": g})
        edit = ExtraItem.objects.filter(pk=request.GET.get("edit")).first() if request.GET.get("edit") else None
        top = RoomCharge.objects.filter(voided_at__isnull=True, charged_on__gte=since)
        return render(request, "dashboard/extras_menu.html", {
            "groups": groups, "edit": edit, "categories": ExtraItem.CATEGORY_CHOICES,
            "month_total": top.aggregate(s=Sum("amount"))["s"] or ZERO, "month_lines": top.count(),
            "custom_total": top.filter(item__isnull=True).aggregate(s=Sum("amount"))["s"] or ZERO,
        })

    def post(self, request):
        from stays.signals import log

        p = request.POST
        action = p.get("action")
        if action == "save":
            item = get_object_or_404(ExtraItem, pk=p["item"]) if p.get("item") else ExtraItem()
            name = p.get("name", "").strip()[:80]
            price = parse_decimal(p.get("price"))
            if not name or price is None or price < 0:
                messages.error(request, "An item needs a name and a price of zero or more.")
                return redirect(reverse("dashboard:extras_menu") + (f"?edit={item.pk}" if not item._state.adding else ""))
            old_price = None if item._state.adding else item.price
            item.name, item.price = name, price
            item.category = p.get("category") if p.get("category") in dict(ExtraItem.CATEGORY_CHOICES) else "other"
            item.unit = p.get("unit", "").strip()[:20]
            item.emoji = p.get("emoji", "").strip()[:4]
            item.stock = parse_int(p.get("stock"), None, 0, 100000) if p.get("stock", "").strip() != "" else None
            item.low_stock_at = parse_int(p.get("low_stock_at"), 5, 0, 10000)
            item.sort = parse_int(p.get("sort"), 100, 0, 1000)
            item.is_active = bool(p.get("is_active"))
            item.guest_can_order = bool(p.get("guest_can_order"))
            item.save()
            if old_price is not None and old_price != price:
                log("charges", f"Price of {item.name} changed {old_price:,.2f} → {price:,.2f}", reverse("dashboard:extras_menu"))
            elif old_price is None:
                log("charges", f"Added {item.name} to the extras menu at {price:,.2f}", reverse("dashboard:extras_menu"))
            messages.success(request, f"{item.name} saved. Existing charges keep the price they were posted at.")
        elif action == "restock":
            item = get_object_or_404(ExtraItem, pk=p.get("item"))
            n = parse_int(p.get("qty"), 0, -10000, 10000)
            if item.stock is None:
                item.stock = 0
            item.stock = max(0, item.stock + n)
            item.save(update_fields=["stock", "updated_at"])
            log("charges", f"Stock of {item.name} {'+' if n >= 0 else ''}{n} → {item.stock}", reverse("dashboard:extras_menu"))
            messages.success(request, f"{item.name}: {item.stock} in stock.")
        elif action == "toggle":
            item = get_object_or_404(ExtraItem, pk=p.get("item"))
            item.is_active = not item.is_active
            item.save(update_fields=["is_active", "updated_at"])
            messages.info(request, f"{item.name} {'is back on the menu' if item.is_active else 'hidden from the menu'}.")
        return redirect("dashboard:extras_menu")
