"""Day-to-day operations: the housekeeping board and the editable property profile."""
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from stays.models import Apartment, Booking, MaintenanceTicket, PropertyProfile

from .views import StaffMixin


class HousekeepingView(StaffMixin, View):
    """Every unit as a door card, sorted by what needs doing first. Built for phones."""
    section = "housekeeping"

    def get(self, request):
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        apartments = list(Apartment.objects.exclude(status=Apartment.INACTIVE).select_related("housekeeping_by"))
        in_house = {b.apartment_id: b for b in Booking.objects.filter(status=Booking.CHECKED_IN).select_related("guest")}
        upcoming = {}
        for b in Booking.objects.filter(status__in=[Booking.PENDING, Booking.CONFIRMED], check_in__gte=today).select_related("guest").order_by("check_in"):
            upcoming.setdefault(b.apartment_id, b)
        leaving = {b.apartment_id for b in in_house.values() if b.check_out <= today}
        tickets = {}
        for t in MaintenanceTicket.objects.exclude(status=MaintenanceTicket.RESOLVED):
            tickets.setdefault(t.apartment_id, []).append(t)

        cards = []
        for a in apartments:
            guest = in_house.get(a.id)
            nxt = upcoming.get(a.id)
            arriving_today = bool(nxt and nxt.check_in == today)
            arriving_tomorrow = bool(nxt and nxt.check_in == tomorrow)
            needs_work = a.housekeeping != Apartment.HK_INSPECTED
            if guest and a.id not in leaving:
                rank, tag = 8, "occupied"
            elif needs_work and arriving_today:
                rank, tag = 0, "urgent"
            elif a.id in leaving:
                rank, tag = 1, "leaving"
            elif needs_work and arriving_tomorrow:
                rank, tag = 2, "soon"
            elif needs_work:
                rank, tag = 3 + Apartment.HK_FLOW.index(a.housekeeping) * 0.1, "todo"
            else:
                rank, tag = 9, "ready"
            step = Apartment.HK_FLOW.index(a.housekeeping)
            cards.append({
                "apt": a, "guest": guest, "next": nxt, "arriving_today": arriving_today, "arriving_tomorrow": arriving_tomorrow,
                "leaving": a.id in leaving, "rank": rank, "tag": tag, "step": step,
                "next_state": Apartment.HK_FLOW[step + 1] if step < 3 else None,
                "next_label": dict(Apartment.HK_CHOICES)[Apartment.HK_FLOW[step + 1]] if step < 3 else None,
                "tickets": tickets.get(a.id, []),
            })
        cards.sort(key=lambda c: (c["rank"], c["apt"].number))
        counts = {s: sum(1 for c in cards if c["apt"].housekeeping == s) for s in Apartment.HK_FLOW}
        return render(request, "dashboard/housekeeping.html", {
            "cards": cards, "counts": counts, "flow": [(s, dict(Apartment.HK_CHOICES)[s]) for s in Apartment.HK_FLOW],
            "today": today, "urgent": sum(1 for c in cards if c["tag"] == "urgent"),
            "checkin_time": settings.KUNDA["checkin_time"],
        })

    def post(self, request):
        a = get_object_or_404(Apartment, pk=request.POST.get("apartment"))
        state = request.POST.get("state")
        if state not in Apartment.HK_FLOW:
            messages.error(request, "Choose a valid room state.")
            return redirect("dashboard:housekeeping")
        from stays.signals import log

        a.housekeeping = state
        a.housekeeping_note = request.POST.get("note", a.housekeeping_note if state != Apartment.HK_DIRTY else "").strip()[:200]
        a.housekeeping_at = timezone.now()
        a.housekeeping_by = request.user
        a.save(update_fields=["housekeeping", "housekeeping_note", "housekeeping_at", "housekeeping_by", "updated_at"])
        log("housekeeping", f"Apt {a.number} → {a.get_housekeeping_display()}", "/dashboard/housekeeping/")
        if request.headers.get("x-requested-with") == "fetch":
            from django.http import JsonResponse

            return JsonResponse({"ok": True, "state": state, "label": a.get_housekeeping_display()})
        messages.success(request, f"Apt {a.number}: {a.get_housekeeping_display()}.")
        return redirect("dashboard:housekeeping")


class PropertyProfileView(StaffMixin, View):
    """Business details, contacts, payment numbers and policies — no redeploy needed."""
    section = "property"

    GROUPS = [
        ("Identity", "building", [("name", "Business name", "text"), ("tagline", "Tagline", "text")]),
        ("Contact & location", "geo-alt", [
            ("phone", "Phone", "text"), ("whatsapp", "WhatsApp number (digits, with country code)", "text"), ("email", "Email", "email"),
            ("address", "Address", "text"), ("lat", "Latitude", "text"), ("lng", "Longitude", "text"),
        ]),
        ("Stay rules", "clock", [
            ("checkin_time", "Check-in from", "time"), ("checkout_time", "Check-out by", "time"), ("hold_hours", "Hours to pay a deposit before a hold is released", "number"),
        ]),
        ("Payment details shown to guests", "wallet2", [
            ("wave_number", "Wave number", "text"), ("afrimoney_number", "Afrimoney number", "text"), ("qmoney_number", "QMoney number", "text"),
            ("bank_details", "Bank details", "text"),
        ]),
    ]

    def get(self, request):
        prof = PropertyProfile.get()
        defaults = settings.KUNDA_DEFAULTS
        groups = [
            {"title": t, "icon": i, "fields": [{"name": n, "label": l, "type": ty, "value": getattr(prof, n) if getattr(prof, n) is not None else "", "default": defaults.get(n, "")} for n, l, ty in fs]}
            for t, i, fs in self.GROUPS
        ]
        return render(request, "dashboard/property.html", {"prof": prof, "groups": groups, "defaults": defaults})

    def post(self, request):
        prof = PropertyProfile.get()
        p = request.POST
        if p.get("action") == "reset":
            prof.delete()
            PropertyProfile.get()
            from stays.middleware import apply_property_profile

            apply_property_profile(force=True)
            messages.info(request, "Profile reset. The site is using the values from the server settings again.")
            return redirect("dashboard:property")
        for _, _, fields in self.GROUPS:
            for name, _, kind in fields:
                raw = p.get(name, "").strip()
                if kind == "number":
                    setattr(prof, name, int(raw) if raw.isdigit() and 1 <= int(raw) <= 168 else None)
                else:
                    setattr(prof, name, raw[: PropertyProfile._meta.get_field(name).max_length or 1000])
        prof.house_rules = p.get("house_rules", "").strip()
        prof.cancellation_policy = p.get("cancellation_policy", "").strip()
        prof.updated_by = request.user
        prof.save()
        from stays.middleware import apply_property_profile

        apply_property_profile(force=True)
        messages.success(request, "Property profile saved. The website, receipts and WhatsApp messages use it now.")
        return redirect("dashboard:property")
