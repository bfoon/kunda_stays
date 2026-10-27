from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings

from ..whatsapp import link

register = template.Library()


@register.filter
def money(value):
    try:
        v = Decimal(value or 0)
    except (InvalidOperation, TypeError):
        return value
    s = f"{v:,.0f}" if v == v.to_integral_value() else f"{v:,.2f}"
    return f"{settings.KUNDA['currency_symbol']} {s}"


STATUS_CLASSES = {
    "pending": "ks-pill--sun",
    "confirmed": "ks-pill--river",
    "checked_in": "ks-pill--mangrove",
    "checked_out": "ks-pill--muted",
    "cancelled": "ks-pill--bougain",
    "no_show": "ks-pill--bougain",
    "available": "ks-pill--mangrove",
    "maintenance": "ks-pill--sun",
    "inactive": "ks-pill--muted",
    "rejected": "ks-pill--bougain",
    "open": "ks-pill--bougain",
    "in_progress": "ks-pill--sun",
    "resolved": "ks-pill--mangrove",
    "paid": "ks-pill--mangrove",
    "partial": "ks-pill--sun",
    "unpaid": "ks-pill--bougain",
    "sent": "ks-pill--mangrove",
    "manual": "ks-pill--sun",
    "failed": "ks-pill--bougain",
    "urgent": "ks-pill--bougain",
    "high": "ks-pill--sun",
    "normal": "ks-pill--river",
    "low": "ks-pill--muted",
}


@register.filter
def pill(status):
    return STATUS_CLASSES.get(status, "ks-pill--muted")


@register.simple_tag
def wa(number, text=""):
    return link(number, text)


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Rebuild the current querystring with some keys replaced."""
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            q.pop(k, None)
        else:
            q[k] = v
    return "?" + q.urlencode() if q else "?"


@register.filter
def get_item(d, key):
    return d.get(key) if hasattr(d, "get") else None
