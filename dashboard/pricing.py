"""Rates & pricing studio: base rates, stacking price rules and the month price heatmap."""
import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from stays.models import ZERO, Apartment, Booking, RateRule
from stays.utils import parse_date, parse_decimal, parse_int

from .views import StaffMixin, _month_add


def _compact(v):
    v = float(v)
    if v >= 1000:
        s = f"{v / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{s}k"
    return f"{v:.0f}"


def _season_dates(today, start_month, start_day, end_month, end_day):
    """Next occurrence of a seasonal window that may cross New Year."""
    start = date(today.year, start_month, start_day)
    end_year = today.year + (1 if (end_month, end_day) < (start_month, start_day) else 0)
    end = date(end_year, end_month, end_day)
    if end < today:
        start, end = date(start.year + 1, start_month, start_day), date(end.year + 1, end_month, end_day)
    return start.isoformat(), end.isoformat()


def presets(today):
    hs = _season_dates(today, 11, 1, 4, 30)
    xmas = _season_dates(today, 12, 20, 1, 3)
    rainy = _season_dates(today, 7, 1, 9, 30)
    year_end = date(today.year + 1, today.month, 1) - timedelta(days=1)
    return [
        {"label": "Tourist high season", "icon": "sun", "name": "High season (Nov–Apr)", "start": hs[0], "end": hs[1], "type": "percent", "value": "15", "weekdays": "0123456", "min_nights": 0, "colour": "#F2B705"},
        {"label": "Christmas & New Year", "icon": "stars", "name": "Festive peak", "start": xmas[0], "end": xmas[1], "type": "percent", "value": "25", "weekdays": "0123456", "min_nights": 0, "colour": "#B8336A"},
        {"label": "Weekend nights", "icon": "moon-stars", "name": "Weekend (Fri & Sat)", "start": today.isoformat(), "end": year_end.isoformat(), "type": "percent", "value": "10", "weekdays": "45", "min_nights": 0, "colour": "#0E6A78"},
        {"label": "Rainy season deal", "icon": "cloud-drizzle", "name": "Rainy season (Jul–Sep)", "start": rainy[0], "end": rainy[1], "type": "percent", "value": "-15", "weekdays": "0123456", "min_nights": 0, "colour": "#1F6F50"},
        {"label": "Week-long stay", "icon": "calendar-week", "name": "7+ nights discount", "start": today.isoformat(), "end": year_end.isoformat(), "type": "percent", "value": "-10", "weekdays": "0123456", "min_nights": 7, "colour": "#2E9468"},
    ]


