"""Finance: profit & loss, expenses ledger and the end-of-shift till count."""
import csv
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from stays.models import ZERO, Apartment, Booking, CashUp, Expense, MaintenanceTicket, Payment
from stays.utils import parse_date, parse_decimal, parse_int

from .roles import can
from .views import StaffMixin, _month_add

CATEGORY_ICONS = {
    "electricity": "lightning-charge", "water": "droplet", "fuel": "fuel-pump", "internet": "wifi", "salaries": "people",
    "cleaning": "basket", "supplies": "box-seam", "repairs": "wrench-adjustable", "security": "shield-check",
    "marketing": "megaphone", "tax": "bank", "rent": "house-door", "other": "three-dots",
}


def _period(request):
    """(start, end_exclusive, label, key) from ?period= or ?from=&to=."""
    today = timezone.localdate()
    key = request.GET.get("period", "month")
    frm, to = parse_date(request.GET.get("from")), parse_date(request.GET.get("to"))
    if frm and to and to >= frm:
        return frm, to + timedelta(days=1), f"{frm:%d %b %Y} – {to:%d %b %Y}", "custom"
    month = today.replace(day=1)
    if key == "last_month":
        s = _month_add(month, -1)
        return s, month, s.strftime("%B %Y"), key
    if key == "year":
        s = today.replace(month=1, day=1)
        return s, today + timedelta(days=1), f"{today.year} so far", key
    if key == "30d":
        return today - timedelta(days=29), today + timedelta(days=1), "Last 30 days", key
    return month, _month_add(month, 1), month.strftime("%B %Y"), "month"


