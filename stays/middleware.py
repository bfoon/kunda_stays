"""Request plumbing for the operations portal.

1. Remembers who is making the request so model signals can write the activity log.
2. Applies the Property profile (edited in the portal) on top of the .env business
   details in settings.KUNDA, so receipts, WhatsApp texts and pages all pick it up.
"""
import threading

_local = threading.local()


def current_user():
    return getattr(_local, "user", None)


def current_ip():
    return getattr(_local, "ip", None)


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


_applied_stamp = {"value": None}


def apply_property_profile(force=False):
    """Merge the saved Property profile into settings.KUNDA. Cheap: one indexed query."""
    from django.conf import settings
    from django.db import DatabaseError

    from .models import PropertyProfile

    try:
        row = PropertyProfile.objects.filter(pk=1).values("updated_at").first()
    except DatabaseError:  # tables not migrated yet
        return
    stamp = row["updated_at"] if row else None
    if not force and stamp == _applied_stamp["value"]:
        return
    merged = dict(settings.KUNDA_DEFAULTS)
    if row:
        prof = PropertyProfile.objects.get(pk=1)
        for field in PropertyProfile.FIELD_MAP:
            value = getattr(prof, field)
            if value not in ("", None):
                merged[field] = value
        if prof.hold_hours:
            merged["hold_hours"] = prof.hold_hours
    settings.KUNDA.clear()
    settings.KUNDA.update(merged)
    _applied_stamp["value"] = stamp


class PortalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        _local.user = user if user is not None and user.is_authenticated else None
        _local.ip = _client_ip(request)
        apply_property_profile()
        try:
            return self.get_response(request)
        finally:
            _local.user = None
            _local.ip = None
