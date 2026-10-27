"""Automatic activity log + housekeeping hooks.

Every important change is written to ActivityLog from here, so the staff views stay
simple and nothing is forgotten — whether the change came from the portal, the guest
website, the Django admin or a Celery task.
"""
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_delete, post_init, post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from .models import (ActivityLog, Apartment, Booking, CashUp, Expense, Payment, PropertyProfile, RateRule)


def log(category, summary, link="", user=None, actor=""):
    from .middleware import current_ip, current_user

    user = user or current_user()
    try:
        ActivityLog.objects.create(
            user=user, actor=actor if not user else "", category=category, summary=summary[:255], link=link[:255],
            ip=current_ip(),
        )
    except Exception:  # logging must never break the real action
        pass


def _money(v):
    from django.conf import settings

    return f"{settings.KUNDA['currency_symbol']} {v:,.0f}"


# ---------- remember original values so we can describe what changed ----------

@receiver(post_init, sender=Booking)
def _booking_init(sender, instance, **kwargs):
    instance._orig = (instance.status, instance.check_in, instance.check_out) if instance.pk else None


@receiver(post_init, sender=Payment)
def _payment_init(sender, instance, **kwargs):
    instance._orig_status = instance.status if instance.pk else None


@receiver(post_init, sender=Apartment)
def _apartment_init(sender, instance, **kwargs):
    instance._orig_rates = (instance.daily_rate, instance.monthly_rate, instance.cleaning_fee) if instance.pk else None


# ---------- bookings ----------

STATUS_VERBS = {
    Booking.CONFIRMED: "Confirmed",
    Booking.CHECKED_IN: "Checked in",
    Booking.CHECKED_OUT: "Checked out",
    Booking.CANCELLED: "Cancelled",
    Booking.NO_SHOW: "Marked no-show",
}


@receiver(post_save, sender=Booking)
def _booking_saved(sender, instance, created, **kwargs):
    b = instance
    link = reverse("dashboard:booking", args=[b.pk])
    who = f"{b.reference} · {b.guest.full_name} · Apt {b.apartment.number}"
    if created:
        actor = "Guest (website)" if b.source == "website" and not b.created_by_id else ""
        log("booking", f"New booking {who} ({b.check_in:%d %b}–{b.check_out:%d %b})", link, actor=actor)
    elif b._orig:
        old_status, old_ci, old_co = b._orig
        if old_status != b.status and b.status in STATUS_VERBS:
            log("booking", f"{STATUS_VERBS[b.status]} {who}", link)
            if b.status == Booking.CHECKED_OUT:
                # The unit needs turning over before the next guest.
                Apartment.objects.filter(pk=b.apartment_id).update(
                    housekeeping=Apartment.HK_DIRTY, housekeeping_note=f"Checked out {timezone.localtime():%H:%M}",
                    housekeeping_at=timezone.now(), housekeeping_by=None,
                )
        if (old_ci, old_co) != (b.check_in, b.check_out):
            log("booking", f"Changed dates {who} to {b.check_in:%d %b}–{b.check_out:%d %b}, new total {_money(b.total_amount)}", link)
    b._orig = (b.status, b.check_in, b.check_out)


# ---------- payments ----------

@receiver(post_save, sender=Payment)
def _payment_saved(sender, instance, created, **kwargs):
    p = instance
    link = reverse("dashboard:booking", args=[p.booking_id])
    ref = p.booking.reference
    if created and p.submitted_by_guest:
        log("payment", f"Guest reported {_money(p.amount)} via {p.get_method_display()} for {ref} — needs verifying", link, actor="Guest (website)")
    elif p._orig_status != p.status:
        if p.status == Payment.CONFIRMED:
            verb = "Refunded" if p.kind == Payment.REFUND else "Received"
            log("payment", f"{verb} {_money(p.amount)} via {p.get_method_display()} for {ref} · receipt {p.receipt_number}", link)
        elif p.status == Payment.REJECTED:
            log("payment", f"Rejected {_money(p.amount)} {p.get_method_display()} payment for {ref}", link)
    p._orig_status = p.status


# ---------- pricing & property ----------

@receiver(post_save, sender=Apartment)
def _apartment_saved(sender, instance, created, **kwargs):
    a = instance
    link = reverse("dashboard:apartment_edit", args=[a.pk])
    if created:
        log("property", f"Added Apt {a.number} – {a.name}", link)
    elif a._orig_rates and a._orig_rates[0] != a.daily_rate:
        log("rates", f"Apt {a.number} nightly rate {_money(a._orig_rates[0])} → {_money(a.daily_rate)}", link)
    a._orig_rates = (a.daily_rate, a.monthly_rate, a.cleaning_fee)


@receiver(post_save, sender=RateRule)
def _rule_saved(sender, instance, created, **kwargs):
    r = instance
    state = "" if r.is_active else " (paused)"
    log("rates", f"{'Created' if created else 'Updated'} price rule “{r.name}” {r.effect_label}, {r.start:%d %b}–{r.end:%d %b %Y}{state}", reverse("dashboard:rates"))


@receiver(post_delete, sender=RateRule)
def _rule_deleted(sender, instance, **kwargs):
    log("rates", f"Deleted price rule “{instance.name}”", reverse("dashboard:rates"))


@receiver(post_save, sender=PropertyProfile)
def _profile_saved(sender, instance, **kwargs):
    log("property", "Updated the property profile (business details, policies, payment numbers)", reverse("dashboard:property"))


# ---------- finance ----------

@receiver(post_save, sender=Expense)
def _expense_saved(sender, instance, created, **kwargs):
    if created:
        e = instance
        log("finance", f"Expense {_money(e.amount)} · {e.get_category_display()} · {e.description}", reverse("dashboard:expenses"))


@receiver(post_delete, sender=Expense)
def _expense_deleted(sender, instance, **kwargs):
    log("finance", f"Deleted expense {_money(instance.amount)} · {instance.description}", reverse("dashboard:expenses"))


@receiver(post_save, sender=CashUp)
def _cashup_saved(sender, instance, created, **kwargs):
    c = instance
    if created:
        v = c.variance
        state = "balanced" if v == 0 else (f"over by {_money(v)}" if v > 0 else f"short by {_money(-v)}")
        log("finance", f"Closed the till for {c.business_date:%d %b} — counted {_money(c.counted_cash)}, {state}", reverse("dashboard:till"))


# ---------- sign-in ----------

@receiver(user_logged_in)
def _logged_in(sender, request, user, **kwargs):
    log("auth", "Signed in", user=user)


@receiver(user_logged_out)
def _logged_out(sender, request, user, **kwargs):
    if user is not None:
        log("auth", "Signed out", user=user)


@receiver(user_login_failed)
def _login_failed(sender, credentials, request=None, **kwargs):
    name = (credentials or {}).get("username", "")[:60]
    log("auth", f"Failed sign-in attempt for “{name}”", actor="Unknown")