class FinanceView(StaffMixin, View):
    section = "finance"

    def get(self, request):
        from stays.services import signed_amount

        start, end, label, key = _period(request)
        today = timezone.localdate()
        pays = Payment.objects.filter(status=Payment.CONFIRMED, paid_at__date__gte=start, paid_at__date__lt=end)
        income = pays.aggregate(s=Sum(signed_amount()))["s"] or ZERO
        expenses = Expense.objects.filter(spent_on__gte=start, spent_on__lt=end)
        tickets = MaintenanceTicket.objects.filter(created_at__date__gte=start, created_at__date__lt=end, cost__gt=0)
        ticket_cost = tickets.aggregate(s=Sum("cost"))["s"] or ZERO
        spent = (expenses.aggregate(s=Sum("amount"))["s"] or ZERO) + ticket_cost
        net = income - spent

        if request.GET.get("export") == "csv":
            return self._csv(start, end, pays, expenses, tickets)

        names = dict(Expense.CATEGORY_CHOICES)
        by_cat = [
            {"key": r["category"], "label": names.get(r["category"], r["category"]), "total": r["total"], "n": r["n"], "icon": CATEGORY_ICONS.get(r["category"], "tag")}
            for r in expenses.values("category").annotate(total=Sum("amount"), n=Count("id")).order_by("-total")
        ]
        if ticket_cost:
            by_cat.append({"key": "tickets", "label": "Maintenance tickets", "total": ticket_cost, "n": tickets.count(), "icon": "tools"})
            by_cat.sort(key=lambda r: -r["total"])
        top = max((r["total"] for r in by_cat), default=ZERO) or Decimal(1)
        for r in by_cat:
            r["pct"] = int(r["total"] / top * 100)

        method_names = dict(Payment.METHOD_CHOICES)
        by_method = [
            {"label": method_names.get(r["method"], r["method"]), "total": r["total"], "n": r["n"]}
            for r in pays.values("method").annotate(total=Sum(signed_amount()), n=Count("id")).order_by("-total")
        ]

        # Per-apartment profitability
        per_apt = {a.id: {"apt": a, "income": ZERO, "costs": ZERO} for a in Apartment.objects.exclude(status=Apartment.INACTIVE)}
        for r in pays.values("booking__apartment_id").annotate(t=Sum(signed_amount())):
            if r["booking__apartment_id"] in per_apt:
                per_apt[r["booking__apartment_id"]]["income"] = r["t"]
        for r in expenses.exclude(apartment=None).values("apartment_id").annotate(t=Sum("amount")):
            if r["apartment_id"] in per_apt:
                per_apt[r["apartment_id"]]["costs"] += r["t"]
        for r in tickets.values("apartment_id").annotate(t=Sum("cost")):
            if r["apartment_id"] in per_apt:
                per_apt[r["apartment_id"]]["costs"] += r["t"]
        apt_rows = sorted(per_apt.values(), key=lambda r: -(r["income"] - r["costs"]))
        for r in apt_rows:
            r["net"] = r["income"] - r["costs"]
        shared = expenses.filter(apartment=None).aggregate(s=Sum("amount"))["s"] or ZERO

        # 12-month trend ending with the period's month
        last = (end - timedelta(days=1)).replace(day=1)
        first = _month_add(last, -11)
        inc_m = {r["m"].date() if hasattr(r["m"], "date") else r["m"]: r["t"] for r in Payment.objects.filter(
            status=Payment.CONFIRMED, paid_at__date__gte=first, paid_at__date__lt=_month_add(last, 1)
        ).annotate(m=TruncMonth("paid_at")).values("m").annotate(t=Sum(signed_amount()))}
        exp_m = {r["m"]: r["t"] for r in Expense.objects.filter(spent_on__gte=first, spent_on__lt=_month_add(last, 1)).annotate(m=TruncMonth("spent_on")).values("m").annotate(t=Sum("amount"))}
        tick_m = {r["m"].date() if hasattr(r["m"], "date") else r["m"]: r["t"] for r in MaintenanceTicket.objects.filter(created_at__date__gte=first, created_at__date__lt=_month_add(last, 1), cost__gt=0).annotate(m=TruncMonth("created_at")).values("m").annotate(t=Sum("cost"))}
        trend = {"labels": [], "income": [], "expenses": [], "net": []}
        for i in range(12):
            m = _month_add(first, i)
            inc, exp = float(inc_m.get(m, 0) or 0), float((exp_m.get(m, 0) or 0) + (tick_m.get(m, 0) or 0))
            trend["labels"].append(m.strftime("%b %y"))
            trend["income"].append(inc)
            trend["expenses"].append(exp)
            trend["net"].append(inc - exp)

        # Receivables ageing
        buckets = [
            {"key": "future", "label": "Arriving later", "hint": "Deposits and balances not yet due", "items": [], "total": ZERO},
            {"key": "inhouse", "label": "In house now", "hint": "Collect before check-out", "items": [], "total": ZERO},
            {"key": "recent", "label": "Left in the last 30 days", "hint": "Chase this week", "items": [], "total": ZERO},
            {"key": "old", "label": "Left over 30 days ago", "hint": "Consider writing off or a final reminder", "items": [], "total": ZERO},
        ]
        for b in Booking.objects.filter(status__in=Booking.ACTIVE + (Booking.CHECKED_OUT,)).select_related("guest", "apartment").prefetch_related("payments"):
            bal = b.balance
            if bal <= 0:
                continue
            if b.status == Booking.CHECKED_IN:
                i = 1
            elif b.status == Booking.CHECKED_OUT:
                i = 2 if b.check_out >= today - timedelta(days=30) else 3
            else:
                i = 0
            buckets[i]["items"].append(b)
            buckets[i]["total"] += bal
        receivable = sum((x["total"] for x in buckets), ZERO)

        return render(request, "dashboard/finance.html", {
            "start": start, "end": end - timedelta(days=1), "label": label, "key": key,
            "income": income, "spent": spent, "net": net, "margin": int(net / income * 100) if income > 0 else None,
            "by_cat": by_cat, "by_method": by_method, "apt_rows": apt_rows, "shared": shared,
            "trend": trend, "buckets": buckets, "receivable": receivable,
            "unreviewed": CashUp.objects.filter(reviewed_at__isnull=True).count(),
        })

    def _csv(self, start, end, pays, expenses, tickets):
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="ledger-{start}-{end - timedelta(days=1)}.csv"'
        w = csv.writer(resp)
        w.writerow(["Date", "Direction", "Category / method", "Description", "Apartment", "Amount", "Reference", "Receipt no."])
        rows = []
        for p in pays.select_related("booking__guest", "booking__apartment"):
            amt = -p.amount if p.kind == Payment.REFUND else p.amount
            rows.append([timezone.localtime(p.paid_at).date(), "In", p.get_method_display(), f"{p.get_kind_display()} · {p.booking.reference} · {p.booking.guest.full_name}", p.booking.apartment.number, amt, p.reference, p.receipt_number or ""])
        for e in expenses.select_related("apartment"):
            rows.append([e.spent_on, "Out", e.get_category_display(), f"{e.description}{' · ' + e.payee if e.payee else ''}", e.apartment.number if e.apartment else "Shared", -e.amount, e.reference, ""])
        for t in tickets.select_related("apartment"):
            rows.append([timezone.localtime(t.created_at).date(), "Out", "Maintenance ticket", t.title, t.apartment.number, -t.cost, "", ""])
        for r in sorted(rows, key=lambda r: r[0]):
            w.writerow(r)
        return resp