class RatesView(StaffMixin, View):
    section = "property"

    def get(self, request):
        from stays.services import nightly_prices

        today = timezone.localdate()
        try:
            y, m = map(int, (request.GET.get("month") or "").split("-"))
            month_start = date(y, m, 1)
        except ValueError:
            month_start = today.replace(day=1)
        month_end = _month_add(month_start, 1)
        days = [month_start + timedelta(days=i) for i in range((month_end - month_start).days)]

        apartments = list(Apartment.objects.exclude(status=Apartment.INACTIVE))
        rules = list(RateRule.objects.filter(is_active=True, start__lt=month_end, end__gte=month_start).prefetch_related("apartments"))
        rule_apts = {r.id: {a.id for a in r.apartments.all()} for r in rules}

        busy = set()
        for apt_id, ci, co in Booking.objects.filter(status__in=Booking.ACTIVE + (Booking.CHECKED_OUT,), check_in__lt=month_end, check_out__gt=month_start).values_list("apartment_id", "check_in", "check_out"):
            d = max(ci, month_start)
            while d < min(co, month_end):
                busy.add((apt_id, d))
                d += timedelta(days=1)

        rows = []
        for a in apartments:
            mine = [r for r in rules if not rule_apts[r.id] or a.id in rule_apts[r.id]]
            cells = []
            for day, price, applied in nightly_prices(a, month_start, month_end, stay_nights=1, rules=mine):
                ratio = (price / a.daily_rate) if a.daily_rate else Decimal(1)
                level = "fixed" if any(r.adjust_type == RateRule.FIXED for r, _ in applied) else (
                    "down" if ratio < Decimal("0.97") else "base" if ratio <= Decimal("1.03") else "up" if ratio <= Decimal("1.16") else "peak"
                )
                cells.append({
                    "day": day, "price": price, "short": _compact(price), "level": level, "booked": (a.id, day) in busy,
                    "past": day < today, "rules": ", ".join(r.name for r, _ in applied),
                })
            month_value = sum((c["price"] for c in cells if c["booked"]), ZERO)
            rows.append({"apt": a, "cells": cells, "booked_value": month_value, "booked_nights": sum(1 for c in cells if c["booked"])})

        lanes = []
        for r in rules:
            if r.min_nights > 1:
                continue  # depends on stay length, so it can't be drawn per night
            s, e = max(r.start, month_start), min(r.end + timedelta(days=1), month_end)
            lanes.append({"rule": r, "col": (s - month_start).days + 2, "span": max(1, (e - s).days), "apts": len(rule_apts[r.id])})

        edit = None
        if request.GET.get("edit"):
            edit = RateRule.objects.filter(pk=request.GET["edit"]).prefetch_related("apartments").first()
        all_rules = RateRule.objects.prefetch_related("apartments").order_by("-is_active", "priority", "start")
        return render(request, "dashboard/rates.html", {
            "apartments": apartments, "rows": rows, "days": days, "lanes": lanes, "month": month_start, "today": today,
            "prev": _month_add(month_start, -1), "next": month_end, "rules": all_rules, "edit": edit,
            "edit_apts": {a.id for a in edit.apartments.all()} if edit else set(),
            "types": RateRule.TYPE_CHOICES, "weekdays": list(enumerate(RateRule.WEEKDAYS)),
            "presets": presets(today), "default_end": (today + timedelta(days=30)).isoformat(),
        })

    def post(self, request):
        p = request.POST
        action = p.get("action")
        back = reverse("dashboard:rates") + (f"?month={p['month']}" if p.get("month") else "")

        if action == "save_rule":
            rule = get_object_or_404(RateRule, pk=p["rule"]) if p.get("rule") else RateRule(created_by=request.user)
            start, end = parse_date(p.get("start")), parse_date(p.get("end"))
            value = parse_decimal(p.get("value"))
            name = p.get("name", "").strip()[:80]
            weekdays = "".join(sorted(set(d for d in p.getlist("weekdays") if d in "0123456")))
            errors = []
            if not name:
                errors.append("Give the rule a name guests will understand, e.g. “High season”.")
            if not start or not end or end < start:
                errors.append("Choose a start date and an end date on or after it.")
            if value is None:
                errors.append("Enter how much the price changes.")
            if not weekdays:
                errors.append("Tick at least one night of the week.")
            if p.get("adjust_type") == RateRule.FIXED and value is not None and value <= 0:
                errors.append("A set nightly price must be more than zero.")
            if p.get("adjust_type") == RateRule.PERCENT and value is not None and value <= -100:
                errors.append("A percentage can't take the price below zero.")
            if errors:
                for e in errors:
                    messages.error(request, e)
                edit_qs = "new=1#rule-form" if rule._state.adding else f"edit={rule.pk}#rule-form"
                return redirect(back + ("&" if "?" in back else "?") + edit_qs)
            rule.name, rule.start, rule.end, rule.value, rule.weekdays = name, start, end, value, weekdays
            rule.adjust_type = p.get("adjust_type") if p.get("adjust_type") in dict(RateRule.TYPE_CHOICES) else RateRule.PERCENT
            rule.min_nights = parse_int(p.get("min_nights"), 0, 0, 365)
            rule.priority = parse_int(p.get("priority"), 10, -100, 100)
            rule.colour = (p.get("colour") or "#F2B705")[:7]
            rule.is_active = bool(p.get("is_active"))
            rule.save()
            rule.apartments.set(Apartment.objects.filter(pk__in=[i for i in p.getlist("apartments") if i]))
            messages.success(request, f"Rule “{rule.name}” saved. Quotes use it straight away.")
        elif action == "toggle_rule":
            rule = get_object_or_404(RateRule, pk=p.get("rule"))
            rule.is_active = not rule.is_active
            rule.save()
            messages.info(request, f"“{rule.name}” {'switched on' if rule.is_active else 'paused'}.")
        elif action == "delete_rule":
            rule = get_object_or_404(RateRule, pk=p.get("rule"))
            name = rule.name
            rule.delete()
            messages.info(request, f"Rule “{name}” deleted. Existing bookings keep the price they were quoted.")
        elif action == "save_base":
            changed = 0
            for a in Apartment.objects.all():
                daily = parse_decimal(p.get(f"daily_{a.pk}"))
                if daily is None or daily <= 0:
                    continue
                monthly = parse_decimal(p.get(f"monthly_{a.pk}")) or None
                cleaning = parse_decimal(p.get(f"cleaning_{a.pk}"), ZERO) or ZERO
                deposit = parse_int(p.get(f"deposit_{a.pk}"), a.deposit_percent, 0, 100)
                if (daily, monthly, cleaning, deposit) != (a.daily_rate, a.monthly_rate, a.cleaning_fee, a.deposit_percent):
                    a.daily_rate, a.monthly_rate, a.cleaning_fee, a.deposit_percent = daily, monthly, cleaning, deposit
                    a.save()
                    changed += 1
            messages.success(request, f"Base rates saved for {changed} apartment{'s' if changed != 1 else ''}." if changed else "No base rates changed.")
        elif action == "bulk_adjust":
            pct = parse_decimal(p.get("percent"))
            step = parse_int(p.get("round_to"), 50, 1, 1000)
            ids = [i for i in p.getlist("bulk_apts") if i]
            if pct is None or pct <= -100:
                messages.error(request, "Enter a percentage, e.g. 5 or -10.")
                return redirect(back)
            qs = Apartment.objects.filter(pk__in=ids) if ids else Apartment.objects.exclude(status=Apartment.INACTIVE)
            n = 0
            for a in qs:
                raw = a.daily_rate * (Decimal(100) + pct) / Decimal(100)
                a.daily_rate = max((raw / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step, Decimal(step))
                if a.monthly_rate and p.get("include_monthly"):
                    rawm = a.monthly_rate * (Decimal(100) + pct) / Decimal(100)
                    a.monthly_rate = max((rawm / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step, Decimal(step))
                a.save()
                n += 1
            messages.success(request, f"Nightly rates changed by {pct:g}% on {n} apartment{'s' if n != 1 else ''}, rounded to {step}.")
        return redirect(back)