class ExpensesView(StaffMixin, View):
    section = "finance"

    def get(self, request):
        qs = Expense.objects.select_related("apartment", "recorded_by")
        f = request.GET
        frm, to = parse_date(f.get("from")), parse_date(f.get("to"))
        if not frm and not to and not f.get("all"):
            frm = timezone.localdate().replace(day=1)
        if frm:
            qs = qs.filter(spent_on__gte=frm)
        if to:
            qs = qs.filter(spent_on__lte=to)
        if f.get("category"):
            qs = qs.filter(category=f["category"])
        if f.get("apartment"):
            qs = qs.filter(apartment_id=f["apartment"]) if f["apartment"] != "shared" else qs.filter(apartment=None)
        total = qs.aggregate(s=Sum("amount"))["s"] or ZERO
        payees = list(Expense.objects.exclude(payee="").values_list("payee", flat=True).distinct()[:40])
        return render(request, "dashboard/expenses.html", {
            "page": Paginator(qs, 30).get_page(f.get("page")), "total": total, "count": qs.count(),
            "categories": [(k, l, CATEGORY_ICONS.get(k, "tag")) for k, l in Expense.CATEGORY_CHOICES],
            "methods": Expense.METHOD_CHOICES, "apartments": Apartment.objects.all(), "f": f, "frm": frm, "to": to,
            "today": timezone.localdate(), "payees": payees,
        })

    def post(self, request):
        p = request.POST
        if p.get("action") == "delete":
            e = get_object_or_404(Expense, pk=p.get("expense"))
            if e.receipt:
                e.receipt.delete(save=False)
            e.delete()
            messages.info(request, "Expense deleted.")
            return redirect(request.META.get("HTTP_REFERER") or "dashboard:expenses")

        amount = parse_decimal(p.get("amount"))
        spent_on = parse_date(p.get("spent_on")) or timezone.localdate()
        desc = p.get("description", "").strip()[:200]
        if not amount or amount <= 0 or not desc:
            messages.error(request, "An expense needs an amount and a short description.")
            return redirect("dashboard:expenses")
        if spent_on > timezone.localdate():
            messages.error(request, "The date can't be in the future.")
            return redirect("dashboard:expenses")
        receipt = request.FILES.get("receipt")
        if receipt and receipt.size > 10 * 1024 * 1024:
            messages.error(request, "Receipt files must be under 10 MB.")
            return redirect("dashboard:expenses")
        e = Expense(
            spent_on=spent_on, amount=amount, description=desc,
            category=p.get("category") if p.get("category") in dict(Expense.CATEGORY_CHOICES) else "other",
            payee=p.get("payee", "").strip()[:120], method=p.get("method") if p.get("method") in dict(Expense.METHOD_CHOICES) else "cash",
            reference=p.get("reference", "").strip()[:80], recorded_by=request.user,
            apartment=Apartment.objects.filter(pk=p.get("apartment")).first() if p.get("apartment") else None,
        )
        if receipt:
            e.receipt = receipt
        e.save()
        messages.success(request, f"Expense of {settings.KUNDA['currency_symbol']} {amount:,.2f} recorded.")
        return redirect("dashboard:expenses")


class TillView(StaffMixin, View):
    """Close the till: count the cash drawer and tick off mobile-money takings."""
    section = "till"

    def _takings(self, user, day):
        pays = Payment.objects.filter(status=Payment.CONFIRMED, received_by=user, paid_at__date=day).select_related("booking__guest", "booking__apartment").order_by("paid_at")
        methods = {}
        expected_cash = ZERO
        for p in pays:
            amt = -p.amount if p.kind == Payment.REFUND else p.amount
            m = methods.setdefault(p.method, {"label": p.get_method_display(), "total": ZERO, "count": 0})
            m["total"] += amt
            m["count"] += 1
            if p.method == "cash":
                expected_cash += amt
        return list(pays), methods, expected_cash

    def get(self, request):
        today = timezone.localdate()
        day = parse_date(request.GET.get("date")) if can(request.user, "finance") else None
        day = day or today
        pays, methods, expected_cash = self._takings(request.user, day)
        closed = CashUp.objects.filter(staff=request.user, business_date=day).first()
        history = CashUp.objects.select_related("staff", "reviewed_by")
        if not can(request.user, "finance"):
            history = history.filter(staff=request.user)
        return render(request, "dashboard/till.html", {
            "day": day, "today": today, "pays": pays, "methods": methods, "expected_cash": expected_cash,
            "non_cash": {k: v for k, v in methods.items() if k != "cash"},
            "denoms": settings.KUNDA["cash_denominations"], "closed": closed,
            "history": history[:25], "reviewer": can(request.user, "finance"),
        })

    def post(self, request):
        p = request.POST
        if p.get("action") == "review":
            if not can(request.user, "finance"):
                messages.error(request, "Only finance or a manager can sign off a till.")
                return redirect("dashboard:till")
            c = get_object_or_404(CashUp, pk=p.get("cashup"))
            if c.staff_id == request.user.id and not request.user.is_superuser:
                messages.error(request, "Someone else should sign off your own till.")
                return redirect("dashboard:till")
            c.reviewed_by, c.reviewed_at = request.user, timezone.now()
            c.save(update_fields=["reviewed_by", "reviewed_at", "updated_at"])
            messages.success(request, f"Signed off {c.staff.get_username()}'s till for {c.business_date:%d %b}.")
            return redirect("dashboard:till")

        day = timezone.localdate()
        if CashUp.objects.filter(staff=request.user, business_date=day).exists() and not p.get("again"):
            messages.info(request, "You've already closed today's till.")
            return redirect("dashboard:till")
        _, methods, expected_cash = self._takings(request.user, day)
        counts, counted = {}, ZERO
        for d in settings.KUNDA["cash_denominations"]:
            n = parse_int(p.get(f"count_{d}"), 0, 0, 100000)
            if n:
                counts[str(d)] = n
                counted += Decimal(d) * n
        loose = parse_decimal(p.get("loose"), ZERO) or ZERO
        if loose:
            counts["loose"] = str(loose)
            counted += loose
        float_amount = parse_decimal(p.get("float"), ZERO) or ZERO
        checked = set(p.getlist("checked"))
        method_data = {k: {"label": v["label"], "total": str(v["total"]), "count": v["count"], "checked": k in checked} for k, v in methods.items()}
        unchecked = [v["label"] for k, v in methods.items() if k != "cash" and k not in checked]
        note = p.get("note", "").strip()
        c = CashUp.objects.create(
            business_date=day, staff=request.user, expected_cash=expected_cash, counted_cash=counted, float_amount=float_amount,
            counts=counts, methods=method_data, note=note,
        )
        v = c.variance
        if v == 0:
            messages.success(request, "Till closed and balanced. Nice work.")
        else:
            word = "over" if v > 0 else "short"
            messages.warning(request, f"Till closed {word} by {settings.KUNDA['currency_symbol']} {abs(v):,.2f}. Finance will review it.")
        if unchecked:
            messages.info(request, f"Not yet matched to statements: {', '.join(unchecked)}.")
        return redirect("dashboard:till")
